"""Configuration for the cyberbullying multimodal data collection (MLOps TP1).

Everything that defines the collection perimeter lives here so that a run is
reproducible and every parameter can be logged to MLflow:
sources, search keywords, target classes, paths and network settings.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths (relative to the TP1_Collecte/ root)
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
RAW_CSV = DATA_DIR / "cyberbullying_raw.csv"
CLEAN_CSV = DATA_DIR / "cyberbullying_raw_clean.csv"
REPORT_MD = ROOT / "REPORT.md"
README_MD = ROOT / "README.md"

# --------------------------------------------------------------------------- #
# Collection perimeter (TP Part 1)
# --------------------------------------------------------------------------- #
THEME = "cyberbullying"
SOURCES = ["4chan", "stackexchange"]

# Keywords are grouped by the class we want to be able to detect later.
# They are the only search terms used by the collectors.
KEYWORDS_BY_CLASS: dict[str, list[str]] = {
    "insulte": [
        "idiot", "stupid", "moron", "loser", "ugly", "dumb", "brainlet",
        "worthless", "pathetic", "trash", "garbage", "useless",
    ],
    "menace": [
        "kill yourself", "kys", "you should die", "i will kill you",
        "death threat", "you deserve to die",
    ],
    "haine": [
        "you people are", "all of you are", "subhuman", "go back to your country",
        "worthless group", "inferior race",
    ],
    "provocation": [
        "cope", "seethe", "cry about it", "stay mad", "lmao get rekt", "ratio",
        "skill issue", "git gud",
    ],
    "neutre": ["thanks", "anyone know", "how do i", "help please"],
}

KEYWORDS: list[str] = [kw for kws in KEYWORDS_BY_CLASS.values() for kw in kws]

# --------------------------------------------------------------------------- #
# 4chan archive (public, read-only JSON API, robots.txt respected)
# --------------------------------------------------------------------------- #
FOURCHAN_BOARDS = ["g", "v"]
FOURCHAN_THREADS_PER_BOARD = 6
FOURCHAN_MAX_POSTS_PER_THREAD = 40

# --------------------------------------------------------------------------- #
# Stack Exchange (public API, no key; 300 requests/day quota)
# --------------------------------------------------------------------------- #
STACKEXCHANGE_SITES = ["stackoverflow", "gaming"]
STACKEXCHANGE_PAGESIZE = 100

# --------------------------------------------------------------------------- #
# Images
# --------------------------------------------------------------------------- #
MAX_IMAGES = 20
MAX_IMAGE_BYTES = 2_000_000
IMAGE_TIMEOUT_S = 30

# --------------------------------------------------------------------------- #
# Network
# --------------------------------------------------------------------------- #
USER_AGENT = "mlops-tp1-cyberbullying/1.0 (academic data collection, contact: student@fs.tn)"
REQUEST_TIMEOUT_S = 30
REQUEST_PAUSE_S = 1.0  # politeness delay between requests to the same host

# --------------------------------------------------------------------------- #
# MLflow
# --------------------------------------------------------------------------- #
MLFLOW_EXPERIMENT = "cyberbullying_Data_Collection"
MLFLOW_TRACKING_URI = (ROOT / "mlruns").as_uri()
