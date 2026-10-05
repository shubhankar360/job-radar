"""Salary normalisation to annual USD.

Rates are fixed on purpose. A ranking that moves with the FX market reorders
the queue every morning for no reason; a few percent of drift does not
change whether a job is worth applying to. Update ``USD_PER`` when it does.
"""

from __future__ import annotations

import re

USD_PER = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "AUD": 0.66, "NZD": 0.60,
    "CHF": 1.12, "SEK": 0.095, "NOK": 0.093, "DKK": 0.145, "PLN": 0.25,
    "AED": 0.272, "SAR": 0.267, "SGD": 0.74, "INR": 0.012, "BRL": 0.18,
    "MXN": 0.055, "JPY": 0.0067, "ZAR": 0.055, "ILS": 0.27, "CZK": 0.043,
}

PERIOD_FACTOR = {
    "annual": 1, "yearly": 1, "year": 1, "monthly": 12, "month": 12,
    "weekly": 52, "week": 52, "fortnightly": 26, "daily": 230, "day": 230,
    "hourly": 1880, "hour": 1880,  # ~40h x 47 working weeks
}

_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR", "¥": "JPY"}
_CODE = re.compile(r"\b(" + "|".join(USD_PER) + r")\b")
_NUM = re.compile(r"(\d+(?:[.,]\d+)*)\s*(k|m|lpa|lakh|lakhs|l|cr)?\b", re.I)


def to_annual_usd(amount: float | None, currency: str | None, period: str | None) -> float | None:
    if amount is None:
        return None
    cur = (currency or "USD").upper()
    rate = USD_PER.get(cur)
    if rate is None:
        return None
    f = PERIOD_FACTOR.get((period or "annual").lower().rstrip("s"), PERIOD_FACTOR.get((period or "").lower(), 1))
    return round(float(amount) * f * rate, 2)


def _num(tok: str, suffix: str | None) -> float:
    tok = tok.replace(",", "")
    v = float(tok)
    s = (suffix or "").lower()
    if s == "k":
        v *= 1_000
    elif s == "m":
        v *= 1_000_000
    elif s in ("lpa", "lakh", "lakhs", "l"):
        v *= 100_000
    elif s == "cr":
        v *= 10_000_000
    return v


def parse_salary_text(text: str) -> tuple[float | None, float | None, str, str]:
    """Parse free text like "$120k - $150k", "€60,000–80,000 / year",
    "$45/hr", "₹80L–₹1.4Cr". Returns (min, max, currency, period) in the
    text's own currency and period; (None, None, "", "") if nothing usable.
    """
    if not text:
        return None, None, "", ""
    t = text.replace("–", "-").replace("—", "-")
    cur = ""
    for sym, code in _SYMBOL.items():
        if sym in t:
            cur = code
            break
    m = _CODE.search(t.upper())
    if m:
        cur = m.group(1)
    low = t.lower()
    period = "annual"
    if re.search(r"/\s*h(ou)?r|per hour|hourly|an hour|/hr\b", low):
        period = "hourly"
    elif re.search(r"/\s*mo(nth)?\b|per month|monthly|a month|pm\b", low):
        period = "monthly"
    elif re.search(r"/\s*day|per day|daily", low):
        period = "daily"
    nums = []
    for n, suf in _NUM.findall(t):
        try:
            v = _num(n, suf)
        except ValueError:
            continue
        if v < 1:
            continue
        nums.append((v, suf))
    if not nums:
        return None, None, cur, period
    # "$120-150k": the k on the second number applies to the first as well.
    if len(nums) >= 2 and not nums[0][1] and nums[1][1].lower() == "k" and nums[0][0] < 1000:
        nums[0] = (nums[0][0] * 1000, "k")
    vals = [v for v, _ in nums[:2]]
    # Bare small numbers with no period word are almost always thousands
    # ("$80 - $120" on a full-time role), except for hourly rates.
    if period == "annual" and all(v < 1000 for v in vals):
        vals = [v * 1000 for v in vals]
    lo, hi = min(vals), max(vals)
    return lo, hi, cur or "USD", period
