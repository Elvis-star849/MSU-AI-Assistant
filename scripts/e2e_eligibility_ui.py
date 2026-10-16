"""
Live browser checks of the admissions features on a RUNNING assistant (real retrieval and Groq calls for the documents
path; eligibility answers are deterministic). Complements scripts/e2e_live_ui.py. Not part of the unit tests.

    python scripts/e2e_eligibility_ui.py --url http://127.0.0.1:8502 [--out logs/e2e_eligibility] [--dev-mode]

Checks: adviser shortlist + O Level request + disclaimer (no counts); the O Level reply completing the check;
a correction; "why can't I"; a named programme answered first; grades without subjects -> follow-up; fees and a
deadline paraphrase -> fixed reply; a deadline the advert states -> quoted with its page; a documents question with
the programme-details panel; the Programme explorer and Admin pages; Technical details hidden unless --dev-mode.
Writes a JSON report and screenshots; exit 0 only if every check passes.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DISCLAIMER = "the Admissions Office makes the final decision"  # the adviser's closing sentence
DONE = """(n) => { const m = document.querySelectorAll('[data-testid="stChatMessage"]');
  return m.length >= n && !document.querySelector('[data-testid="stSpinner"]')
    && m[m.length - 1].innerText.replace('school', '').trim().length > 20; }"""


def ask(page, question):
    n = page.locator('[data-testid="stChatMessage"]').count() + 2
    box = page.locator('[data-testid="stChatInputTextArea"]')
    box.fill(question)
    box.press("Enter")
    page.wait_for_function(DONE, arg=n, timeout=180_000)
    page.wait_for_timeout(2000)
    page.wait_for_function(DONE, arg=n, timeout=60_000)
    msgs = page.locator('[data-testid="stChatMessage"]')
    return msgs.nth(msgs.count() - 1).inner_text()


def count(text, label):
    m = re.search(rf"(\d+)\s*\n?\s*{label}", text)
    return int(m.group(1)) if m else -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8502")
    ap.add_argument("--out", default="logs/e2e_eligibility")
    ap.add_argument("--dev-mode", action="store_true", help="the server runs with MSU_ASSISTANT_DEV_MODE=1")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = []

    def check(name, ok, text):
        row = {"check": name, "pass": bool(ok), "excerpt": re.sub(r"\s+", " ", text)[:300]}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    tech = (lambda t: "Technical details" in t) if a.dev_mode else (lambda t: "Technical details" not in t)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1800})
        page.goto(a.url, wait_until="domcontentloaded")
        page.locator('[data-testid="stChatInputTextArea"]').wait_for(timeout=240_000)

        t = ask(page, "I have Mathematics A, Computer Science A and Economics B, what can I study?")
        check("A Levels: short shortlist, O Level question, disclaimer, no counts",
              "Your A Levels fit these programmes" in t and "Computer Science" in t and "O Level English Language and "
              "Mathematics grades" in t and DISCLAIMER in t and "conditional matches" not in t
              and "Eligibility checker" not in t and tech(t), t)
        t = ask(page, "English B, Maths C, 6 passes")
        check("O Level reply completes the check", "✅ Meets the advertised requirements" in t and DISCLAIMER in t, t)
        t = ask(page, "Sorry, actually Economics is A")
        check("correction applied", "Economics A (was B)" in t, t)
        t = ask(page, "Why can't I do Biotechnology?")
        check("why not: the named programme, route by route", "Biotechnology" in t and "not open to you" in t, t)
        page.screenshot(path=str(out / "eligibility_conversation.png"), full_page=True)

        page.get_by_text("New chat").first.click()
        page.wait_for_timeout(1500)
        t = ask(page, "I have Mathematics A, Physics B and Chemistry B. Can I do Computer Science?")
        check("named programme answered first", t.find("Bachelor of Science Honours Degree in Computer Science") >= 0
              and t.find("Bachelor of Science Honours Degree in Computer Science") < 400, t)
        page.get_by_text("New chat").first.click()
        page.wait_for_timeout(1500)
        t = ask(page, "I got A, B and C at A Level. What can I study?")
        check("grades without subjects -> follow-up", "Which A Level subjects did you get those grades" in t and tech(t), t)
        t = ask(page, "How much are the fees?")
        check("fees -> fixed reply, no routing label", "admissions@admin.msu.ac.zw" in t and "Out of scope" not in t, t)
        t = ask(page, "Is it too late to apply for 2027?")
        check("deadline paraphrase -> fixed reply", "admissions@admin.msu.ac.zw" in t, t)
        t = ask(page, "What is the application deadline for Mining Engineering?")
        check("deadline stated in the advert -> quoted with page", "31 March 2027" in t and "p. 23" in t, t)
        t = ask(page, "How long is the BSc Honours in Human Resource Management and how is it offered?")
        check("documents answer with all routes and programme details",
              re.search(r"4\W*years?", t) and re.search(r"3\W*years?", t) and "Weekend School" in t
              and "Programme details (2027 intake advert)" in t and tech(t), t)
        page.screenshot(path=str(out / "router_paths.png"), full_page=True)

        page.goto(a.url.rstrip("/") + "/programme_explorer", wait_until="domcontentloaded")
        page.get_by_text("programme(s)").first.wait_for(timeout=120_000)
        body = page.inner_text("body")
        check("programme explorer page", "Programme explorer" in body and "programme(s)" in body, body)
        page.goto(a.url.rstrip("/") + "/admin", wait_until="domcontentloaded")
        page.get_by_text(re.compile("First-run setup|Sign in")).first.wait_for(timeout=120_000)
        body = page.inner_text("body")
        check("admin page requires sign-in", ("Sign in" in body or "First-run setup" in body)
              and "Upload a document" not in body, body)
        page.screenshot(path=str(out / "admin_sign_in.png"), full_page=True)
        browser.close()
    ok = all(r["pass"] for r in report)
    (out / "e2e_eligibility_report.json").write_text(json.dumps({"url": a.url, "dev_mode": a.dev_mode, "all_passed": ok,
                                                                 "results": report}, indent=1, ensure_ascii=False),
                                                     encoding="utf-8")
    print(json.dumps({"all_passed": ok, "passed": sum(r["pass"] for r in report), "total": len(report)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
