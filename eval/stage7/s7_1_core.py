"""S7-1 core logic (imported by the S7-1 scripts and tests/test_s7_1.py). Frozen by hash before generation.

Manifest and ordering, request construction from frozen evidence, the guarded live runner, blind grading packages,
owner spot-check selection and the pre-agreed results/criteria (eval/stage7/s7_1_design.json).
"""
import hashlib, json, math, os, random, re, secrets, time
from typing import Any, Callable, Dict, List, Optional

from src.context import build_messages, prompt_sha256
from src.llm.base import GenerationSettings, LLMError

ARMS = ("arm0", "arm1", "arm2")
REPLICATE = "arm0_replicate"
MAIN_ARMS = ARMS + (REPLICATE,)
CATEGORIES = ("natural_language", "exact_code", "code_in_context")
DIMENSIONS = ("correctness", "groundedness", "completeness", "directness")
OOS_FLAGS = ("appropriate_abstention", "unsupported_general_knowledge_answer", "invented_msu_specific_information",
             "evidence_supports_answer")
COMPARISONS = {"arm1_vs_arm0": ("arm1", "arm0"), "arm2_vs_arm0": ("arm2", "arm0"),
               "replicate_vs_arm0": (REPLICATE, "arm0")}
MIN_PACE_S = 3.0
PRIVATE_DIR = os.path.expanduser("~/rag_private/s7_1")
REASONING_MARKERS = [r"<think>", r"</think>", r"<\|channel\|>", r"\bassistantfinal\b", r"^\s*analysis\b",
                     r"chain[- ]of[- ]thought", r"\bthe user (asks|is asking|wants)\b", r"\bwe need to\b",
                     r"\blet me think\b", r"\bi need to (check|figure|think)\b", r"^\s*reasoning\s*:"]


# ------------------------------------------------------------------ hashing
def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


# ------------------------------------------------------------------ manifest
def plan_items(main_ids: List[str], oos_ids: List[str]) -> List[Dict[str, str]]:
    items = [{"item_id": f"{q}/{arm}", "question_id": q, "set": "main", "arm": arm,
              "prompt": "arm0" if arm == REPLICATE else arm} for q in main_ids for arm in MAIN_ARMS]
    items += [{"item_id": f"{q}/{arm}", "question_id": q, "set": "oos", "arm": arm, "prompt": arm}
              for q in oos_ids for arm in ARMS]
    return items


def replicate_adjacent(order: List[Dict[str, str]]) -> bool:
    return any(a["question_id"] == b["question_id"] and {a["arm"], b["arm"]} == {"arm0", REPLICATE}
               for a, b in zip(order, order[1:]))


def randomized_order(items: List[Dict[str, str]], seed: int):
    """Seeded shuffle; while a replicate is next to its original, take the next permutation from the same generator."""
    rng = random.Random(seed)
    order = list(items)
    rng.shuffle(order)
    reshuffles = 0
    while replicate_adjacent(order):
        rng.shuffle(order)
        reshuffles += 1
    return order, reshuffles


def frozen_settings(design: Dict[str, Any]) -> GenerationSettings:
    s = design["generation_settings"]
    return GenerationSettings(model=s["model"], temperature=s["temperature"], reasoning_effort=s["reasoning_effort"],
                              max_completion_tokens=s["max_completion_tokens"], timeout_s=s["timeout_s"],
                              max_retries=s["max_retries"])


def build_request(item: Dict[str, str], evidence: Dict[str, Any], prompts: Dict[str, Any]) -> Dict[str, Any]:
    q = evidence["questions"][item["question_id"]]
    messages = build_messages(q["question"], q["evidence"], system_prompt=prompts["arms"][item["prompt"]]["text"])
    return {"messages": messages, "system_sha256": sha256_text(messages[0].content),
            "user_sha256": sha256_text(messages[1].content), "prompt_sha256": prompt_sha256(messages)}


