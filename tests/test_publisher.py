import pytest

from wp_publisher.publisher import PublishBlocked, Publisher
from wp_publisher.wp_client import WPAuthError, WPClient, WPError, WPRateLimitError
from tests.conftest import make_article
from tests.fake_wp import FakeWordPress


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "desk.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    return path


def test_create_then_idempotent_rerun(client, fake_wp, article, image):
    publisher = Publisher(client)
    first = publisher.publish(article, featured_image=image)
    assert first.action == "created" and first.status == "draft"
    post = fake_wp.posts[first.post_id]
    assert post["meta"]["ai_meta_description"] == article.meta_description
    assert 'application/ld+json' in post["content"]["raw"]
    assert len(fake_wp.media) == 1 and post["featured_media"] in fake_wp.media
    assert sorted(fake_wp.terms["tags"].values()) == ["desks", "ergonomics"]

    writes_before = sum(1 for m, _ in fake_wp.calls if m == "POST")
    second = publisher.publish(article, featured_image=image)
    assert second.action == "unchanged" and second.post_id == first.post_id
    assert sum(1 for m, _ in fake_wp.calls if m == "POST") == writes_before   # nothing written
    assert len(fake_wp.posts) == 1 and len(fake_wp.media) == 1


def test_update_sends_only_changed_fields(client, fake_wp, article):
    publisher = Publisher(client)
    created = publisher.publish(article)
    changed = make_article(excerpt="A new excerpt for the same post.", tags=["desks", "posture"])
    result = publisher.publish(changed)
    assert result.action == "updated" and result.post_id == created.post_id
    assert set(result.changed_fields) == {"excerpt", "tags"}
    assert "posture" in fake_wp.terms["tags"].values()


def test_draft_run_will_not_touch_a_live_post(client, article):
    publisher = Publisher(client)
    assert publisher.publish(article, publish=True).status == "publish"
    with pytest.raises(PublishBlocked, match="already publish"):
        publisher.publish(make_article(excerpt="changed"))


def test_publish_flag_promotes_draft(client, article):
    publisher = Publisher(client)
    publisher.publish(article)
    result = publisher.publish(article, publish=True)
    assert result.action == "updated" and result.status == "publish" and result.changed_fields == ("status",)


def test_dry_run_makes_no_calls(client, fake_wp, article):
    assert Publisher(client).publish(article, dry_run=True).action == "dry-run"
    assert fake_wp.calls == []


def test_existing_term_is_reused_case_insensitively(client, fake_wp, article):
    fake_wp.terms["categories"][50] = "home office"
    Publisher(client).publish(article)
    assert list(fake_wp.terms["categories"].values()).count("home office") == 1
    assert "Home Office" not in fake_wp.terms["categories"].values()


def test_existing_media_is_reused(client, fake_wp, article, image):
    fake_wp.media[77] = {"id": 77, "media_details": {"file": "2026/10/desk.png"}, "source_url": "x/desk.png"}
    result = Publisher(client).publish(article, featured_image=image)
    assert fake_wp.posts[result.post_id]["featured_media"] == 77 and len(fake_wp.media) == 1


def test_missing_image_blocks(client, article, tmp_path):
    with pytest.raises(PublishBlocked, match="not found"):
        Publisher(client).publish(article, featured_image=tmp_path / "nope.png")


def test_bad_credentials_raise_auth_error(fake_wp, article):
    client = WPClient("http://wp.test", "editor", "wrong password", session=fake_wp, sleep=lambda s: None)
    with pytest.raises(WPAuthError) as exc:
        Publisher(client).publish(article)
    assert exc.value.status == 401 and "incorrect_password" in str(exc.value)


def test_missing_settings_raise_auth_error():
    with pytest.raises(WPAuthError):
        WPClient("", "user", "pass")


def test_user_without_publish_capability_is_blocked(article):
    wp = FakeWordPress(can_publish=False)
    client = WPClient("http://wp.test", *FakeWordPress.USER, session=wp, sleep=lambda s: None)
    with pytest.raises(PublishBlocked, match="publish_posts"):
        Publisher(client).publish(article, publish=True)


def test_429_is_retried_using_retry_after(client, fake_wp, article):
    waits = []
    client.sleep = waits.append
    fake_wp.forced = [(429, {"Retry-After": "3"}), (429, {"Retry-After": "1"})]
    assert Publisher(client).publish(article).action == "created"
    assert waits == [3.0, 1.0]


def test_429_gives_up_after_max_retries(client, fake_wp, article):
    client.max_retries = 2
    fake_wp.forced = [(429, {"Retry-After": "1"})] * 3
    with pytest.raises(WPRateLimitError):
        Publisher(client).publish(article)


def test_retry_after_is_capped(client, fake_wp, article):
    waits = []
    client.sleep, client.max_wait = waits.append, 10
    fake_wp.forced = [(503, {"Retry-After": "3600"})]
    Publisher(client).publish(article)
    assert waits == [10]


def test_other_errors_are_not_retried(client, fake_wp):
    fake_wp.forced = [(400, {})]
    with pytest.raises(WPError) as exc:
        client.me()
    assert exc.value.status == 400 and len(fake_wp.calls) == 1


def test_warns_when_script_would_be_stripped(article, caplog):
    wp = FakeWordPress(unfiltered_html=False)
    client = WPClient("http://wp.test", *FakeWordPress.USER, session=wp, sleep=lambda s: None)
    Publisher(client).publish(article)
    assert "unfiltered_html" in caplog.text
