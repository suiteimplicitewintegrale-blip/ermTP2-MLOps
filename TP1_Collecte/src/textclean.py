"""Text cleaning, HTML extraction, anonymised ids and weak class labelling."""

from __future__ import annotations

import hashlib
import re
import unicodedata

from bs4 import BeautifulSoup

from . import config

# --------------------------------------------------------------------------- #
# HTML -> plain text
# --------------------------------------------------------------------------- #
_BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "blockquote", "pre", "section", "article",
    "tr", "td", "h1", "h2", "h3", "h4", "h5", "h6", "table", "figure",
]
_LOOKS_LIKE_HTML = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")


def html_to_text(html: str | None) -> str:
    """Convert a fragment of HTML (4chan/Stack Exchange body) to plain text.

    ``<br>`` and closing block tags become line breaks, entities are unescaped,
    inline markup (``<b>``, ``<code>``, links) keeps its visible text and the
    ``href`` targets are dropped.
    """
    if not html:
        return ""
    marked = re.sub(r"(?i)<br\s*/?>", "\n", str(html))
    soup = BeautifulSoup(marked, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")
    text = soup.get_text().replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line)


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
_PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", "«": '"', "»": '"',
}
_URL_RE = re.compile(r"(?i)\bhttps?://\S+|\bwww\.\S+")
_MENTION_RE = re.compile(r"@[\w.\-]+")
_HASHTAG_RE = re.compile(r"#(\w+)")
_REPEAT_RE = re.compile(r"(.)\1{2,}", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(raw: str | None) -> str:
    """Normalise one message for the cleaned corpus.

    Removes URLs, ``@`` mentions (usernames are PII) and ``#`` symbols, lowers
    the case, normalises unicode and collapses exaggerated character repeats and
    whitespace. Emojis are kept on purpose: they carry affect signal that is
    useful for cyberbullying detection.
    """
    if raw is None:
        return ""
    text = str(raw)
    if _LOOKS_LIKE_HTML.search(text):
        text = html_to_text(text)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans(_PUNCT_MAP))
    text = _URL_RE.sub(" ", text)
    text = _MENTION_RE.sub(" ", text)
    text = _HASHTAG_RE.sub(r"\1", text)
    text = _REPEAT_RE.sub(r"\1\1", text)
    text = text.lower()
    return _WHITESPACE_RE.sub(" ", text).strip()


# --------------------------------------------------------------------------- #
# Anonymised identifiers
# --------------------------------------------------------------------------- #
def make_id(source: str, native_id: str) -> str:
    """Build a stable, anonymised identifier: ``<source>-<sha1[:12]>``.

    The native id is never stored, so no message can be traced back to an
    account through the dataset itself.
    """
    digest = hashlib.sha1(f"{source}:{native_id}".encode("utf-8")).hexdigest()[:12]
    prefix = re.sub(r"[^a-z0-9]+", "", source.lower())
    return f"{prefix}-{digest}"


# --------------------------------------------------------------------------- #
# Weak labelling and relevance
# --------------------------------------------------------------------------- #
_CLASS_PRIORITY = ["menace", "haine", "insulte", "provocation", "neutre"]
_KEYWORD_RE = {
    kw: re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)
    for kw in config.KEYWORDS
}


def matched_keywords(text: str | None) -> list[str]:
    """Return the collection keywords present in ``text`` (whole words only)."""
    if not text:
        return []
    return [kw for kw, rx in _KEYWORD_RE.items() if rx.search(text)]


def is_relevant(text: str | None) -> bool:
    """A message enters the corpus when it matches at least one keyword."""
    return bool(matched_keywords(text))


def classify(text: str | None) -> str:
    """Assign the most serious class matched by the message.

    Priority: threat > hate > insult > provocation > neutral. The labelling is a
    keyword heuristic used for corpus description, not a trained classifier.
    """
    lowered = (text or "").lower()
    for cls in _CLASS_PRIORITY:
        if any(
            re.search(rf"\b{re.escape(kw)}\b", lowered)
            for kw in config.KEYWORDS_BY_CLASS[cls]
        ):
            return cls
    return "neutre"
