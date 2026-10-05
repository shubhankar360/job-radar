import pytest

from jobradar.eligibility import assess

from .conftest import make_job


@pytest.mark.parametrize("kw,status", [
    (dict(worldwide=True, location=""), "yes"),
    (dict(location="Remote - India", regions=["Remote - India"]), "yes"),
    (dict(location="North America · APJ · EMEA", regions=["North America", "APJ", "EMEA"]), "yes"),
    (dict(location="Bengaluru", regions=["Bengaluru"], remote=False), "yes"),
    (dict(location="Anywhere in the World"), "yes"),
    # EMEA alone is run from European payroll; it does not include India.
    (dict(location="EMEA", regions=["EMEA"]), "no"),
    (dict(location="Remote - US", regions=["United States"]), "no"),
    (dict(location="Remote (UK)", regions=["UK"]), "no"),
    (dict(location="Remote", regions=[], description="Overlap with UTC+3 to UTC+8 required."), "likely"),
    (dict(location="Remote", regions=[], description="Must work UTC-8 to UTC-5 hours."), "no"),
    (dict(location="Remote", regions=[], description="Nice team."), "likely"),
    (dict(location="Remote", regions=[], description="You must be authorized to work in the US."), "no"),
    (dict(location="Dubai", regions=["Dubai"], remote=False, description="We offer visa sponsorship and relocation package."), "relocate"),
    (dict(location="London", regions=["London"], remote=False, description="We are unable to sponsor visas."), "no"),
    (dict(location="Berlin", remote=False, regions=[]), "no"),
])
def test_assess(kw, status):
    assert assess(make_job(**kw)).status == status


def test_onsite_in_candidate_country_is_marked():
    v = assess(make_job(location="Bengaluru · New Delhi", regions=["Bengaluru", "New Delhi"], remote=False))
    assert v.status == "yes" and "on-site/hybrid" in v.reason


def test_other_candidate_country():
    assert assess(make_job(location="Remote - US", regions=["United States"]), country="united states").status == "yes"
