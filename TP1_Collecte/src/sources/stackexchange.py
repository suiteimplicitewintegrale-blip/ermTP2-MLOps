"""Collection from the public Stack Exchange API (no key, 300 requests/day).

Why questions and answers rather than comments? The ``q`` parameter of
``/comments`` matches the *parent post*, so the returned comments rarely contain
the keyword themselves. ``/search/advanced`` really does search the post body,
so the collected messages carry the vocabulary we are after. Each question and
its answers are kept as separate messages.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from .. import config
from ..textclean import html_to_text, is_relevant, make_id

API_ROOT = "https://api.stackexchange.com/2.3"
SEARCH_URL = f"{API_ROOT}/search/advanced"
ANSWERS_URL = f"{API_ROOT}/questions/{{ids}}/answers"
STACKOVERFLOW_HOST = "https://stackoverflow.com"


def site_host(site: str) -> str:
    """Stack Overflow has its own domain, the others follow ``<slug>.stackexchange.com``."""
    return STACKOVERFLOW_HOST if site == "stackoverflow" else f"https://{site}.stackexchange.com"


def post_permalink(site: str, question_id: int, answer_id: int | None = None) -> str:
    """Public permalink of a question or of one of its answers."""
    base = f"{site_host(site)}/q/{question_id}"
    return base if answer_id is None else f"{base}#{answer_id}"


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


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + " […]"


def parse_question(site: str, item: dict) -> dict | None:
    """Map one Stack Exchange question to a corpus record."""
    body = html_to_text(item.get("body", ""))
    title = html_to_text(item.get("title", ""))
    text = f"{title}. {body}".strip(". ") if title else body
    text = _truncate(text.strip(), config.MAX_TEXT_CHARS)
    if len(text) < config.MIN_TEXT_CHARS:
        return None

    question_id = item.get("question_id")
    metadata = {
        "site": site,
        "kind": "question",
        "score": item.get("score", 0),
        "nb_answers": item.get("answer_count", 0),
        "tags": item.get("tags", []),
        "has_image": False,
    }
    return {
        "id": make_id("stackexchange", f"{site}-q{question_id}"),
        "date": _iso_date(item.get("creation_date")),
        "text": text,
        "media": "",
        "url": item.get("link") or post_permalink(site, question_id),
        "source": "stackexchange",
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }


def parse_answer(site: str, item: dict) -> dict | None:
    """Map one Stack Exchange answer to a corpus record."""
    text = _truncate(html_to_text(item.get("body", "")).strip(), config.MAX_TEXT_CHARS)
    if len(text) < config.MIN_TEXT_CHARS:
        return None

    answer_id = item.get("answer_id")
    question_id = item.get("question_id")
    metadata = {
        "site": site,
        "kind": "answer",
        "score": item.get("score", 0),
        "question_id": question_id,
        "is_accepted": bool(item.get("is_accepted", False)),
        "has_image": False,
    }
    return {
        "id": make_id("stackexchange", f"{site}-a{answer_id}"),
        "date": _iso_date(item.get("creation_date")),
        "text": text,
        "media": "",
        "url": post_permalink(site, question_id, answer_id),
        "source": "stackexchange",
        "metadata": json.dumps(metadata, ensure_ascii=False),
    }


class StackExchangeCollector:
    """Searches questions matching the collection keywords, then their answers."""

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

    def search_questions(self, site: str, query: str,
                         pagesize: int | None = None) -> list[dict]:
        pagesize = pagesize or config.STACKEXCHANGE_PAGESIZE
        payload = self._get(
            SEARCH_URL,
            {"site": site, "q": query, "pagesize": pagesize, "order": "desc",
             "sort": "votes", "filter": "withbody"},
        )
        return payload.get("items", [])

    def fetch_answers(self, site: str, question_ids: list[int]) -> list[dict]:
        answers: list[dict] = []
        for chunk in batched(question_ids, 100):
            self.sleep(config.REQUEST_PAUSE_S)
            payload = self._get(
                ANSWERS_URL.format(ids=";".join(str(i) for i in chunk)),
                {"site": site, "filter": "withbody",
                 "pagesize": config.STACKEXCHANGE_PAGESIZE, "sort": "votes",
                 "order": "desc"},
            )
            answers.extend(payload.get("items", []))
        return answers

    def collect_site(self, site: str, queries: list[str],
                     collect_answers: bool | None = None) -> list[dict]:
        if collect_answers is None:
            collect_answers = config.STACKEXCHANGE_COLLECT_ANSWERS
        questions: list[dict] = []
        seen: set[int] = set()
        for query in queries:
            self.sleep(config.REQUEST_PAUSE_S)
            for item in self.search_questions(site, query):
                if item.get("question_id") not in seen:
                    seen.add(item["question_id"])
                    questions.append(item)
        if not questions:
            return []

        # Half the budget goes to questions, half to their answers: capping only
        # at the end would fill the whole quota with questions and silently drop
        # every answer.
        budget = config.STACKEXCHANGE_MAX_PER_SITE
        if collect_answers:
            questions = questions[: max(1, budget // 2)]

        records: list[dict] = []
        for question in questions:
            record = parse_question(site, question)
            if record is not None:
                records.append(record)

        if collect_answers:
            answers = self.fetch_answers(site, [q["question_id"] for q in questions])
            for answer in answers:
                record = parse_answer(site, answer)
                if record is not None:
                    records.append(record)

        if self.keywords_only:
            records = [r for r in records if is_relevant(r["text"])]
        return records[:budget]

    def collect(self, sites: list[str] | None = None,
                queries: list[str] | None = None) -> list[dict]:
        sites = sites or config.STACKEXCHANGE_SITES
        queries = queries or config.STACKEXCHANGE_QUERIES
        records: list[dict] = []
        for site in sites:
            records.extend(self.collect_site(site, queries))
        return records
