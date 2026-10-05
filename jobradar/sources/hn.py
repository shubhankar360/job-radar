"""Hacker News "Ask HN: Who is hiring?" — the monthly thread.

Worth the parsing trouble: founders post here themselves, a lot of the roles
never reach a job board, and many explicitly say REMOTE (GLOBAL). Posts
follow a loose ``Company | Role | Location | Remote | Salary`` convention on
their first line; everything else is free text.
"""

from __future__ import annotations

import re

from ..http import Http
from ..models import Job
from ..salary import parse_salary_text
from ..text import html_to_text, parse_date

_URL = re.compile(r'href="([^"]+)"')
_ROLE_WORDS = re.compile(r"engineer|developer|scientist|designer|devrel|advocate|architect|intern|founding|ml|ai\b|analyst|researcher", re.I)


def latest_thread_id(http: Http) -> str | None:
    data = http.json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=6")
    for h in data.get("hits", []):
        if "who is hiring" in (h.get("title") or "").lower():
            return h["objectID"]
    return None


def parse_post(c: dict) -> Job | None:
    """Parse one top-level comment. Replies never reach here: only the
    thread's direct children are passed in, and those are the job posts."""
    raw = c.get("text") or ""
    if not raw:
        return None
    text = html_to_text(raw)
    first = text.split("\n", 1)[0]
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = re.sub(r"\(.*?\)", "", parts[0]).strip()[:80]
    role_parts = [p for p in parts[1:] if _ROLE_WORDS.search(p)]
    title = (role_parts[0] if role_parts else parts[1])[:140]
    sal = next((p for p in parts if re.search(r"[$€£₹]\s?\d|\d+\s?k\b", p, re.I)), "")
    # Whatever is left after company, role, pay and contract words is where.
    loc_parts = [p for p in parts[1:] if p not in (title, sal) and not _ROLE_WORDS.search(p)
                 and not re.fullmatch(r"(full[- ]?time|part[- ]?time|contract(or)?|intern(ship)?|equity|visa.*|https?://\S+|[\w.-]+\.(com|io|ai|co|dev)\S*)", p, re.I)]
    location = "; ".join(loc_parts)[:200]
    lo, hi, cur, per = parse_salary_text(sal)
    links = _URL.findall(raw)
    hn_url = f"https://news.ycombinator.com/item?id={c['id']}"
    remote = bool(re.search(r"\bremote\b", first, re.I))
    if not remote and not location:
        # HN convention is to shout REMOTE when it applies; a header without
        # it is an office job, usually in the Bay Area or New York.
        location = "On-site (location not parsed)"
    worldwide = bool(re.search(r"remote\s*\(?\s*(global|worldwide|anywhere|international)|work from anywhere", text, re.I)) or None
    return Job(
        source="hn", source_id=str(c["id"]), company=company, title=title, url=hn_url,
        apply_url=links[0].replace("&#x2F;", "/") if links else hn_url, location=location,
        remote=remote, worldwide=worldwide, salary_text=sal, salary_min=lo, salary_max=hi,
        salary_currency=cur, salary_period=per, posted_at=parse_date(c.get("created_at")),
        description=text,
    )


def who_is_hiring(http: Http, cfg: dict) -> list[Job]:
    tid = cfg.get("thread_id") or latest_thread_id(http)
    if not tid:
        return []
    item = http.json(f"https://hn.algolia.com/api/v1/items/{tid}")
    out = []
    for c in item.get("children", []):
        j = parse_post(c)
        if j:
            out.append(j)
    return out
