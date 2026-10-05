"""Rank jobs for one candidate.

The score is a sum of named, bounded parts, and every part leaves a reason
string behind. A ranking you cannot explain is a ranking you cannot fix,
and the first thing anyone does with a list like this is ask "why is *that*
at the top?".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .eligibility import Verdict, assess
from .models import Job
from .profile import Profile
from .salary import parse_salary_text, to_annual_usd
from .seniority import level_from_title, years_required
from .vocab import tech_in

AI_BAN = re.compile(
    r"(do not|don't|please (do )?not|must not|refrain from)\s+(use|using)\s+(ai|chatgpt|llms?|generative)"
    r"|without (the use of |using )?(ai|chatgpt|generative ai)( tools)?( assistance)?"
    r"|ai[- ]generated (answers|responses|content|applications)[^.]{0,60}(disqualif|reject|not be considered)"
    r"|(answers|responses)[^.]{0,40}(must|should) be (written )?(in )?your own words",
    re.I,
)

_STOP = {
    "en": {"the", "and", "with", "you", "our", "for", "are", "will", "your", "team"},
    "de": {"und", "der", "die", "das", "mit", "wir", "sie", "für", "eine", "unser", "deine", "du"},
    "es": {"y", "el", "la", "los", "con", "para", "una", "nuestro", "tu", "experiencia", "equipo"},
    "pt": {"e", "o", "os", "com", "para", "uma", "nosso", "você", "experiência", "equipe", "não"},
    "fr": {"et", "le", "la", "les", "avec", "pour", "une", "nous", "vous", "notre", "équipe"},
    "nl": {"en", "het", "een", "met", "voor", "wij", "jij", "onze", "je", "ervaring"},
}


def posting_language(text: str) -> str:
    """Crude stop-word vote. It only has to tell 'English' from 'not', and a
    posting written in German almost always wants German in the interview."""
    words = re.findall(r"[a-zäöüßéèêáíóúãõçñ]+", (text or "")[:3000].lower())
    if len(words) < 40:
        return "en"
    counts = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOP.items()}
    best = max(counts, key=counts.get)
    return best if best != "en" and counts[best] > counts["en"] * 1.3 else "en"


LEVEL_POINTS ={"intern": 4, "junior": 10, "mid": 5, "senior": -10, "lead": -14, "staff": -24, "principal": -28}
EXCLUDED_LEVELS = {"manager", "director", "exec"}


@dataclass
class Scored:
    job: Job
    score: float
    verdict: Verdict
    archetype: str | None
    matched: list[str]
    gaps: list[str]
    level: str
    years: int | None
    usd_min: float | None
    usd_max: float | None
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    excluded: str | None = None  # why it is hidden, if it is

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 1), "verdict": self.verdict.status, "verdict_reason": self.verdict.reason,
            "archetype": self.archetype, "matched": self.matched, "gaps": self.gaps, "level": self.level,
            "years": self.years, "usd_min": self.usd_min, "usd_max": self.usd_max, "flags": self.flags,
            "reasons": self.reasons, "excluded": self.excluded,
        }


def detect_archetype(title: str, profile: Profile) -> tuple[str | None, float]:
    best, best_w = None, 0.0
    for name, a in profile.archetypes.items():
        for pat in a.get("title", []):
            if re.search(pat, title, re.I) and a.get("weight", 20) > best_w:
                best, best_w = name, float(a.get("weight", 20))
    return best, best_w


_TITLE_PAY = re.compile(r"(up\s*to|upto|from)?\s*[$€£]\s?\d[\d,.]*\s*k?\s*(-|–|to)?\s*([$€£]\s?\d[\d,.]*\s*k?)?\s*(/\s*h(ou)?r|per hour|/\s*yr|/\s*year|/\s*mo)?", re.I)


def _usd(job: Job) -> tuple[float | None, float | None]:
    lo = to_annual_usd(job.salary_min, job.salary_currency, job.salary_period)
    hi = to_annual_usd(job.salary_max, job.salary_currency, job.salary_period) or lo
    if lo is None and hi is None:
        # Contract marketplaces put the rate in the title: "… | Upto $85/hr".
        m = _TITLE_PAY.search(job.title)
        if m and re.search(r"\d", m.group(0)):
            a, b, cur, per = parse_salary_text(m.group(0))
            lo = to_annual_usd(a, cur, per)
            hi = to_annual_usd(b, cur, per) or lo
    return lo, hi


def score_job(job: Job, profile: Profile, now: datetime | None = None) -> Scored:
    now = now or datetime.now(timezone.utc)
    prefs = profile.prefs
    text = f"{job.title}\n{job.description}"
    reasons: list[str] = []
    flags: list[str] = []
    s = 0.0

    # Cheapest gates first: most postings fail on the title alone, and the
    # eligibility and salary work is wasted on them.
    archetype, arch_w = detect_archetype(job.title, profile)
    level = level_from_title(job.title)
    if job.employment_type == "internship":
        level = "intern"
    base = dict(job=job, archetype=archetype, level=level)

    def out(score, excluded=None, matched=(), gaps=(), verdict=None, years=None, usd=(None, None)):
        return Scored(score=score, matched=list(matched), gaps=list(gaps), flags=flags, reasons=reasons,
                      excluded=excluded, verdict=verdict or Verdict("no", "not assessed"), years=years,
                      usd_min=usd[0], usd_max=usd[1], **base)

    if not archetype:
        return out(0, "title outside target roles")
    if level in EXCLUDED_LEVELS:
        return out(0, f"{level}-level title")
    if level == "intern" and not prefs.get("internships", True):
        return out(0, "internships switched off")
    verdict = assess(job, prefs.get("country", "india"), prefs.get("utc_offset", 5.5))
    if not verdict.ok:
        return out(0, f"not eligible: {verdict.reason}", verdict=verdict)
    years = years_required(job.description)
    usd_min, usd_max = _usd(job)
    full = dict(verdict=verdict, years=years, usd=(usd_min, usd_max))

    # 1. role fit
    s += arch_w
    reasons.append(f"+{arch_w:.0f} title fits '{archetype}'")

    # 2. skills the candidate actually has that the posting names
    matched, mweight = [], 0.0
    for sk, pats in profile.skill_patterns():
        if any(p.search(text) for p in pats):
            matched.append(sk.name)
            mweight += sk.weight
    skill_pts = min(30.0, mweight * 2)
    s += skill_pts
    if matched:
        reasons.append(f"+{skill_pts:.0f} skills named: {', '.join(matched[:6])}{'…' if len(matched) > 6 else ''}")

    # 3. what it asks for that the candidate lacks
    gaps = sorted(tech_in(text) - profile.covered_vocab() - set(matched))
    if gaps:
        pen = min(12.0, 2.0 * len(gaps))
        s -= pen
        reasons.append(f"-{pen:.0f} asks for {', '.join(gaps[:5])}{'…' if len(gaps) > 5 else ''}")

    # 4. level and years
    lp = LEVEL_POINTS.get(level, 0)
    if lp:
        s += lp
        reasons.append(f"{lp:+d} {level} level")
    max_years = prefs.get("comfortable_years", 2)
    if years is not None:
        if years <= max_years:
            s += 5
            reasons.append(f"+5 asks {years}+ yrs")
        else:
            yp = -min(20, 5 * (years - max_years))
            s += yp
            reasons.append(f"{yp:+d} asks {years}+ yrs")

    # 5. pay
    pay = usd_max or usd_min
    if pay:
        if level == "intern":
            pp = 10 if pay >= 24_000 else (4 if pay >= 9_000 else -6)
        else:
            pp = 20 if pay >= 120_000 else 15 if pay >= 80_000 else 10 if pay >= 50_000 else 5 if pay >= 30_000 else -10
        s += pp
        reasons.append(f"{pp:+d} pays up to ${pay:,.0f}/yr")
        if pay < prefs.get("min_usd", 0) and level != "intern":
            flags.append("below your floor")
        # A pay band is the most honest seniority signal a posting has: a
        # $250k+ floor is a senior/staff hire whatever the title says.
        floor = usd_min or pay
        if floor >= 200_000 and level in ("mid", "junior") and job.employment_type not in ("contract", "freelance"):
            s -= 12
            reasons.append(f"-12 pay floor ${floor:,.0f} implies a senior hire")
    else:
        flags.append("no salary listed")

    # 6. freshness and how long it has been open
    age = job.age_days(now)
    if age is not None:
        fp = 10 if age <= 3 else 7 if age <= 7 else 3 if age <= 14 else 0 if age <= 30 else -8 if age <= 60 else -15
        if fp:
            s += fp
            reasons.append(f"{fp:+d} posted {age:.0f}d ago")
    if job.first_published:
        open_days = (now - job.first_published).days
        if open_days > 120:
            s -= 5
            flags.append(f"open {open_days // 30} months")
            reasons.append("-5 open for months (evergreen or hard to fill)")

    # 7. eligibility certainty
    # Relocation is a real path (UK and UAE employers sponsor visas) but it is
    # slower and riskier than remote, which is what the candidate asked for.
    ep = {"yes": 8, "likely": 2, "relocate": -18}[verdict.status]
    s += ep
    reasons.append(f"{ep:+d} eligibility {verdict.status}: {verdict.reason}")
    if verdict.status == "relocate":
        flags.append("on-site abroad (visa offered)")
    elif "on-site/hybrid" in verdict.reason:
        home = [c.lower() for c in prefs.get("home_cities", [])]
        if any(c in job.location.lower() for c in home):
            flags.append("office in your city")
            reasons.append("+0 on-site, but in your city")
        else:
            s -= 6
            flags.append("on-site / hybrid")
            reasons.append("-6 not remote")

    lang = posting_language(job.description)
    if lang != "en":
        s -= 15
        flags.append(f"posting in {lang} — likely needs that language")
        reasons.append(f"-15 written in {lang}")

    # 8. preferred markets
    pref_regions = [r.lower() for r in prefs.get("preferred_markets", [])]
    blob = f"{job.location} {job.salary_currency} {job.description[:2000]}".lower()
    hits = [r for r in pref_regions if re.search(rf"\b{re.escape(r)}\b", blob)]
    if hits:
        s += 4
        reasons.append(f"+4 market: {hits[0]}")

    if job.employment_type == "part-time":
        s -= 5
        reasons.append("-5 part-time")
    # Some employers state the ban only on the live form, never in the
    # posting, so a known list backs up the text match.
    banned = {c.lower() for c in prefs.get("ai_ban_companies", [])}
    if AI_BAN.search(job.description) or job.company.lower() in banned:
        flags.append("bans AI-written answers")

    return out(round(max(0.0, min(100.0, s)), 1), matched=matched, gaps=gaps, **full)
