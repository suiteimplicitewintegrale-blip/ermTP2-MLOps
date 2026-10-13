"""Collection from the public Stack Exchange API (no key, 300 requests/day).

Two calls per query: the default filter gives the comment permalink and date,
``filter=withbody`` gives the HTML body. Comments carry no image, so the
``media`` column stays empty for this source.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from .. import config
from ..textclean import html_to_text, is_relevant, make_id

API_ROOT = "https://api.stackexchange.com/2.3"
COMMENTS_URL = f"{API_ROOT}/comments"
COMMENTS_BY_ID_URL = f"{API_ROOT}/comments/{{ids}}"


def batched(items, size: int):
    """Yield consecutive chunks of ``size`` items."""
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _iso_date(epoch_seconds: float | int | None) -> str:
    if not epoch_seconds:
        return ""
    return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).strftime("%Y-%m-%d")


def merge_bodies(items: list[dict], bodies: list[dict]) -> list[dict]:
    """Attach HTML bodies to the comments they belong to.

    Comments deleted between the two calls simply disappear.
    """
    by_id = {b.get("comment_id"): b.get("body", "") for b in bodies}
    return [dict(item, body=by_id[item["comment_id"]]) for item in items
            if item.get("comment_id") in by_id]


def parse_comment(site: str, item: dict, body_item: dict) -> dict | None:
    """Map one Stack Exchange comment to a corpus record (``None`` if empty)."""
    text = html_to_text(body_item.get("body", "")).strip()
    if not text:
        return None

    comment_id = item.get("comment_id")
    metadata = {
        "site": site,
        "post_id": item.get("post_id"),
        "score": item.get("score", 0),
        "edited": bool(item.get("edited", False)),
        "has_image": False,
    }
    return {
        "id": make_id("stackexchange", f"{site}-{comment_id}"),
        "date": _iso_date(item.get("creation_date")),
        "text": text,
        "media": "",
        "url": item.get("link", ""),
        "source": "stackexchange",
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }


class StackExchangeCollector:
    """Searches comments matching the collection keywords on a few sites."""

    def __init__(self, session: requests.Session | None = None, sleep=time.sleep,
                 keywords_only: bool = True):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})
        self.sleep = sleep
        self.keywords_only = keywords_only
        self.quota_remaining: int | None = None

    def _get(self, url: str, params: dict) -> dict:
        response = self.session.get(url, timeout=config.REQUEST_TIMEOUT_S, params=params)
        response.raise_for_status()
        payload = response.json()
        if "quota_remaining" in payload:
            self.quota_remaining = payload["quota_remaining"]
        if payload.get("backoff"):
            self.sleep(float(payload["backoff"]))
        return payload

    def search_comments(self, site: str, query: str, pagesize: int) -> list[dict]:
        payload = self._get(
            COMMENTS_URL,
            {"site": site, "q": query, "pagesize": pagesize, "order": "desc",
             "sort": "creation", "filter": "default"},
        )
        return payload.get("items", [])

    def fetch_bodies(self, site: str, comment_ids: list[int]) -> list[dict]:
        bodies: list[dict] = []
        for chunk in batched(comment_ids, 100):
            self.sleep(config.REQUEST_PAUSE_S)
            payload = self._get(
                COMMENTS_BY_ID_URL.format(ids=";".join(str(i) for i in chunk)),
                {"site": site, "filter": "withbody"},
            )
            bodies.extend(payload.get("items", []))
        return bodies

    def collect_site(self, site: str, queries: list[str],
                     pagesize: int | None = None) -> list[dict]:
        pagesize = pagesize or config.STACKEXCHANGE_PAGESIZE
        items: list[dict] = []
        seen: set[int] = set()
        for query in queries:
            self.sleep(config.REQUEST_PAUSE_S)
            for item in self.search_comments(site, query, pagesize):
                if item.get("comment_id") not in seen:
                    seen.add(item["comment_id"])
                    items.append(item)

        if not items:
            return []
        bodies = self.fetch_bodies(site, [i["comment_id"] for i in items])
        records = []
        for item, body in zip(merge_bodies(items, bodies), merge_bodies(items, bodies)):
            pass  # placeholder replaced below
        records = []
        for merged in merge_bodies(items, bodies):
            record = parse_comment(site, merged, merged)
            if record is None:
                continue
            if self.keywords_only and not is_relevant(record["text"]):
                continue
            records.append(record)
        return records

    def collect(self, sites: list[str] | None = None,
                queries: list[str] | None = None) -> list[dict]:
        sites = sites or config.STACKEXCHANGE_SITES
        queries = queries or config.STACKEXCHANGE_QUERIES
        records: list[dict] = []
        for site in sites:
            records.extend(self.collect_site(site, queries))
        return records
