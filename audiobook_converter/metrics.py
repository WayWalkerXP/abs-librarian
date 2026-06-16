"""Run metrics and CSV history reporting."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from .models import ProcessingStats

class RunHistoryReporter:
    """Append one persistent CSV row summarizing each completed converter run."""

    HEADER = [
        "date",
        "time",
        "numBooksProcessed",
        "numSingleFilesProcessed",
        "numFolderBooksProcessed",
        "numSingleFilesConverted",
        "numFolderBooksConverted",
        "numFolderBooksSkipped",
        "numFolderBooksFailed",
        "numBytesOriginal",
        "numBytesAfterConversion",
        "numBytesDiff",
        "pctDiff",
        "runTime",
    ]

    def __init__(self, csv_path: Path) -> None:
        self.csv_path = csv_path

    def append(self, stats: ProcessingStats, elapsed: str) -> None:
        """Create the run-history CSV if needed, then append calculated run totals."""

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        should_create = not self.csv_path.exists()
        if should_create:
            logging.info("Creating run history CSV: %s", self.csv_path)

        now = datetime.now()
        bytes_diff = stats.bytes_original - stats.bytes_after_conversion
        pct_diff = (bytes_diff / stats.bytes_original) * 100 if stats.bytes_original else 0.0
        row = [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            stats.converted,
            stats.single_files_processed,
            stats.folder_books_processed,
            stats.single_files_converted,
            stats.folder_books_converted,
            stats.folder_books_skipped,
            stats.folder_books_failed,
            stats.bytes_original,
            stats.bytes_after_conversion,
            bytes_diff,
            f"{pct_diff:.2f}",
            elapsed,
        ]
        logging.info(
            "Run history totals: "
            "converted=%s, single_files_processed=%s, folder_books_processed=%s, "
            "single_files_converted=%s, folder_books_converted=%s, "
            "folder_books_skipped=%s, folder_books_failed=%s, "
            "original_bytes=%s, converted_bytes=%s, diff_bytes=%s, "
            "pct_diff=%.2f, runtime=%s",
            stats.converted,
            stats.single_files_processed,
            stats.folder_books_processed,
            stats.single_files_converted,
            stats.folder_books_converted,
            stats.folder_books_skipped,
            stats.folder_books_failed,
            stats.bytes_original,
            stats.bytes_after_conversion,
            bytes_diff,
            pct_diff,
            elapsed,
        )

        with self.csv_path.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            if should_create:
                writer.writerow(self.HEADER)
            writer.writerow(row)
        logging.info("Appended run history CSV row to %s", self.csv_path)
