"""Publish a validated Article to WordPress: idempotent by slug, draft unless told otherwise."""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .article import Article
from .faq_schema import build_content
from .wp_client import WPClient, WPError, media_filename

log = logging.getLogger(__name__)
META_KEY = "ai_meta_description"


class PublishBlocked(RuntimeError):
    """A safety rule stopped the write (e.g. would overwrite a live post without --publish)."""


@dataclass
class PublishResult:
    action: str          # "created" | "updated" | "unchanged" | "dry-run"
    post_id: Optional[int]
    status: str
    link: str
    edit_link: str
    changed_fields: tuple = ()


def _raw(value):
    return value.get("raw", value.get("rendered", "")) if isinstance(value, dict) else (value or "")


class Publisher:
    def __init__(self, client: Optional[WPClient]):
        """`client` may be None for dry runs, which never touch WordPress."""
        self.client = client

    def check_access(self, publish: bool) -> dict:
        user = self.client.me()
        caps = user.get("capabilities", {})
        needed = "publish_posts" if publish else "edit_posts"
        if not caps.get(needed):
            raise PublishBlocked(f"User {user.get('slug')!r} lacks the {needed} capability.")
        if not caps.get("unfiltered_html"):
            log.warning("User lacks unfiltered_html: WordPress will strip the FAQ JSON-LD <script>. "
                        "Use an Administrator (single site) or add the schema with an SEO plugin.")
        return user

    def _featured_media_id(self, image: Path, alt: str, existing: Optional[dict]) -> int:
        if not image.is_file():
            raise PublishBlocked(f"Featured image not found: {image}")
        wanted = image.name.lower()
        if existing and existing.get("featured_media"):
            current = self.client.get_media(existing["featured_media"])
            if current and media_filename(current) == wanted:
                return current["id"]
        found = self.client.find_media_by_filename(image.name)
        if found:
            return found["id"]
        return self.client.upload_media(image, alt_text=alt)["id"]

    def publish(self, article: Article, publish: bool = False, featured_image: Optional[Path] = None,
                dry_run: bool = False) -> PublishResult:
        status = "publish" if publish else "draft"
        content = build_content(article.body_html, article.faq)

        if dry_run:
            log.info("Dry run: would %s post %r as %s", "write", article.slug, status)
            return PublishResult("dry-run", None, status, "", "")

        self.check_access(publish)
        existing = self.client.find_post_by_slug(article.slug)
        if existing and existing["status"] in ("publish", "future", "private") and not publish:
            raise PublishBlocked(
                f"Post {existing['id']} with slug {article.slug!r} is already {existing['status']}. "
                "Refusing to change a live post from a draft run; pass --publish to update it deliberately.")

        payload = {
            "title": article.title,
            "slug": article.slug,
            "excerpt": article.excerpt,
            "content": content,
            "status": status,
            "categories": sorted(self.client.ensure_terms("categories", article.categories)),
            "tags": sorted(self.client.ensure_terms("tags", article.tags)),
            "meta": {META_KEY: article.meta_description},
        }
        if featured_image:
            payload["featured_media"] = self._featured_media_id(Path(featured_image), article.title, existing)

        if existing is None:
            post = self.client.create_post(payload)
            log.info("Created post %d (%s)", post["id"], post["status"])
            return self._result("created", post, tuple(payload))

        changed = self._diff(existing, payload)
        if not changed:
            log.info("Post %d already matches; nothing to do", existing["id"])
            return self._result("unchanged", existing)
        post = self.client.update_post(existing["id"], {k: payload[k] for k in changed})
        log.info("Updated post %d: %s", post["id"], ", ".join(changed))
        return self._result("updated", post, tuple(changed))

    @staticmethod
    def _diff(existing: dict, payload: dict) -> tuple:
        changed = []
        for key, value in payload.items():
            if key == "meta":
                current = (existing.get("meta") or {}).get(META_KEY)
                # If the site lacks the meta plugin the key never comes back; don't loop on it.
                if current is not None and current != value[META_KEY]:
                    changed.append(key)
            elif key in ("categories", "tags"):
                if sorted(existing.get(key) or []) != value:
                    changed.append(key)
            elif key in ("title", "excerpt", "content"):
                if _raw(existing.get(key)).strip() != value.strip():
                    changed.append(key)
            elif existing.get(key) != value:
                changed.append(key)
        return tuple(changed)

    def _result(self, action: str, post: dict, changed: tuple = ()) -> PublishResult:
        return PublishResult(
            action=action, post_id=post["id"], status=post["status"], link=post.get("link", ""),
            edit_link=f"{self.client.base_url}/wp-admin/post.php?post={post['id']}&action=edit",
            changed_fields=changed,
        )
