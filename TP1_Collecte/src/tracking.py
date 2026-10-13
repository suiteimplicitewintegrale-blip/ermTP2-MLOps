"""MLOps traceability: every collection run is logged in MLflow.

The experiment stores the collection parameters (sources, keywords, date, number
of extracted items), the metrics of the resulting corpus and the artefacts
(``cyberbullying_raw.csv``, ``cyberbullying_raw_clean.csv``, mini-report, README)
so the whole dataset version can be replayed or audited.
"""

from __future__ import annotations

from pathlib import Path

from . import config


def log_run(report: dict, tracking_uri: str | None = None,
            experiment: str | None = None, extra_artifacts: list[str] | None = None) -> str | None:
    """Log one collection run. Returns the MLflow run id (``None`` if unavailable)."""
    try:
        import mlflow
    except ImportError:  # MLflow is optional: the pipeline stays runnable
        print("[tracking] mlflow not installed - run not logged")
        return None

    mlflow.set_tracking_uri(tracking_uri or config.MLFLOW_TRACKING_URI)
    mlflow.set_experiment(experiment or config.MLFLOW_EXPERIMENT)

    stats = report["stats"]
    artifacts = [
        report.get("raw_csv"),
        report.get("clean_csv"),
        report.get("report_md"),
        str(config.README_MD),
    ]
    artifacts.extend(extra_artifacts or [])

    with mlflow.start_run(run_name=f"collect_{report['run_date'][:10]}") as run:
        mlflow.set_tags({
            "theme": config.THEME,
            "project": "MLOps TP-FR 1",
            "stage": "data_collection",
        })
        mlflow.log_params({
            "sources": ", ".join(report["sources"]),
            "nb_keywords": len(report["keywords"]),
            "keywords": ", ".join(report["keywords"][:20]),
            "collection_date": report["run_date"],
            "boards_4chan": ", ".join(config.FOURCHAN_BOARDS),
            "sites_stackexchange": ", ".join(config.STACKEXCHANGE_SITES),
            "max_images": report.get("max_images", config.MAX_IMAGES),
            "keywords_4chan": str(config.FOURCHAN_THREADS_PER_BOARD) + " threads/board",
        })
        mlflow.log_metrics({
            "nb_raw": report["nb_raw"],
            "nb_clean": report["nb_clean"],
            "nb_duplicates_removed": report["nb_duplicates_removed"],
            "nb_images": report["images"]["downloaded"],
            "pct_with_image": stats["pct_with_image"],
            "mean_length": stats["mean_length"],
            "lexical_diversity": stats["lexical_diversity"],
        })
        for source, count in stats["nb_by_source"].items():
            mlflow.log_metric(f"nb_{source}", count)
        for cls, pct in stats["pct_by_class"].items():
            mlflow.log_metric(f"pct_{cls}", pct)

        for artifact in artifacts:
            if artifact and Path(artifact).exists():
                mlflow.log_artifact(str(artifact))
            elif artifact:
                print(f"[tracking] artefact missing, skipped: {artifact}")

        return run.info.run_id


def dvc_track(paths: list[str] | None = None) -> bool:
    """Put the produced datasets under DVC version control (optional).

    DVC requires a Git repository; if either tool is missing the corpus is left
    untouched and the caller is told so.
    """
    import subprocess

    paths = paths or [str(config.RAW_CSV), str(config.CLEAN_CSV)]
    try:
        subprocess.run(["dvc", "add", *paths], cwd=config.ROOT, check=True,
                       capture_output=True, text=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"[tracking] dvc add failed: {exc}")
        return False
