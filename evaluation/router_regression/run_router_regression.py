"""
Live router regression: the labelled cases in cases.json against the real model (GROQ_MODEL), one call per case
that is not decided by the keyword guard. Not part of the unit tests (it needs Groq; about 40 calls per repeat,
well under US$0.01).

    python evaluation/router_regression/run_router_regression.py [--repeat 2]

Writes evaluation/results/router_regression/router_regression_<timestamp>.json with every decision and the
accuracy per category. Exit 0 only if every case gets the expected label in every repeat.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1)
    a = ap.parse_args()
    from src.assistant import ACCEPTED_GENERATION        # the app's default model settings (GROQ_MODEL path)
    from src.llm import create_client, load_config
    from src.router import route_with_reason
    cfg = load_config()
    llm, settings = create_client(cfg), cfg.settings.with_changes(**ACCEPTED_GENERATION)
    cases = json.loads(Path(__file__).with_name("cases.json").read_text(encoding="utf-8"))["cases"]
    rows, per_cat = [], defaultdict(lambda: [0, 0])
    for r in range(a.repeat):
        for c in cases:
            t = time.perf_counter()
            label, reason = route_with_reason(c["q"], c.get("history", []), llm, settings)
            ok = label == c["expect"]
            per_cat[c["cat"]][0] += ok
            per_cat[c["cat"]][1] += 1
            rows.append({"repeat": r + 1, **c, "got": label, "reason": reason, "ok": ok,
                         "ms": round((time.perf_counter() - t) * 1000)})
            print(("PASS" if ok else "FAIL"), c["cat"], label, reason, "|", c["q"], flush=True)
    summary = {"model": settings.model, "cases": len(cases), "repeats": a.repeat,
               "passed": sum(x["ok"] for x in rows), "total": len(rows),
               "by_category": {k: f"{v[0]}/{v[1]}" for k, v in per_cat.items()}}
    out = ROOT / "evaluation/results/router_regression"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"router_regression_{stamp}.json").write_text(json.dumps({"summary": summary, "results": rows},
                                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
