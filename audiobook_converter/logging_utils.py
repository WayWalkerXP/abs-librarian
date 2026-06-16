"""Console and logging helpers."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from colorama import Fore, Style, init as colorama_init

from .models import ProcessingStats

class ConsoleDisplay:
    """Centralized color and emoji handling for console output."""

    EMOJIS = {
        "scan": "🔍",
        "convert": "🎧",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "archive": "📦",
        "summary": "🏁",
    }

    def __init__(self, use_color: bool, use_emoji: bool) -> None:
        self.use_color = use_color
        self.use_emoji = use_emoji
        colorama_init(autoreset=True, strip=not use_color)

    def info(self, message: str, emoji: str | None = None) -> None:
        self._write(message, Fore.WHITE + Style.BRIGHT, emoji)

    def success(self, message: str) -> None:
        self._write(message, Fore.WHITE + Style.BRIGHT, "success")

    def warning(self, message: str) -> None:
        self._write(message, Fore.YELLOW, "warning")

    def error(self, message: str) -> None:
        self._write(message, Fore.RED, "error", stream=sys.stderr)

    def critical(self, message: str) -> None:
        self._write(message, Fore.RED + Style.BRIGHT, "error", stream=sys.stderr)

    def summary(self, message: str) -> None:
        self._write(message, Fore.WHITE + Style.BRIGHT, "summary")

    def _write(self, message: str, color: str, emoji: str | None, stream: Any = sys.stdout) -> None:
        prefix = ""
        if self.use_emoji and emoji:
            prefix = f"{self.EMOJIS.get(emoji, emoji)} "
        if self.use_color:
            print(f"{color}{prefix}{message}{Style.RESET_ALL}", file=stream)
        else:
            print(f"{prefix}{message}", file=stream)

def configure_logging(log_file: Path) -> None:
    """Configure file logging for all application activity."""

    logging.basicConfig(
        filename=log_file,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )

def format_elapsed(seconds: float) -> str:
    """Format elapsed seconds as HH:MM:SS."""

    total_seconds = int(round(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def print_summary(display: ConsoleDisplay, stats: ProcessingStats, elapsed: str) -> None:
    """Display and log the final summary report."""

    lines = [
        "Processing Complete",
        f"Books Found: {stats.scanned}",
        f"Books Processed: {stats.processed}",
        f"Remaining: {stats.remaining}",
        f"Converted: {stats.converted}",
        f"Single-File Books Processed: {stats.single_files_processed}",
        f"Folder Books Processed: {stats.folder_books_processed}",
        f"Single Files Converted: {stats.single_files_converted}",
        f"Folder Books Converted: {stats.folder_books_converted}",
        f"Folder Books Skipped: {stats.folder_books_skipped}",
        f"Folder Books Failed: {stats.folder_books_failed}",
        f"Skipped: {stats.skipped}",
        f"Failed: {stats.failed}",
        f"Elapsed Time: {elapsed}",
    ]
    display.summary(lines[0])
    for line in lines[1:]:
        display.info(line)
    logging.info("Summary: %s", "; ".join(lines))
