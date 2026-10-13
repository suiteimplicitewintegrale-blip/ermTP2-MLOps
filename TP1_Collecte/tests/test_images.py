"""Tests for image downloading (network replaced by an injected fetcher)."""

from __future__ import annotations

import pandas as pd
import pytest

from src import images


def rec(id_, media):
    return {
        "id": id_,
        "date": "2025-04-25",
        "text": "look at this loser",
        "media": media,
        "url": "https://boards.4chan.org/g/thread/1#p1",
        "source": "4chan",
        "metadata": "{}",
    }


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
JPG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 64


class TestImageExtension:
    def test_keeps_known_extension(self):
        assert images.image_extension("https://i.4cdn.org/g/123.png") == ".png"
        assert images.image_extension("https://i.4cdn.org/g/123.JPG") == ".jpg"

    def test_defaults_to_jpg_when_unknown(self):
        assert images.image_extension("https://x.com/noext") == ".jpg"

    def test_ignores_query_string(self):
        assert images.image_extension("https://x.com/a.webp?foo=1") == ".webp"


class TestDownloadImages:
    @pytest.fixture
    def frame(self):
        return pd.DataFrame(
            [
                rec("4chan-1", "https://i.4cdn.org/g/111.png"),
                rec("4chan-2", "https://i.4cdn.org/g/222.jpg"),
                rec("se-1", ""),
                rec("4chan-3", ""),
            ]
        )

    def test_downloads_only_rows_with_media(self, tmp_path, frame):
        out, report = images.download_images(frame, tmp_path, fetch=lambda url: PNG_BYTES)
        assert report["downloaded"] == 2
        assert report["failed"] == 0

    def test_media_column_becomes_relative_path(self, tmp_path, frame):
        out, _ = images.download_images(frame, tmp_path, fetch=lambda url: PNG_BYTES)
        path = out.loc[out["id"] == "4chan-1", "media"].iloc[0]
        assert path == "images/4chan-1.png"

    def test_files_exist_on_disk(self, tmp_path, frame):
        images.download_images(frame, tmp_path, fetch=lambda url: PNG_BYTES)
        assert (tmp_path / "4chan-1.png").exists()
        assert (tmp_path / "4chan-2.jpg").exists()

    def test_respects_max_images(self, tmp_path, frame):
        out, report = images.download_images(frame, tmp_path, max_images=1, fetch=lambda url: PNG_BYTES)
        assert report["downloaded"] == 1
        assert (out["media"] != "").sum() == 1

    def test_leaves_undownloaded_media_untouched(self, tmp_path, frame):
        out, _ = images.download_images(frame, tmp_path, max_images=1, fetch=lambda url: PNG_BYTES)
        # row 2 keeps its remote url, it was not downloaded
        assert out.loc[out["id"] == "4chan-2", "media"].iloc[0] == "https://i.4cdn.org/g/222.jpg"

    def test_records_failures_without_crashing(self, tmp_path, frame):
        def boom(url):
            raise OSError("network down")

        out, report = images.download_images(frame, tmp_path, fetch=boom)
        assert report["failed"] == 2
        assert report["downloaded"] == 0
        assert (out["media"] == "").sum() == 2

    def test_rejects_oversized_payload(self, tmp_path, frame):
        big = b"0" * (images.MAX_IMAGE_BYTES + 1)
        _, report = images.download_images(frame, tmp_path, fetch=lambda url: big)
        assert report["downloaded"] == 0
        assert report["skipped_too_big"] == 2

    def test_does_not_keep_html_error_pages(self, tmp_path, frame):
        _, report = images.download_images(frame, tmp_path, fetch=lambda url: b"<html>404</html>")
        assert report["downloaded"] == 0
        assert report["failed"] == 2

    def test_polite_delay_only_between_requests(self, tmp_path, frame):
        sleeps = []
        images.download_images(
            frame, tmp_path, fetch=lambda url: PNG_BYTES, sleep=sleeps.append
        )
        assert len(sleeps) == 1  # 2 downloads -> 1 pause between them

    def test_returns_new_frame(self, tmp_path, frame):
        out, _ = images.download_images(frame, tmp_path, fetch=lambda url: PNG_BYTES)
        assert out is not frame
        assert len(out) == len(frame)

    def test_idempotent_when_files_already_there(self, tmp_path, frame):
        images.download_images(frame, tmp_path, fetch=lambda url: PNG_BYTES)
        calls = []

        def counting(url):
            calls.append(url)
            return PNG_BYTES

        _, report = images.download_images(frame, tmp_path, fetch=counting)
        assert report["downloaded"] == 2
