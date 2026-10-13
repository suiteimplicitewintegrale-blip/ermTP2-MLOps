"""Tests for HTML extraction, text cleaning, anonymised ids and weak labelling."""

from __future__ import annotations

from src import config
from src.textclean import (
    classify,
    clean_text,
    html_to_text,
    make_id,
    matched_keywords,
)


class TestHtmlToText:
    def test_strips_tags_and_keeps_text(self):
        assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"

    def test_br_becomes_newline(self):
        assert html_to_text("line one<br>line two") == "line one\nline two"

    def test_closing_block_tags_become_newlines(self):
        assert html_to_text("<p>one</p><p>two</p>") == "one\ntwo"

    def test_quotelink_keeps_visible_text(self):
        html = 'blah <a href="#p123" class="quotelink">&gt;&gt;123</a> yeah'
        out = html_to_text(html)
        assert ">>123" in out
        assert "href" not in out

    def test_entities_are_unescaped(self):
        assert html_to_text("don&#039;t &amp; won&#39;t") == "don't & won't"

    def test_code_block_is_kept_as_text(self):
        assert "print(1)" in html_to_text("<p><code>print(1)</code></p>")

    def test_empty_html(self):
        assert html_to_text("") == ""


class TestCleanText:
    def test_lowercases(self):
        assert clean_text("You Are So UGLY") == "you are so ugly"

    def test_removes_urls(self):
        out = clean_text("look at https://example.com/a?b=1 now")
        assert "http" not in out
        assert "example.com" not in out
        assert out.startswith("look at") and out.endswith("now")

    def test_removes_www_urls(self):
        assert "www" not in clean_text("see www.foo.org ok")

    def test_removes_mentions(self):
        # @mentions are usernames -> PII, dropped entirely
        assert clean_text("hey @SomeUser stop it") == "hey stop it"

    def test_hashtag_keeps_word_drops_symbol(self):
        assert clean_text("this #cyberbullying stuff") == "this cyberbullying stuff"

    def test_keeps_emoji(self):
        # emojis carry affect signal for cyberbullying detection
        assert "😡" in clean_text("you are dumb 😡")

    def test_collapses_whitespace_and_newlines(self):
        assert clean_text("  a \n\n  b\t c ") == "a b c"

    def test_normalises_unicode(self):
        # full-width characters are normalised by NFKC
        assert clean_text("ｈｅｌｌｏ") == "hello"

    def test_normalises_smart_quotes(self):
        assert clean_text("it’s a “quote”") == "it's a \"quote\""

    def test_collapses_exaggerated_repeats(self):
        assert clean_text("sooooo stupid") == "soo stupid"
        assert clean_text("!!!!!!") == "!!"

    def test_keeps_legit_double_letters(self):
        assert clean_text("class assignment") == "class assignment"

    def test_is_idempotent(self):
        once = clean_text("HEY @bob visit https://x.io/y !!! soooo dumb")
        assert clean_text(once) == once


class TestMakeId:
    def test_is_deterministic_and_prefixed(self):
        a = make_id("4chan", "12345")
        assert a == make_id("4chan", "12345")
        assert a.startswith("4chan-")

    def test_does_not_leak_native_id(self):
        assert "12345" not in make_id("4chan", "12345")

    def test_differs_across_sources(self):
        assert make_id("4chan", "1") != make_id("stackexchange", "1")


class TestClassify:
    def test_insult(self):
        assert classify("you are an idiot loser") == "insulte"

    def test_threat(self):
        assert classify("just kys already") == "menace"

    def test_hate(self):
        assert classify("all of you are worthless group") == "haine"

    def test_provocation(self):
        assert classify("cope harder, stay mad") == "provocation"

    def test_neutral_default(self):
        assert classify("how do i install pandas on linux") == "neutre"

    def test_threat_wins_over_insult(self):
        assert classify("stupid kid, kys") == "menace"

    def test_priority_hate_over_provocation(self):
        assert classify("cope, all of you are subhuman") == "haine"

    def test_empty_is_neutral(self):
        assert classify("") == "neutre"


class TestMatchedKeywords:
    def test_finds_keywords(self):
        assert set(matched_keywords("what an idiot, kys")) == {"idiot", "kys"}

    def test_empty_when_none(self):
        assert matched_keywords("nice weather today") == []

    def test_multiword_keyword(self):
        assert "kill yourself" in matched_keywords("why dont you kill yourself")

    def test_respects_word_boundary(self):
        # "idiot" must not match inside another word
        assert matched_keywords("idiotic behavior") == [kw for kw in ["idiot"] if False]

    def test_case_insensitive(self):
        assert "loser" in matched_keywords("LOSER")


class TestConfigPerimeter:
    def test_at_least_two_sources(self):
        assert len(config.SOURCES) >= 2

    def test_five_classes_defined(self):
        assert set(config.KEYWORDS_BY_CLASS) == {
            "insulte", "menace", "haine", "provocation", "neutre",
        }

    def test_every_class_has_keywords(self):
        for cls, kws in config.KEYWORDS_BY_CLASS.items():
            assert kws, f"no keyword for {cls}"
