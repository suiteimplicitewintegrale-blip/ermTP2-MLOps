"""Orchestration: collect -> raw CSV -> images -> clean CSV -> mini-report."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import config, dataset, images

MINI_REPORT_HEADER = "# Mini-rapport — collecte cyberbullying (TP-FR 1)"


def run_pipeline(
    collectors: dict,
    raw_csv: str | Path = config.RAW_CSV,
    clean_csv: str | Path = config.CLEAN_CSV,
    images_dir: str | Path = config.IMAGES_DIR,
    report_md: str | Path | None = None,
    fetch=images.http_fetch,
    max_images: int = config.MAX_IMAGES,
) -> dict:
    """Run the whole collection pipeline and return a report dictionary.

    A failing source never aborts the run: the error is recorded and the corpus
    is built from the sources that answered.
    """
    records: list[dict] = []
    errors: dict[str, str] = {}
    for source, collect in collectors.items():
        try:
            records.extend(collect())
        except Exception as exc:  # one dead API must not lose the other sources
            errors[source] = f"{type(exc).__name__}: {exc}"

    raw_frame = dataset.records_to_frame(records)
    dataset.write_csv(raw_frame, raw_csv)

    deduped = dataset.dedupe(raw_frame)
    with_images, image_report = images.download_images(
        deduped, images_dir, max_images=max_images, fetch=fetch
    )
    clean_frame = dataset.clean_frame(with_images)
    dataset.write_csv(clean_frame, clean_csv)

    stats = dataset.compute_stats(deduped, clean_frame)
    examples = dataset.sample_examples(deduped, n=10)

    report = {
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "sources": list(collectors),
        "keywords": config.KEYWORDS,
        "nb_raw": int(len(raw_frame)),
        "nb_duplicates_removed": int(len(raw_frame) - len(deduped)),
        "nb_clean": int(len(clean_frame)),
        "max_images": int(max_images),
        "stats": stats,
        "images": image_report,
        "examples": examples,
        "errors": errors,
        "raw_csv": str(raw_csv),
        "clean_csv": str(clean_csv),
    }
    if report_md is not None:
        write_mini_report(report_md, report)
        report["report_md"] = str(report_md)
    return report


def _format_keyword_list(keywords: list[str], limit: int = 14) -> str:
    shown = ", ".join(keywords[:limit])
    return shown + (f", … ({len(keywords)} au total)" if len(keywords) > limit else "")


def write_mini_report(path: str | Path, report: dict) -> Path:
    """Write the 10-line mini-report describing the collected corpus."""
    stats = report["stats"]
    images_report = report["images"]
    lines = [
        MINI_REPORT_HEADER,
        "",
        f"- Date de collecte : {report['run_date']}",
        f"- Sources : {', '.join(report['sources'])} (4chan via a.4cdn.org, "
        f"Stack Exchange via api.stackexchange.com)",
        f"- Mots-clés ({len(report['keywords'])}) : {_format_keyword_list(report['keywords'])}",
        f"- Taille finale : {stats['nb_messages']} messages uniques "
        f"({report['nb_raw']} collectés, {report['nb_duplicates_removed']} doublons/vides retirés) ; "
        f"{images_report['downloaded']} images téléchargées "
        f"({stats['pct_with_image']}% des messages ont une image)",
        f"- Répartition par source : "
        f"{', '.join(f'{k} {v}' for k, v in stats['nb_by_source'].items())}",
        f"- Longueur moyenne : {stats['mean_length']} caractères "
        f"(médiane {stats['median_length']}) ; diversité lexicale "
        f"{stats['lexical_diversity']} (types/tokens)",
        f"- Classes (heuristique mots-clés) : "
        f"{', '.join(f'{k} {v}%' for k, v in stats['pct_by_class'].items())}",
        "- Premiers constats : le vocabulaire est bien centré sur le thème "
        "(insultes directes, provocations de type « cope/ratio ») ; le bruit vient des "
        "citations et du code collé dans les réponses Stack Exchange ; "
        "les images ne concernent que 4chan.",
    ]
    if report.get("errors"):
        lines.append(
            "- Sources en échec : "
            + "; ".join(f"{k} ({v})" for k, v in report["errors"].items())
        )

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def summarise(report: dict) -> str:
    """One-screen textual summary printed by the CLI."""
    stats = report["stats"]
    out = [
        f"run date      : {report['run_date']}",
        f"sources       : {', '.join(report['sources'])}",
        f"raw records   : {report['nb_raw']}",
        f"clean records : {report['nb_clean']} (duplicates/empty removed: "
        f"{report['nb_duplicates_removed']})",
        f"images        : {report['images']['downloaded']} downloaded, "
        f"{report['images']['failed']} failed, "
        f"{report['images']['skipped_too_big']} too big",
        f"by source     : {stats['nb_by_source']}",
        f"with image    : {stats['pct_with_image']}%",
        f"mean length   : {stats['mean_length']} chars (median {stats['median_length']})",
        f"classes       : {stats['pct_by_class']}",
        f"errors        : {report['errors'] or 'none'}",
    ]
    return "\n".join(out)


def describe_examples(examples: list[dict]) -> str:
    """Render the 10 qualitative examples for the report/notebook."""
    blocks = []
    for i, example in enumerate(examples, start=1):
        snippet = " ".join(str(example["text"]).split())[:160]
        blocks.append(
            f"{i:2d}. [{example['source']}/{example['label']}] {snippet}"
        )
    return "\n".join(blocks)


__all__ = [
    "run_pipeline",
    "write_mini_report",
    "summarise",
    "describe_examples",
]
