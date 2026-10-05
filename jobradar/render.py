"""Render a tailored CV to HTML and PDF, plus a cover letter and a form-answer
sheet.

PDFs come from headless Chrome because it is already on every developer's
machine and prints CSS exactly as the browser shows it; there is no second
layout engine to disagree with the HTML. The CV is held to a page budget by
re-rendering with the least relevant bullet removed until it fits.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import Job
from .profile import Profile
from .score import Scored
from .tailor import Tailored

CSS = """
@page { size: A4; margin: 10.5mm 12mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 8.9pt; line-height: 1.31; color: #16181d; margin: 0; }
a { color: #16181d; text-decoration: none; }
code { font-family: "SF Mono", Menlo, monospace; font-size: 8.1pt; }
header { border-bottom: 1.5pt solid #16181d; padding-bottom: 5pt; margin-bottom: 6pt; }
h1 { font-size: 19pt; letter-spacing: 1.5pt; font-weight: 700; margin: 0 0 1pt; text-transform: uppercase; }
.tagline { font-size: 9.3pt; font-weight: 600; color: #3d4350; margin-bottom: 3pt; }
.contact { font-size: 8.2pt; color: #3d4350; line-height: 1.5; }
.contact span { white-space: nowrap; }
.sep { color: #a6acb8; padding: 0 3.5pt; }
h2 { font-size: 8.9pt; font-weight: 700; text-transform: uppercase; letter-spacing: 1.1pt; margin: 8pt 0 3.5pt; padding-bottom: 1.5pt; border-bottom: .7pt solid #b9bec8; break-after: avoid; }
p { margin: 0 0 3pt; }
.summary { text-align: justify; }
.skill { margin-bottom: 1.8pt; }
.entry { margin-bottom: 5.5pt; break-inside: avoid; }
.row { display: flex; justify-content: space-between; align-items: baseline; gap: 9pt; }
.role { font-size: 9.5pt; font-weight: 700; }
.org { font-weight: 600; color: #3d4350; }
.when { font-size: 8.2pt; font-weight: 600; color: #3d4350; white-space: nowrap; }
.meta { font-size: 8.1pt; color: #5a6070; font-style: italic; margin: .5pt 0 1.5pt; }
ul { margin: 1.5pt 0 0; padding-left: 11pt; }
li { margin-bottom: 1.6pt; }
li::marker { color: #7b8290; }
b.hl, b { font-weight: 700; color: #16181d; }
.ml li { margin-bottom: 1.2pt; }
"""

LETTER_CSS = """
@page { size: A4; margin: 22mm 22mm; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.5; color: #16181d; margin: 0; }
.head { border-bottom: 1.2pt solid #16181d; padding-bottom: 6pt; margin-bottom: 16pt; }
.head h1 { font-size: 15pt; letter-spacing: 1pt; text-transform: uppercase; margin: 0 0 2pt; }
.head div { font-size: 9pt; color: #3d4350; }
p { margin: 0 0 10pt; }
"""

E = html.escape


def _contact(profile: Profile) -> str:
    p = profile.person
    first = [E(p["location"]), E(p.get("remote_line", "")), f'<a href="mailto:{E(p["email"])}">{E(p["email"])}</a>', E(p["phone"])]
    links = []
    for l in p.get("links", []):
        s = f'<a href="{E(l["url"])}">{E(l["label"])}</a>'
        if l.get("note"):
            s += f" — {E(l['note'])}"
        links.append(s)
    sep = '<span class="sep">|</span>'
    return (sep.join(f"<span>{x}</span>" for x in first if x) + "<br>" + sep.join(f"<span>{x}</span>" for x in links))


def cv_html(t: Tailored, profile: Profile, job: Job | None = None) -> str:
    """The profile's text already carries its own inline markup (<b>, <i>,
    <code>), which is why bullet and summary text is inserted unescaped.
    Everything that comes from a *job posting* is escaped."""
    parts = [f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'><title>{E(profile.person['name'])} — CV"
             f"{(' — ' + E(job.company)) if job else ''}</title><style>{CSS}</style></head><body>"]
    parts.append(f"<header><h1>{E(profile.person['name'])}</h1><div class='tagline'>{E(t.headline)}</div>"
                 f"<div class='contact'>{_contact(profile)}</div></header>")
    parts.append(f"<section><h2>Summary</h2><p class='summary'>{t.summary}</p></section>")
    parts.append("<section><h2>Technical Skills</h2>")
    for g in t.skills:
        parts.append(f"<div class='skill'><b>{E(g['group'])}:</b> {' · '.join(E(i) for i in g['items'])}</div>")
    parts.append("</section><section><h2>Experience</h2>")
    for e in t.experience:
        parts.append(f"<div class='entry'><div class='row'><div><span class='role'>{E(e['role'])}</span> "
                     f"<span class='org'>— {E(e['org'])}</span></div><div class='when'>{E(e['when'])}</div></div>")
        if e.get("meta"):
            parts.append(f"<div class='meta'>{E(e['meta'])}</div>")
        parts.append("<ul>" + "".join(f"<li>{b['text']}</li>" for b in e["bullets"]) + "</ul></div>")
    gh = next((l["label"] for l in profile.person.get("links", []) if "github" in l["url"]), "")
    parts.append(f"</section><section><h2>Projects{(' — ' + E(gh)) if gh else ''}</h2>")
    for p in t.projects:
        if not p["bullets"]:
            continue
        parts.append(f"<div class='entry'><div class='row'><div><span class='role'>{E(p['name'])}</span> "
                     f"<span class='org'>— {E(p['tagline'])}</span></div><div class='when'>{E(p['stack'])}</div></div>")
        parts.append("<ul>" + "".join(f"<li>{b['text']}</li>" for b in p["bullets"]) + "</ul></div>")
    parts.append("</section>")
    if t.ml_projects:
        parts.append("<section><h2>Machine Learning Projects</h2><ul class='ml'>"
                     + "".join(f"<li>{x}</li>" for x in t.ml_projects) + "</ul></section>")
    edu = profile.data.get("education", [])
    if edu:
        parts.append("<section><h2>Education</h2>")
        for ed in edu:
            parts.append(f"<div class='entry' style='margin-bottom:2pt'><div class='row'><div><span class='role'>{E(ed['what'])}</span> "
                         f"<span class='org'>— {E(ed['where'])}</span></div><div class='when'>{E(ed['when'])}</div></div></div>")
        if profile.data.get("education_note"):
            parts.append(f"<p style='margin-top:2pt'>{E(profile.data['education_note'])}</p>")
        parts.append("</section>")
    if profile.data.get("additional"):
        parts.append("<section><h2>Additional</h2>" + "".join(f"<div class='skill'>{x}</div>" for x in profile.data["additional"]) + "</section>")
    parts.append("</body></html>")
    return "".join(parts)


def chrome_path() -> str | None:
    for c in [os.environ.get("CHROME"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]:
        if c and Path(c).exists():
            return c
    return None


def html_to_pdf(html_path: Path, pdf_path: Path) -> bool:
    chrome = chrome_path()
    if not chrome:
        return False
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf_path}", html_path.resolve().as_uri()],
                   check=True, capture_output=True, timeout=90)
    return pdf_path.exists()


def pdf_pages(pdf_path: Path) -> int:
    counts = [int(x) for x in re.findall(rb"/Count (\d+)", pdf_path.read_bytes())]
    return max(counts) if counts else 0


def render_cv(t: Tailored, profile: Profile, out_dir: Path, stem: str, job: Job | None = None,
              max_pages: int = 2) -> tuple[Path, Path | None, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path, pdf_path = out_dir / f"{stem}.html", out_dir / f"{stem}.pdf"
    for _ in range(12):
        html_path.write_text(cv_html(t, profile, job))
        if not html_to_pdf(html_path, pdf_path):
            return html_path, None, 0
        n = pdf_pages(pdf_path)
        if n <= max_pages or not t.drop_one():
            return html_path, pdf_path, n
    return html_path, pdf_path, pdf_pages(pdf_path)


# -- cover letter --------------------------------------------------------------

HOOKS = {
    "ai-engineer": "I build LLM systems end to end and run them in production, and I measure them before I claim anything about them.",
    "forward-deployed": "I build LLM features alongside the people who use them, and turning a customer's problem into a system that works is the part of the job I am best at.",
    "ai-training": "I write and review code every day, and I have published work on evaluating LLM systems rigorously, including results that went against expectation.",
    "full-stack": "I am the only engineer on a live production platform, so I own everything from the database to the pixels, and I test against the real system as well as the convenient one.",
    "frontend-creative": "I care about how an interface feels and I measure it: frame budgets, payload sizes, and what the browser actually renders.",
    "devrel": "I build AI developer tooling and I explain it in writing, with every demo runnable from a clean checkout.",
    "automation": "I build AI automations that run unattended in production, and I price and test them before I trust them.",
    "ml-data": "I work from measurement, across classical ML and LLM systems, and I publish results even when they disagree with the consensus.",
}


def _plain(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s))


_VERB = r"(?:[A-Z][a-z]+ed|Built|Ran|Shipped|Caught|Rebuilt|Wrote|Found|Led|Made|Took|Chose|Cut|Set)"


def _first_person(text: str) -> str:
    """CV bullets drop the subject ("Priced models before…"); a letter
    cannot. Re-insert "I" before each sentence-initial past-tense verb."""
    return re.sub(rf"(?<=[.;] )({_VERB})\b", lambda m: "I " + m.group(1).lower(), text)


def _sentence(b: dict, owner: dict) -> str:
    # "(below)" points at the CV's projects section, which a letter lacks.
    text = _first_person(_plain(b["text"])).replace(" (below)", " (on my GitHub)")
    if "role" in owner:
        first, rest = text.split(" ", 1) if " " in text else (text, "")
        if re.fullmatch(_VERB, first):
            return f"At {owner['org'].split(' (')[0].split(',')[0]}, I {first.lower()} {rest}"
        return text
    return f"{owner['name']} ({owner.get('url', '').replace('https://', '')}) — {owner['tagline']}: {text}"


def cover_letter(t: Tailored, profile: Profile, job: Job, scored: Scored) -> str:
    """A short, plain letter assembled from the same evidence as the CV.
    Returns plain text; the caller decides whether to use it at all (it is
    never produced for postings that ban AI-assisted answers)."""
    pieces = []
    for section in (t.experience, t.projects):
        for owner in section:
            for b in owner["bullets"][:1]:
                pieces.append((b["_rel"], _sentence(b, owner)))
    pieces.sort(key=lambda x: x[0], reverse=True)
    evidence = [p for _, p in pieces[:2]]
    named = [m for m in scored.matched if m not in ("LLMs",)][:4]
    lines = [f"Dear {job.company} hiring team,", ""]
    lines.append(f"I'm applying for the {job.title} role. {HOOKS.get(t.archetype, HOOKS['ai-engineer'])}")
    lines.append("")
    if named:
        lines.append(f"The posting asks for {', '.join(named[:-1]) + ' and ' + named[-1] if len(named) > 1 else named[0]}, "
                     "which is the work I've been doing:")
        lines.append("")
    for e in evidence:
        lines.append(f"- {e}")
    lines.append("")
    real_gaps = [g for g in t.gaps][:2]
    if real_gaps:
        lines.append(f"To be straightforward about gaps: I haven't used {' or '.join(real_gaps)} in production yet. "
                     "I learn by building and measuring, and every repo linked on my CV shows how quickly that turns into shipped, tested work.")
        lines.append("")
    a = profile.data.get("answers", {})
    lines.append(a.get("letter_logistics") or
                 "I can work as a contractor or through an employer of record, and I can start within a week.")
    lines.append("")
    lines.append("Thank you for reading — code, tests and the live platform are all linked on the CV.")
    lines.append("")
    lines.append(profile.person["name"])
    lines.append(f"{profile.person['email']} · {profile.person['phone']}")
    return "\n".join(lines)


def letter_html(text: str, profile: Profile) -> str:
    paras = []
    buf: list[str] = []
    for line in text.split("\n") + [""]:
        if line.strip():
            buf.append(E(line))
        elif buf:
            paras.append("<p>" + "<br>".join(buf) + "</p>")
            buf = []
    p = profile.person
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{E(p['name'])} — Cover letter</title>"
            f"<style>{LETTER_CSS}</style></head><body><div class='head'><h1>{E(p['name'])}</h1>"
            f"<div>{E(p['location'])} · {E(p['email'])} · {E(p['phone'])}</div></div>{''.join(paras)}</body></html>")


def answers_md(profile: Profile, job: Job, scored: Scored, hist: dict | None = None) -> str:
    a = profile.data.get("answers", {})
    pay = ""
    if scored.usd_min or scored.usd_max:
        pay = f"${(scored.usd_min or 0):,.0f}–${(scored.usd_max or 0):,.0f}/yr (normalised)"
    lines = [f"# {job.title} — {job.company}", "",
             f"- **Apply:** {job.apply_url or job.url}",
             f"- **Posting:** {job.url}",
             f"- **Location:** {job.location or '—'}  ·  eligibility **{scored.verdict.status}** ({scored.verdict.reason})",
             f"- **Pay:** {job.salary_text or pay or 'not listed'}",
             f"- **Score:** {scored.score:.0f}  ·  role family `{scored.archetype}`  ·  level {scored.level}"
             + (f"  ·  asks {scored.years}+ yrs" if scored.years else ""),
             f"- **Skills it names that you have:** {', '.join(scored.matched) or '—'}",
             f"- **Gaps to address honestly:** {', '.join(scored.gaps) or 'none detected'}"]
    if scored.flags:
        lines.append(f"- **Flags:** {', '.join(scored.flags)}")
    if hist:
        lines.append(f"- **History:** first seen {str(hist.get('first_seen', ''))[:10]}, reposts {hist.get('reposts', 0)}, "
                     f"company opened {hist.get('company_new_roles_30d', 0)} roles in 30 days, seen on {', '.join(hist.get('sources', []))}")
    if "bans AI-written answers" in scored.flags:
        lines += ["", "> **This employer bans AI-written answers.** No cover letter was generated. "
                  "Write every free-text answer yourself, in your own words."]
    lines += ["", "## Standard answers (your facts — copy into the form)", ""]
    for k, v in a.items():
        lines.append(f"**{k.replace('_', ' ').capitalize()}:** {v}  ")
    lines += ["", "## Why the engine ranked it here", ""] + [f"- {r}" for r in scored.reasons]
    return "\n".join(lines) + "\n"
