from __future__ import annotations

import html
import re
from datetime import datetime, timezone

_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section|article)[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")


def html_to_text(s: str | None) -> str:
    """Good-enough HTML to text for keyword work. Unescapes twice because
    Greenhouse double-encodes its content field (``&lt;div&gt;``)."""
    if not s:
        return ""
    s = html.unescape(html.unescape(s))
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S | re.I)
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = _WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n\n", s)
    return s.strip()


def parse_date(v) -> datetime | None:
    """Accepts epoch seconds, ISO-8601 strings (with or without zone) and
    RFC-822 dates from RSS. Always returns an aware UTC datetime."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        if v > 1e12:  # milliseconds
            v = v / 1000
        return datetime.fromtimestamp(v, tz=timezone.utc)
    s = str(v).strip()
    if s.isdigit():
        return parse_date(int(s))
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    from email.utils import parsedate_to_datetime

    try:
        d = parsedate_to_datetime(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9+#./ ]+", " ", s.lower()).split())


def term_regex(term: str) -> re.Pattern:
    """Word-boundary matcher that survives terms like ``C++``, ``.NET``,
    ``Node.js`` and ``CI/CD`` where ``\\b`` alone breaks."""
    esc = re.escape(term.lower())
    return re.compile(rf"(?<![a-z0-9]){esc}(?![a-z0-9])", re.I)
