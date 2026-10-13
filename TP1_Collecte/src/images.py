"""Download the images referenced by the corpus into ``data/images/``."""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import requests

from . import config

KNOWN_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
MAX_IMAGE_BYTES = config.MAX_IMAGE_BYTES
MAGIC_PREFIXES = (
    b"\x89PNG",          # png
    b"\xff\xd8\xff",     # jpeg
    b"GIF87a",           # gif
    b"GIF89a",
    b"BM",               # bmp
)


def image_extension(url: str) -> str:
    """Extension to use for a downloaded image (``.jpg`` when unknown)."""
    path = str(url).split("?")[0].split("#")[0]
    suffix = Path(path).suffix.lower()
    if suffix == ".jpeg":
        return ".jpg"
    return suffix if suffix in KNOWN_EXTENSIONS else ".jpg"


class ImageTooLargeError(Exception):
    """Raised when a download exceeds :data:`MAX_IMAGE_BYTES`."""


def _looks_like_image(payload: bytes) -> bool:
    if payload.startswith(MAGIC_PREFIXES):
        return True
    return payload[:4] == b"RIFF" and payload[8:12] == b"WEBP"


def http_fetch(url: str, timeout: int = config.IMAGE_TIMEOUT_S) -> bytes:
    """Default fetcher: streaming GET that aborts oversized payloads.

    The body is read in chunks and dropped as soon as it passes
    :data:`MAX_IMAGE_BYTES`, so a hostile or broken URL cannot fill the memory.
    """
    with requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": config.USER_AGENT},
        stream=True,
    ) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ImageTooLargeError(f"{url} exceeds {MAX_IMAGE_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)


def download_images(
    frame: pd.DataFrame,
    out_dir: str | Path,
    max_images: int = config.MAX_IMAGES,
    fetch=http_fetch,
    sleep=time.sleep,
    url_prefix: str = "images",
) -> tuple[pd.DataFrame, dict]:
    """Download up to ``max_images`` images and rewrite ``media`` to local paths.

    Returns the updated frame and a small report. Rows whose image could not be
    downloaded keep an empty ``media`` so the corpus never lies about what it
    actually holds. ``fetch`` is injected so tests run without network.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = frame.copy()
    report = {
        "downloaded": 0,
        "failed": 0,
        "skipped_too_big": 0,
        "already_present": 0,
        "bytes": 0,
    }
    if out.empty:
        return out, report

    media = out["media"].fillna("").astype(str)
    targets = [idx for idx in out.index if media.loc[idx].strip()]

    for position, idx in enumerate(targets):
        if report["downloaded"] >= max_images:
            break
        if position > 0:
            # politeness delay before every request, including after a failure
            sleep(config.REQUEST_PAUSE_S)
        url = media.loc[idx].strip()
        name = f"{out.loc[idx, 'id']}{image_extension(url)}"
        dest = out_dir / name
        relative = f"{url_prefix}/{name}"
        try:
            if dest.exists() and dest.stat().st_size > 0:
                report["already_present"] += 1
                report["downloaded"] += 1
                out.loc[idx, "media"] = relative
                continue
            payload = fetch(url)
            if len(payload) > MAX_IMAGE_BYTES:
                report["skipped_too_big"] += 1
                out.loc[idx, "media"] = ""
                continue
            if not _looks_like_image(payload):
                report["failed"] += 1
                out.loc[idx, "media"] = ""
                continue
            dest.write_bytes(payload)
            report["downloaded"] += 1
            report["bytes"] += len(payload)
            out.loc[idx, "media"] = relative
        except ImageTooLargeError:
            report["skipped_too_big"] += 1
            out.loc[idx, "media"] = ""
            continue
        except Exception:  # network, disk, HTTP error: keep the corpus usable
            report["failed"] += 1
            out.loc[idx, "media"] = ""
            continue

    report["bytes"] = int(report["bytes"])
    return out, report
