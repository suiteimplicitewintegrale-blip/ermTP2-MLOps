"""Tests for the source parsers (offline, using captured API payloads)."""

from __future__ import annotations

import json

from src import config
from src.sources import fourchan, stackexchange

FOURCHAN_POST = {
    "no": 105076684,
    "resto": 105076600,
    "time": 1745612650,
    "name": "Anonymous",
    "trip": "!abc",
    "com": 'fucking <span class="quote">&gt;&gt;105076600</span><br>you are an '
           '<a href="https://example.com" rel="nofollow">idiot</a> &amp; a loser',
    "tim": 1745612650141704,
    "ext": ".png",
    "w": 800,
    "h": 600,
    "fsize": 123456,
    "md5": "deadbeef",
    "replies": 3,
    "images": 2,
}

FOURCHAN_POST_NO_IMAGE = {
    "no": 105076685,
    "resto": 105076600,
    "time": 1745612700,
    "com": "cope harder seethe",
    "replies": 0,
}

SE_QUESTION = {
    "question_id": 11304926,
    "creation_date": 1385468758,
    "score": 42,
    "answer_count": 7,
    "tags": ["python", "csv"],
    "title": "Why is my parser so stupid?",
    "body": "<p>My <b>stupid</b> parser keeps failing on &quot;quoted&quot; fields.</p>",
    "link": "https://stackoverflow.com/questions/11304926/why-is-my-parser-so-stupid",
    "owner": {"user_id": 42, "display_name": "Some User"},
}

SE_ANSWER = {
    "answer_id": 5550001,
    "question_id": 11304926,
    "creation_date": 1385469999,
    "score": 9,
    "is_accepted": True,
    "body": "<p>You are an idiot, just use the csv module.</p>",
    "owner": {"user_id": 43, "display_name": "Another User"},
}


