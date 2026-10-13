"""Tests for the raw/clean dataset construction, dedup, cleaning and statistics."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src import dataset

REC_TEMPLATE = {
    "id": "4chan-aaa",
    "date": "2025-04-25",
    "text": "you are an idiot",
    "media": "",
    "url": "https://boards.4chan.org/g/thread/1#p1",
    "source": "4chan",
    "metadata": json.dumps({"board": "g"}),
}


def rec(**kw):
    out = dict(REC_TEMPLATE)
    out.update(kw)
    return out


@pytest.fixture
def raw_records():
    return [
        rec(id="4chan-1", text="You are an IDIOT  !!!", source="4chan"),
        rec(id="4chan-2", text="you are an idiot", source="4chan"),          # dupe after cleaning
        rec(id="se-1", text="  ", source="stackexchange"),                    # empty -> dropped
        rec(id="se-2", text="how do i install pandas", source="stackexchange"),
        rec(
            id="4chan-3",
            text="look at this https://t.co/abc 😡 loser",
            source="4chan",
            media="https://i.4cdn.org/g/1.png",
        ),
    ]


class TestRecordsToFrame:
    def test_has_spec_columns_in_order(self):
        df = dataset.records_to_frame([rec()])
        assert list(df.columns) == ["id", "date", "text", "media", "url", "source", "metadata"]

    def test_empty_input_gives_empty_frame(self):
        df = dataset.records_to_frame([])
        assert df.empty
        assert list(df.columns) == ["id", "date", "text", "media", "url", "source", "metadata"]

    def test_fills_missing_optional_fields(self):
        partial = {"id": "x", "date": "2025-01-01", "text": "hi", "source": "4chan"}
        df = dataset.records_to_frame([partial])
        assert df.loc[0, "media"] == ""
        assert df.loc[0, "url"] == ""
        assert df.loc[0, "metadata"] == "{}"


class TestDedupe:
    def test_removes_case_and_space_duplicates(self, raw_records):
        df = dataset.dedupe(dataset.records_to_frame(raw_records))
        assert df["text"].str.lower().str.split().str.join(" ").duplicated().sum() == 0

    def test_keeps_first_occurrence(self, raw_records):
        df = dataset.dedupe(dataset.records_to_frame(raw_records))
        assert "4chan-1" in set(df["id"]) and "4chan-2" not in set(df["id"])

    def test_removes_duplicate_urls(self):
        df = dataset.dedupe(
            dataset.records_to_frame(
                [rec(id="a", text="hello there"), rec(id="b", text="different text but same url")]
            )
        )
        assert len(df) == 1

    def test_dedupes_within_but_not_across_sources(self):
        df = dataset.dedupe(
            dataset.records_to_frame(
                [
                    rec(id="a", text="same text here", source="4chan", url="u1"),
                    rec(id="b", text="same text here", source="stackexchange", url="u2"),
                ]
            )
        )
        assert len(df) == 1  # same text == same message, keep one

    def test_drops_empty_and_whitespace_rows(self, raw_records):
        df = dataset.dedupe(dataset.records_to_frame(raw_records))
        assert not df["text"].str.strip().eq("").any()

    def test_drops_too_short_rows(self):
        df = dataset.dedupe(dataset.records_to_frame([rec(id="a", text="ok"), rec(id="b", text="real sentence here")]))
        assert len(df) == 1


class TestCleanFrame:
    def test_returns_spec_columns_only(self, raw_records):
        df = dataset.clean_frame(dataset.dedupe(dataset.records_to_frame(raw_records)))
        assert list(df.columns) == ["date", "clean_text", "media", "url", "source"]

    def test_labels_column_is_not_leaked(self, raw_records):
        df = dataset.clean_frame(dataset.dedupe(dataset.records_to_frame(raw_records)))
        assert "label" not in df.columns

    def test_text_is_cleaned(self, raw_records):
        df = dataset.clean_frame(dataset.dedupe(dataset.records_to_frame(raw_records)))
        assert df["clean_text"].str.contains("https").sum() == 0
        assert not df["clean_text"].str.contains("  ").any()

    def test_preserves_row_count_and_order(self, raw_records):
        deduped = dataset.dedupe(dataset.records_to_frame(raw_records))
        assert len(dataset.clean_frame(deduped)) == len(deduped)


class TestStats:
    def test_reports_required_metrics(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        clean = dataset.clean_frame(raw)
        stats = dataset.compute_stats(raw, clean)
        assert set(stats) >= {
            "nb_messages", "nb_by_source", "pct_with_image",
            "mean_length", "median_length", "pct_by_class", "lexical_diversity",
        }

    def test_counts_are_consistent(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        clean = dataset.clean_frame(raw)
        stats = dataset.compute_stats(raw, clean)
        assert stats["nb_messages"] == len(clean)
        assert sum(stats["nb_by_source"].values()) == len(clean)

    def test_pct_with_image(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        clean = dataset.clean_frame(raw)
        stats = dataset.compute_stats(raw, clean)
        assert 0.0 <= stats["pct_with_image"] <= 100.0

    def test_lexical_diversity_between_0_and_1(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        clean = dataset.clean_frame(raw)
        stats = dataset.compute_stats(raw, clean)
        assert 0.0 < stats["lexical_diversity"] <= 1.0

    def test_empty_frame_does_not_crash(self):
        empty = dataset.records_to_frame([])
        stats = dataset.compute_stats(empty, dataset.clean_frame(empty))
        assert stats["nb_messages"] == 0


class TestCsvIo:
    def test_write_and_read_roundtrip(self, tmp_path, raw_records):
        df = dataset.records_to_frame(raw_records)
        path = tmp_path / "out.csv"
        dataset.write_csv(df, path)
        back = pd.read_csv(path)
        assert list(back.columns) == list(df.columns)
        assert len(back) == len(df)

    def test_write_csv_creates_parent_dirs(self, tmp_path, raw_records):
        path = tmp_path / "nested" / "dir" / "out.csv"
        dataset.write_csv(dataset.records_to_frame(raw_records), path)
        assert path.exists()

    def test_csv_is_utf8(self, tmp_path):
        df = dataset.records_to_frame([rec(text="emoji 😡 test")])
        path = tmp_path / "u.csv"
        dataset.write_csv(df, path)
        assert "😡" in path.read_text(encoding="utf-8")


class TestExamples:
    def test_picks_varied_examples(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        examples = dataset.sample_examples(raw, n=3)
        assert len(examples) <= 3
        assert len({e["source"] for e in examples}) >= 1

    def test_returns_dataframe_with_label_and_keywords(self, raw_records):
        raw = dataset.dedupe(dataset.records_to_frame(raw_records))
        out = dataset.sample_examples(raw, n=2, as_frame=True)
        assert {"text", "source", "label", "keywords"} <= set(out.columns)

    def test_fewer_rows_than_requested(self):
        raw = dataset.records_to_frame([rec()])
        assert len(dataset.sample_examples(raw, n=10, as_frame=True)) == 1
