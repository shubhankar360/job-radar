from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Job:
    """One posting, normalised across every source.

    Salary fields are always annual USD after normalisation (see salary.py);
    the original wording is kept in ``salary_text`` so nothing is lost.
    """

    source: str
    source_id: str
    company: str
    title: str
    url: str
    apply_url: str = ""
    location: str = ""
    # Explicit country / region restrictions the source gave us. Empty list
    # means the source said nothing, *not* that the job is worldwide; sources
    # that do mean "worldwide" by an empty list set ``worldwide`` instead.
    regions: list[str] = field(default_factory=list)
    worldwide: bool | None = None
    remote: bool | None = None
    employment_type: str = ""  # full-time | part-time | contract | internship | freelance
    seniority: str = ""  # as given by the source, if any
    salary_text: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""  # annual | monthly | hourly ...
    posted_at: datetime | None = None
    first_published: datetime | None = None  # Greenhouse exposes the original post date
    description: str = ""  # plain text
    tags: list[str] = field(default_factory=list)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def key(self) -> str:
        """Identity of the *role*, independent of source and posting id.

        Used to spot the same job on two boards and the same job reposted
        under a new id, which is the strongest ghost-job signal there is.
        """
        return role_key(self.company, self.title)

    def age_days(self, now: datetime | None = None) -> float | None:
        if not self.posted_at:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0.0, (now - self.posted_at).total_seconds() / 86400)

    def to_row(self) -> dict:
        d = asdict(self)
        for k in ("posted_at", "first_published"):
            d[k] = d[k].isoformat() if d[k] else None
        return d


_NOISE = re.compile(r"\b(remote|hybrid|onsite|on-site|f/m/d|m/w/d|m/f/d|w/m/d|all genders)\b")


def role_key(company: str, title: str) -> str:
    c = re.sub(r"[^a-z0-9]+", " ", company.lower())
    c = re.sub(r"\b(inc|ltd|llc|gmbh|limited|corp|co|technologies|labs?)\b", " ", c)
    t = _NOISE.sub(" ", title.lower())
    t = re.sub(r"\([^)]*\)", " ", t)  # "(EMEA)", "(m/w/d)", "(R5428)"
    t = re.sub(r"[^a-z0-9]+", " ", t)
    raw = " ".join(c.split()) + "|" + " ".join(t.split())
    return hashlib.sha1(raw.encode()).hexdigest()[:16]
