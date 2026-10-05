"""Can a candidate living in country X actually be hired for this job?

This is the filter that saves the most wasted applications. "Remote" on a
job board usually means "remote within the US" or "remote within the EU";
applying from elsewhere gets an automated rejection on the location
question. Every decision returns a reason so the ranking can be audited.

Verdicts:
  yes       the posting explicitly includes the candidate's country or region
            (or says worldwide / anywhere)
  likely    remote with no stated restriction, or a timezone band that
            covers the candidate
  relocate  on-site/hybrid abroad, but the posting offers visa sponsorship
            or relocation
  no        restricted to places the candidate cannot legally work from
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Job

# Which region words include which countries. Deliberately conservative:
# EMEA is *not* taken to include India, because in practice "Remote, EMEA"
# roles are run from a European payroll and screen on it.
REGION_MEMBERS = {
    "apac": {"india", "singapore", "australia", "japan", "philippines", "indonesia", "malaysia",
             "vietnam", "thailand", "new zealand", "south korea", "hong kong", "taiwan", "sri lanka",
             "bangladesh", "pakistan", "nepal"},
    "apj": {"india", "singapore", "australia", "japan", "philippines", "indonesia", "malaysia",
            "vietnam", "thailand", "new zealand", "south korea"},
    "asia": {"india", "singapore", "japan", "philippines", "indonesia", "malaysia", "vietnam",
             "thailand", "south korea", "hong kong", "taiwan", "sri lanka", "bangladesh", "pakistan",
             "nepal", "united arab emirates", "saudi arabia", "qatar"},
    "south asia": {"india", "sri lanka", "bangladesh", "pakistan", "nepal"},
    "middle east": {"united arab emirates", "saudi arabia", "qatar", "bahrain", "oman", "kuwait", "israel", "jordan"},
    "mena": {"united arab emirates", "saudi arabia", "qatar", "bahrain", "oman", "kuwait", "egypt", "jordan", "morocco"},
    "gcc": {"united arab emirates", "saudi arabia", "qatar", "bahrain", "oman", "kuwait"},
}

COUNTRY_ALIASES = {
    "india": ["india", "bharat", "bangalore", "bengaluru", "delhi", "new delhi", "mumbai", "pune",
              "hyderabad", "chennai", "gurgaon", "gurugram", "noida", "kolkata", "ahmedabad"],
    "united states": ["united states", "usa", "u.s.", "us only", "us-only", "us based", "us-based",
                      "remote - us", "remote, us", "remote (us", "remote us", "north america", "namer",
                      "new york", "san francisco", "seattle", "austin", "boston", "chicago", "los angeles"],
    "united kingdom": ["united kingdom", "uk", "u.k.", "england", "london", "manchester", "edinburgh", "britain", "scotland"],
    "united arab emirates": ["united arab emirates", "uae", "dubai", "abu dhabi", "sharjah"],
    "canada": ["canada", "toronto", "vancouver", "montreal"],
    "germany": ["germany", "berlin", "munich", "hamburg", "deutschland"],
    "europe": ["europe", "european union", "eu only", "eu-based", "cet", "cest", "eea"],
    "latam": ["latam", "latin america", "south america", "brazil", "argentina", "mexico", "colombia"],
    "emea": ["emea"],
}

WORLDWIDE = re.compile(r"\b(worldwide|anywhere|global(ly)?|any location|all countries|work from anywhere|fully distributed|international)\b", re.I)
SPONSOR = re.compile(r"(visa sponsorship (is )?(available|provided|offered)|(offer|provide)s? (visa )?sponsorship|we (will |can |do )?sponsor|sponsorship available|relocation (package|support|assistance)|help(s)? (you )?relocate|willing to sponsor|visa support)", re.I)
NO_SPONSOR = re.compile(r"(not able to sponsor|unable to sponsor|cannot sponsor|can't sponsor|no (visa )?sponsorship|without (the need for )?(visa )?sponsorship|must (be|have) (legally )?(authori[sz]ed|eligible|the right) to work in|right to work in the (uk|us|united)|us citizens? only|green card)", re.I)
UTC = re.compile(r"(utc|gmt)\s*([+-−])\s*(\d{1,2})(?::?(\d{2}))?(?:\s*(?:to|-|–|and)\s*(?:utc|gmt)?\s*([+-−])\s*(\d{1,2}))?", re.I)
ONSITE = re.compile(r"\b(on-?site|in[- ]office|hybrid|in person|relocat)", re.I)


@dataclass
class Verdict:
    status: str  # yes | likely | relocate | no
    reason: str

    @property
    def ok(self) -> bool:
        return self.status in ("yes", "likely", "relocate")


def _mentions(text: str, country: str) -> bool:
    for alias in COUNTRY_ALIASES.get(country, [country]):
        if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            return True
    return False


def _regions_cover(regions: list[str], country: str) -> tuple[bool, str]:
    for r in regions:
        rl = r.lower().strip()
        if rl in ("worldwide", "anywhere", "global"):
            return True, r
        if rl == country or _mentions(rl, country):
            return True, r
        for reg, members in REGION_MEMBERS.items():
            if re.search(rf"\b{reg}\b", rl) and country in members:
                return True, r
    return False, ""


def _utc_covers(text: str, offset_hours: float) -> bool | None:
    m = UTC.search(text)
    if not m:
        return None
    sign = -1 if m.group(2) in "-−" else 1
    a = sign * (int(m.group(3)) + int(m.group(4) or 0) / 60)
    if m.group(5):
        sign2 = -1 if m.group(5) in "-−" else 1
        b = sign2 * int(m.group(6))
    else:
        # "UTC+1 ± 3 hours" style overlap is common; treat a single offset as ±3h.
        a, b = a - 3, a + 3
    lo, hi = min(a, b), max(a, b)
    return lo - 0.5 <= offset_hours <= hi + 0.5


def assess(job: Job, country: str = "india", utc_offset: float = 5.5) -> Verdict:
    country = country.lower()
    loc = (job.location or "").lower()
    regions = [r for r in job.regions if r]
    desc = job.description or ""
    head = (job.title + " " + loc).lower()

    if job.worldwide:
        return Verdict("yes", "source marks it worldwide")

    covered, which = _regions_cover(regions, country)
    if covered:
        # An ATS that says isRemote=false is telling us the office matters.
        onsite = " (on-site/hybrid)" if job.remote is False else ""
        return Verdict("yes", f"open to {which}{onsite}")

    if _mentions(loc, country) or _mentions(head, country):
        if ONSITE.search(loc) and not job.remote:
            return Verdict("yes", f"in {country} (on-site/hybrid)")
        return Verdict("yes", f"location names {country}")

    if WORLDWIDE.search(loc) or (not regions and WORLDWIDE.search(desc[:1500] if desc else "")
                                 and re.search(r"remote", loc + desc[:1500], re.I)):
        return Verdict("yes", "worldwide / anywhere")

    utc = _utc_covers(loc + " " + desc[:3000], utc_offset)
    if utc:
        return Verdict("likely", "timezone band covers the candidate")

    restricted = regions or [c for c in COUNTRY_ALIASES if c != country and _mentions(loc, c)]
    if restricted:
        if SPONSOR.search(desc) and not NO_SPONSOR.search(desc):
            return Verdict("relocate", f"based in {', '.join(restricted[:3])}; sponsorship/relocation offered")
        return Verdict("no", f"restricted to {', '.join(str(r) for r in restricted[:3])}")

    if utc is False:
        return Verdict("no", "timezone band excludes the candidate")

    if NO_SPONSOR.search(desc):
        return Verdict("no", "requires existing work authorisation")

    if job.remote or "remote" in loc:
        return Verdict("likely", "remote, no location restriction stated")

    if not loc:
        return Verdict("likely", "no location given")
    return Verdict("no", f"on-site in {job.location}")
