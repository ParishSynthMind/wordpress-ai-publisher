import pytest

from wp_publisher.article import Article, FAQItem
from wp_publisher.brief import parse_brief
from wp_publisher.wp_client import WPClient
from tests.fake_wp import FakeWordPress

BRIEF = """topic: How to choose a standing desk
keywords: standing desk
word_count: 300
categories: Home Office
tags: desks, ergonomics
facts:
- Desks adjust from 62 cm to 127 cm.
- Frames have a 5 year warranty.
---
Practical tone.
"""


@pytest.fixture
def brief():
    return parse_brief(BRIEF)


def make_article(**overrides):
    body = "".join(f"<h2>Section {i}</h2><p>{'A standing desk helps you change position during the day. ' * 9}</p>"
                   for i in range(3))
    data = dict(
        title="How to choose a standing desk for your home office",
        slug="choose-a-standing-desk",
        excerpt="What to check before buying a standing desk.",
        meta_description="A plain-English checklist for choosing a standing desk: height range, stability, "
                         "motors and warranty.",
        body_html=body,
        faq=[FAQItem("How high does it go?", "It adjusts from 62 cm to 127 cm."),
             FAQItem("Is there a warranty?", "Frames have a 5 year warranty.")],
        tags=["desks", "ergonomics"],
        categories=["Home Office"],
    )
    data.update(overrides)
    return Article(**data)


@pytest.fixture
def article():
    return make_article()


@pytest.fixture
def fake_wp():
    return FakeWordPress()


@pytest.fixture
def client(fake_wp):
    return WPClient("http://wp.test", *FakeWordPress.USER, session=fake_wp, sleep=lambda s: None)