# ------------------------------------------------------------------ live runner
def read_attempts(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_attempt(path: str, record: Dict[str, Any]):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def execute(manifest: Dict[str, Any], evidence: Dict[str, Any], prompts: Dict[str, Any], client: Any,
            settings: GenerationSettings, runs_path: str, pace_s: float = MIN_PACE_S,
            sleep: Callable[[float], None] = time.sleep, resend_item: Optional[str] = None,
            resend_approval: Optional[str] = None, log: Callable[[str], None] = print) -> Dict[str, Any]:
    """
    Send the manifest items that have never been attempted, in the frozen order, one attempt each, stopping at the
    first failure. resend_item (with a written owner approval) re-sends one failed item as an extra attempt.
    """
    if pace_s < MIN_PACE_S:
        raise ValueError(f"pacing must be at least {MIN_PACE_S} s")
    if settings.max_retries != 0:
        raise ValueError("S7-1 requires max_retries=0")
    order = manifest["order"]
    planned = {i["item_id"]: i for i in order}
    if len(planned) != manifest["total_items"] or len(order) != manifest["total_items"]:
        raise ValueError("manifest item count does not match total_items")
    attempts = read_attempts(runs_path)
    attempted = {a["item_id"] for a in attempts}
    if any(a["item_id"] not in planned for a in attempts):
        raise ValueError("runs file contains an item that is not in the manifest")
    if resend_item is not None:
        failed = [a for a in attempts if a["item_id"] == resend_item]
        if resend_item not in planned or not failed or failed[-1]["succeeded"]:
            raise ValueError("only a previously failed manifest item can be resent")
        if not resend_approval:
            raise ValueError("a resend requires a recorded explicit owner approval")
        todo, attempt_type = [planned[resend_item]], "approved_resend_extra_attempt"
    else:
        todo, attempt_type = [i for i in order if i["item_id"] not in attempted], "planned"
    sent = 0
    for item in todo:
        if attempt_type == "planned" and item["item_id"] in {a["item_id"] for a in read_attempts(runs_path)}:
            raise RuntimeError("item already attempted")  # never twice within the manifest
        if sent:
            sleep(pace_s)
        request = build_request(item, evidence, prompts)
        if request["prompt_sha256"] != item["prompt_sha256"]:
            raise RuntimeError(f"request for {item['item_id']} does not match the frozen manifest hash")
        record = {**{k: item[k] for k in ("item_id", "position", "question_id", "set", "arm", "prompt")},
                  "attempt_type": attempt_type, "resend_approval": resend_approval,
                  "requested_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                  "system_sha256": request["system_sha256"], "user_sha256": request["user_sha256"],
                  "prompt_sha256": request["prompt_sha256"], "settings": settings.to_record()}
        sent += 1
        try:
            r = client.generate(request["messages"], settings)
        except LLMError as error:
            record.update({"succeeded": False, "attempts": error.attempts, "error": error.to_record()})
            append_attempt(runs_path, record)
            log(f"{item['position']:>2} {item['item_id']}: FAILED ({error.kind}); run stopped")
            return {"sent": sent, "stopped_on_failure": item["item_id"]}
        markers = [m for m in REASONING_MARKERS if re.search(m, r.text, re.IGNORECASE | re.MULTILINE)]
        record.update({"succeeded": True, "attempts": r.attempts, "returned_model": r.returned_model,
                       "latency_ms": r.latency_ms, "usage": r.usage, "finish_reason": r.finish_reason,
                       "request_id": r.request_id,
                       "reasoning_check": {"reasoning_requested_excluded": r.reasoning_requested_excluded,
                                           "provider_returned_reasoning_field": r.provider_returned_reasoning,
                                           "answer_reasoning_markers_found": markers},
                       "answer": r.text})
        append_attempt(runs_path, record)
        log(f"{item['position']:>2} {item['item_id']}: ok {r.latency_ms} ms, finish {r.finish_reason}")
    return {"sent": sent, "stopped_on_failure": None}


# ------------------------------------------------------------------ blind packages
def strip_markdown(text: str) -> str:
    """Remove formatting that could identify a prompt arm's style: headings, bullets, emphasis, rules, tables."""
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?", s) or re.fullmatch(r"[-*_=]{3,}", s):
            continue
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^(?:[-*+•]|\d+[.)])\s+", "", s)
        if s.startswith("|") and s.endswith("|") and len(s) > 1:
            s = "; ".join(c.strip() for c in s.strip("|").split("|"))
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])", r"\1", s)
        s = s.replace("`", "")
        lines.append(s)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _evidence_block(q: Dict[str, Any]) -> str:
    parts = []
    for n, e in enumerate(q["evidence"], 1):
        head = f"[Evidence {n}] {e['source']}, p. {e['page']}" + (f" | {e['heading']}" if e.get("heading") else "")
        parts.append(f"{head}\n{e['text']}")
    return "\n\n".join(parts) if parts else "(no evidence passages)"


