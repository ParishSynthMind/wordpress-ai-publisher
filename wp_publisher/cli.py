"""Command line: draft, check, publish, or run all three.

    python -m wp_publisher run briefs/standing-desk.md            # draft + check + save as WP draft
    python -m wp_publisher run briefs/standing-desk.md --publish  # same, but goes live
    python -m wp_publisher draft briefs/standing-desk.md -o out/article.json
    python -m wp_publisher check out/article.json --brief briefs/standing-desk.md
    python -m wp_publisher publish out/article.json --brief briefs/standing-desk.md

Exit codes: 0 ok, 1 other error, 2 failed checks, 3 auth error, 4 rate limited, 5 blocked by a safety rule.
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .article import Article
from .brief import BriefError, load_brief
from .drafter import ClaudeDrafter, DraftError, OfflineDrafter
from .publisher import PublishBlocked, Publisher
from .validate import validate
from .wp_client import WPAuthError, WPClient, WPError, WPRateLimitError

log = logging.getLogger("wp_publisher")


def load_env_file(path: Path) -> None:
    """Minimal KEY=VALUE loader. Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def make_client() -> WPClient:
    return WPClient(os.environ.get("WP_BASE_URL", ""), os.environ.get("WP_USERNAME", ""),
                    os.environ.get("WP_APP_PASSWORD", ""))


def draft_with_checks(brief, offline: bool, attempts: int, allow_stats: bool):
    drafter = OfflineDrafter() if offline else ClaudeDrafter(model=os.environ.get("LLM_MODEL", "claude-sonnet-5-5"))
    feedback, tokens_in, tokens_out = "", 0, 0
    for attempt in range(1, attempts + 1):
        result = drafter.draft(brief, feedback=feedback)
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        report = validate(result.article, brief, allow_unverified_stats=allow_stats)
        log.info("Draft %d checks:\n%s", attempt, report.as_text())
        if report.ok:
            break
        feedback = "\n".join(f"- {f.message}" for f in report.errors)
    log.info("Model usage: %d input / %d output tokens", tokens_in, tokens_out)
    return result.article, report


def append_log(entry: dict) -> None:
    out = Path(os.environ.get("PUBLISH_LOG", "out/publish-log.jsonl"))
    out.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def do_publish(article: Article, brief, args) -> int:
    report = validate(article, brief, allow_unverified_stats=args.allow_unverified_stats)
    print(report.as_text())
    if not report.ok:
        print("Not publishing: fix the errors above (or redraft).", file=sys.stderr)
        return 2
    result = Publisher(None if args.dry_run else make_client()).publish(article, publish=args.publish,
                                              featured_image=brief.featured_image, dry_run=args.dry_run)
    print(f"{result.action}: post {result.post_id} status={result.status}")
    if result.edit_link:
        print(f"  edit: {result.edit_link}\n  link: {result.link}")
    if result.changed_fields and result.action == "updated":
        print(f"  changed: {', '.join(result.changed_fields)}")
    append_log({"action": result.action, "post_id": result.post_id, "status": result.status,
                "slug": article.slug, "changed": list(result.changed_fields)})
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="wp_publisher", description=__doc__.split("\n")[0])
    parser.add_argument("--env-file", default=".env", help="KEY=VALUE file to load (default .env)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, publishing=True):
        p.add_argument("--allow-unverified-stats", action="store_true",
                       help="Report figures not found in the brief as warnings instead of errors.")
        if publishing:
            p.add_argument("--publish", action="store_true", help="Publish live. Default is a draft.")
            p.add_argument("--dry-run", action="store_true", help="Check everything, write nothing.")

    p = sub.add_parser("draft", help="Draft an article from a brief and check it.")
    p.add_argument("brief")
    p.add_argument("-o", "--out", default="out/article.json")
    p.add_argument("--offline", action="store_true", help="Use the canned offline drafter (no API key).")
    p.add_argument("--attempts", type=int, default=2)
    common(p, publishing=False)

    p = sub.add_parser("check", help="Run the checks on a saved article.")
    p.add_argument("article")
    p.add_argument("--brief", required=True)
    common(p, publishing=False)

    p = sub.add_parser("publish", help="Check and publish a saved article.")
    p.add_argument("article")
    p.add_argument("--brief", required=True)
    common(p)

    p = sub.add_parser("run", help="Draft, check and publish in one go.")
    p.add_argument("brief")
    p.add_argument("-o", "--out", default="out/article.json")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--attempts", type=int, default=2)
    common(p)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_env_file(Path(args.env_file))

    try:
        if args.command == "check":
            report = validate(Article.load(args.article), load_brief(args.brief), args.allow_unverified_stats)
            print(report.as_text())
            return 0 if report.ok else 2

        if args.command == "publish":
            return do_publish(Article.load(args.article), load_brief(args.brief), args)

        brief = load_brief(args.brief)
        article, report = draft_with_checks(brief, args.offline, args.attempts, args.allow_unverified_stats)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        article.save(args.out)
        print(f"Saved {args.out}")
        if not report.ok:
            print(report.as_text())
            return 2
        if args.command == "draft":
            print(report.as_text())
        if args.command == "run":
            return do_publish(article, brief, args)
        return 0
    except (BriefError, DraftError) as exc:
        log.error("%s", exc)
        return 1
    except WPAuthError as exc:
        log.error("WordPress login problem: %s (check WP_BASE_URL, WP_USERNAME and the Application Password)", exc)
        return 3
    except WPRateLimitError as exc:
        log.error("WordPress kept answering 429 after every retry: %s", exc)
        return 4
    except PublishBlocked as exc:
        log.error("%s", exc)
        return 5
    except WPError as exc:
        log.error("WordPress error: %s", exc)
        return 1
