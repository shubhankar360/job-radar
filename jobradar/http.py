"""Tiny stdlib HTTP client with an on-disk cache.

The cache matters more than it looks: a full run touches ~150 endpoints, and
re-ranking or re-tailoring should never hit the network again. Entries
expire after ``ttl`` seconds (default 6 hours, so a morning run and an
afternoon run see different feeds)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "Mozilla/5.0 (compatible; job-radar/0.1; +https://github.com/shubhankar360/job-radar)"


class FetchError(Exception):
    pass


class Http:
    def __init__(self, cache_dir: Path | None = None, ttl: int = 6 * 3600, offline: bool = False):
        self.cache_dir = cache_dir
        self.ttl = ttl
        self.offline = offline
        self.requests = 0
        self.cache_hits = 0
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".gz")

    def get(self, url: str, *, retries: int = 2, timeout: int = 30) -> bytes:
        p = self._path(url)
        if p and p.exists() and (self.offline or time.time() - p.stat().st_mtime < self.ttl):
            self.cache_hits += 1
            return gzip.decompress(p.read_bytes())
        if self.offline:
            raise FetchError(f"offline and not cached: {url}")
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    body = r.read()
                self.requests += 1
                if p:
                    tmp = p.with_suffix(".tmp")
                    tmp.write_bytes(gzip.compress(body))
                    os.replace(tmp, p)
                return body
            except urllib.error.HTTPError as e:
                # 4xx is an answer, not a blip: a wrong board slug 404s forever.
                if 400 <= e.code < 500 and e.code != 429:
                    raise FetchError(f"{e.code} {url}") from e
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            time.sleep(1.5 * (attempt + 1))
        raise FetchError(f"{url}: {last}")

    def json(self, url: str, **kw):
        return json.loads(self.get(url, **kw))
