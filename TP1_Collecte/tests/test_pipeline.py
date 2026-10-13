"""End-to-end tests of the collection pipeline with fake collectors (no network)."""

from __future__ import annotations

import csv
import json

from src import pipeline


def fake_record(id_, text, source="4chan", media="", url=None):
    return {
        "id": id_,
        "date": "2025-04-25",
        "text": text,
        "media": media,
        "url": url or f"https://example.org/{id_}",
        "source": source,
        "metadata": json.dumps({"board": "g"}),
    }


FAKE_RECORDS = [
    fake_record("4chan-1", "you are an idiot <br> @user"),
    fake_record("4chan-2", "you are an idiot <br> @user"),      # duplicate
    fake_record("4chan-3", "cope harder, seethe", media="https://i.4cdn.org/g/3.png"),
    fake_record("se-1", "how do i install pandas", source="stackexchange"),
    fake_record("se-2", "   ", source="stackexchange"),          # empty
]


class TestRunPipeline:
    def test_writes_raw_and_clean_csv(self, tmp_path):
        report = pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3], "stackexchange": lambda: FAKE_RECORDS[3:]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        assert (tmp_path / "raw.csv").exists()
        assert (tmp_path / "clean.csv").exists()
        assert report["nb_raw"] == 5
        assert report["nb_clean"] == 3

    def test_raw_csv_has_spec_columns(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        with open(tmp_path / "raw.csv", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        assert header == ["id", "date", "text", "media", "url", "source", "metadata"]

    def test_clean_csv_has_spec_columns(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        with open(tmp_path / "clean.csv", encoding="utf-8", newline="") as fh:
            header = next(csv.reader(fh))
        assert header == ["date", "clean_text", "media", "url", "source"]

    def test_clean_csv_holds_clean_text(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        text = (tmp_path / "clean.csv").read_text(encoding="utf-8")
        assert "@user" not in text
        assert "<br>" not in text

    def test_images_are_relative_paths_in_clean_csv(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[2:3]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        assert "images/4chan-3.png" in (tmp_path / "clean.csv").read_text(encoding="utf-8")

    def test_report_contains_stats_and_sources(self, tmp_path):
        report = pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3], "stackexchange": lambda: FAKE_RECORDS[3:]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        assert report["stats"]["nb_messages"] == 3
        assert set(report["stats"]["nb_by_source"]) == {"4chan", "stackexchange"}

    def test_writes_mini_report(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:3]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            report_md=tmp_path / "REPORT.md",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        content = (tmp_path / "REPORT.md").read_text(encoding="utf-8")
        assert "cyberbullying" in content.lower()
        assert len(content.splitlines()) <= 40

    def test_one_failing_collector_does_not_kill_the_run(self, tmp_path):
        def boom():
            raise RuntimeError("api down")

        report = pipeline.run_pipeline(
            collectors={"4chan": boom, "stackexchange": lambda: FAKE_RECORDS[3:]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        assert report["nb_raw"] >= 1
        assert "4chan" in report["errors"]

    def test_metadata_json_survives_raw_csv(self, tmp_path):
        pipeline.run_pipeline(
            collectors={"4chan": lambda: FAKE_RECORDS[:1]},
            raw_csv=tmp_path / "raw.csv",
            clean_csv=tmp_path / "clean.csv",
            images_dir=tmp_path / "images",
            fetch=lambda url: b"\x89PNG\r\n\x1a\n" + b"0" * 32,
        )
        body = (tmp_path / "raw.csv").read_text(encoding="utf-8").splitlines()[1]
        assert json.loads(next(csv.reader([body]))[6])["board"] == "g"
