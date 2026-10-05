"""Turn the store into a ranked queue: dedupe, score, apply history."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .models import Job
from .profile import Profile
from .score import Scored, score_job
from .store import Store
from .text import parse_date

# When the same role is on several boards, keep the copy whose apply link
# goes to the employer: their ATS first, a founder's HN post next, then the
# aggregators (whose links often bounce through their own page).
SOURCE_RANK = {"greenhouse": 0, "ashby": 0, "lever": 0, "hn": 1, "himalayas": 2, "jobicy": 3,
               "weworkremotely": 3, "remotive": 3, "remoteok": 4}


def job_from_row(row) -> Job:
    d = json.loads(row["data"])
    d["posted_at"] = parse_date(d.get("posted_at"))
    d["first_published"] = parse_date(d.get("first_published"))
    return Job(**d)


def rank(store: Store, profile: Profile, *, active_days: int = 2, now: datetime | None = None) -> list[Scored]:
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=active_days)).isoformat()
    best: dict[str, Job] = {}
    for row in store.latest(since):
        j = job_from_row(row)
        cur = best.get(j.key)
        if cur is None or SOURCE_RANK.get(j.source, 9) < SOURCE_RANK.get(cur.source, 9):
            if cur is not None and not j.salary_min and cur.salary_min:
                j.salary_min, j.salary_max = cur.salary_min, cur.salary_max
                j.salary_currency, j.salary_period = cur.salary_currency, cur.salary_period
            best[j.key] = j

    by_key, velocity = store.history_bulk()
    applied = store.applied_keys()
    caps = {k.lower(): v for k, v in profile.prefs.get("company_caps", {}).items()}
    blocked = {c.lower() for c in profile.prefs.get("blocked_companies", [])}
    out: list[Scored] = []
    updates: list[tuple[float, str, str]] = []
    for key, j in best.items():
        sc = score_job(j, profile, now)
        hist = {**by_key.get(key, {"reposts": 0, "first_seen": None, "sources": [j.source]}),
                "company_new_roles_30d": velocity.get(j.company.lower(), 0)}
        if not sc.excluded:
            if hist["reposts"] >= 2:
                sc.flags.append(f"reposted {hist['reposts']}x")
                sc.score = max(0.0, sc.score - 4)
                sc.reasons.append(f"-4 reposted {hist['reposts']} times")
            if hist["company_new_roles_30d"] >= 5:
                sc.flags.append(f"{hist['company_new_roles_30d']} open roles")
            # Prepared-but-not-sent jobs stay in the queue; that is where
            # their tailored CV and apply button live.
            if key in applied and applied[key] != "queued":
                sc.excluded = f"already {applied[key]}"
            cap = caps.get(j.company.lower())
            if cap and store.company_count(j.company, cap[1]) >= cap[0]:
                sc.excluded = sc.excluded or f"company cap {cap[0]} per {cap[1]}d reached"
            if j.company.lower() in blocked:
                sc.excluded = sc.excluded or "blocked company"
            updates.append((sc.score, json.dumps({**sc.to_dict(), "history": hist}), j.uid))
        out.append(sc)
    store.save_scores(updates)
    out.sort(key=lambda s: (s.excluded is None, s.score), reverse=True)
    return out
