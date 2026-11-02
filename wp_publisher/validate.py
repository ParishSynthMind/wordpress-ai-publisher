"""Checks an Article before it is allowed anywhere near WordPress.

Errors block publishing. Warnings are reported but do not block. Numbers that look like
statistics (percentages, money, "3x", "4 out of 5", "studies show"...) are errors unless the
same figure appears in the brief's facts, because an invented statistic on a client's site is
the most damaging thing an AI draft can do.
"""
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List

from .article import Article
from .brief import Brief

ALLOWED_TAGS = {"h2", "h3", "h4", "p", "ul", "ol", "li", "strong", "em", "b", "i", "a",
                "blockquote", "br", "code"}
DEFAULT_BANNED = [
    "guaranteed", "guarantee", "100% safe", "risk-free", "risk free", "best in the world",
    "number one", "#1", "cure", "cures", "miracle", "get rich", "no side effects",
    "as an ai", "language model", "doctors recommend", "clinically proven",
]
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
NUMBER_PATTERNS = [
    r"\d[\d,.]*\s?(?:%|percent\b|per cent\b)",
    r"[$£€]\s?\d[\d,.]*(?:\s?(?:k|m|bn|million|billion))?",
    r"\b\d[\d,.]*\s?(?:x|times)\b",
    r"\b\d+\s+(?:out of|in)\s+\d+\b",
    r"\b\d[\d,.]*\s+(?:cm|mm|m|kg|lbs?|hours?|minutes?|days?|weeks?|months?|years?|people|customers|users|businesses)\b",
]
RESEARCH_PHRASES = [
    "studies show", "study shows", "research shows", "research suggests", "according to a study",
    "according to research", "a recent survey", "surveys show", "experts agree", "scientists say",
]


@dataclass
class Finding:
    severity: str  # "error" | "warning"
    code: str
    message: str


@dataclass
class Report:
    findings: List[Finding] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def add(self, severity: str, code: str, message: str) -> None:
        self.findings.append(Finding(severity, code, message))

    def as_text(self) -> str:
        if not self.findings:
            return "All checks passed."
        return "\n".join(f"[{f.severity.upper()}] {f.code}: {f.message}" for f in self.findings)


