from datetime import timedelta

from jobradar.rank import rank
from jobradar.store import Store

from .conftest import NOW, make_job


def test_repost_is_same_source_new_id(tmp_path):
    st = Store(tmp_path / "r.db")
    st.upsert([make_job(source_id="1"), make_job(source="himalayas", source_id="h1")])  # syndication
    assert st.history_for(make_job().key, "Acme")["reposts"] == 0
    st.upsert([make_job(source_id="2"), make_job(source_id="3")])  # two reposts on the same board
    h = st.history_for(make_job().key, "Acme")
    assert h["reposts"] == 2 and h["sources"] == ["ashby", "himalayas"]
    by_key, vel = st.history_bulk()
    assert by_key[make_job().key]["reposts"] == 2 and vel["acme"] == 1


def test_role_key_ignores_noise():
    a = make_job(company="Acme Inc.", title="AI Engineer (Remote, EMEA)")
    b = make_job(company="acme", title="AI Engineer - Remote")
    assert a.key == b.key


def test_rank_dedupes_and_respects_history(tmp_path, profile):
    st = Store(tmp_path / "r.db")
    st.upsert([
        make_job(source="himalayas", source_id="h1", worldwide=True, salary_min=70000, salary_currency="USD"),
        make_job(source="ashby", source_id="a1", worldwide=True),  # same role, employer's ATS wins
        make_job(company="Other", source_id="o1", title="Python Developer", worldwide=True),
        make_job(company="Bigco", source_id="b1", title="ML Engineer", worldwide=True),
    ])
    for t in ("One", "Two", "Three"):
        st.set_status(company="Bigco", title=t, status="applied")
    st.set_status(company="Other", title="Python Developer", status="applied")
    out = {s.job.company: s for s in rank(st, profile, now=NOW + timedelta(hours=1))}
    assert out["Acme"].job.source == "ashby" and out["Acme"].job.salary_min == 70000  # salary carried over
    assert out["Other"].excluded == "already applied"
    assert "company cap" in out["Bigco"].excluded


def test_queued_jobs_stay_visible(tmp_path, profile):
    st = Store(tmp_path / "r.db")
    j = make_job(worldwide=True)
    st.upsert([j])
    st.set_status(uid=j.uid, status="queued", folder="/tmp/x")
    assert rank(st, profile, now=NOW + timedelta(hours=1))[0].excluded is None
    st.set_status(uid=j.uid, status="applied")
    assert st.applications()[0]["applied_at"]
    assert rank(st, profile, now=NOW + timedelta(hours=1))[0].excluded == "already applied"
