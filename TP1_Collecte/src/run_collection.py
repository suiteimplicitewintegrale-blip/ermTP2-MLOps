"""Command line entry point of the collection pipeline.

Usage (from ``TP1_Collecte/``)::

    python -m src.run_collection                 # real collection + MLflow run
    python -m src.run_collection --no-mlflow     # collection only
    python -m src.run_collection --max-images 5  # smaller image budget

Collected content comes from public APIs only (4chan archive, Stack Exchange).
No personal data is stored: author names are dropped and identifiers hashed.
"""

from __future__ import annotations

import argparse
import sys

from . import config, pipeline, tracking
from .sources.fourchan import FourChanCollector
from .sources.stackexchange import StackExchangeCollector


def build_collectors(boards: list[str], sites: list[str]) -> dict:
    """Real collectors, one per source (network calls happen when called)."""
    chan = FourChanCollector()
    stack = StackExchangeCollector()
    return {
        "4chan": lambda: chan.collect(boards),
        "stackexchange": lambda: stack.collect(sites, config.STACKEXCHANGE_QUERIES),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cyberbullying multimodal data collection")
    parser.add_argument("--boards", nargs="*", default=config.FOURCHAN_BOARDS,
                        help="4chan boards to scrape (default: g v)")
    parser.add_argument("--sites", nargs="*", default=config.STACKEXCHANGE_SITES,
                        help="Stack Exchange sites to query")
    parser.add_argument("--max-images", type=int, default=config.MAX_IMAGES)
    parser.add_argument("--no-mlflow", action="store_true",
                        help="skip the MLflow tracking run")
    parser.add_argument("--no-report", action="store_true",
                        help="skip the mini-report file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    collectors = build_collectors(args.boards, args.sites)

    report = pipeline.run_pipeline(
        collectors=collectors,
        raw_csv=config.RAW_CSV,
        clean_csv=config.CLEAN_CSV,
        images_dir=config.IMAGES_DIR,
        report_md=None if args.no_report else config.REPORT_MD,
        max_images=args.max_images,
    )

    print(pipeline.summarise(report))
    print()
    print(pipeline.describe_examples(report["examples"]))

    if not args.no_mlflow:
        run_id = tracking.log_run(report)
        print(f"\n[mlflow] run id: {run_id}")

    if report["nb_clean"] == 0:
        print("\nERROR: empty corpus - check network access and the source APIs", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
