"""
MSU AI Assistant health check (never prints credentials).

    python healthcheck.py                       configuration + knowledge base + retrieval (offline, no API call)
    python healthcheck.py --url http://localhost:8501     also checks the running web server (/_stcore/health)
    python healthcheck.py --live-llm            also makes ONE short Groq answer call end to end (costs < US$0.001)

Exit code 0 = healthy, 1 = a check failed. Output is one line per check.
"""
import argparse
import json
import os
import sys
import time
import urllib.request

os.environ.setdefault("HF_HUB_OFFLINE", "1")
for _stream in (sys.stdout, sys.stderr):      # model answers contain non-ASCII; Windows consoles default to cp1252
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--live-llm", action="store_true")
    a = ap.parse_args()
    results = []

    def check(name, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            results.append((name, True, detail))
        except Exception as error:  # report the type and message only; messages never contain credentials
            results.append((name, False, f"{type(error).__name__}: {error}"))
        print(f"[{'OK' if results[-1][1] else 'FAIL'}] {name} ({time.perf_counter() - t0:.1f}s): {results[-1][2]}",
              flush=True)
        return results[-1][1]

    from src.profiles import C3, LABELS, current_profile, verify_public_pointer
    profile = check("profile", lambda: (lambda p: f"{p} - {LABELS[p]}")(current_profile()))

    def key():
        from src.llm import load_config
        cfg = load_config()
        if not cfg.key_configured:
            raise RuntimeError("GROQ_API_KEY is not set (answers disabled; retrieval still works)")
        return f"Groq key present (model {cfg.settings.model})"
    check("llm configuration", key)

    if profile and current_profile() == C3:
        check("public knowledge base", lambda: (lambda p: f"active public version {p['version']} verified")(verify_public_pointer()))

    holder = {}

    def load():
        from src.assistant import Assistant
        holder["a"] = Assistant.create(offline=True)
        return f"loaded ({holder['a'].prompt_version})"
    if check("retrieval pipeline load", load):
        def retrieve(q, expect):
            ev = holder["a"].retriever.retrieve(q)
            sources = {e["source"] for e in ev}
            if not ev or (expect and expect not in sources):
                raise RuntimeError(f"unexpected sources {sorted(sources)}")
            return f"{len(ev)} passages; sources {sorted(sources)}"
        check("retrieval: yearbook", lambda: retrieve("Describe BM134", None))
        if current_profile() == C3:
            check("retrieval: 2027 road map", lambda: retrieve("When does second-quarter face-to-face tuition run in 2027?",
                                                              "MSU 2027 Road Map"))
    if a.live_llm:
        def live():
            from src.assistant import Assistant
            r = Assistant.create().ask("When does second-quarter face-to-face tuition run in 2027?")
            if r.status != "answered" or not r.answer:
                raise RuntimeError(f"status {r.status}: {r.error_message}")
            return f"answered in {r.timings_ms.get('total', 0):,.0f} ms; {len(r.sources)} sources; {r.answer[:80]!r}…"
        check("live answer (one Groq call)", live)
    if a.url:
        def web():
            with urllib.request.urlopen(a.url.rstrip("/") + "/_stcore/health", timeout=10) as resp:
                body = resp.read().decode()
            if resp.status != 200 or body.strip() != "ok":
                raise RuntimeError(f"HTTP {resp.status} {body[:40]!r}")
            return f"{a.url} healthy"
        check("web server", web)
    ok = all(r[1] for r in results if r[0] != "llm configuration") and \
        (any(r[0] == "llm configuration" and r[1] for r in results) or not a.live_llm)
    print(json.dumps({"healthy": ok, "failed": [r[0] for r in results if not r[1]]}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
