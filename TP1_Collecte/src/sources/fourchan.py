"""Collection from the public 4chan archive (read-only JSON API, no key).

Only public board content is read, through ``a.4cdn.org`` which is the public
dump API. No account, no login, no personal data: authors are anonymous and are
never stored (see :mod:`src.textclean.make_id`).
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from .. import config
from ..textclean import html_to_text, is_relevant, make_id

CATALOG_URL = "https://a.4cdn.org/{board}/catalog.json"
THREAD_URL = "https://a.4cdn.org/{board}/thread/{no}.json"
IMAGE_HOST = "https://i.4cdn.org/{board}/{tim}{ext}"
BOARD_URL = "https://boards.4chan.org/{board}/thread/{no}"


def image_url(board: str, tim: int, ext: str) -> str:
    return IMAGE_HOST.format(board=board, tim=tim, ext=ext)


def thread_url(board: str, thread_no: int, post_no: int | None = None) -> str:
    post_no = thread_no if post_no is None else post_no
    return f"{BOARD_URL.format(board=board, no=thread_no)}#p{post_no}"


def _iso_date(epoch_seconds: float | int | None) -> str:
    if not epoch_seconds:
        return ""
    return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).strftime("%Y-%m-%d")


def parse_post(board: str, post: dict) -> dict | None:
    """Map one raw 4chan post to a corpus record (``None`` when unusable)."""
    text = html_to_text(post.get("com", "")).strip()
    if not text:
        return None

    post_no = int(post.get("no", 0) or 0)
    thread_no = int(post.get("resto") or post_no)
    tim, ext = post.get("tim"), post.get("ext")
    media = image_url(board, tim, ext) if tim and ext else ""

    metadata = {
        "board": board,
        "thread_no": thread_no,
        "has_image": bool(media),
        "replies": post.get("replies", 0),
        "images": post.get("images", 0),
        "is_op": thread_no == post_no,
    }
    return {
        "id": make_id("4chan", f"{board}-{post_no}"),
        "date": _iso_date(post.get("time")),
        "text": text,
        "media": media,
        "url": thread_url(board, thread_no, post_no),
        "source": "4chan",
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }


def parse_thread(board: str, payload: dict) -> list[dict]:
    """Map a whole ``thread/{no}.json`` payload to records."""
    records = []
    for post in payload.get("posts", []):
        record = parse_post(board, post)
        if record is not None:
            records.append(record)
    return records


def is_image_post(record: dict, min_chars: int) -> bool:
    """True for a post that brings an image *and* enough text to be usable."""
    return bool(record.get("media")) and len(record.get("text", "")) >= min_chars


def select_kept(
    posts: list[dict],
    keywords_only: bool = True,
    keep_image_posts: bool = True,
    max_image_posts: int = config.FOURCHAN_MAX_IMAGE_POSTS_PER_THREAD,
    min_image_chars: int = config.FOURCHAN_MIN_IMAGE_POST_CHARS,
    max_posts: int = config.FOURCHAN_MAX_POSTS_PER_THREAD,
) -> list[dict]:
    """Keep keyword posts plus a few image posts per thread, in reading order.

    Keyword matches are the backbone of the corpus; a capped number of image
    posts is added so the multimodal part has material without drowning the
    corpus in off-topic chatter.
    """
    if not keywords_only:
        return posts[:max_posts]

    kept: list[dict] = []
    image_posts = 0
    for post in posts:
        if is_relevant(post["text"]):
            kept.append(post)
        elif keep_image_posts and image_posts < max_image_posts and is_image_post(post, min_image_chars):
            kept.append(post)
            image_posts += 1
        if len(kept) >= max_posts:
            break
    return kept


class FourChanCollector:
    """Fetches threads from a board catalog and keeps keyword-matching posts.

    Image posts with a real text body are kept in limited number even without a
    keyword: they are what feeds the multimodal part of the corpus. Boards ``g``
    and ``v`` are work-safe boards, which is why they were chosen.
    """

    def __init__(self, session: requests.Session | None = None, sleep=time.sleep,
                 keywords_only: bool = True, keep_image_posts: bool | None = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.USER_AGENT})
        self.sleep = sleep
        self.keywords_only = keywords_only
        self.keep_image_posts = (
            config.FOURCHAN_KEEP_IMAGE_POSTS if keep_image_posts is None else keep_image_posts
        )

    def _get_json(self, url: str) -> dict:
        response = self.session.get(url, timeout=config.REQUEST_TIMEOUT_S)
        response.raise_for_status()
        return response.json()

    def thread_numbers(self, board: str) -> list[int]:
        catalog = self._get_json(CATALOG_URL.format(board=board))
        numbers = [
            thread["no"]
            for page in catalog
            for thread in page.get("threads", [])
            if not thread.get("sticky") and thread.get("replies", 0) > 0
        ]
        return numbers[: config.FOURCHAN_THREADS_PER_BOARD]

    def collect_board(self, board: str, limit_threads: int | None = None) -> list[dict]:
        limit = limit_threads or config.FOURCHAN_THREADS_PER_BOARD
        records: list[dict] = []
        for thread_no in self.thread_numbers(board)[:limit]:
            self.sleep(config.REQUEST_PAUSE_S)
            payload = self._get_json(THREAD_URL.format(board=board, no=thread_no))
            posts = parse_thread(board, payload)
            kept = select_kept(
                posts,
                keywords_only=self.keywords_only,
                keep_image_posts=self.keep_image_posts,
            )
            records.extend(kept)
        return records

    def collect(self, boards: list[str] | None = None) -> list[dict]:
        records: list[dict] = []
        for board in boards or config.FOURCHAN_BOARDS:
            records.extend(self.collect_board(board))
        return records