class TestFourChanParsePost:
    def test_returns_expected_columns(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert set(rec) == {"id", "date", "text", "media", "url", "source", "metadata"}

    def test_source_is_fourchan(self):
        assert fourchan.parse_post("g", FOURCHAN_POST)["source"] == "4chan"

    def test_html_is_cleaned_from_text(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert "<" not in rec["text"]
        assert ">>105076600" in rec["text"]
        assert "idiot" in rec["text"]

    def test_date_is_iso_utc(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert rec["date"] == "2025-04-25"
        assert len(rec["date"]) == 10

    def test_media_is_full_image_url(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert rec["media"] == "https://i.4cdn.org/g/1745612650141704.png"

    def test_media_empty_without_image(self):
        assert fourchan.parse_post("g", FOURCHAN_POST_NO_IMAGE)["media"] == ""

    def test_url_points_to_thread_post(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert rec["url"] == "https://boards.4chan.org/g/thread/105076600#p105076684"

    def test_metadata_is_json_without_author_identity(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        meta = json.loads(rec["metadata"])
        assert meta["board"] == "g"
        assert meta["replies"] == 3
        assert "name" not in meta and "trip" not in meta

    def test_id_is_anonymised(self):
        rec = fourchan.parse_post("g", FOURCHAN_POST)
        assert rec["id"].startswith("4chan-")
        assert "105076684" not in rec["id"]

    def test_op_post_resto_zero_uses_own_no(self):
        op = dict(FOURCHAN_POST, resto=0)
        assert "105076684" in fourchan.parse_post("g", op)["url"]

    def test_empty_comment_returns_none(self):
        assert fourchan.parse_post("g", dict(FOURCHAN_POST, com="")) is None

    def test_whitespace_only_comment_returns_none(self):
        assert fourchan.parse_post("g", dict(FOURCHAN_POST, com="<br>  ")) is None


class TestFourChanParseThread:
    def test_parses_all_posts(self):
        payload = {"posts": [FOURCHAN_POST, FOURCHAN_POST_NO_IMAGE]}
        recs = fourchan.parse_thread("g", payload)
        assert len(recs) == 2

    def test_skips_posts_without_text(self):
        payload = {"posts": [{"no": 1, "resto": 0, "time": 1}, FOURCHAN_POST]}
        assert len(fourchan.parse_thread("g", payload)) == 1


class TestFourChanSelection:
    @staticmethod
    def post(no, text, media=""):
        return {"id": f"4chan-{no}", "text": text, "media": media, "source": "4chan"}

    def test_keeps_keyword_posts(self):
        posts = [self.post(1, "you are an idiot here"), self.post(2, "nice weather today indeed")]
        kept = fourchan.select_kept(posts)
        assert [p["id"] for p in kept] == ["4chan-1"]

    def test_adds_a_few_image_posts_without_keyword(self):
        posts = [
            self.post(1, "a perfectly neutral sentence about technology", "https://i.4cdn.org/g/1.png"),
            self.post(2, "another neutral sentence about technology", "https://i.4cdn.org/g/2.png"),
        ]
        kept = fourchan.select_kept(posts, max_image_posts=1)
        assert [p["id"] for p in kept] == ["4chan-1"]

    def test_ignores_image_posts_without_enough_text(self):
        posts = [self.post(1, "ok", "https://i.4cdn.org/g/1.png")]
        assert fourchan.select_kept(posts) == []

    def test_image_posts_can_be_disabled(self):
        posts = [self.post(1, "a perfectly neutral sentence about technology", "https://i.4cdn.org/g/1.png")]
        assert fourchan.select_kept(posts, keep_image_posts=False) == []

    def test_respects_max_posts(self):
        posts = [self.post(i, "you are an idiot, number " + str(i)) for i in range(10)]
        assert len(fourchan.select_kept(posts, max_posts=4)) == 4

    def test_keeps_reading_order(self):
        posts = [
            self.post(1, "you are an idiot here"),
            self.post(2, "a neutral sentence with an image attached", "https://i.4cdn.org/g/2.png"),
            self.post(3, "another idiot message here"),
        ]
        assert [p["id"] for p in fourchan.select_kept(posts)] == ["4chan-1", "4chan-2", "4chan-3"]

    def test_keywords_only_false_keeps_everything(self):
        posts = [self.post(1, "hello"), self.post(2, "world hello")]
        assert len(fourchan.select_kept(posts, keywords_only=False)) == 2


class TestStackExchangeParse:
    def test_question_columns(self):
        rec = stackexchange.parse_question("stackoverflow", SE_QUESTION)
        assert set(rec) == {"id", "date", "text", "media", "url", "source", "metadata"}

    def test_source_label(self):
        assert stackexchange.parse_question("stackoverflow", SE_QUESTION)["source"] == "stackexchange"

    def test_title_and_body_are_merged(self):
        rec = stackexchange.parse_question("stackoverflow", SE_QUESTION)
        assert rec["text"].startswith("Why is my parser so stupid?")
        assert "stupid" in rec["text"]

    def test_html_is_stripped(self):
        rec = stackexchange.parse_question("stackoverflow", SE_QUESTION)
        assert "<" not in rec["text"]
        assert '"quoted"' in rec["text"]

    def test_date_iso(self):
        assert stackexchange.parse_question("stackoverflow", SE_QUESTION)["date"] == "2013-11-26"

    def test_no_media_on_stackexchange(self):
        assert stackexchange.parse_question("stackoverflow", SE_QUESTION)["media"] == ""

    def test_question_url_is_the_permalink(self):
        rec = stackexchange.parse_question("stackoverflow", SE_QUESTION)
        assert rec["url"] == SE_QUESTION["link"]

    def test_question_url_is_rebuilt_when_api_has_no_link(self):
        item = {k: v for k, v in SE_QUESTION.items() if k != "link"}
        rec = stackexchange.parse_question("stackoverflow", item)
        assert rec["url"] == "https://stackoverflow.com/q/11304926"

    def test_metadata_has_no_author_identity(self):
        rec = stackexchange.parse_question("stackoverflow", SE_QUESTION)
        meta = json.loads(rec["metadata"])
        assert meta == {
            "site": "stackoverflow",
            "kind": "question",
            "score": 42,
            "nb_answers": 7,
            "tags": ["python", "csv"],
            "has_image": False,
        }
        assert "Some User" not in rec["metadata"]

    def test_empty_question_returns_none(self):
        assert stackexchange.parse_question("stackoverflow", dict(SE_QUESTION, body="", title="")) is None

    def test_answer_columns_and_source(self):
        rec = stackexchange.parse_answer("stackoverflow", SE_ANSWER)
        assert set(rec) == {"id", "date", "text", "media", "url", "source", "metadata"}
        assert rec["source"] == "stackexchange"

    def test_answer_html_stripped(self):
        rec = stackexchange.parse_answer("stackoverflow", SE_ANSWER)
        assert "<" not in rec["text"]
        assert "idiot" in rec["text"]

    def test_answer_url_anchors_to_the_answer(self):
        rec = stackexchange.parse_answer("stackoverflow", SE_ANSWER)
        assert rec["url"] == "https://stackoverflow.com/q/11304926#5550001"

    def test_answer_metadata(self):
        meta = json.loads(stackexchange.parse_answer("stackoverflow", SE_ANSWER)["metadata"])
        assert meta["kind"] == "answer"
        assert meta["is_accepted"] is True
        assert "Another User" not in json.dumps(meta)

    def test_empty_answer_returns_none(self):
        assert stackexchange.parse_answer("stackoverflow", dict(SE_ANSWER, body="<p>  </p>")) is None

    def test_long_text_is_truncated(self):
        item = dict(SE_ANSWER, body="<p>" + "word " * 1000 + "</p>")
        rec = stackexchange.parse_answer("stackoverflow", item)
        assert len(rec["text"]) <= config.MAX_TEXT_CHARS + 5

    def test_ids_differ_between_question_and_answer(self):
        q = stackexchange.parse_question("stackoverflow", SE_QUESTION)["id"]
        a = stackexchange.parse_answer("stackoverflow", SE_ANSWER)["id"]
        assert q != a

    def test_url_uses_the_site_slug(self):
        assert stackexchange.site_host("gaming") == "https://gaming.stackexchange.com"
        assert stackexchange.site_host("stackoverflow") == "https://stackoverflow.com"

    def test_permalink_of_other_sites(self):
        assert stackexchange.post_permalink("gaming", 99) == "https://gaming.stackexchange.com/q/99"


class TestStackExchangeCollector:
    """The collector is driven by a fake session, so no network is involved."""

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.urls = []

        def get(self, url, timeout=None, params=None):
            self.urls.append((url, params))
            if "search/advanced" in url:
                return TestStackExchangeCollector.FakeResponse(
                    {"items": [dict(SE_QUESTION, question_id=1000 + i) for i in range(400)],
                     "quota_remaining": 300}
                )
            return TestStackExchangeCollector.FakeResponse({
                "items": [dict(SE_ANSWER, answer_id=7000 + i, question_id=1000 + i)
                          for i in range(400)],
                "quota_remaining": 299,
            })

    def collector(self, session):
        return stackexchange.StackExchangeCollector(session=session, sleep=lambda _s: None)

    def test_answers_are_not_starved_by_the_question_budget(self):
        session = self.FakeSession()
        records = self.collector(session).collect_site("stackoverflow", ["stupid"])

        kinds = [json.loads(r["metadata"])["kind"] for r in records]
        assert kinds.count("question") > 0
        assert kinds.count("answer") > 0, "answers must survive the per-site cap"

    def test_respects_the_per_site_cap(self):
        records = self.collector(self.FakeSession()).collect_site("stackoverflow", ["stupid"])
        assert len(records) <= config.STACKEXCHANGE_MAX_PER_SITE

    def test_answers_can_be_switched_off(self):
        session = self.FakeSession()
        records = self.collector(session).collect_site("stackoverflow", ["stupid"],
                                                       collect_answers=False)
        kinds = {json.loads(r["metadata"])["kind"] for r in records}
        assert kinds == {"question"}
        assert not any("answers" in url for url, _ in session.urls)

    def test_multiple_queries_do_not_duplicate_questions(self):
        records = self.collector(self.FakeSession()).collect_site("stackoverflow", ["a", "b"])
        ids = [r["id"] for r in records]
        assert len(ids) == len(set(ids))

    def test_keywords_only_drops_off_theme_messages(self):
        session = self.FakeSession()
        collector = self.collector(session)
        collector.keywords_only = True
        on_theme = collector.collect_site("stackoverflow", ["stupid"])
        collector.keywords_only = False
        everything = collector.collect_site("stackoverflow", ["stupid"])
        assert len(on_theme) <= len(everything)


class TestQueries:
    def test_fourchan_builds_image_url(self):
        assert fourchan.image_url("g", 123, ".jpg") == "https://i.4cdn.org/g/123.jpg"

    def test_fourchan_thread_url(self):
        assert fourchan.thread_url("g", 99) == "https://boards.4chan.org/g/thread/99#p99"

    def test_stackexchange_batches_ids(self):
        batches = list(stackexchange.batched(range(250), 100))
        assert [len(b) for b in batches] == [100, 100, 50]
