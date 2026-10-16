#!/usr/bin/env python3
"""MSU eligibility checker (January/February 2027 intake, undergraduate and diploma).
Usage:
  python3 eligibility_checker.py --a "Mathematics=A,Computer Science=A,Economics=B" [--o "English=B,Mathematics=C,passes=6"] [--json]
Reads MSU_Eligibility_Rules.json from the same folder. Deterministic: no AI involved.
"""
import json,os,sys,argparse
HERE=os.path.dirname(os.path.abspath(__file__))
D=json.load(open(os.path.join(HERE,"MSU_Eligibility_Rules.json"),encoding="utf-8"))
PTS=D["meta"]["grade_scale"]; PASS=set(D["meta"]["pass_grades"]); TAX=D["taxonomy"]; AL=D["aliases"]
O_ORDER={"A":6,"B":5,"C":4,"D":3,"E":2,"U":1,"F":1,"G":0}
def norm(name):
    k=name.strip().lower()
    if k in AL: return AL[k]
    for s in TAX:
        if s.lower()==k: return s
    return name.strip().title()
def a_subject_cats(s): return set(TAX.get(s,[]))
def slot_ok(slot,subj,grade):
    ok=False
    for t in slot["any_of"]:
        if t=="ANY": ok=True
        elif t in ("SCI","COM","ARTS","LANG"): ok=ok or t in a_subject_cats(subj)
        elif t==subj: ok=True
    if not ok: return False
    g=slot.get("min_grade")
    return g is None or PTS[grade]>=PTS[g]
def match(slots,passed):
    subs=list(passed.items())
    def go(i,used):
        if i==len(slots): return []
        for s,g in subs:
            if s in used: continue
            if slot_ok(slots[i],s,g):
                r=go(i+1,used|{s})
                if r is not None: return [s]+r
        return None
    return go(0,frozenset())
def parse_pairs(txt):
    out={}
    for part in (txt or "").split(","):
        if "=" in part:
            k,v=part.split("=",1); out[k.strip()]=v.strip()
    return out
def o_check(rule,o):
    """returns (fails, to_confirm)"""
    fails=[];conf=[]
    if o is None:
        conf.append("O Level: at least %d passes at grade %s or better"%(rule["min_passes"],rule["min_pass_grade"]))
        for s,g in rule["required_subjects"].items(): conf.append("O Level %s%s"%(s," at grade %s or better"%g if g else ""))
        return fails,conf
    oo={}
    for k,v in o.items():
        if k.lower()=="passes": continue
        oo[norm_o(k)]=v.upper()
    if "passes" in {k.lower() for k in o}:
        n=int([v for k,v in o.items() if k.lower()=="passes"][0])
        if n<rule["min_passes"]: fails.append("needs at least %d O Level passes at grade %s or better (you gave %d)"%(rule["min_passes"],rule["min_pass_grade"],n))
    else: conf.append("number of O Level passes at grade %s or better (needs %d)"%(rule["min_pass_grade"],rule["min_passes"]))
    for s,g in rule["required_subjects"].items():
        have=find_o(oo,s)
        need=g or rule["min_pass_grade"]
        if have is None: conf.append("O Level %s at grade %s or better"%(s,need))
        elif O_ORDER.get(have,0)<O_ORDER[need]: fails.append("O Level %s needs grade %s or better (you gave %s)"%(s,need,have))
    return fails,conf
def norm_o(k):
    k=k.strip().lower()
    m={"english":"English Language","english language":"English Language","maths":"Mathematics","math":"Mathematics","mathematics":"Mathematics",
       "science":"Science","combined science":"Combined Science","integrated science":"Combined Science"}
    return m.get(k,k.title())
def find_o(oo,s):
    if s in oo: return oo[s]
    if s=="Science":
        for c in ("Science","Combined Science","Biology","Chemistry","Physics","Integrated Science"):
            if c in oo: return oo[c]
    if s=="Combined Science":
        for c in ("Combined Science","Science","Integrated Science"):
            if c in oo: return oo[c]
    return None
def check(a_level,o_level=None):
    passed={};notes=[];failed_grades=[]
    for k,v in a_level.items():
        s=norm(k);g=v.strip().upper()
        if g in PASS: passed[s]=g
        else: failed_grades.append("%s (%s)"%(s,g))
    res={"eligible":[],"eligible_confirm":[],"not_eligible":[],"other_route":[]}
    for p in D["programmes"]:
        base=dict(id=p["id"],programme=p["programme"],faculty=p["faculty"],modes=p["modes"],duration=p["duration"],notes=list(p["modelling_notes"]))
        r=p["a_level_rule"]
        of,oc=o_check(p["o_level_rule"],o_level)
        if p["route"]=="a_level":
            m=match(r["slots"],passed)
            why=[]
            if m is None:
                why.append("A Level subjects/grades do not meet: "+" + ".join("/".join(s["any_of"])+(" (%s or better)"%s["min_grade"] if s.get("min_grade") else "") for s in r["slots"]))
            if r.get("min_points") and m is not None:
                best=sorted((PTS[g] for g in passed.values()),reverse=True)[:3]
                if sum(best)<r["min_points"]: why.append("needs at least %d A Level points (best three subjects give %d)"%(r["min_points"],sum(best)))
            why+=of
            if why: res["not_eligible"].append(dict(base,reasons=why)); continue
            if r.get("requires_employment"): base["notes"].append("Applicant must also be employed in a relevant field and give proof of employment.")
            if oc: res["eligible_confirm"].append(dict(base,to_confirm=oc))
            else: res["eligible"].append(base)
        elif p["route"]=="o_level_only":
            if of: res["not_eligible"].append(dict(base,reasons=of))
            elif oc: res["eligible_confirm"].append(dict(base,to_confirm=oc))
            else: res["eligible"].append(base)
        else:
            res["other_route"].append(dict(base,requirements=p["requirements_as_advertised"]))
    res["failed_a_level_grades"]=failed_grades; res["a_level_points_best_three"]=sum(sorted((PTS[g] for g in passed.values()),reverse=True)[:3])
    return res
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--a",required=True);ap.add_argument("--o");ap.add_argument("--json",action="store_true")
    a=ap.parse_args(); r=check(parse_pairs(a.a),parse_pairs(a.o) if a.o else None)
    if a.json: print(json.dumps(r,indent=1,ensure_ascii=False)); return
    print("A Level points (best three passes):",r["a_level_points_best_three"])
    if r["failed_a_level_grades"]: print("Not passes:",", ".join(r["failed_a_level_grades"]))
    for k,t in [("eligible","MEETS THE ADVERTISED REQUIREMENTS"),("eligible_confirm","MEETS A LEVEL REQUIREMENTS; O LEVEL TO CONFIRM"),("other_route","OTHER ROUTES (diploma, teaching qualification, employment; not decided by grades)")]:
        print("\n== %s: %d =="%(t,len(r[k])))
        for x in r[k]: print(" -",x["programme"],"|",x["faculty"],"|",", ".join(x["modes"]))
    print("\nNot eligible:",len(r["not_eligible"]))
if __name__=="__main__": main()