class _BodyScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags: List[str] = []
        self.headings: List[int] = []
        self.bad_attrs: List[str] = []
        self.text_parts: List[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if re.fullmatch(r"h[1-6]", tag):
            self.headings.append(int(tag[1]))
        for name, value in attrs:
            value = (value or "").strip().lower()
            if name.startswith("on") or name == "style":
                self.bad_attrs.append(f"{tag}[{name}]")
            elif name in ("href", "src") and value.startswith(("javascript:", "data:")):
                self.bad_attrs.append(f"{tag}[{name}={value[:20]}]")
            elif tag == "a" and name not in ("href", "title", "rel", "target"):
                self.bad_attrs.append(f"a[{name}]")
            elif tag != "a":
                self.bad_attrs.append(f"{tag}[{name}]")

    def handle_data(self, data):
        self.text_parts.append(data)


def body_text(html: str) -> str:
    scanner = _BodyScanner()
    scanner.feed(html)
    return " ".join(" ".join(scanner.text_parts).split())


def _norm_number(s: str) -> str:
    return re.sub(r"[^\d.]", "", s).rstrip(".")


def flag_unsourced_numbers(text: str, facts: List[str]) -> List[str]:
    facts_text = " ".join(facts).lower()
    fact_numbers = {_norm_number(n) for n in re.findall(r"\d[\d,.]*", facts_text)}
    flagged = []
    for pattern in NUMBER_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            numbers = [_norm_number(n) for n in re.findall(r"\d[\d,.]*", match.group(0))]
            if any(n and n not in fact_numbers for n in numbers):
                flagged.append(match.group(0).strip())
    lower = text.lower()
    for phrase in RESEARCH_PHRASES:
        if phrase in lower and phrase not in facts_text:
            flagged.append(phrase)
    return sorted(set(flagged))


def validate(article: Article, brief: Brief, allow_unverified_stats: bool = False) -> Report:
    report = Report()

    if not 20 <= len(article.title) <= 70:
        report.add("error", "title_length", f"Title is {len(article.title)} characters; keep it 20 to 70.")
    if not SLUG_RE.match(article.slug) or len(article.slug) > 80:
        report.add("error", "slug", f"Slug {article.slug!r} must be lowercase words joined by hyphens.")
    if not 70 <= len(article.meta_description) <= 160:
        report.add("error", "meta_description_length",
                   f"Meta description is {len(article.meta_description)} characters; keep it 70 to 160.")
    if not 1 <= len(article.excerpt) <= 300:
        report.add("error", "excerpt_length", f"Excerpt is {len(article.excerpt)} characters; keep it 1 to 300.")

    scanner = _BodyScanner()
    scanner.feed(article.body_html)
    text = " ".join(" ".join(scanner.text_parts).split())
    words = len(text.split())
    low, high = int(brief.word_count * 0.6), int(brief.word_count * 1.5)
    if not low <= words <= high:
        report.add("error", "word_count", f"Body has {words} words; the brief asks for about {brief.word_count} ({low} to {high}).")

    if 1 in scanner.headings:
        report.add("error", "h1_in_body", "Body contains an <h1>; the post title is already the h1.")
    if scanner.headings.count(2) < 2:
        report.add("error", "too_few_sections", "Body needs at least two <h2> section headings.")
    previous = 1
    for level in scanner.headings:
        if level > previous + 1:
            report.add("error", "heading_order", f"Heading jumps from h{previous} to h{level}.")
            break
        previous = level

    bad_tags = sorted({t for t in scanner.tags if t not in ALLOWED_TAGS and t != "h1"})
    if bad_tags:
        report.add("error", "disallowed_html", f"Tags not allowed in the body: {', '.join(bad_tags)}.")
    if scanner.bad_attrs:
        report.add("error", "unsafe_attributes", f"Attributes not allowed: {', '.join(sorted(set(scanner.bad_attrs)))}.")

    if not 2 <= len(article.faq) <= 8:
        report.add("error", "faq_count", f"FAQ has {len(article.faq)} items; use 2 to 8.")
    for i, item in enumerate(article.faq, 1):
        if not item.question or not item.answer:
            report.add("error", "faq_empty", f"FAQ item {i} is missing a question or answer.")
        elif len(item.answer) > 600:
            report.add("error", "faq_answer_length", f"FAQ answer {i} is over 600 characters.")
        elif "<" in item.question + item.answer:
            report.add("error", "faq_html", f"FAQ item {i} contains HTML; FAQ text must be plain.")

    if not 1 <= len(article.tags) <= 10:
        report.add("error", "tag_count", f"{len(article.tags)} tags; use 1 to 10.")
    if not 1 <= len(article.categories) <= 3:
        report.add("error", "category_count", f"{len(article.categories)} categories; use 1 to 3.")

    everything = " ".join([article.title, article.excerpt, article.meta_description, text]
                          + [f"{f.question} {f.answer}" for f in article.faq])
    lower = everything.lower()
    for phrase in DEFAULT_BANNED + [b.lower() for b in brief.banned_claims]:
        if re.search(r"(?<![a-z])" + re.escape(phrase.lower()) + r"(?![a-z])", lower):
            report.add("error", "banned_claim", f"Contains a banned claim: {phrase!r}.")

    flagged = flag_unsourced_numbers(everything, brief.facts)
    if flagged:
        report.add("warning" if allow_unverified_stats else "error", "unverified_statistic",
                   "Figures or research claims not found in the brief's facts: " + "; ".join(flagged))

    if brief.keywords:
        missing = [k for k in brief.keywords if k.lower() not in lower]
        if missing:
            report.add("warning", "keyword_missing", f"Keywords not used: {', '.join(missing)}.")
        elif brief.keywords[0].lower() not in article.title.lower():
            report.add("warning", "keyword_not_in_title", f"Main keyword {brief.keywords[0]!r} is not in the title.")
    return report
