"""Stage 6 held-out sampling: the Stage 5 procedure, unchanged, with a new seed and Stage 5 items excluded."""
import json, re, random, collections, sys
SEED = 20261009
recs = [json.loads(l) for l in open('faiss_store/chunks.jsonl', encoding='utf-8')]

# ---- course codes (identical regexes/filters to Stage 5) ----
pat = re.compile(r'^([A-Z]{2,6}) ?(\d{3}):? ([A-Z][^\n]{5,80})\n((?:This|The) (?:module|course)[^\n]{20,})', re.M)
code = re.compile(r'\b([A-Z]{2,6}) ?(\d{3})(?!\d)')
mentions = collections.Counter()
for r in recs:
    for a, b in set(code.findall(r['text'])): mentions[a+b] += 1
stage4 = {'HAWS433','MPG704','BSS204','HRFS412','PSY134','HMPC433','EC439','BED133','HFEE212','ANTH102','HAWS439','HFSC136'}
stage5 = {'DSC603','SEMA204','SEPS101','HPHS201','BAEH141','HALCS211','MECDP704','MEHD733','MSECH704','SEMA102','MARS565','MUS137',
          'BM134','HAM105','MSCM703','MIM732','CIT135','HMETE103','HNS124','MIP845','MFA700','BM135','MIP803','BM136'}
used = stage4 | stage5
cands = {}
for r in recs:
    for m in pat.finditer(r['text']):
        k = m.group(1)+m.group(2)
        if k in used: continue
        cands.setdefault(k, []).append((r['source'][4:7], r['page'], r['chunk_id'], m.group(3).strip(), m.group(4)[:70]))
clean = {k: v for k, v in cands.items() if len({x[3].lower() for x in v}) == 1}
by = {'Hum': [], 'Sci': []}
for k, v in sorted(clean.items()): by[v[0][0]].append(k)
rng = random.Random(SEED)
pick = {b: rng.sample(by[b], 12) for b in by}
print({b: len(by[b]) for b in by})
for b in pick:
    for i, k in enumerate(pick[b], 1):
        v = clean[k]
        print(b, i, k, '| mentions', mentions[k], '| desc pages', [x[1] for x in v], '|', v[0][3], '|', v[0][4])

# ---- natural-language topics (identical heading regex/exclusions to Stage 5) ----
h = re.compile(r'^(\d{1,2}(?:\.\d{1,2})?\.?) ([A-Z][A-Za-z ,\'&/()-]{5,70})$', re.M)
exclude = re.compile(r'(?i)defer|classif|vice-chancellor|disciplin|plagiar|supplementar|termination|forensic|definition|interpretation|title|contents|introduction|preamble|short title|programme structure|module|grading|weighting|purpose|entry requirement', re.I)
stage5_topics = {'functions of faculty boards','programme delivery','chairman and vice-chairman of council','membership of the university',
                 'upgrade from mphil to phd/dphil','damage to hall property','master of philosophy degree','undertaking at registration',
                 'doctor of philosophy degree (honoris causa)','failure to satisfy examiners'}
heads = {}
for r in recs:
    if r['page'] > 200: continue
    for m in h.finditer(r['text'].split('\n', 1)[1]):
        t = m.group(2).strip(' .')
        if exclude.search(t) or len(t.split()) < 2: continue
        heads.setdefault(t.lower(), (t, r['source'][4:7], r['page']))
keys = sorted(k for k in heads if k not in stage5_topics)
print(len(keys), 'eligible headings')
rng2 = random.Random(SEED)
for i, k in enumerate(rng2.sample(keys, 30), 1): print(i, heads[k])