def _answer_key(q: Dict[str, Any]) -> str:
    key = q.get("answer_key")
    if not key:
        return "None (out-of-scope question)."
    sufficient = ", ".join(f"Evidence {n}" for n in q["sufficient_evidence_numbers"]) or "none"
    return (f"{key['sufficient']} (yearbook pages: {', '.join(key['pages'])}). "
            f"Supplied passages previously graded sufficient on their own: {sufficient}.")


ABSOLUTE_OUTPUT = ('Return only JSON: {"main": [{"label": ..., "correctness": 0-2, "groundedness": 0-2, '
                   '"completeness": 0-2, "directness": 0-2, "hallucination": true/false, "hallucination_detail": '
                   '"...", "citation_note": "...", "notes": "..."}], "oos": [{"label": ..., '
                   '"appropriate_abstention": true/false, "unsupported_general_knowledge_answer": true/false, '
                   '"invented_msu_specific_information": true/false, "evidence_supports_answer": true/false, '
                   '"detail": "..."}]} with exactly one entry per answer label.')
PAIRWISE_OUTPUT = ('Return only JSON: {"pairwise": [{"label": ..., "preferred": "A" | "B" | "tie", "reason": "..."}]} '
                   'with exactly one entry per comparison label.')
GRADER_PREAMBLE = ("You are grading anonymous answers produced by a question-answering assistant for Midlands State "
                   "University (MSU) students. The assistant was given the evidence passages shown and was expected "
                   "to answer from them. Grade only from this package. Do not inspect any files and do not use any "
                   "tools.")


def _rubric_text(design: Dict[str, Any]) -> str:
    r = design["absolute_rubric"]
    lines = ["RUBRIC FOR IN-SCOPE QUESTIONS (each 0-2):"]
    for dim in DIMENSIONS:
        lines.append(f"- {dim}: " + "; ".join(f"{k} = {v}" for k, v in sorted(r[dim].items(), reverse=True)))
    lines += [f"- hallucination flag: {r['hallucination_flag']}", f"- conflicting evidence: {r['conflict_rule']}",
              f"- citations: {r['citation_note']}"]
    o = design["oos_rubric_S7_1B"]
    lines += ["", "RUBRIC FOR OUT-OF-SCOPE QUESTIONS (yes/no each):",
              "- appropriate_abstention; unsupported_general_knowledge_answer; invented_msu_specific_information; "
              "evidence_supports_answer (the supplied evidence genuinely supports an answer)",
              f"- preferred behaviour: {o['preferred_behaviour']}"] + [f"- {rule}" for rule in o["rules"]]
    return "\n".join(lines)


