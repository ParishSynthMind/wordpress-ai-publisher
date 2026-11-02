"""Read a topic brief file.

A brief is a small text file: `key: value` header lines, a line with `---`, then free-text notes.
List values are comma-separated. Lines under `facts:` that start with "- " are the only facts and
numbers the article is allowed to state (anything else numeric gets flagged by the validator).

    topic: How to choose a standing desk
    audience: home office workers
    keywords: standing desk, ergonomics
    word_count: 900
    categories: Home Office
    tags: ergonomics, desks
    featured_image: images/desk.jpg
    facts:
    - Most standing desks adjust between about 60 cm and 125 cm.
    ---
    Friendly, practical tone. Mention checking the warranty.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

LIST_KEYS = {"keywords", "categories", "tags", "banned_claims"}


class BriefError(ValueError):
    pass


@dataclass
class Brief:
    topic: str
    audience: str = "general readers"
    keywords: List[str] = field(default_factory=list)
    word_count: int = 900
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    tone: str = "clear, friendly and practical"
    featured_image: Optional[Path] = None
    facts: List[str] = field(default_factory=list)
    banned_claims: List[str] = field(default_factory=list)
    notes: str = ""


def parse_brief(text: str, base_dir: Optional[Path] = None) -> Brief:
    header, _, notes = text.partition("\n---")
    values = {}
    facts: List[str] = []
    in_facts = False
    for raw in header.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if in_facts and line.lstrip().startswith("- "):
            facts.append(line.lstrip()[2:].strip())
            continue
        in_facts = False
        if ":" not in line:
            raise BriefError(f"Brief line is not 'key: value': {line!r}")
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "facts":
            in_facts = True
            continue
        values[key] = value

    if not values.get("topic"):
        raise BriefError("Brief needs a 'topic:' line.")

    def as_list(key: str) -> List[str]:
        return [v.strip() for v in values.get(key, "").split(",") if v.strip()]

    try:
        word_count = int(values.get("word_count", "900"))
    except ValueError:
        raise BriefError("word_count must be a whole number.")
    if not 300 <= word_count <= 3000:
        raise BriefError("word_count must be between 300 and 3000.")

    image = values.get("featured_image")
    image_path = None
    if image:
        image_path = Path(image)
        if not image_path.is_absolute() and base_dir is not None:
            image_path = base_dir / image_path

    return Brief(
        topic=values["topic"],
        audience=values.get("audience", "general readers"),
        keywords=as_list("keywords"),
        word_count=word_count,
        categories=as_list("categories"),
        tags=as_list("tags"),
        tone=values.get("tone", "clear, friendly and practical"),
        featured_image=image_path,
        facts=facts,
        banned_claims=as_list("banned_claims"),
        notes=notes.strip().lstrip("-").strip(),
    )


def load_brief(path) -> Brief:
    path = Path(path)
    return parse_brief(path.read_text(encoding="utf-8"), base_dir=path.parent)
