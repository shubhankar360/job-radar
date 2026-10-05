import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from jobradar.models import Job
from jobradar.profile import Profile

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def profile() -> Profile:
    return Profile.load(ROOT / "examples" / "profile.example.json")


@pytest.fixture
def now() -> datetime:
    return NOW


def make_job(**kw) -> Job:
    base = dict(source="ashby", source_id="1", company="Acme", title="AI Engineer", url="https://x/1",
                apply_url="https://x/1/apply", location="Remote", remote=True,
                description="We build LLM and RAG products in Python with FastAPI. 2+ years of experience.",
                posted_at=NOW - timedelta(days=2))
    base.update(kw)
    return Job(**base)


class FakeHttp:
    """Serves fixture files instead of the network, keyed by URL substring."""

    def __init__(self, routes: dict[str, str]):
        self.routes = routes
        self.calls: list[str] = []

    def _match(self, url: str) -> str:
        self.calls.append(url)
        for frag, name in self.routes.items():
            if frag in url:
                return (FIXTURES / name).read_text()
        from jobradar.http import FetchError
        raise FetchError(f"404 {url}")

    def json(self, url: str, **kw):
        return json.loads(self._match(url))

    def get(self, url: str, **kw) -> bytes:
        return self._match(url).encode()
