"""Job sources. Each module exposes ``fetch(http, cfg) -> list[Job]``.

A source failing must never sink the run: ``fetch_all`` records the error
and carries on, because one board being down on a given morning is normal.
"""

from __future__ import annotations

from typing import Callable

from ..http import Http
from ..models import Job
from . import ats, boards, hn

SOURCES: dict[str, Callable[[Http, dict], list[Job]]] = {
    "himalayas": boards.himalayas,
    "remotive": boards.remotive,
    "remoteok": boards.remoteok,
    "jobicy": boards.jobicy,
    "weworkremotely": boards.weworkremotely,
    "hn": hn.who_is_hiring,
    "greenhouse": ats.greenhouse,
    "ashby": ats.ashby,
    "lever": ats.lever,
}


def fetch_all(http: Http, cfg: dict, only: list[str] | None = None, log=print) -> tuple[list[Job], dict]:
    jobs: list[Job] = []
    report: dict[str, str] = {}
    for name, fn in SOURCES.items():
        if only and name not in only:
            continue
        scfg = cfg.get(name, {})
        if scfg.get("enabled") is False:
            continue
        try:
            got = fn(http, scfg)
            jobs.extend(got)
            report[name] = f"{len(got)} jobs"
        except Exception as e:  # noqa: BLE001 — a broken source is reported, not fatal
            report[name] = f"error: {e}"
        log(f"  {name:<15} {report[name]}")
    return jobs, report
