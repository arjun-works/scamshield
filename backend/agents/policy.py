"""Loads docs/policies.md and finds sections by ID or keyword.

Sections have stable IDs (POL-2.3, POL-5.4 ...). The investigation agent may
only cite IDs that exist here, which keeps its policy references grounded.
"""

import os
import re
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = Path(os.getenv("POLICY_PATH", REPO_ROOT / "docs" / "policies.md"))

_HEADING = re.compile(r"^## (POL-\d+) (.+)$")
_SECTION = re.compile(r"^\*\*(POL-\d+\.\d+) (.+?)\.\*\*\s*(.*)$")
_SECTION_ID = re.compile(r"POL-\d+(?:\.\d+)?", re.IGNORECASE)


@lru_cache
def load_sections() -> dict[str, dict]:
    """All policy sections as {id: {"id", "title", "text"}}."""
    sections: dict[str, dict] = {}
    current = None
    for line in POLICY_PATH.read_text(encoding="utf-8").splitlines():
        heading, section = _HEADING.match(line), _SECTION.match(line)
        if heading:
            current = {"id": heading[1], "title": heading[2], "text": ""}
        elif section:
            current = {"id": section[1], "title": section[2], "text": section[3]}
        elif line.strip() == "---":
            current = None
            continue
        elif current is not None:
            current["text"] = (current["text"] + "\n" + line).strip()
            continue
        else:
            continue
        sections[current["id"]] = current
    return sections


def valid_section_ids() -> set[str]:
    return set(load_sections())


def search_policy(topic: str, limit: int = 3) -> list[dict]:
    """Sections matching a section ID (e.g. "POL-2.3") or keywords in the topic."""
    sections = load_sections()

    # Exact IDs mentioned in the topic win. "POL-5" also returns POL-5.x.
    wanted = [match.upper() for match in _SECTION_ID.findall(topic)]
    if wanted:
        found = [s for sid, s in sections.items() if any(sid == w or sid.startswith(w + ".") for w in wanted)]
        if found:
            return found[: max(limit, len(wanted))]

    # Otherwise rank by how many topic words appear in the section.
    words = {w for w in re.findall(r"[a-z]+", topic.lower()) if len(w) > 2}
    scored = []
    for section in sections.values():
        text = f"{section['title']} {section['text']}".lower()
        score = sum(text.count(word) for word in words) + 3 * sum(word in section["title"].lower() for word in words)
        if score:
            scored.append((score, section))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [section for _, section in scored[:limit]]
