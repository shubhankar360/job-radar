import pytest

from jobradar.salary import parse_salary_text, to_annual_usd
from jobradar.seniority import level_from_title, years_required
from jobradar.text import html_to_text, parse_date, term_regex
from jobradar.vocab import tech_in


@pytest.mark.parametrize("text,expected", [
    ("$120k - $150k", (120_000, 150_000, "USD", "annual")),
    ("$120-150k", (120_000, 150_000, "USD", "annual")),
    ("€60,000–80,000 / year", (60_000, 80_000, "EUR", "annual")),
    ("Upto $85/hr", (85, 85, "USD", "hourly")),
    ("£4,000 per month", (4_000, 4_000, "GBP", "monthly")),
    ("₹80L–₹1.4Cr", (8_000_000, 14_000_000, "INR", "annual")),
    ("AED 18,000 a month", (18_000, 18_000, "AED", "monthly")),
    ("$80 - $120", (80_000, 120_000, "USD", "annual")),  # bare small numbers on a salaried role are thousands
])
def test_parse_salary_text(text, expected):
    assert parse_salary_text(text) == expected


def test_parse_salary_text_nothing():
    assert parse_salary_text("competitive")[0] is None
    assert parse_salary_text("") == (None, None, "", "")


def test_to_annual_usd():
    assert to_annual_usd(100_000, "USD", "annual") == 100_000
    assert to_annual_usd(50, "USD", "hourly") == 94_000
    assert to_annual_usd(4_000, "GBP", "monthly") == pytest.approx(60_960)
    assert to_annual_usd(10, "XYZ", "annual") is None  # unknown currency is unknown, not USD
    assert to_annual_usd(None, "USD", "annual") is None


@pytest.mark.parametrize("title,level", [
    ("Senior AI Engineer", "senior"), ("Staff Software Engineer, AI", "staff"), ("Principal ML Engineer", "principal"),
    ("Engineering Manager, Agents", "manager"), ("Head of AI", "exec"), ("Junior Python Developer", "junior"),
    ("Software Engineer, New Grad (2027)", "junior"), ("AI Engineer Intern", "intern"), ("AI Engineer", "mid"),
    ("GenAI Architect", "senior"), ("Sr. Backend Engineer", "senior"), ("Software Engineer II", "mid"),
])
def test_level_from_title(title, level):
    assert level_from_title(title) == level


def test_years_required_takes_the_binding_requirement():
    assert years_required("5+ years of software experience, 2+ years with LLMs") == 5
    assert years_required("You have 3-5 years experience building APIs") == 3
    assert years_required("For 25 years we have served customers.") is None
    assert years_required("No experience required") is None


def test_html_to_text_handles_greenhouse_double_encoding():
    assert html_to_text("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;") == "Hello & welcome"
    assert "x" not in html_to_text("<script>var x=1</script>")


def test_parse_date_variants():
    assert parse_date(1791000000).year == 2026
    assert parse_date(1791000000000).year == 2026  # milliseconds
    assert parse_date("2026-10-03T20:01:00").tzinfo is not None
    assert parse_date("Wed, 16 Sep 2026 10:00:00 +0000").day == 16
    assert parse_date("not a date") is None


def test_term_regex_survives_punctuation():
    assert term_regex("C++").search("Strong C++ skills")
    assert term_regex("Node.js").search("node.js and more")
    assert not term_regex("Java").search("JavaScript only")
    assert not term_regex("RAG").search("leverage")


def test_tech_in_go_is_case_sensitive():
    assert "Golang" in tech_in("Services in Go, Python and Rust")
    assert "Golang" not in tech_in("Ready to go further with us")
    assert {"PostgreSQL", "Kubernetes", "RAG"} <= tech_in("Postgres, k8s and retrieval-augmented generation")
