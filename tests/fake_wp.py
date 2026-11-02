"""An in-memory stand-in for the WordPress REST API, plugged in as the requests session."""
import json
from urllib.parse import urlparse


class FakeResponse:
    def __init__(self, status_code, body=None, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeWordPress:
    USER = ("editor", "abcd efgh ijkl mnop")

    def __init__(self, unfiltered_html=True, can_publish=True):
        self.auth = None
        self.headers = {}
        self.posts, self.media = {}, {}
        self.terms = {"categories": {1: "Uncategorized"}, "tags": {}}
        self.next_id = 100
        self.forced = []          # list of (status, headers) returned before normal handling
        self.calls = []
        self.caps = {"edit_posts": True, "publish_posts": can_publish, "unfiltered_html": unfiltered_html}

    def _id(self):
        self.next_id += 1
        return self.next_id

    def request(self, method, url, timeout=None, params=None, json=None, data=None, headers=None):
        path = urlparse(url).path.replace("/wp-json", "")
        self.calls.append((method, path))
        if self.forced:
            status, hdrs = self.forced.pop(0)
            return FakeResponse(status, {"code": "rate_limited", "message": "slow down"}, hdrs)
        user, password = self.auth
        if (user, password) != (self.USER[0], self.USER[1].replace(" ", "")):
            return FakeResponse(401, {"code": "incorrect_password", "message": "The provided password is an invalid application password."})
        params = params or {}
        parts = path.strip("/").split("/")[2:]   # after wp/v2

        if parts == ["users", "me"]:
            return FakeResponse(200, {"id": 1, "slug": "editor", "capabilities": self.caps})

        if parts[0] == "posts":
            if len(parts) == 1 and method == "GET":
                found = [p for p in self.posts.values() if p["slug"] == params.get("slug")]
                return FakeResponse(200, found)
            if len(parts) == 1 and method == "POST":
                pid = self._id()
                self.posts[pid] = self._store_post(pid, json, {})
                return FakeResponse(201, self.posts[pid])
            pid = int(parts[1])
            self.posts[pid] = self._store_post(pid, json, self.posts[pid])
            return FakeResponse(200, self.posts[pid])

        if parts[0] in ("categories", "tags"):
            terms = self.terms[parts[0]]
            if method == "GET":
                search = params.get("search", "").lower()
                return FakeResponse(200, [{"id": i, "name": n} for i, n in terms.items() if search in n.lower()])
            if any(n.lower() == json["name"].lower() for n in terms.values()):
                return FakeResponse(400, {"code": "term_exists", "message": "exists"})
            tid = self._id()
            terms[tid] = json["name"]
            return FakeResponse(201, {"id": tid, "name": json["name"]})

        if parts[0] == "media":
            if len(parts) == 1 and method == "GET":
                search = params.get("search", "").lower()
                return FakeResponse(200, [m for m in self.media.values() if search in m["media_details"]["file"]])
            if len(parts) == 1 and method == "POST":
                name = headers["Content-Disposition"].split('filename="')[1].rstrip('"')
                mid = self._id()
                self.media[mid] = {"id": mid, "alt_text": "", "media_details": {"file": f"2026/11/{name}"},
                                   "source_url": f"http://wp.test/uploads/2026/11/{name}", "bytes": len(data)}
                return FakeResponse(201, self.media[mid])
            mid = int(parts[1])
            if mid not in self.media:
                return FakeResponse(404, {"code": "rest_post_invalid_id", "message": "Invalid post ID."})
            if method == "POST":
                self.media[mid].update(json)
            return FakeResponse(200, self.media[mid])
        return FakeResponse(404, {"code": "rest_no_route", "message": "No route"})

    @staticmethod
    def _store_post(pid, payload, current):
        post = dict(current) or {"id": pid, "meta": {"ai_meta_description": ""}, "featured_media": 0,
                                 "categories": [], "tags": []}
        for key, value in payload.items():
            if key in ("title", "excerpt", "content"):
                post[key] = {"raw": value, "rendered": value}
            elif key == "meta":
                post["meta"] = {**post.get("meta", {}), **value}
            else:
                post[key] = value
        post["link"] = f"http://wp.test/?p={pid}"
        return post
