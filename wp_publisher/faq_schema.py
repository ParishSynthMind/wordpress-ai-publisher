"""FAQ section HTML plus schema.org FAQPage JSON-LD, appended to the post content."""
import html
import json
from typing import List

from .article import FAQItem

FAQ_MARKER = "<!-- wordpress-ai-publisher:faq -->"


def faq_jsonld(items: List[FAQItem]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": item.question,
             "acceptedAnswer": {"@type": "Answer", "text": item.answer}}
            for item in items
        ],
    }


def faq_html(items: List[FAQItem]) -> str:
    if not items:
        return ""
    parts = [FAQ_MARKER, "<h2>Frequently asked questions</h2>"]
    for item in items:
        parts.append(f"<h3>{html.escape(item.question)}</h3>\n<p>{html.escape(item.answer)}</p>")
    # "</" is escaped so an answer can never close the script tag early.
    data = json.dumps(faq_jsonld(items), ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    parts.append(f'<script type="application/ld+json">{data}</script>')
    return "\n".join(parts)


def build_content(body_html: str, items: List[FAQItem]) -> str:
    faq = faq_html(items)
    return body_html.strip() + ("\n\n" + faq if faq else "")
