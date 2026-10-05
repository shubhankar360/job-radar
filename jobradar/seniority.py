from __future__ import annotations

import re

LEVELS = ["intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager", "director", "exec"]

_TITLE = [
    ("intern", r"\b(intern|internship|trainee|apprentice|working student|werkstudent)\b"),
    ("exec", r"\b(vp|vice president|chief|cto|ceo|head of)\b"),
    ("director", r"\bdirector\b"),
    ("manager", r"\b(manager|management)\b(?!.*\bproduct\b)"),
    ("principal", r"\b(principal|distinguished)\b"),
    ("staff", r"\bstaff\b"),
    # Architects are hired for judgement that comes from years; a junior
    # architect title is rare enough to special-case if it ever appears.
    ("senior", r"\barchitect\b(?!.*\bjunior\b)"),
    ("lead", r"\b(lead|tech lead|team lead)\b"),
    ("senior", r"\b(senior|sr\.?|snr)\b|\b(iii|iv)\b"),
    ("junior", r"\b(junior|jr\.?|entry[- ]level|graduate|new grad|associate|early[- ]career)\b|\bi\b$"),
    ("mid", r"\b(mid[- ]level|intermediate|ii)\b"),
]

_YEARS = re.compile(
    r"(\d{1,2})\s*(?:\+|plus)?\s*(?:-|–|to)?\s*(\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b[^.\n]{0,40}?"
    r"(?:experience|exp\b|professional|industry|working|building|in\b|of\b|with\b)",
    re.I,
)


def level_from_title(title: str) -> str:
    t = title.lower()
    # "Engineering Manager" is a manager; "Product Manager" is a different job
    # family and is filtered out elsewhere, so the manager rule is fine as is.
    for level, pat in _TITLE:
        if re.search(pat, t):
            return level
    return "mid"


def years_required(text: str) -> int | None:
    """Largest plausible 'N+ years' requirement in the description.

    Takes the maximum because postings stack them ("5+ years overall, 2+
    with LLMs") and the candidate has to clear all of them; ignores numbers
    over 12, which are company ages ("for 25 years we have…"), not
    requirements.
    """
    found = []
    for m in _YEARS.finditer(text or ""):
        lo = int(m.group(1))
        if 0 < lo <= 12:
            found.append(lo)
    return max(found) if found else None
