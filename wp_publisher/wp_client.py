"""A small WordPress REST API client using Application Password (HTTP Basic) auth."""
import html
import logging
import mimetypes
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 502, 503, 504}
POST_STATUSES = "publish,future,draft,pending,private"


class WPError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class WPAuthError(WPError):
    """401/403: wrong username or Application Password, or the user lacks the capability."""


class WPRateLimitError(WPError):
    """Still getting 429 Too Many Requests after every retry."""


class WPClient:
    def __init__(self, base_url: str, username: str, app_password: str, session=None,
                 max_retries: int = 4, timeout: float = 30.0, max_wait: float = 60.0,
                 sleep: Callable[[float], None] = time.sleep):
        if not base_url or not username or not app_password:
            raise WPAuthError("WP_BASE_URL, WP_USERNAME and WP_APP_PASSWORD must all be set.")
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        # Application Passwords are shown with spaces; WordPress accepts them with or without.
        self.session.auth = (username, app_password.replace(" ", ""))
        self.session.headers.update({"User-Agent": "wordpress-ai-publisher/1.0"})
        self.max_retries = max_retries
        self.timeout = timeout
        self.max_wait = max_wait
        self.sleep = sleep

    # -- transport -----------------------------------------------------------------------------

    def request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}/wp-json{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise WPError(f"Could not reach {self.base_url}: {exc}") from exc
                wait = min(2 ** (attempt - 1), self.max_wait)
                log.warning("%s %s failed (%s); retry %d in %.0fs", method, path, exc, attempt, wait)
                self.sleep(wait)
                continue

            if response.status_code in RETRY_STATUSES and attempt <= self.max_retries:
                wait = self._retry_after(response, attempt)
                log.warning("%s %s -> %d; retry %d in %.1fs", method, path, response.status_code, attempt, wait)
                self.sleep(wait)
                continue
            if response.status_code >= 400:
                self._raise(response, method, path)
            return response.json() if response.content else None

    def _retry_after(self, response, attempt: int) -> float:
        header = response.headers.get("Retry-After", "")
        try:
            return min(max(float(header), 0.0), self.max_wait)
        except ValueError:
            return min(2.0 ** (attempt - 1), self.max_wait)

    @staticmethod
    def _raise(response, method: str, path: str):
        try:
            body = response.json()
            code, message = body.get("code", ""), body.get("message", "")
        except ValueError:
            code, message = "", response.text[:200]
        status = response.status_code
        text = f"{method} {path} -> {status} {code}: {message}".strip()
        if status in (401, 403):
            raise WPAuthError(text, status, code)
        if status == 429:
            raise WPRateLimitError(text, status, code)
        raise WPError(text, status, code)

    # -- API -----------------------------------------------------------------------------------

    def me(self) -> dict:
        return self.request("GET", "/wp/v2/users/me", params={"context": "edit"})

    def find_post_by_slug(self, slug: str) -> Optional[dict]:
        posts = self.request("GET", "/wp/v2/posts",
                             params={"slug": slug, "status": POST_STATUSES, "context": "edit"})
        return posts[0] if posts else None

    def create_post(self, payload: dict) -> dict:
        return self.request("POST", "/wp/v2/posts", json=payload)

    def update_post(self, post_id: int, payload: dict) -> dict:
        return self.request("POST", f"/wp/v2/posts/{post_id}", json=payload)

    def ensure_terms(self, taxonomy: str, names: List[str]) -> List[int]:
        """Return term ids for `names` in `taxonomy` ("categories" or "tags"), creating missing ones."""
        ids = []
        for name in names:
            found = self.request("GET", f"/wp/v2/{taxonomy}", params={"search": name, "per_page": 100})
            match = next((t for t in found if html.unescape(t["name"]).lower() == name.lower()), None)
            if match:
                ids.append(match["id"])
                continue
            try:
                created = self.request("POST", f"/wp/v2/{taxonomy}", json={"name": name})
                log.info("Created %s %r (id %d)", taxonomy[:-1] if taxonomy == "tags" else "category", name, created["id"])
                ids.append(created["id"])
            except WPError as exc:
                if exc.code != "term_exists":
                    raise
                # Another run created it in between, or the search missed it.
                retry = self.request("GET", f"/wp/v2/{taxonomy}", params={"search": name, "per_page": 100})
                ids.append(next(t["id"] for t in retry if html.unescape(t["name"]).lower() == name.lower()))
        return ids

    def get_media(self, media_id: int) -> Optional[dict]:
        try:
            return self.request("GET", f"/wp/v2/media/{media_id}", params={"context": "edit"})
        except WPError as exc:
            if exc.status == 404:
                return None
            raise

    def find_media_by_filename(self, filename: str) -> Optional[dict]:
        stem = Path(filename).stem
        found = self.request("GET", "/wp/v2/media", params={"search": stem, "per_page": 100, "context": "edit"})
        for item in found:
            if media_filename(item) == filename.lower():
                return item
        return None

    def upload_media(self, path: Path, alt_text: str = "") -> dict:
        path = Path(path)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if not mime.startswith("image/"):
            raise WPError(f"Featured image must be an image file, got {mime} for {path.name}.")
        headers: Dict[str, str] = {"Content-Disposition": f'attachment; filename="{path.name}"',
                                   "Content-Type": mime}
        media = self.request("POST", "/wp/v2/media", data=path.read_bytes(), headers=headers)
        if alt_text:
            media = self.request("POST", f"/wp/v2/media/{media['id']}", json={"alt_text": alt_text})
        log.info("Uploaded %s as media %d", path.name, media["id"])
        return media


def media_filename(item: dict) -> str:
    """The uploaded file's name as WordPress stored it, e.g. 'desk.jpg'."""
    source = (item.get("media_details") or {}).get("file") or item.get("source_url") or ""
    return source.rsplit("/", 1)[-1].lower()
