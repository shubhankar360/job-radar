"""job-radar command line.

    python -m jobradar fetch              # pull every source into the store
    python -m jobradar rank --top 25      # print the ranked queue
    python -m jobradar prepare --top 10   # tailored CV + letter + answers per job
    python -m jobradar dashboard          # write out/index.html
    python -m jobradar serve              # dashboard with working status buttons
    python -m jobradar status <uid> applied
    python -m jobradar log "Company" "Role" applied   # something applied to elsewhere
    python -m jobradar daily              # fetch + rank + prepare + dashboard

Everything lives under a home directory (``--home`` or $JOBRADAR_HOME,
default ~/.jobradar) holding profile.json, config.json, radar.db and the
generated files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .dashboard import build as build_dashboard
from .dashboard import serve as serve_dashboard
from .http import Http
from .profile import Profile
from .rank import job_from_row, rank
from .render import answers_md, cover_letter, html_to_pdf, letter_html, render_cv
from .score import Scored
from .sources import fetch_all
from .store import STATUSES, Store
from .tailor import tailor


def home_dir(arg: str | None) -> Path:
    return Path(arg or os.environ.get("JOBRADAR_HOME") or "~/.jobradar").expanduser()


def load(home: Path) -> tuple[Profile, dict, Store]:
    prof = home / "profile.json"
    if not prof.exists():
        sys.exit(f"no profile at {prof} — copy examples/profile.example.json there and edit it")
    cfg_path = home / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    return Profile.load(prof), cfg, Store(home / "radar.db")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


def cmd_fetch(home: Path, args) -> None:
    profile, cfg, store = load(home)
    http = Http(home / "cache", ttl=args.ttl, offline=args.offline)
    print("fetching:")
    jobs, report = fetch_all(http, cfg.get("sources", {}), only=args.only)
    new = store.upsert(jobs)
    store.record_run(len(jobs), report)
    print(f"{len(jobs)} postings ({new} new) · {http.requests} requests, {http.cache_hits} from cache")


def _print(scored: list[Scored], top: int) -> None:
    shown = [s for s in scored if not s.excluded][:top]
    for i, s in enumerate(shown, 1):
        j = s.job
        pay = f"${(s.usd_max or s.usd_min):,.0f}" if (s.usd_max or s.usd_min) else "—"
        print(f"{i:>3}. {s.score:5.1f}  {j.title[:58]:<58}  {j.company[:24]:<24} {pay:>9}  {s.verdict.status:<8} "
              f"{(j.age_days() or 0):>3.0f}d  {j.uid}")
    reasons: dict[str, int] = {}
    for s in scored:
        if s.excluded:
            k = s.excluded.split(":")[0]
            reasons[k] = reasons.get(k, 0) + 1
    print(f"\n{len([s for s in scored if not s.excluded])} ranked; filtered out: "
          + ", ".join(f"{v} {k}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))


def cmd_rank(home: Path, args) -> list[Scored]:
    profile, cfg, store = load(home)
    scored = rank(store, profile, active_days=args.days)
    if not getattr(args, "quiet", False):
        _print(scored, args.top)
    return scored


def prepare_one(s: Scored, profile: Profile, store: Store, home: Path, force: bool = False) -> Path:
    j = s.job
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    folder = home / "applications" / f"{day}_{slug(j.company)}_{slug(j.title)}"
    if folder.exists() and not force:
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    t = tailor(j, s, profile)
    _, pdf, pages = render_cv(t, profile, folder, "cv", j)
    if pdf:
        # A descriptive filename survives being downloaded into a recruiter's folder.
        nice = folder / f"{slug(profile.person['name']).replace('-', '_').title()}_CV_{slug(j.company)}.pdf"
        nice.write_bytes(pdf.read_bytes())
    if "bans AI-written answers" not in s.flags:
        letter = cover_letter(t, profile, j, s)
        (folder / "cover_letter.txt").write_text(letter)
        lh = folder / "cover_letter.html"
        lh.write_text(letter_html(letter, profile))
        html_to_pdf(lh, folder / "cover_letter.pdf")
    hist = store.history_for(j.key, j.company)
    (folder / "answers.md").write_text(answers_md(profile, j, s, hist))
    (folder / "job.json").write_text(json.dumps({**j.to_row(), "scored": s.to_dict(), "history": hist,
                                                 "cv_pages": pages, "dropped_bullets": t.dropped}, indent=1))
    store.set_status(uid=j.uid, key=j.key, company=j.company, title=j.title, url=j.apply_url or j.url,
                     status="queued", folder=str(folder))
    return folder


def cmd_prepare(home: Path, args) -> None:
    profile, cfg, store = load(home)
    scored = rank(store, profile, active_days=args.days)
    targets: list[Scored]
    if args.uid:
        targets = [s for s in scored if s.job.uid in args.uid]
        missing = set(args.uid) - {s.job.uid for s in targets}
        for uid in missing:
            row = store.db.execute("SELECT * FROM jobs WHERE uid=?", (uid,)).fetchone()
            if row:
                from .score import score_job
                targets.append(score_job(job_from_row(row), profile))
            else:
                print(f"unknown uid {uid}")
    else:
        queued = {a["key"] for a in store.applications()}
        targets = [s for s in scored if not s.excluded and s.score >= args.min_score and s.job.key not in queued][: args.top]
    for s in targets:
        f = prepare_one(s, profile, store, home, force=args.force)
        print(f"  {s.score:5.1f}  {s.job.company} — {s.job.title}\n         {f}")
    build_dashboard(rank(store, profile, active_days=args.days), store, home)


def cmd_dashboard(home: Path, args) -> Path:
    profile, cfg, store = load(home)
    path = build_dashboard(rank(store, profile, active_days=args.days), store, home)
    print(path)
    return path


def cmd_serve(home: Path, args) -> None:
    profile, cfg, store = load(home)

    def rebuild():
        p, _, st = load(home)
        build_dashboard(rank(st, p, active_days=args.days), st, home)

    rebuild()
    serve_dashboard(home, home / "radar.db", port=args.port, rebuild=rebuild, open_browser=not args.no_open)


def cmd_status(home: Path, args) -> None:
    _, _, store = load(home)
    store.set_status(uid=args.uid, status=args.status, notes=args.note or "")
    print(f"{args.uid} → {args.status}")


def cmd_log(home: Path, args) -> None:
    _, _, store = load(home)
    store.set_status(company=args.company, title=args.title, status=args.status, url=args.url or "",
                     notes=args.note or "", applied_at=args.date)
    print(f"logged {args.company} — {args.title}: {args.status}")


def cmd_cv(home: Path, args) -> None:
    """Untailored CVs, one per role family: the version for job boards,
    recruiters and a portfolio site. ``--public`` drops the phone number,
    because a PDF on the open web gets scraped."""
    import copy

    from .eligibility import Verdict
    from .models import Job

    profile, _, _ = load(home)
    if args.public:
        profile = copy.deepcopy(profile)
        profile.data["person"]["phone"] = ""
    out = Path(args.out).expanduser() if args.out else home / "cv"
    name = slug(profile.person["name"]).replace("-", "_").title()
    for a in args.archetype or list(profile.archetypes):
        job = Job(source="cv", source_id=a, company="", title=a, url="")
        s = Scored(job=job, score=0, verdict=Verdict("yes", ""), archetype=a, matched=[], gaps=[], level="mid",
                   years=None, usd_min=None, usd_max=None)
        stem = f"{name}_CV_{a.replace('-', '_')}" + ("_public" if args.public else "")
        _, pdf, pages = render_cv(tailor(job, s, profile), profile, out, stem)
        print(f"  {a:<18} {pages} pages  {pdf}")


def cmd_daily(home: Path, args) -> None:
    cmd_fetch(home, argparse.Namespace(ttl=args.ttl, offline=False, only=None))
    args.uid, args.force, args.min_score = None, False, args.min_score
    cmd_prepare(home, args)
    profile, _, store = load(home)
    top = [s for s in rank(store, profile, active_days=args.days) if not s.excluded][:3]
    msg = "; ".join(f"{s.job.company} ({s.score:.0f})" for s in top) or "no new matches"
    if sys.platform == "darwin":
        subprocess.run(["osascript", "-e", f'display notification "{msg}" with title "job-radar: today\'s top picks"'],
                       capture_output=True)
    print("top:", msg)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="jobradar", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", help="data directory (default $JOBRADAR_HOME or ~/.jobradar)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("fetch")
    p.add_argument("--only", nargs="*")
    p.add_argument("--ttl", type=int, default=6 * 3600)
    p.add_argument("--offline", action="store_true", help="use the cache only")

    for name in ("rank", "dashboard"):
        p = sub.add_parser(name)
        p.add_argument("--top", type=int, default=30)
        p.add_argument("--days", type=int, default=2, help="only jobs seen in the last N days")

    p = sub.add_parser("prepare")
    p.add_argument("uid", nargs="*", help="specific job uids (default: the top N not yet prepared)")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--min-score", type=float, default=55)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("serve")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--no-open", action="store_true")

    p = sub.add_parser("status")
    p.add_argument("uid")
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--note")

    p = sub.add_parser("log", help="record an application made outside job-radar")
    p.add_argument("company")
    p.add_argument("title")
    p.add_argument("status", choices=STATUSES)
    p.add_argument("--url")
    p.add_argument("--note")
    p.add_argument("--date", help="ISO date it was sent, if not today")

    p = sub.add_parser("cv", help="render untailored CVs per role family")
    p.add_argument("archetype", nargs="*")
    p.add_argument("--out")
    p.add_argument("--public", action="store_true", help="omit the phone number")

    p = sub.add_parser("daily")
    p.add_argument("--top", type=int, default=8)
    p.add_argument("--min-score", type=float, default=55)
    p.add_argument("--days", type=int, default=2)
    p.add_argument("--ttl", type=int, default=3 * 3600)

    args = ap.parse_args(argv)
    home = home_dir(args.home)
    {"fetch": cmd_fetch, "rank": cmd_rank, "prepare": cmd_prepare, "dashboard": cmd_dashboard,
     "serve": cmd_serve, "status": cmd_status, "log": cmd_log, "daily": cmd_daily, "cv": cmd_cv}[args.cmd](home, args)


if __name__ == "__main__":
    main()
