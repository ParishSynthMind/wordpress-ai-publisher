import json
from types import SimpleNamespace

import pytest

from wp_publisher import cli
from wp_publisher.drafter import ARTICLE_SCHEMA, ClaudeDrafter, DraftError, OfflineDrafter
from wp_publisher.validate import validate
from tests.conftest import make_article


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0)


def reply(data=None, stop_reason="end_turn"):
    text = json.dumps(data) if data is not None else ""
    return SimpleNamespace(stop_reason=stop_reason, model="claude-sonnet-5-5",
                           content=[SimpleNamespace(type="text", text=text)],
                           usage=SimpleNamespace(input_tokens=900, output_tokens=1500))


def fake_client(*replies):
    messages = FakeMessages(replies)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_claude_drafter_parses_structured_output(brief):
    client, messages = fake_client(reply(make_article().to_dict()))
    result = ClaudeDrafter(client=client).draft(brief)
    assert result.article.title.startswith("How to choose") and result.output_tokens == 1500
    sent = messages.requests[0]
    assert sent["model"] == "claude-sonnet-5-5"
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": ARTICLE_SCHEMA}
    assert sent["fallbacks"] == "default"
    assert "<brief>" in sent["messages"][0]["content"] and "62 cm" in sent["messages"][0]["content"]


def test_feedback_is_sent_on_redraft(brief):
    client, messages = fake_client(reply(make_article().to_dict()))
    ClaudeDrafter(client=client).draft(brief, feedback="- Title too long")
    assert "Title too long" in messages.requests[0]["messages"][0]["content"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_unusable_replies_raise(brief, stop_reason):
    client, _ = fake_client(reply({}, stop_reason=stop_reason))
    with pytest.raises(DraftError):
        ClaudeDrafter(client=client).draft(brief)


def test_offline_drafter_output_passes_checks(brief):
    article = OfflineDrafter().draft(brief).article
    assert validate(article, brief).ok, validate(article, brief).as_text()


BRIEF = "topic: Choosing a standing desk for home\nword_count: 400\ncategories: Home\ntags: desks\n---\n"


def test_cli_offline_dry_run(tmp_path, monkeypatch):
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.chdir(tmp_path)
    for key in ("WP_BASE_URL", "WP_USERNAME", "WP_APP_PASSWORD"):
        monkeypatch.delenv(key, raising=False)   # a dry run must not need WordPress settings
    code = cli.main(["run", "brief.md", "--offline", "--dry-run", "-o", "out/a.json"])
    assert code == 0 and (tmp_path / "out/a.json").exists()
    assert json.loads((tmp_path / "out/publish-log.jsonl").read_text().splitlines()[0])["action"] == "dry-run"


def test_cli_check_fails_bad_article(tmp_path):
    (tmp_path / "brief.md").write_text(BRIEF)
    make_article(excerpt="Guaranteed results.").save(tmp_path / "a.json")
    assert cli.main(["check", str(tmp_path / "a.json"), "--brief", str(tmp_path / "brief.md")]) == 2


def test_cli_maps_auth_error_to_exit_3(tmp_path, monkeypatch):
    (tmp_path / "brief.md").write_text(BRIEF)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WP_BASE_URL", "")
    assert cli.main(["run", "brief.md", "--offline"]) == 3
