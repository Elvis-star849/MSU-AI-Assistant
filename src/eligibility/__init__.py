"""Deterministic MSU eligibility checker (January/February 2027 intake). No AI: rules come from
MSU_Eligibility_Rules.json in this folder. Public API: check(a_level, o_level=None) and parse_pairs(text).
The checker's own tests: cd src/eligibility && python test_checker.py
"""
from src.eligibility.eligibility_checker import D as RULES, check, norm, parse_pairs

__all__ = ["RULES", "check", "norm", "parse_pairs"]
