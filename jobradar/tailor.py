"""Evidence-constrained tailoring.

Given a job and a profile, decide *which* true things to say and in what
order: the headline and summary for the role family, the bullets most
relevant to this posting, the skills it names moved to the front of their
lines. Nothing is generated; every sentence that reaches the CV exists
verbatim in the profile. ``tests/test_tailor.py`` enforces that.

What the posting asks for and the profile lacks is reported as a gap, for
the candidate to address honestly (or to learn), never papered over.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Job
from .profile import Profile
from .score import Scored
from .text import term_regex
from .vocab import tech_in

CONCEPTS = {
    "testing": r"\btest(s|ing)?\b|\bqa\b|quality assurance|test coverage",
    "security": r"\bsecurity\b|\bsecure\b|\bauth(entication|orization)?\b|owasp|vulnerab",
    "auth": r"\bauth(entication)?\b|\blogin\b|\bsso\b|oauth",
    "billing": r"\bbilling\b|\bpayments?\b|\bsubscriptions?\b|\bstripe\b|\bcredits?\b",
    "performance": r"\bperformance\b|\blatency\b|\bfast\b|optimi[sz]",
    "frontend": r"front[- ]?end|\bui\b|\bux\b|\binterfaces?\b|\bbrowser\b",
    "backend": r"back[- ]?end|\bapis?\b|\bservices?\b|\bserver\b",
    "customer": r"\bcustomers?\b|\bclients?\b|\busers?\b|\bstakeholders?\b",
    "growth": r"\bgrowth\b|\bacquisition\b|\bconversion\b|\bmarketing\b|\bleads?\b",
    "product": r"\bproduct\b|\bshipp?(ing|ed)?\b|\bfeatures?\b",
    "cost": r"\bcost\b|\bbudget\b|\bunit economics\b|\bspend\b|\befficien",
    "measurement": r"\bmetrics?\b|\bmeasur|\bdata[- ]driven\b|\bexperiments?\b|\ba/b\b",
    "data pipeline": r"\bpipelines?\b|\betl\b|\bingest",
    "crawling": r"\bcrawl|\bscrap(e|ing)\b",
    "automation": r"\bautomat",
    "video": r"\bvideo\b|\bmedia\b|\bcontent generation\b",
    "reliability": r"\breliab|\bresilien|\buptime\b|\bincident|\bproduction\b",
    "open source": r"open[- ]source",
    "debugging": r"\bdebug|\btroubleshoot|\broot cause",
    "operations": r"\boperations\b|\bops\b",
    "communication": r"\bcommunicat|\bwriting\b|\bdocumentation\b|\bdocs\b",
    "ownership": r"\bownership\b|\bautonom|\bself[- ]starter|\bindependent",
    "search": r"\bsearch\b|\branking\b|\bretriev",
    "long-running": r"\basync\b|\bqueues?\b|\bworkflows?\b|\blong[- ]running",
    "data science": r"\bdata scien|\bstatistic|\bmodel(s|ing)\b",
    "machine learning": r"\bmachine learning\b|\bml\b",
    "quality": r"\bquality\b|\bcorrectness\b",
    "build tooling": r"\bbuild\b|\bbundl|\btooling\b",
    "pipeline": r"\bpipelines?\b",
    "data": r"\bdata\b",
}
_CONCEPT_RE = {k: re.compile(v, re.I) for k, v in CONCEPTS.items()}


def concepts_in(text: str) -> set[str]:
    return {k for k, r in _CONCEPT_RE.items() if r.search(text)}


@dataclass
class Tailored:
    archetype: str
    headline: str
    summary: str
    skills: list[dict]  # [{"group": str, "items": [str], "matched": [str]}]
    experience: list[dict]
    projects: list[dict]
    ml_projects: list[str]
    jd_terms: set[str]
    matched: list[str]
    gaps: list[str]
    dropped: list[str] = field(default_factory=list)  # bullet ids left out, lowest relevance first

    def drop_one(self) -> bool:
        """Remove the least relevant optional bullet. Used to fit two pages."""
        best = None
        for section in (self.projects, self.experience):
            for e in section:
                floor = e.get("min_bullets", 1)
                if len(e["bullets"]) <= floor:
                    continue
                b = min(e["bullets"], key=lambda b: b["_rel"])
                if best is None or b["_rel"] < best[1]["_rel"]:
                    best = (e, b)
        if best is None:
            if self.ml_projects:
                self.ml_projects.pop()
                return True
            return False
        best[0]["bullets"].remove(best[1])
        self.dropped.append(best[1]["id"])
        return True


def _lower(s: set[str]) -> set[str]:
    return {x.lower() for x in s}


def tailor(job: Job, scored: Scored, profile: Profile) -> Tailored:
    text = f"{job.title}\n{job.description}"
    archetype = scored.archetype if scored.archetype in profile.archetypes else "ai-engineer"
    # Named technologies are specific evidence; themes like "product" or
    # "customer" appear in nearly every posting, so they only break ties.
    tech = _lower(tech_in(text) | set(scored.matched))
    themes = _lower(concepts_in(text))
    jd = tech | themes

    def rel(b: dict, section_bonus: float = 0) -> float:
        tags = _lower(set(b.get("tags", [])))
        return b.get("priority", 5) + 3 * len(tags & tech) + min(3.0, 0.75 * len(tags & themes)) + section_bonus

    experience = []
    for e in profile.data.get("experience", []):
        bs = [dict(b, _rel=rel(b)) for b in e.get("bullets", [])]
        bs.sort(key=lambda b: b["_rel"], reverse=True)
        experience.append({**{k: v for k, v in e.items() if k != "bullets"}, "bullets": bs})

    projects = []
    for p in profile.data.get("projects", []):
        p_overlap = len(_lower(set(p.get("tags", []))) & tech)
        bs = [dict(b, _rel=rel(b, p_overlap)) for b in p.get("bullets", [])]
        bs.sort(key=lambda b: b["_rel"], reverse=True)
        projects.append({**{k: v for k, v in p.items() if k != "bullets"}, "bullets": bs,
                         "_rel": max((b["_rel"] for b in bs), default=0) + p_overlap})
    projects.sort(key=lambda p: p["_rel"], reverse=True)

    # Skills: within each line, what the posting names goes first; lines that
    # match more go higher. The "learning" line always stays last and is
    # never reordered into looking like production experience.
    skills = []
    for g in profile.data.get("skills", []):
        items = [it if isinstance(it, dict) else {"name": it} for it in g.get("items", [])]
        hit = []
        for it in items:
            pats = [term_regex(t) for t in [it["name"], *it.get("aliases", [])]]
            if any(p.search(text) for p in pats):
                hit.append(it["name"])
        ordered = [it["name"] for it in items if it["name"] in hit] + [it["name"] for it in items if it["name"] not in hit]
        skills.append({"group": g["group"], "items": ordered, "matched": hit, "learning": bool(g.get("learning"))})
    core = [s for s in skills if not s["learning"]]
    core.sort(key=lambda s: len(s["matched"]), reverse=True)
    skills = core + [s for s in skills if s["learning"]]

    arch = profile.archetypes.get(archetype, {})
    summaries = profile.data.get("summaries", {})
    return Tailored(
        archetype=archetype,
        headline=arch.get("headline") or profile.archetypes.get("ai-engineer", {}).get("headline", ""),
        summary=summaries.get(archetype) or summaries.get("default", ""),
        skills=skills, experience=experience, projects=projects,
        ml_projects=list(profile.data.get("ml_projects", [])), jd_terms=jd,
        matched=scored.matched, gaps=scored.gaps,
    )
