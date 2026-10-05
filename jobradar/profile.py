"""Candidate profile: the single source of truth for everything the engine
may say about the candidate.

The tailoring step can only *select and order* what is in here. It cannot
write a new claim. That is the design constraint that makes automated CV
tailoring safe to use: the worst a bad ranking can do is pick a less
relevant true bullet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .text import term_regex


@dataclass
class Skill:
    name: str
    aliases: list[str] = field(default_factory=list)
    weight: float = 1.0
    covers: list[str] = field(default_factory=list)  # vocab canonicals this skill satisfies
    learning: bool = False  # listed honestly as "learning"; never counts as a match

    def patterns(self) -> list[re.Pattern]:
        return [term_regex(t) for t in [self.name, *self.aliases]]


@dataclass
class Profile:
    data: dict
    path: Path | None = None

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        p = Path(path).expanduser()
        return cls(json.loads(p.read_text()), p)

    # -- convenience accessors -------------------------------------------------
    @property
    def person(self) -> dict:
        return self.data["person"]

    @property
    def prefs(self) -> dict:
        return self.data.get("preferences", {})

    @property
    def archetypes(self) -> dict:
        return self.data.get("archetypes", {})

    def skill_patterns(self) -> list[tuple[Skill, list[re.Pattern]]]:
        """Compiled once per profile; scoring calls this for every job."""
        if not hasattr(self, "_skill_patterns"):
            self._skill_patterns = [(s, s.patterns()) for s in self.skills() if not s.learning]
        return self._skill_patterns

    def skills(self) -> list[Skill]:
        out = []
        for group in self.data.get("skills", []):
            learning = bool(group.get("learning"))
            for it in group.get("items", []):
                if isinstance(it, str):
                    out.append(Skill(it, learning=learning))
                else:
                    out.append(Skill(it["name"], it.get("aliases", []), it.get("weight", 1.0),
                                     [] if learning else it.get("covers", []), learning))
        return out

    def covered_vocab(self) -> set[str]:
        """Vocabulary terms the candidate can honestly claim."""
        cov = set(self.data.get("covers_vocab", []))
        for s in self.skills():
            cov.update(s.covers)
        return cov

    def all_bullets(self):
        """Yield (section, entry_index, bullet_index, bullet) for every bullet."""
        for section in ("experience", "projects"):
            for ei, entry in enumerate(self.data.get(section, [])):
                for bi, b in enumerate(entry.get("bullets", [])):
                    yield section, ei, bi, b
