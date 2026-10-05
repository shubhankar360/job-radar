"""Company career boards on the three ATSs with public JSON: Greenhouse,
Ashby and Lever. These are the primary source, not a mirror — the posting is
fresher here than on any aggregator, and the apply link goes straight to the
employer's form.

Board config entries look like ``{"slug": "livekit", "name": "LiveKit"}``.
A wrong slug 404s; that is reported once and skipped.
"""

from __future__ import annotations

import re

from ..http import FetchError, Http
from ..models import Job
from ..salary import parse_salary_text
from ..text import html_to_text, parse_date

_REMOTE = re.compile(r"\bremote\b|anywhere|distributed|work from home|wfh", re.I)


def _boards(cfg: dict) -> list[dict]:
    return [b if isinstance(b, dict) else {"slug": b} for b in cfg.get("boards", [])]


def _split_locations(s: str) -> list[str]:
    return [p.strip() for p in re.split(r"[;|/]|\bor\b", s or "") if p.strip()]


def greenhouse(http: Http, cfg: dict) -> list[Job]:
    out: list[Job] = []
    for b in _boards(cfg):
        slug = b["slug"]
        try:
            data = http.json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        except FetchError:
            continue
        for j in data.get("jobs", []):
            loc = (j.get("location") or {}).get("name", "")
            meta = {m.get("name", "").lower(): m.get("value") for m in j.get("metadata") or [] if isinstance(m, dict)}
            loc_type = str(meta.get("location type") or meta.get("workplace type") or "")
            desc = html_to_text(j.get("content"))
            remote = bool(_REMOTE.search(loc) or _REMOTE.search(loc_type))
            regions = _split_locations(loc)
            sal = _salary_from_text(desc)
            out.append(Job(
                source="greenhouse", source_id=str(j["id"]), company=b.get("name") or j.get("company_name") or slug,
                title=j.get("title", ""), url=j.get("absolute_url", ""), apply_url=j.get("absolute_url", ""),
                location=loc, regions=[r for r in regions if not _REMOTE.fullmatch(r)],
                remote=remote, posted_at=parse_date(j.get("updated_at")),
                first_published=parse_date(j.get("first_published")), description=desc,
                tags=[d.get("name", "") for d in j.get("departments") or []], **sal,
            ))
    return out


def ashby(http: Http, cfg: dict) -> list[Job]:
    out: list[Job] = []
    for b in _boards(cfg):
        slug = b["slug"]
        try:
            data = http.json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
        except FetchError:
            continue
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations") or []]
            locs = [x for x in locs if x]
            remote = bool(j.get("isRemote")) or (j.get("workplaceType") or "").lower() == "remote"
            comp = j.get("compensation") or {}
            sal = _ashby_salary(comp)
            emp = {"FullTime": "full-time", "PartTime": "part-time", "Contract": "contract",
                   "Intern": "internship", "Temporary": "contract"}.get(j.get("employmentType") or "", "")
            out.append(Job(
                source="ashby", source_id=j["id"], company=b.get("name") or slug, title=j.get("title", ""),
                url=j.get("jobUrl", ""), apply_url=j.get("applyUrl") or j.get("jobUrl", ""),
                location=" · ".join(locs), regions=[x for x in locs if not _REMOTE.fullmatch(x)],
                remote=remote, employment_type=emp, posted_at=parse_date(j.get("publishedAt")),
                description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                tags=[t for t in (j.get("department"), j.get("team")) if t], **sal,
            ))
    return out


def lever(http: Http, cfg: dict) -> list[Job]:
    out: list[Job] = []
    for b in _boards(cfg):
        slug = b["slug"]
        host = "api.eu.lever.co" if b.get("eu") else "api.lever.co"
        try:
            data = http.json(f"https://{host}/v0/postings/{slug}?mode=json")
        except FetchError:
            continue
        for j in data if isinstance(data, list) else []:
            cats = j.get("categories") or {}
            locs = cats.get("allLocations") or [cats.get("location") or ""]
            locs = [x for x in locs if x]
            desc = "\n".join(filter(None, [
                j.get("descriptionPlain"),
                *[(l.get("text", "") + "\n" + html_to_text(l.get("content", ""))) for l in j.get("lists") or []],
                j.get("additionalPlain"),
            ]))
            sr = j.get("salaryRange") or {}
            sal = ({"salary_min": sr.get("min"), "salary_max": sr.get("max"), "salary_currency": sr.get("currency") or "",
                    "salary_period": {"per-year-salary": "annual", "per-month-salary": "monthly",
                                      "per-hour-wage": "hourly"}.get(sr.get("interval") or "", "annual")}
                   if sr else _salary_from_text(desc))
            commitment = (cats.get("commitment") or "").lower()
            out.append(Job(
                source="lever", source_id=j["id"], company=b.get("name") or slug, title=j.get("text", ""),
                url=j.get("hostedUrl", ""), apply_url=j.get("applyUrl") or j.get("hostedUrl", ""),
                location=" · ".join(locs), regions=[x for x in locs if not _REMOTE.fullmatch(x)],
                remote=(j.get("workplaceType") == "remote") or any(_REMOTE.search(x) for x in locs),
                employment_type="internship" if "intern" in commitment else
                ("contract" if "contract" in commitment else ("full-time" if "full" in commitment else commitment)),
                posted_at=parse_date(j.get("createdAt")), description=desc, tags=[cats.get("team") or ""], **sal,
            ))
    return out


def _ashby_salary(comp: dict) -> dict:
    for tier in comp.get("compensationTiers") or []:
        for c in tier.get("components") or []:
            if (c.get("compensationType") or "").lower() == "salary" and c.get("minValue"):
                return {"salary_min": c.get("minValue"), "salary_max": c.get("maxValue"),
                        "salary_currency": c.get("currencyCode") or "USD",
                        "salary_period": {"1 YEAR": "annual", "1 MONTH": "monthly", "1 HOUR": "hourly"}.get(
                            (c.get("interval") or "1 YEAR").upper(), "annual"),
                        "salary_text": tier.get("tierSummary") or ""}
    s = comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary") or ""
    if s:
        lo, hi, cur, per = parse_salary_text(s)
        return {"salary_min": lo, "salary_max": hi, "salary_currency": cur, "salary_period": per, "salary_text": s}
    return {}


_PAY_LINE = re.compile(
    r"([^\n.]{0,80}(salary|compensation|pay range|base pay|ote|annual base)[^\n]{0,160})", re.I)


def _salary_from_text(desc: str) -> dict:
    """Pull a range out of prose ("The base salary range for this role is
    $140,000—$180,000 USD"). Only lines that both mention pay and contain a
    currency figure count, so funding amounts ("raised $40M") are ignored."""
    for m in _PAY_LINE.finditer(desc or ""):
        line = m.group(1)
        if not re.search(r"[$€£₹]|\b(USD|EUR|GBP|AED|INR)\b", line):
            continue
        lo, hi, cur, per = parse_salary_text(line)
        if lo and lo >= 10 and not re.search(r"\b(raised|funding|series|valuation)\b", line, re.I):
            return {"salary_min": lo, "salary_max": hi, "salary_currency": cur, "salary_period": per,
                    "salary_text": line.strip()[:160]}
    return {}
