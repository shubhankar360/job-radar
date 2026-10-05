"""Aggregator boards with public feeds."""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET

from ..http import FetchError, Http
from ..models import Job
from ..salary import parse_salary_text
from ..text import html_to_text, parse_date

_EMP = {
    "full time": "full-time", "full-time": "full-time", "fulltime": "full-time", "full_time": "full-time",
    "part time": "part-time", "part-time": "part-time", "part_time": "part-time",
    "contract": "contract", "contractor": "contract", "freelance": "freelance",
    "internship": "internship", "intern": "internship", "temporary": "contract",
}


def _emp(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    return _EMP.get(str(v or "").strip().lower(), str(v or "").strip().lower())


def himalayas(http: Http, cfg: dict) -> list[Job]:
    """Himalayas search, filtered to the candidate's country server-side.

    ``country=`` returns jobs that list that country *or* are worldwide, and
    an empty ``locationRestrictions`` means worldwide on this board — which
    is why this source sets ``worldwide`` explicitly rather than leaving the
    empty list ambiguous.
    """
    country = cfg.get("country", "India")
    out: dict[str, Job] = {}
    for q in cfg.get("queries", ["ai engineer"]):
        for page in range(1, cfg.get("pages", 2) + 1):
            qs = urllib.parse.urlencode({"q": q, "country": country, "sort": "recent", "page": page})
            try:
                data = http.json(f"https://himalayas.app/jobs/api/search?{qs}")
            except FetchError:
                break
            rows = data.get("jobs") or []
            for j in rows:
                guid = j.get("guid") or j.get("applicationLink")
                if not guid or guid in out:
                    continue
                regions = j.get("locationRestrictions") or []
                out[guid] = Job(
                    source="himalayas",
                    source_id=guid.rsplit("/", 1)[-1],
                    company=j.get("companyName", ""),
                    title=j.get("title", ""),
                    url=guid,
                    apply_url=j.get("applicationLink") or guid,
                    location=", ".join(regions) or "Worldwide",
                    regions=regions,
                    worldwide=not regions,
                    remote=True,
                    employment_type=_emp(j.get("employmentType")),
                    seniority=", ".join(j.get("seniority") or []),
                    salary_min=j.get("minSalary"),
                    salary_max=j.get("maxSalary"),
                    salary_currency=j.get("currency") or "",
                    salary_period=j.get("salaryPeriod") or "annual",
                    posted_at=parse_date(j.get("pubDate")),
                    description=html_to_text(j.get("description") or j.get("excerpt")),
                    tags=list(j.get("categories") or [])[:12],
                )
            if len(rows) < 20:
                break
    return list(out.values())


def remotive(http: Http, cfg: dict) -> list[Job]:
    out = []
    for cat in cfg.get("categories", ["software-dev", "data", "ai-ml"]):
        try:
            data = http.json(f"https://remotive.com/api/remote-jobs?category={cat}")
        except FetchError:
            continue
        for j in data.get("jobs", []):
            loc = j.get("candidate_required_location") or ""
            lo, hi, cur, per = parse_salary_text(j.get("salary") or "")
            out.append(Job(
                source="remotive", source_id=str(j["id"]), company=(j.get("company_name") or "").strip(),
                title=j.get("title", ""), url=j.get("url", ""), apply_url=j.get("url", ""),
                location=loc, regions=[r.strip() for r in re.split(r"[,;/]| or ", loc) if r.strip()],
                worldwide=bool(re.search(r"worldwide|anywhere", loc, re.I)) or None,
                remote=True, employment_type=_emp(j.get("job_type", "").replace("_", " ")),
                salary_text=j.get("salary") or "", salary_min=lo, salary_max=hi,
                salary_currency=cur, salary_period=per,
                posted_at=parse_date(j.get("publication_date")),
                description=html_to_text(j.get("description")), tags=j.get("tags") or [],
            ))
    return out


def remoteok(http: Http, cfg: dict) -> list[Job]:
    data = http.json("https://remoteok.com/api")
    out = []
    for j in data[1:]:  # element 0 is the legal notice
        if not isinstance(j, dict) or not j.get("id"):
            continue
        loc = (j.get("location") or "").strip()
        out.append(Job(
            source="remoteok", source_id=str(j["id"]), company=j.get("company", ""),
            title=j.get("position", ""), url=j.get("url", ""), apply_url=j.get("apply_url") or j.get("url", ""),
            location=loc or "Remote", regions=[r.strip() for r in re.split(r"[,;/]", loc) if r.strip()],
            worldwide=bool(re.search(r"worldwide|anywhere|global", loc, re.I)) or None,
            remote=True, salary_min=j.get("salary_min") or None, salary_max=j.get("salary_max") or None,
            salary_currency="USD" if j.get("salary_min") else "", salary_period="annual",
            posted_at=parse_date(j.get("epoch") or j.get("date")),
            description=html_to_text(j.get("description")), tags=j.get("tags") or [],
        ))
    return out


def jobicy(http: Http, cfg: dict) -> list[Job]:
    out: dict[str, Job] = {}
    for ind in cfg.get("industries", ["dev", "data-science"]):
        try:
            data = http.json(f"https://jobicy.com/api/v2/remote-jobs?count=100&industry={ind}")
        except FetchError:
            continue
        for j in data.get("jobs", []):
            sid = str(j["id"])
            geo = j.get("jobGeo") or ""
            regions = [r.strip() for r in re.split(r"[,;/]|\band\b", geo) if r.strip()]
            out[sid] = Job(
                source="jobicy", source_id=sid, company=j.get("companyName", ""), title=html_to_text(j.get("jobTitle", "")),
                url=j.get("url", ""), apply_url=j.get("url", ""), location=geo, regions=regions,
                worldwide=bool(re.search(r"anywhere|worldwide", geo, re.I)) or None, remote=True,
                employment_type=_emp(j.get("jobType")), seniority=j.get("jobLevel") or "",
                salary_min=j.get("salaryMin"), salary_max=j.get("salaryMax"),
                salary_currency=j.get("salaryCurrency") or "", salary_period=(j.get("salaryPeriod") or "annual"),
                posted_at=parse_date(j.get("pubDate")), description=html_to_text(j.get("jobDescription")),
                tags=list(j.get("jobIndustry") or []),
            )
    return list(out.values())


def weworkremotely(http: Http, cfg: dict) -> list[Job]:
    out = []
    for cat in cfg.get("categories", ["remote-programming-jobs", "remote-full-stack-programming-jobs",
                                       "remote-back-end-programming-jobs", "remote-front-end-programming-jobs"]):
        try:
            raw = http.get(f"https://weworkremotely.com/categories/{cat}.rss")
        except FetchError:
            continue
        root = ET.fromstring(raw)
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            company, _, role = title.partition(":")
            if not role:
                company, role = "", title
            link = it.findtext("link") or ""
            region = it.findtext("region") or ""
            out.append(Job(
                source="weworkremotely", source_id=link.rstrip("/").rsplit("/", 1)[-1], company=company.strip(),
                title=role.strip(), url=link, apply_url=link, location=region or "Remote",
                regions=[r.strip() for r in re.split(r"[,;/]", region) if r.strip()],
                worldwide=bool(re.search(r"anywhere|worldwide", region, re.I)) or None, remote=True,
                employment_type=_emp(it.findtext("type") or ""),
                posted_at=parse_date(it.findtext("pubDate")), description=html_to_text(it.findtext("description")),
            ))
    return out
