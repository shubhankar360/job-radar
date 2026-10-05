from jobradar.sources import ats, boards, fetch_all, hn

from .conftest import FakeHttp


def test_himalayas_empty_restrictions_mean_worldwide():
    http = FakeHttp({"himalayas.app/jobs/api/search": "himalayas.json"})
    jobs = boards.himalayas(http, {"queries": ["ai engineer", "python"], "pages": 1})
    assert len(jobs) == 2  # deduplicated across queries
    w = next(j for j in jobs if j.company == "Worldco")
    assert w.worldwide is True and w.salary_min == 60000 and w.description == "Build LLM agents in Python."
    i = next(j for j in jobs if j.company == "Indiaco")
    assert i.worldwide is False and i.regions == ["India", "Singapore"] and i.salary_period == "hourly"
    assert "country=India" in http.calls[0]


def test_ashby_salary_components_and_listing():
    jobs = ats.ashby(FakeHttp({"ashbyhq": "ashby.json"}), {"boards": [{"slug": "acme", "name": "Acme"}]})
    assert [j.source_id for j in jobs] == ["a1", "a3"]  # unlisted role skipped
    a1 = jobs[0]
    assert (a1.salary_min, a1.salary_max, a1.salary_currency, a1.salary_period) == (135000, 300000, "USD", "annual")
    assert a1.regions == ["North America", "APJ", "EMEA"] and a1.remote is True and a1.company == "Acme"
    a3 = jobs[1]
    assert a3.employment_type == "internship" and a3.remote is False
    assert (a3.salary_min, a3.salary_currency) == (40000, "GBP")


def test_greenhouse_salary_from_prose_ignores_funding():
    jobs = ats.greenhouse(FakeHttp({"greenhouse": "greenhouse.json"}), {"boards": ["acme"]})
    ml = jobs[0]
    assert ml.remote is True and (ml.salary_min, ml.salary_max) == (90000, 120000)
    assert ml.first_published.month == 3
    assert jobs[1].salary_min is None


def test_lever_hourly_range():
    j = ats.lever(FakeHttp({"lever.co": "lever.json"}), {"boards": ["acme"]})[0]
    assert j.employment_type == "contract" and j.salary_period == "hourly" and j.remote
    assert "3+ years" in j.description


def test_aggregators():
    r = boards.remotive(FakeHttp({"remotive": "remotive.json"}), {"categories": ["software-dev"]})[0]
    assert r.worldwide and r.company == "Remco" and r.salary_min == 80000
    o = boards.remoteok(FakeHttp({"remoteok": "remoteok.json"}), {})[0]
    assert o.title == "Full Stack Engineer" and o.regions == ["USA"]
    w = boards.weworkremotely(FakeHttp({"weworkremotely": "wwr.rss"}), {"categories": ["x"]})[0]
    assert w.company == "Sticky Co" and w.title == "AI agent engineer" and w.worldwide


def test_hn_who_is_hiring():
    http = FakeHttp({"search_by_date": "hn_search.json", "items/1": "hn_item.json"})
    jobs = hn.who_is_hiring(http, {})
    assert [j.company for j in jobs] == ["Hedge", "Tetherish"]
    hedge, teth = jobs
    assert hedge.remote is False and hedge.location.startswith("San Francisco")
    assert (hedge.salary_min, hedge.salary_max) == (180000, 250000)
    assert teth.remote and teth.worldwide and teth.apply_url == "https://tetherish.io/jobs"


def test_fetch_all_survives_a_broken_source():
    http = FakeHttp({"remotive": "remotive.json"})
    jobs, report = fetch_all(http, {"remoteok": {}}, only=["remotive", "remoteok"], log=lambda *_: None)
    assert len(jobs) == 3 and report["remoteok"].startswith("error")
