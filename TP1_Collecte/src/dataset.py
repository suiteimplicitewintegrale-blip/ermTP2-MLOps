"""Build, clean, describe and persist the corpus (pandas in, pandas out)."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from . import config
from .textclean import classify, clean_text, matched_keywords

RAW_COLUMNS = ["id", "date", "text", "media", "url", "source", "metadata"]
CLEAN_COLUMNS = ["date", "clean_text", "media", "url", "source"]
MIN_TEXT_LENGTH = config.MIN_TEXT_CHARS
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


def records_to_frame(records: list[dict]) -> pd.DataFrame:
    """Turn source records into the raw table (spec column order preserved)."""
    rows = []
    for record in records:
        rows.append({
            "id": record.get("id", ""),
            "date": record.get("date", ""),
            "text": record.get("text", ""),
            "media": record.get("media", "") or "",
            "url": record.get("url", "") or "",
            "source": record.get("source", ""),
            "metadata": record.get("metadata", "") or "{}",
        })
    return pd.DataFrame(rows, columns=RAW_COLUMNS)


def _normalise_key(text: str) -> str:
    """Comparison key used to detect duplicate messages.

    Built on the cleaned text with punctuation removed, so a repost that only
    differs in case, spacing or trailing punctuation is recognised as the same
    message.
    """
    cleaned = clean_text(text)
    key = " ".join(_NON_WORD_RE.sub(" ", cleaned).split())
    return key or cleaned


def dedupe(frame: pd.DataFrame, min_length: int = MIN_TEXT_LENGTH) -> pd.DataFrame:
    """Drop empty, too short and duplicated messages.

    Duplicates are detected on the normalised text and on the source URL, so a
    repost of the same message is kept once even if it has a new identifier.
    Messages without a permalink are kept: the source link is desirable but its
    absence must never make a whole source disappear from the corpus.
    """
    if frame.empty:
        return frame.copy()

    out = frame.copy()
    out["text"] = out["text"].fillna("").astype(str)
    out = out[out["text"].str.strip().str.len() >= min_length]

    key = out["text"].map(_normalise_key)
    out = out.assign(_text_key=key)
    out = out.drop_duplicates(subset=["_text_key"], keep="first")

    urls = out["url"].fillna("").astype(str).str.strip()
    out = out[~(urls.ne("") & urls.duplicated())]
    return out.drop(columns=["_text_key"]).reset_index(drop=True)


def clean_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Produce the cleaned corpus with exactly the columns asked for by the spec."""
    if frame.empty:
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    cleaned = frame.copy()
    cleaned["clean_text"] = cleaned["text"].map(clean_text)
    return cleaned[CLEAN_COLUMNS].reset_index(drop=True)


def compute_stats(raw: pd.DataFrame, clean: pd.DataFrame) -> dict:
    """Descriptive statistics required by the verification step."""
    nb_messages = int(len(clean))
    if nb_messages == 0:
        return {
            "nb_messages": 0,
            "nb_by_source": {},
            "pct_with_image": 0.0,
            "mean_length": 0.0,
            "median_length": 0.0,
            "pct_by_class": {},
            "lexical_diversity": 0.0,
        }

    lengths = clean["clean_text"].str.len()
    tokens = [
        token
        for text in clean["clean_text"].fillna("")
        for token in str(text).split()
    ]
    with_image = clean["media"].fillna("").astype(str).str.strip().ne("").sum()
    classes = Counter(classify(text) for text in raw["text"].fillna(""))

    return {
        "nb_messages": nb_messages,
        "nb_by_source": {k: int(v) for k, v in clean["source"].value_counts().items()},
        "pct_with_image": round(100.0 * with_image / nb_messages, 2),
        "mean_length": round(float(lengths.mean()), 1),
        "median_length": float(lengths.median()),
        "pct_by_class": {
            k: round(100.0 * v / len(raw), 1) for k, v in classes.most_common()
        },
        "lexical_diversity": round(len(set(tokens)) / len(tokens), 3) if tokens else 0.0,
    }


def sample_examples(raw: pd.DataFrame, n: int = 10, as_frame: bool = False):
    """Pick ``n`` varied examples, one per (class, source) pair when possible."""
    if raw.empty:
        return pd.DataFrame(columns=["text", "source", "label", "keywords"]) if as_frame else []

    working = raw.copy()
    working["label"] = working["text"].map(classify)
    working["keywords"] = working["text"].map(lambda t: ", ".join(matched_keywords(t)))
    working["_length"] = working["text"].map(lambda t: len(str(t)))

    ordered = (
        working.sort_values("_length", ascending=False)
        .drop_duplicates(subset=["label", "source"], keep="first")
        .head(n)
    )
    if len(ordered) < n:
        extra = working[~working["id"].isin(ordered["id"])].head(n - len(ordered))
        ordered = pd.concat([ordered, extra])

    result = ordered[["text", "source", "label", "keywords"]].head(n).reset_index(drop=True)
    return result if as_frame else result.to_dict("records")


def write_csv(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write a dataframe as UTF-8 CSV, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8")
    return path


def read_csv(path: str | Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False)
