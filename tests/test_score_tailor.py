import html
import re

from jobradar.render import _first_person, cover_letter, cv_html
from jobradar.score import posting_language, score_job
from jobradar.tailor import tailor

from .conftest import make_job


def test_good_fit_outranks_weaker_fits(profile, now):
    good = score_job(make_job(salary_min=60000, salary_max=90000, salary_currency="USD", worldwide=True), profile, now)
    senior = score_job(make_job(title="Senior AI Engineer", description="7+ years of experience. Kubernetes, Go.",
                                worldwide=True), profile, now)
    assert good.excluded is None and senior.excluded is None
    assert good.score > senior.score
    assert "Kubernetes" in senior.gaps and "Golang" in senior.gaps


def test_gates(profile, now):
    assert score_job(make_job(title="Account Executive"), profile, now).excluded == "title outside target roles"
    assert score_job(make_job(title="AI Engineer Manager"), profile, now).excluded == "manager-level title"
    us = score_job(make_job(location="Remote - US", regions=["United States"]), profile, now)
    assert us.excluded.startswith("not eligible") and us.score == 0


def test_every_score_part_is_explained(profile, now):
    s = score_job(make_job(worldwide=True, salary_min=50, salary_currency="USD", salary_period="hourly"), profile, now)
    total = 0.0
    for r in s.reasons:
        m = re.match(r"([+-]\d+)", r)
        total += float(m.group(1)) if m else 0
    assert abs(total - s.score) < 1e-6  # the reasons add up to the score


def test_pay_band_implies_seniority(profile, now):
    s = score_job(make_job(worldwide=True, salary_min=260000, salary_max=320000, salary_currency="USD"), profile, now)
    assert any("implies a senior hire" in r for r in s.reasons)


def test_title_rate_is_read_when_no_salary(profile, now):
    s = score_job(make_job(title="Full Stack Engineer - Fully Remote | Upto $85/hr", worldwide=True), profile, now)
    assert s.usd_max == 85 * 1880


def test_ai_ban_flag_from_text_and_list(profile, now):
    t = score_job(make_job(worldwide=True, description="Please do not use AI tools to write your answers. Python LLM RAG."), profile, now)
    assert "bans AI-written answers" in t.flags
    l = score_job(make_job(worldwide=True, company="Handwritten Inc"), profile, now)
    assert "bans AI-written answers" in l.flags


def test_relocation_and_language_penalties(profile, now):
    remote = score_job(make_job(worldwide=True), profile, now)
    reloc = score_job(make_job(location="Dubai", regions=["Dubai"], remote=False,
                               description="LLM RAG Python. We offer visa sponsorship."), profile, now)
    assert reloc.verdict.status == "relocate" and reloc.score < remote.score
    german = "Wir suchen eine Person für unser Team und du arbeitest mit der KI. " * 10
    assert posting_language(german) == "de"
    assert posting_language("We are looking for an engineer to join our team and you will work with the product. " * 5) == "en"


def _profile_texts(profile) -> set[str]:
    out = set()
    for _, _, _, b in profile.all_bullets():
        out.add(b["text"])
    return out


def test_tailored_cv_only_contains_profile_sentences(profile, now):
    """The invariant the whole design rests on: tailoring selects, never writes."""
    job = make_job(worldwide=True, description="TypeScript dashboards, PostgreSQL performance, React. " * 3)
    t = tailor(job, score_job(job, profile, now), profile)
    page = cv_html(t, profile, job)
    allowed = _profile_texts(profile) | set(profile.data.get("ml_projects", []))
    for li in re.findall(r"<li>(.*?)</li>", page, flags=re.S):
        assert li in allowed, f"invented bullet: {li}"
    skills = {it["name"] for g in profile.data["skills"] for it in g["items"]}
    skills_section = page.split("<h2>Experience</h2>")[0]
    for line in re.findall(r"<div class='skill'><b>.*?:</b> (.*?)</div>", skills_section):
        for item in line.split(" · "):
            assert html.unescape(item) in skills


def test_tailor_orders_by_relevance(profile, now):
    db = make_job(worldwide=True, title="Backend Engineer", description="PostgreSQL performance tuning and SQL. " * 3)
    t = tailor(db, score_job(db, profile, now), profile)
    assert t.experience[0]["bullets"][0]["id"] == "ex-db"
    assert t.skills[-1]["learning"]  # never promoted above real skills
    rag = make_job(worldwide=True)
    t2 = tailor(rag, score_job(rag, profile, now), profile)
    assert t2.experience[0]["bullets"][0]["id"] == "ex-rag"


def test_drop_one_respects_minimums(profile, now):
    job = make_job(worldwide=True)
    t = tailor(job, score_job(job, profile, now), profile)
    while t.drop_one():
        pass
    assert all(len(e["bullets"]) >= e.get("min_bullets", 1) for e in t.experience)


def test_cover_letter_is_first_person_and_honest_about_gaps(profile, now):
    job = make_job(worldwide=True, description="LLM RAG Python FastAPI. Experience with Kubernetes and Go required.")
    s = score_job(job, profile, now)
    letter = cover_letter(tailor(job, s, profile), profile, job, s)
    assert letter.startswith("Dear Acme hiring team,")
    assert "haven't used" in letter and "Kubernetes" in letter
    assert "can start in two weeks" in letter


def test_first_person():
    assert _first_person("Built X. Priced models first; Found Y.") == "Built X. I priced models first; I found Y."
