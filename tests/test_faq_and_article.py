import json
import re

from wp_publisher.article import Article, FAQItem, slugify
from wp_publisher.faq_schema import build_content, faq_jsonld


def test_jsonld_shape():
    data = faq_jsonld([FAQItem("Q1?", "A1."), FAQItem("Q2?", "A2.")])
    assert data["@type"] == "FAQPage" and len(data["mainEntity"]) == 2
    assert data["mainEntity"][0]["acceptedAnswer"]["text"] == "A1."


def test_content_has_visible_faq_and_parseable_script():
    content = build_content("<h2>Body</h2>", [FAQItem("Is 5 < 6?", "Yes </script><script>bad()</script>")])
    assert "<h3>Is 5 &lt; 6?</h3>" in content
    script = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.S).group(1)
    assert "</script>" not in script
    assert json.loads(script)["mainEntity"][0]["acceptedAnswer"]["text"].startswith("Yes </script>")


def test_no_faq_means_body_only():
    assert build_content("<p>x</p>", []) == "<p>x</p>"


def test_slugify_and_term_cleanup(tmp_path):
    assert slugify("Héllo, World!  Desks & Chairs") == "hello-world-desks-chairs"
    a = Article.from_dict({"title": "My Title", "slug": "", "excerpt": "e", "meta_description": "m",
                           "body_html": "<p>b</p>", "faq": [{"question": "q", "answer": "a"}],
                           "tags": ["SEO", "seo", " "], "categories": ["News"]})
    assert a.slug == "my-title" and a.tags == ["SEO"]
    a.save(tmp_path / "a.json")
    assert Article.load(tmp_path / "a.json") == a
