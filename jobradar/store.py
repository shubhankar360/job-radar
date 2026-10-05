"""SQLite store: every posting ever seen, every run, every application.

History is what turns a list of jobs into a judgement about them:

* **first seen / last seen** — how long a role has really been open,
  regardless of what date the board shows (boards bump dates on edit).
* **reposts** — the same company + title appearing under new ids. One repost
  is normal; three is a role that is not being filled, or not real.
* **company velocity** — how many roles a company has opened recently. A
  company hiring ten engineers this month has budget; one with a single
  evergreen listing may not.
* **your applications** — never apply twice, and respect per-company caps
  (some employers reject a fourth application in six months outright).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs(
  uid TEXT PRIMARY KEY, key TEXT NOT NULL, source TEXT, company TEXT, title TEXT,
  url TEXT, apply_url TEXT, location TEXT, posted_at TEXT, first_published TEXT,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, data TEXT NOT NULL,
  score REAL, scored TEXT
);
CREATE INDEX IF NOT EXISTS jobs_key ON jobs(key);
CREATE INDEX IF NOT EXISTS jobs_company ON jobs(company);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, at TEXT, n_jobs INTEGER, report TEXT);
CREATE TABLE IF NOT EXISTS applications(
  id INTEGER PRIMARY KEY, uid TEXT, key TEXT, company TEXT, title TEXT, url TEXT,
  status TEXT NOT NULL, applied_at TEXT, updated_at TEXT, folder TEXT, notes TEXT
);
"""

STATUSES = ["queued", "applied", "screening", "interview", "offer", "rejected", "ghosted", "withdrawn", "skipped"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # -- jobs ---------------------------------------------------------------
    def upsert(self, jobs: list[Job], seen_at: str | None = None) -> int:
        seen_at = seen_at or _now()
        new = 0
        for j in jobs:
            row = j.to_row()
            cur = self.db.execute("SELECT 1 FROM jobs WHERE uid=?", (j.uid,)).fetchone()
            if cur:
                self.db.execute(
                    "UPDATE jobs SET last_seen=?, data=?, posted_at=?, title=?, apply_url=? WHERE uid=?",
                    (seen_at, json.dumps(row), row["posted_at"], j.title, j.apply_url, j.uid))
            else:
                new += 1
                self.db.execute(
                    "INSERT INTO jobs(uid,key,source,company,title,url,apply_url,location,posted_at,first_published,"
                    "first_seen,last_seen,data) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (j.uid, j.key, j.source, j.company, j.title, j.url, j.apply_url, j.location, row["posted_at"],
                     row["first_published"], seen_at, seen_at, json.dumps(row)))
        self.db.commit()
        return new

    def record_run(self, n: int, report: dict) -> None:
        self.db.execute("INSERT INTO runs(at,n_jobs,report) VALUES(?,?,?)", (_now(), n, json.dumps(report)))
        self.db.commit()

    def save_score(self, uid: str, score: float, scored: dict) -> None:
        self.db.execute("UPDATE jobs SET score=?, scored=? WHERE uid=?", (score, json.dumps(scored), uid))

    def commit(self) -> None:
        self.db.commit()

    def history_for(self, key: str, company: str) -> dict:
        """Signals about this role and its company from everything seen so far."""
        rows = self.db.execute(
            "SELECT uid, source, posted_at, first_seen FROM jobs WHERE key=? ORDER BY first_seen", (key,)).fetchall()
        # A repost is a new id from the *same* source; the same role on two
        # different boards is syndication, not a repost.
        by_source: dict[str, set] = {}
        for r in rows:
            by_source.setdefault(r["source"], set()).add(r["uid"])
        reposts = max((len(v) - 1 for v in by_source.values()), default=0)
        first_seen = rows[0]["first_seen"] if rows else None
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        velocity = self.db.execute(
            "SELECT COUNT(DISTINCT key) FROM jobs WHERE lower(company)=lower(?) AND first_seen>=?",
            (company, since)).fetchone()[0]
        return {"reposts": reposts, "first_seen": first_seen, "sources": sorted(by_source),
                "company_new_roles_30d": velocity}

    def history_bulk(self, since_days: int = 30) -> tuple[dict, dict]:
        """``history_for`` for every key and company in two queries.

        Ranking needs these signals for thousands of jobs; asking per job
        meant a full table scan each (lower(company) defeats the index) and
        took minutes. Returns (by_key, company_velocity)."""
        by_key: dict[str, dict] = {}
        for r in self.db.execute("SELECT key, source, COUNT(*) n, MIN(first_seen) fs FROM jobs GROUP BY key, source"):
            h = by_key.setdefault(r["key"], {"reposts": 0, "first_seen": r["fs"], "sources": []})
            h["reposts"] = max(h["reposts"], r["n"] - 1)
            h["first_seen"] = min(h["first_seen"], r["fs"])
            h["sources"].append(r["source"])
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()
        velocity = {r[0]: r[1] for r in self.db.execute(
            "SELECT lower(company), COUNT(DISTINCT key) FROM jobs WHERE first_seen>=? GROUP BY lower(company)", (since,))}
        return by_key, velocity

    def save_scores(self, rows: list[tuple[float, str, str]]) -> None:
        self.db.executemany("UPDATE jobs SET score=?, scored=? WHERE uid=?", rows)
        self.db.commit()

    def latest(self, since: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM jobs"
        args: tuple = ()
        if since:
            q += " WHERE last_seen>=?"
            args = (since,)
        return self.db.execute(q, args).fetchall()

    # -- applications -------------------------------------------------------
    def applied_keys(self) -> dict[str, str]:
        rows = self.db.execute("SELECT key, status FROM applications WHERE status!='skipped'").fetchall()
        return {r["key"]: r["status"] for r in rows}

    def company_count(self, company: str, days: int) -> int:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        return self.db.execute(
            "SELECT COUNT(*) FROM applications WHERE lower(company)=lower(?) AND status NOT IN ('queued','skipped') "
            "AND applied_at>=?", (company, since)).fetchone()[0]

    def set_status(self, *, uid: str = "", key: str = "", company: str = "", title: str = "", url: str = "",
                   status: str, folder: str = "", notes: str = "", applied_at: str | None = None) -> int:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        if uid and not key:
            r = self.db.execute("SELECT key, company, title, apply_url FROM jobs WHERE uid=?", (uid,)).fetchone()
            if r:
                key, company, title, url = r["key"], company or r["company"], title or r["title"], url or r["apply_url"]
        if not key:
            from .models import role_key
            key = role_key(company, title)
        existing = self.db.execute("SELECT id, applied_at FROM applications WHERE key=?", (key,)).fetchone()
        now = _now()
        when = applied_at or (now if status not in ("queued", "skipped") else None)
        if existing:
            self.db.execute(
                "UPDATE applications SET status=?, updated_at=?, applied_at=COALESCE(applied_at, ?), "
                "folder=COALESCE(NULLIF(?, ''), folder), notes=COALESCE(NULLIF(?, ''), notes) WHERE id=?",
                (status, now, when, folder, notes, existing["id"]))
            aid = existing["id"]
        else:
            cur = self.db.execute(
                "INSERT INTO applications(uid,key,company,title,url,status,applied_at,updated_at,folder,notes) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)", (uid, key, company, title, url, status, when, now, folder, notes))
            aid = cur.lastrowid
        self.db.commit()
        return aid

    def applications(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM applications ORDER BY COALESCE(applied_at, updated_at) DESC").fetchall()