def build_absolute_package(design, evidence, answers: Dict[str, str], rng: random.Random):
    """answers: item_id -> raw answer. Returns (package text, {label: item_id})."""
    mapping, blocks = {}, []
    for set_name in ("main", "oos"):
        qids = [q for q, v in evidence["questions"].items() if v["set"] == set_name]
        for qid in qids:
            q = evidence["questions"][qid]
            items = sorted(i for i in answers if i.split("/")[0] == qid)
            rng.shuffle(items)
            lines = [f"######## QUESTION {qid} ({'out-of-scope' if set_name == 'oos' else 'in-scope'})",
                     f"Question: {q['question']}", f"Answer key: {_answer_key(q)}", "Evidence supplied to the assistant:",
                     _evidence_block(q)]
            for letter, item_id in zip("abcd", items):
                label = f"{qid}-{letter}"
                mapping[label] = item_id
                lines.append(f"---- ANSWER {label}\n{strip_markdown(answers[item_id])}")
            blocks.append("\n".join(lines))
    text = "\n\n".join([GRADER_PREAMBLE, _rubric_text(design), ABSOLUTE_OUTPUT] + blocks)
    return text, mapping


def build_pairwise_package(design, evidence, answers: Dict[str, str], rng: random.Random):
    """Main questions only: arm1 vs arm0, arm2 vs arm0, replicate vs arm0, shuffled, A/B randomised."""
    pairs = []
    for qid, q in evidence["questions"].items():
        if q["set"] != "main":
            continue
        for comparison, (x, y) in COMPARISONS.items():
            a, b = f"{qid}/{x}", f"{qid}/{y}"
            if rng.random() < 0.5:
                a, b = b, a
            pairs.append({"question_id": qid, "comparison": comparison, "A": a, "B": b})
    rng.shuffle(pairs)
    mapping, blocks = {}, []
    for n, p in enumerate(pairs, 1):
        label = f"P{n:02d}"
        mapping[label] = p
        q = evidence["questions"][p["question_id"]]
        blocks.append("\n".join([f"######## COMPARISON {label}", f"Question: {q['question']}",
                                 f"Answer key: {_answer_key(q)}", "Evidence supplied to the assistant:",
                                 _evidence_block(q), f"---- ANSWER A\n{strip_markdown(answers[p['A']])}",
                                 f"---- ANSWER B\n{strip_markdown(answers[p['B']])}"]))
    text = "\n\n".join([GRADER_PREAMBLE, "PAIRWISE INSTRUCTIONS: " + design["pairwise_rubric"], PAIRWISE_OUTPUT]
                       + blocks)
    return text, mapping


def validate_absolute(grades: Dict[str, Any], mapping: Dict[str, str]) -> List[str]:
    problems = []
    seen = {}
    for entry in grades.get("main", []):
        seen[entry.get("label")] = "main"
        if any(entry.get(d) not in (0, 1, 2) for d in DIMENSIONS) or not isinstance(entry.get("hallucination"), bool):
            problems.append(f"bad main entry {entry.get('label')}")
    for entry in grades.get("oos", []):
        seen[entry.get("label")] = "oos"
        if any(not isinstance(entry.get(f), bool) for f in OOS_FLAGS):
            problems.append(f"bad oos entry {entry.get('label')}")
    for label, item_id in mapping.items():
        expected = "oos" if item_id.split("/")[0].startswith("O") else "main"
        if seen.get(label) != expected:
            problems.append(f"missing or misplaced label {label}")
    problems += [f"unknown label {label}" for label in seen if label not in mapping]
    return problems


def validate_pairwise(grades: Dict[str, Any], mapping: Dict[str, Any]) -> List[str]:
    got = {e.get("label"): e for e in grades.get("pairwise", [])}
    problems = [f"missing {label}" for label in mapping if label not in got]
    problems += [f"unknown {label}" for label in got if label not in mapping]
    problems += [f"bad preference {label}" for label, e in got.items() if e.get("preferred") not in ("A", "B", "tie")]
    return problems


