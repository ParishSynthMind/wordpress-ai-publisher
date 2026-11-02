"""The article Claude returns, as a plain dataclass that round-trips through JSON."""
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List


@dataclass
class FAQItem:
    question: str
    answer: str


@dataclass
class Article:
    title: str
    slug: str
    excerpt: str
    meta_description: str
    body_html: str
    faq: List[FAQItem] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "Article":
        return cls(
            title=str(data.get("title", "")).strip(),
            slug=slugify(str(data.get("slug") or data.get("title", ""))),
            excerpt=str(data.get("excerpt", "")).strip(),
            meta_description=str(data.get("meta_description", "")).strip(),
            body_html=str(data.get("body_html", "")).strip(),
            faq=[FAQItem(str(f.get("question", "")).strip(), str(f.get("answer", "")).strip())
                 for f in data.get("faq", []) if isinstance(f, dict)],
            tags=_clean_terms(data.get("tags", [])),
            categories=_clean_terms(data.get("categories", [])),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path) -> "Article":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", text)[:80].rstrip("-")


def _clean_terms(values) -> List[str]:
    seen, out = set(), []
    for value in values or []:
        term = str(value).strip()
        if term and term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out
