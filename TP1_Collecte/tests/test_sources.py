"""Tests for the source parsers (offline, using captured API payloads)."""

from __future__ import annotations

import json

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

SE_ITEM = {
    "comment_id": 30146633,
    "creation_date": 1385468758,
    "post_id": 11304926,
    "score": 2049,
    "edited": False,
    "link": "https://stackoverflow.com/questions/11304926/x#comment30146633_11304926",
    "owner": {"user_id": 42, "display_name": "Some User"},
}
SE_BODY = {"comment_id": 30146633, "body": "<p>You are an <b>idiot</b>, RTFM.</p>"}


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


class TestStackExchangeParse:
    def test_merge_bodies_adds_body(self):
        merged = stackexchange.merge_bodies([SE_ITEM], [SE_BODY])
        assert merged[0]["body"] == SE_BODY["body"]

    def test_merge_bodies_skips_unknown_id(self):
        assert stackexchange.merge_bodies([SE_ITEM], [{"comment_id": 9, "body": "x"}]) == []

    def test_parse_comment_columns(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        assert set(rec) == {"id", "date", "text", "media", "url", "source", "metadata"}

    def test_source_label(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        assert rec["source"] == "stackexchange"

    def test_html_stripped_and_cleaned(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        assert "<" not in rec["text"]
        assert "idiot" in rec["text"]
        assert "rtfm" in rec["text"]

    def test_date_iso(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        assert rec["date"] == "2013-11-26"

    def test_no_media_on_stackexchange(self):
        assert stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)["media"] == ""

    def test_url_is_comment_permalink(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        assert rec["url"] == SE_ITEM["link"]

    def test_metadata_has_site_and_score_only(self):
        rec = stackexchange.parse_comment("stackoverflow", SE_ITEM, SE_BODY)
        meta = json.loads(rec["metadata"])
        assert meta["site"] == "stackoverflow"
        assert meta["score"] == 2049
        assert "display_name" not in rec["metadata"]
        assert "Some User" not in rec["metadata"]

    def test_empty_body_returns_none(self):
        assert stackexchange.parse_comment("stackoverflow", SE_ITEM, {"comment_id": 1, "body": ""}) is None


class TestQueries:
    def test_fourchan_builds_image_url(self):
        assert fourchan.image_url("g", 123, ".jpg") == "https://i.4cdn.org/g/123.jpg"

    def test_fourchan_thread_url(self):
        assert fourchan.thread_url("g", 99) == "https://boards.4chan.org/g/thread/99#p99"

    def test_stackexchange_batches_ids(self):
        batches = list(stackexchange.batched(range(250), 100))
        assert [len(b) for b in batches] == [100, 100, 50]