# ------------------------------------------------------------------ owner spot-check
def spot_check_selection(absolute: Dict[str, Any], abs_mapping: Dict[str, str], pair_mapping: Dict[str, Any],
                         seed: int) -> Dict[str, List[str]]:
    flags = [e["label"] for e in absolute["main"] if e["hallucination"]]
    flags += [e["label"] for e in absolute["oos"] if e["invented_msu_specific_information"]]
    main_pairs = sorted(l for l, p in pair_mapping.items() if p["comparison"] != "replicate_vs_arm0")
    labels = sorted(abs_mapping)
    sample = sorted(random.Random(seed).sample(labels, math.ceil(len(labels) / 3)))
    return {"hallucination_flags": sorted(flags), "main_pairwise": main_pairs, "absolute_sample": sample}


# ------------------------------------------------------------------ results
def oos_outcome(entry: Dict[str, Any]) -> str:
    if entry["invented_msu_specific_information"]:
        return "serious_failure"
    if entry["unsupported_general_knowledge_answer"]:
        return "abstention_failure"
    if entry["appropriate_abstention"] or entry["evidence_supports_answer"]:
        return "pass"
    return "unclassified_owner_review"


def compute_results(evidence, abs_grades, abs_mapping, pair_grades, pair_mapping, attempts, manifest):
    by_item = {abs_mapping[e["label"]]: e for e in abs_grades["main"] + abs_grades["oos"]}
    cat = {q: v["category"] for q, v in evidence["questions"].items()}
    main_q = [q for q, v in evidence["questions"].items() if v["set"] == "main"]
    oos_q = [q for q, v in evidence["questions"].items() if v["set"] == "oos"]

    ok = [a for a in attempts if a["succeeded"]]
    planned_ok = {a["item_id"] for a in ok}
    validity = {"all_items_succeeded": planned_ok == {i["item_id"] for i in manifest["order"]},
                "all_finish_stop": all(a["finish_reason"] == "stop" for a in ok),
                "no_reasoning_leakage": all(not a["reasoning_check"]["answer_reasoning_markers_found"]
                                            and not a["reasoning_check"]["provider_returned_reasoning_field"]
                                            for a in ok),
                "failed_attempts": [a["item_id"] for a in attempts if not a["succeeded"]],
                "extra_attempts": [a["item_id"] for a in attempts if a["attempt_type"] != "planned"]}
    validity["passed"] = validity["all_items_succeeded"] and validity["all_finish_stop"] and \
        validity["no_reasoning_leakage"]

    summary = {}
    for arm in MAIN_ARMS:
        g = {q: by_item[f"{q}/{arm}"] for q in main_q}
        s = {"overall": {d: sum(g[q][d] for q in main_q) for d in DIMENSIONS}}
        s["overall"]["hallucinations"] = sum(g[q]["hallucination"] for q in main_q)
        for c in CATEGORIES:
            s[c] = {d: sum(g[q][d] for q in main_q if cat[q] == c) for d in DIMENSIONS}
        s["per_question"] = {q: {d: g[q][d] for d in DIMENSIONS} | {"hallucination": g[q]["hallucination"]}
                             for q in main_q}
        summary[arm] = s

    pairwise = {}
    preferred = {e["label"]: e["preferred"] for e in pair_grades["pairwise"]}
    for comparison, (x, _) in COMPARISONS.items():
        rows = {}
        for label, p in pair_mapping.items():
            if p["comparison"] != comparison:
                continue
            choice = preferred[label]
            winner = "tie" if choice == "tie" else p[choice].split("/")[1]
            rows[p["question_id"]] = "tie" if winner == "tie" else ("win" if winner == x else "loss")
        counts = {k: sum(v == k for v in rows.values()) for k in ("win", "tie", "loss")}
        pairwise[comparison] = {"per_question": rows, **counts, "wins_minus_losses": counts["win"] - counts["loss"]}

    base = summary["arm0"]["overall"]
    eligibility = {}
    for arm in ("arm1", "arm2"):
        o, pq = summary[arm]["overall"], summary[arm]["per_question"]
        cond = {"hallucinations_le_arm0": o["hallucinations"] <= base["hallucinations"],
                "groundedness_ge_arm0": o["groundedness"] >= base["groundedness"],
                "correctness_ge_arm0": o["correctness"] >= base["correctness"],
                "no_correctness_2_to_0": not any(summary["arm0"]["per_question"][q]["correctness"] == 2
                                                 and pq[q]["correctness"] == 0 for q in main_q),
                "completeness_within_2_of_arm0": o["completeness"] >= base["completeness"] - 2,
                "pairwise_wins_minus_losses_ge_3": pairwise[f"{arm}_vs_arm0"]["wins_minus_losses"] >= 3}
        eligibility[arm] = {"conditions": cond, "eligible": all(cond.values())}
    eligible = [a for a in ("arm1", "arm2") if eligibility[a]["eligible"]]
    if not eligible:
        selected, rule = "arm0", "neither arm qualified: retain Arm 0"
    elif len(eligible) == 1:
        selected, rule = eligible[0], "only eligible arm"
    else:
        key = lambda a: (-pairwise[f"{a}_vs_arm0"]["wins_minus_losses"], summary[a]["overall"]["hallucinations"],
                         0 if a == "arm1" else 1)
        selected, rule = sorted(eligible, key=key)[0], "both eligible: wins-minus-losses, then hallucinations, then Arm 1"

    rep = pairwise["replicate_vs_arm0"]
    differ = [q for q in main_q if summary[REPLICATE]["per_question"][q]["correctness"] !=
              summary["arm0"]["per_question"][q]["correctness"] or
              summary[REPLICATE]["per_question"][q]["hallucination"] != summary["arm0"]["per_question"][q]["hallucination"]]
    instability = {"replicate_abs_wins_minus_losses": abs(rep["wins_minus_losses"]),
                   "questions_differing_in_correctness_or_hallucination": differ,
                   "absolute_grade_differences_any_dimension": [q for q in main_q if any(
                       summary[REPLICATE]["per_question"][q][d] != summary["arm0"]["per_question"][q][d]
                       for d in DIMENSIONS)]}
    instability["flag_less_reliable"] = instability["replicate_abs_wins_minus_losses"] >= 3 or len(differ) >= 3

    oos = {arm: {q: {"outcome": oos_outcome(by_item[f"{q}/{arm}"]),
                     "general_knowledge_answer": by_item[f"{q}/{arm}"]["unsupported_general_knowledge_answer"]}
                 for q in oos_q} for arm in ARMS}
    oos_counts = {arm: {k: sum(v["outcome"] == k for v in rows.values())
                        for k in ("pass", "abstention_failure", "serious_failure", "unclassified_owner_review")}
                  for arm, rows in oos.items()}
    serious = {arm: [q for q, v in rows.items() if v["outcome"] == "serious_failure"] for arm, rows in oos.items()}

    reasons = []
    if not validity["passed"]:
        reasons.append("validity gate failed")
    if instability["flag_less_reliable"]:
        reasons.append("generation instability threshold met (Arm 0 replicate)")
    if any(serious.values()):
        reasons.append("serious OOS failures: " + json.dumps({a: q for a, q in serious.items() if q}))
    return {"validity": validity, "summary": summary, "pairwise": pairwise, "eligibility": eligibility,
            "selected_prompt": selected, "selection_rule_applied": rule, "instability": instability,
            "oos_S7_1B": {"per_question": oos, "counts": oos_counts, "serious_failures": serious},
            "conclusiveness": {"treat_as_conclusive": not reasons, "reasons_against": reasons},
            "directness_note": "directness is descriptive only; not an acceptance gate",
            "wording": "A winning arm passed the predefined S7-1 criteria on a 15-question development subset; "
                       "this is not proof and no held-out claim is made."}


def new_blind_rng() -> random.Random:
    """Unpredictable seed for blind labels; it is stored only in the private mapping file."""
    seed = secrets.randbits(64)
    rng = random.Random(seed)
    rng.seed_value = seed
    return rng
