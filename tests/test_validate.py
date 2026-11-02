from wp_publisher.article import FAQItem
from wp_publisher.brief import BriefError, parse_brief
from wp_publisher.validate import flag_unsourced_numbers, validate
from tests.conftest import make_article

import pytest


def codes(report):
    return {f.code for f in report.errors}


def test_good_article_passes(article, brief):
    report = validate(article, brief)
    assert report.ok, report.as_text()


def test_brief_parsing(brief):
    assert brief.topic == "How to choose a standing desk"
    assert brief.tags == ["desks", "ergonomics"]
    assert brief.facts == ["Desks adjust from 62 cm to 127 cm.", "Frames have a 5 year warranty."]
    assert brief.notes == "Practical tone."


def test_brief_needs_topic():
    with pytest.raises(BriefError):
        parse_brief("audience: anyone\n---\n")


def test_invented_statistic_is_an_error(brief):
    body = make_article().body_html + "<p>Studies show 73% of office workers feel better after 2 weeks.</p>"
    report = validate(make_article(body_html=body), brief)
    assert "unverified_statistic" in codes(report)
    assert "73%" in report.as_text() and "studies show" in report.as_text()


def test_statistic_from_brief_facts_is_allowed(brief):
    assert flag_unsourced_numbers("Desks adjust from 62 cm to 127 cm with a 5 year warranty.", brief.facts) == []


def test_unverified_stats_can_be_downgraded(brief):
    body = make_article().body_html + "<p>It costs $499.</p>"
    report = validate(make_article(body_html=body), brief, allow_unverified_stats=True)
    assert report.ok and any(f.code == "unverified_statistic" for f in report.warnings)


def test_banned_claims(brief):
    article = make_article(excerpt="Guaranteed to fix your back pain.")
    assert "banned_claim" in codes(validate(article, brief))


def test_banned_word_inside_other_word_is_fine(brief):
    article = make_article(excerpt="Keep cables secure under the desk.")
    assert "banned_claim" not in codes(validate(article, brief))


def test_brief_specific_banned_claims():
    brief = parse_brief("topic: desks\nword_count: 300\nbanned_claims: cheapest\n---\n")
    assert "banned_claim" in codes(validate(make_article(excerpt="The cheapest desk around."), brief))


def test_structure_checks(brief):
    bad = make_article(body_html="<h1>Title again</h1><h2>One</h2><h4>Skipped</h4><p>" + "word " * 300 + "</p>",
                       title="Short", slug="Not A Slug", meta_description="too short")
    found = codes(validate(bad, brief))
    assert {"h1_in_body", "too_few_sections", "heading_order", "title_length", "slug",
            "meta_description_length"} <= found


def test_unsafe_html_rejected(brief):
    body = make_article().body_html + '<script>alert(1)</script><p onclick="x()">hi</p><a href="javascript:x">y</a>'
    found = codes(validate(make_article(body_html=body), brief))
    assert {"disallowed_html", "unsafe_attributes"} <= found


def test_word_count_range(brief):
    assert "word_count" in codes(validate(make_article(body_html="<h2>a</h2><h2>b</h2><p>too short</p>"), brief))


def test_faq_rules(brief):
    assert "faq_count" in codes(validate(make_article(faq=[FAQItem("Q?", "A.")]), brief))
    html_faq = [FAQItem("Q?", "<b>A</b>"), FAQItem("Q2?", "A2.")]
    assert "faq_html" in codes(validate(make_article(faq=html_faq), brief))


def test_missing_keyword_is_only_a_warning(brief):
    brief.keywords = ["treadmill desk"]
    report = validate(make_article(), brief)
    assert report.ok and report.warnings[0].code == "keyword_missing"
