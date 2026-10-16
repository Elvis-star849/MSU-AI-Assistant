"""
Live browser tests of the admissions adviser on a RUNNING assistant (localhost). Not part of the unit tests.

    python scripts/e2e_adviser_ui.py --url http://127.0.0.1:8502 [--out logs/e2e_adviser]

Scenarios (each in a fresh chat): the reported O Level + age example and its complete conversation with quick-reply
buttons; mature-entry enquiry; diploma pathway; stale applicant data; "those were my brother's results"; corrections;
start new assessment (chat confirmation and the sidebar button); progressive recommendations with the Detailed
assessment control; no internal labels or counts in the conversation. Writes a JSON report, a transcript (Markdown)
and screenshots; exit 0 only if every check passes. Adviser turns use no model call, so these tests cost nothing.
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

EXAMPLE = "I have 5 O-Level passes including Maths and English, and I'm 30 years old. What programme can I do?"
TECHNICAL = re.compile(r"\b\d+\s+(?:conditional matches|meet the advertised requirements|other entry routes)\b"
                       r"|Router:|ELIGIBILITY|Eligibility checker|Admissions adviser|Out of scope · fixed reply")
DONE = """(n) => { const m = document.querySelectorAll('[data-testid="stChatMessage"]');
  return m.length >= n && !document.querySelector('[data-testid="stSpinner"]')
    && m[m.length - 1].innerText.replace('school', '').trim().length > 20; }"""


class Session:
    def __init__(self, page, transcript):
        self.page, self.transcript = page, transcript

    def _wait(self, n):
        self.page.wait_for_function(DONE, arg=n, timeout=180_000)
        self.page.wait_for_timeout(1500)
        self.page.wait_for_function(DONE, arg=n, timeout=60_000)

    def last(self):
        msgs = self.page.locator('[data-testid="stChatMessage"]')
        return msgs.nth(msgs.count() - 1).inner_text()

    def ask(self, text):
        n = self.page.locator('[data-testid="stChatMessage"]').count() + 2
        box = self.page.locator('[data-testid="stChatInputTextArea"]')
        box.fill(text)
        box.press("Enter")
        self._wait(n)
        answer = self.last()
        self.transcript.append((text, answer))
        return answer

    def click(self, label):
        n = self.page.locator('[data-testid="stChatMessage"]').count() + 2
        self.page.locator("button", has_text=re.compile(rf"^(?:arrow_forward\s*)?{re.escape(label)}$")).last.click()
        self._wait(n)
        answer = self.last()
        self.transcript.append((f"[button] {label}", answer))
        return answer

    def new_chat(self):
        self.page.get_by_text("New chat").first.click()
        self.page.wait_for_timeout(1500)
        self.transcript.append(("--- new chat ---", ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8502")
    ap.add_argument("--out", default="logs/e2e_adviser")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report, transcript = [], []

    def check(name, ok, text=""):
        row = {"check": name, "pass": bool(ok), "excerpt": re.sub(r"\s+", " ", text)[:300]}
        report.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 2000})
        page.goto(a.url, wait_until="domcontentloaded")
        page.locator('[data-testid="stChatInputTextArea"]').wait_for(timeout=240_000)
        s = Session(page, transcript)

        # 1 the reported example and a complete conversation (buttons for the quick replies)
        t = s.ask(EXAMPLE)
        check("example: one follow-up question, no database report",
              "Do you also have any A Level passes" in t and "5 O Level passes, including Mathematics and English "
              "Language" in t and "mature entry" in t and not TECHNICAL.search(t) and "Detailed assessment" not in t, t)
        check("example: quick-reply buttons", page.locator("button", has_text="No, only O Levels").count() == 1)
        t = s.click("No, only O Levels")
        check("only O Levels -> asks about work experience", "Have you been working since you left school" in t, t)
        t = s.ask("I have worked for 8 years in IT")
        check("work experience -> first shortlist with routes and outstanding requirements",
              "fit you best" in t and "Mature entry" in t and "Still needed:" in t and "Why it fits:" in t
              and "Detailed assessment" in t and "Did you pass a Science subject at O Level" in t
              and not TECHNICAL.search(t), t)
        t = s.click("Yes")
        check("science pass -> shortlist updated with computing programmes", "Computer" in t and "now:" in t, t)
        page.get_by_text("Detailed assessment (all programmes and entry routes)").last.click()
        page.wait_for_timeout(800)
        body = page.inner_text("body")
        check("detailed assessment opens with all routes", "Special entry (post-school qualification)" in body
              and "Mature entry" in body and "Normal entry (O Levels)" in body, body[-400:])
        t = s.ask("Can I study Computer Science?")
        check("programme question answered route by route", "Bachelor of Science Honours Degree in Computer Science" in t
              and "you told me you don't have A Levels" in t and "Mature entry" in t, t)
        sidebar = page.locator('[data-testid="stSidebar"]').inner_text()
        check("profile panel shows provenance", "Your assessment" in sidebar and "Age" in sidebar
              and "my assumption: please check" in sidebar, sidebar[-400:])
        page.screenshot(path=str(out / "01_example_conversation.png"), full_page=True)

        # 2 mature-entry enquiry
        s.new_chat()
        t = s.ask("What about mature entry?")
        check("mature entry explained from the regulations, age asked", "General Academic Regulations" in t
              and "Age alone is not enough" in t and "How old will you be" in t, t)
        t = s.ask("I'm 22")
        t = s.ask("I only have O levels, 5 passes including English and Maths")
        check("under the mature-entry age: no mature route offered as possible",
              "Mature entry" not in t.split("Detailed assessment")[0] or "not open" in t, t)

        # 3 diploma pathway
        s.new_chat()
        t = s.ask("I also have a diploma.")
        check("diploma -> asks its field", "What is your diploma in?" in t, t)
        t = s.ask("Accounting")
        check("diploma field -> special-entry shortlist, never confirmed",
              "Special entry" in t and "Accounting" in t and "decides whether your qualification is relevant" in t, t)
        page.screenshot(path=str(out / "03_diploma.png"), full_page=True)

        # 4 stale data and corrections
        s.new_chat()
        s.ask("I have Mathematics A, Computer Science A and Economics B, what can I study?")
        t = s.ask(EXAMPLE)
        check("stale data: asks before combining", "Are these details for the same person?" in t, t)
        t = s.click("New assessment")
        check("new assessment uses only the latest details", "nothing from earlier is used" in t
              and "Do you also have any A Level passes" in t, t)
        s.new_chat()
        s.ask("I have Mathematics A, Physics B and Chemistry C")
        t = s.ask("Sorry, actually Chemistry is A")
        check("correction applied", "Chemistry A (was C)" in t, t)
        t = s.ask("Actually, those were my brother's results.")
        check("brother's results removed", "I've removed" in t and "won't use them" in t
              and "What qualifications do you have?" in t, t)

        # 5 new assessment: chat confirmation and the sidebar button
        s.new_chat()
        s.ask("I have History A, Shona B and Literature in English B")
        t = s.ask("Start a new assessment.")
        check("reset asks for confirmation", "start a new assessment?" in t, t)
        t = s.click("No, keep my details")
        check("'No, keep my details' keeps them", "kept your details" in t, t)
        page.get_by_role("button", name="Start new assessment").first.click()
        page.wait_for_timeout(800)
        n = page.locator('[data-testid="stChatMessage"]').count() + 2
        page.get_by_role("button", name="Yes, start a new assessment").last.click()
        s._wait(n)
        t = s.last()
        transcript.append(("[sidebar button] Start new assessment → Yes", t))
        check("sidebar button starts a new assessment", "New assessment started" in t, t)
        page.screenshot(path=str(out / "05_new_assessment.png"), full_page=True)
        browser.close()

    ok = all(r["pass"] for r in report)
    (out / "e2e_adviser_report.json").write_text(json.dumps({"url": a.url, "all_passed": ok, "results": report},
                                                            indent=1, ensure_ascii=False), encoding="utf-8")
    md = ["# Admissions adviser: live browser transcript", ""]
    for q, ans in transcript:
        clean = "\n".join(l for l in ans.replace("school\n", "", 1).splitlines()
                          if l.strip() not in ("arrow_forward", "keyboard_arrow_right", "keyboard_arrow_down")).strip()
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        md += (["---", ""] if q.startswith("---") else [f"**Applicant:** {q}", "", "**Assistant:**", "", clean, ""])
    (out / "transcript.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"all_passed": ok, "passed": sum(r["pass"] for r in report), "total": len(report)}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
