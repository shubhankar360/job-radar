"""A single-file dashboard over the ranked queue, plus a tiny local server so
status buttons can write back to the store.

Opened as a file it is read-only (buttons show the CLI command instead);
served by ``jobradar serve`` the buttons update the database directly.
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .score import Scored
from .store import STATUSES, Store


def _row(s: Scored, prepared: dict, home: Path) -> dict:
    j = s.job
    folder = prepared.get(j.key)
    rel = os.path.relpath(folder, home / "out") if folder else None
    return {
        "uid": j.uid, "key": j.key, "company": j.company, "title": j.title, "url": j.url,
        "apply": j.apply_url or j.url, "location": j.location[:90], "source": j.source,
        "score": s.score, "verdict": s.verdict.status, "why_ok": s.verdict.reason, "arch": s.archetype,
        "level": s.level, "years": s.years, "usd": round(s.usd_max or s.usd_min or 0),
        "salary": j.salary_text[:60], "type": j.employment_type or "", "age": round(j.age_days() or 0),
        "matched": s.matched[:8], "gaps": s.gaps[:6], "flags": s.flags, "reasons": s.reasons,
        "folder": rel,
    }


def build(scored: list[Scored], store: Store, home: Path, limit: int = 300) -> Path:
    out = home / "out"
    out.mkdir(parents=True, exist_ok=True)
    apps = store.applications()
    prepared = {a["key"]: a["folder"] for a in apps if a["folder"]}
    status = {a["key"]: a["status"] for a in apps}
    visible = [s for s in scored if not s.excluded][:limit]
    rows = [dict(_row(s, prepared, home), status=status.get(s.job.key, "")) for s in visible]
    tracker = [{k: a[k] for k in a.keys()} for a in apps]
    data = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "rows": rows,
            "tracker": tracker, "statuses": STATUSES,
            "excluded": len([s for s in scored if s.excluded]), "total": len(scored)}
    tpl = (Path(__file__).parent / "dashboard.html").read_text()
    path = out / "index.html"
    path.write_text(tpl.replace("/*__DATA__*/null", json.dumps(data).replace("</", "<\\/")))
    return path


def serve(home: Path, store_path: Path, port: int = 8765, rebuild=None, open_browser: bool = True) -> None:
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(home), **kw)

        def log_message(self, *a):  # quiet
            pass

        def do_GET(self):
            if self.path in ("/", ""):
                self.send_response(302)
                self.send_header("Location", "/out/index.html")
                self.end_headers()
                return
            super().do_GET()

        def do_POST(self):
            if self.path != "/api/status":
                self.send_error(404)
                return
            # Same-origin only: the dashboard is the sole legitimate caller.
            origin = self.headers.get("Origin", "")
            if origin and not origin.startswith(f"http://localhost:{port}") and not origin.startswith(f"http://127.0.0.1:{port}"):
                self.send_error(403)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
            st = Store(store_path)
            try:
                st.set_status(uid=body.get("uid", ""), key=body.get("key", ""), company=body.get("company", ""),
                              title=body.get("title", ""), status=body["status"], notes=body.get("notes", ""))
            except (KeyError, ValueError) as e:
                self.send_error(400, str(e))
                return
            if rebuild:
                rebuild()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://localhost:{port}/out/index.html"
    print(f"dashboard on {url}  (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
