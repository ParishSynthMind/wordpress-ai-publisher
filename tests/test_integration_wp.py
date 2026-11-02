"""Integration tests against the real local WordPress from docker-compose.yml.

    docker compose -p wpai up -d && ./scripts/setup_local_wp.sh
    WP_INTEGRATION=1 pytest -m integration

Each test uses a unique slug and deletes its posts afterwards.
"""
import os
import subprocess
import time
from pathlib import Path

import pytest

from wp_publisher.cli import load_env_file
from wp_publisher.publisher import PublishBlocked, Publisher
from wp_publisher.wp_client import WPAuthError, WPClient, WPRateLimitError
from tests.conftest import make_article

ROOT = Path(__file__).resolve().parent.parent
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("WP_INTEGRATION") != "1", reason="set WP_INTEGRATION=1 with the stack running"),
]


@pytest.fixture(scope="module")
def client():
    load_env_file(ROOT / ".env.local")
    return WPClient(os.environ["WP_BASE_URL"], os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"])


@pytest.fixture
def slug(client):
    value = f"it-{int(time.time() * 1000)}"
    yield value
    post = client.find_post_by_slug(value)
    if post:
        client.request("DELETE", f"/wp/v2/posts/{post['id']}", params={"force": "true"})


def wp_cli(*args):
    project = os.environ.get("COMPOSE_PROJECT_NAME", "wpai")
    subprocess.run(["docker", "compose", "-p", project, "run", "--rm", "-T", "cli", "wp", *args],
                   cwd=ROOT, check=True, capture_output=True)


def test_create_update_rerun_against_real_wordpress(client, slug):
    image = ROOT / "briefs" / "images" / "standing-desk.png"
    publisher = Publisher(client)
    article = make_article(slug=slug)

    created = publisher.publish(article, featured_image=image)
    assert created.action == "created" and created.status == "draft"
    stored = client.request("GET", f"/wp/v2/posts/{created.post_id}", params={"context": "edit"})
    assert stored["meta"]["ai_meta_description"] == article.meta_description
    assert '<script type="application/ld+json">' in stored["content"]["rendered"]
    media_count = len(client.request("GET", "/wp/v2/media", params={"per_page": 100}))

    again = publisher.publish(article, featured_image=image)
    assert again.action == "unchanged" and again.post_id == created.post_id
    assert len(client.request("GET", "/wp/v2/media", params={"per_page": 100})) == media_count

    updated = publisher.publish(make_article(slug=slug, excerpt="Updated excerpt."), featured_image=image)
    assert updated.action == "updated" and updated.changed_fields == ("excerpt",)
    assert client.find_post_by_slug(slug)["excerpt"]["raw"] == "Updated excerpt."


def test_publish_flag_and_live_post_guard(client, slug):
    publisher = Publisher(client)
    publisher.publish(make_article(slug=slug))
    assert publisher.publish(make_article(slug=slug), publish=True).status == "publish"
    with pytest.raises(PublishBlocked):
        publisher.publish(make_article(slug=slug, excerpt="draft run"))


def test_wrong_application_password_is_401(client):
    bad = WPClient(client.base_url, os.environ["WP_USERNAME"], "aaaa bbbb cccc dddd eeee ffff")
    with pytest.raises(WPAuthError) as exc:
        bad.me()
    assert exc.value.status == 401


def test_real_429_is_retried_then_succeeds(client, slug):
    wp_cli("option", "update", "aipub_force_429", "2")
    retrying = WPClient(client.base_url, os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"], max_retries=4)
    assert Publisher(retrying).publish(make_article(slug=slug)).action == "created"


def test_real_429_gives_up_after_retries(client):
    wp_cli("option", "update", "aipub_force_429", "10")
    try:
        impatient = WPClient(client.base_url, os.environ["WP_USERNAME"], os.environ["WP_APP_PASSWORD"], max_retries=2)
        with pytest.raises(WPRateLimitError):
            impatient.me()
    finally:
        wp_cli("option", "update", "aipub_force_429", "0")
