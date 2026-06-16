"""Command-line interface for the audiobook converter."""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .config import AppConfig, ConfigManager, ConfigurationWizard
from .constants import CONFIG_FILE, LOCK_FILE
from .conversion import AsinMetadataManager, AudiobookConverter, ConversionPlanner, CoverArtExtractor, choose_codec
from .errors import ConfigError, DiskSpaceError, ForcedTermination, LockError, ProbeError
from .ffmpeg import CommandResult, FFmpegAnalyzer, run_external_command, terminate_active_external_processes, terminate_external_process
from .filesystem import LockFile, is_disk_space_error, sanitize_filename
from .logging_utils import ConsoleDisplay, configure_logging, format_elapsed, print_summary
from .metadata import build_output_tags, detect_dramatic_audio, first_tag_value, normalize_match_text
from .metrics import RunHistoryReporter
from .prompts import KeyboardController, KeyboardPromptSection
from .validation import ValidationManager


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert audiobook files to validated M4B outputs.")
    parser.add_argument("--mode", choices=("cli", "agent"), default="cli", help="Run interactive CLI mode or non-interactive JSON agent mode.")
    parser.add_argument("--config", default=CONFIG_FILE, help="Path to the INI configuration file.")
    parser.add_argument("--dry-run", action="store_true", help="Analyze and display actions without modifying files.")
    parser.add_argument("--no-color", action="store_true", help="Disable colored console output.")
    parser.add_argument("--no-emoji", action="store_true", help="Disable emoji output.")
    parser.add_argument("--no-folder-books", action="store_true", help="Ignore source-directory folders as books.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Program entry point."""

    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.mode == "agent":
        from app.converter.agent import run_agent
        return run_agent(sys.stdin)
    start_time = time.monotonic()
    repo_cwd = Path.cwd()
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = repo_cwd / config_path
    config_path = config_path.resolve()

    try:
        if not config_path.exists() and not ConfigurationWizard(config_path).run():
            return 0

        config = ConfigManager(config_path).load()
        use_color = config.use_color and not args.no_color
        use_emoji = config.use_emoji and not args.no_emoji
        display = ConsoleDisplay(use_color=use_color, use_emoji=use_emoji)
        configure_logging(config.log_file)
        logging.info("Startup complete; configuration loaded from %s", config_path)

        with LockFile(repo_cwd / LOCK_FILE):
            keyboard = KeyboardController()
            keyboard.start()
            try:
                analyzer = FFmpegAnalyzer()
                codec = choose_codec(analyzer, config, display)
                planner = ConversionPlanner(config, codec)
                validator = ValidationManager(analyzer)
                cover_extractor = CoverArtExtractor(config, display, args.dry_run)
                asin_metadata = AsinMetadataManager()
                converter = AudiobookConverter(
                    config,
                    display,
                    analyzer,
                    planner,
                    validator,
                    cover_extractor,
                    asin_metadata,
                    args.dry_run,
                    keyboard,
                    folder_books_enabled=not args.no_folder_books,
                )
                stats = converter.run()
                elapsed = format_elapsed(time.monotonic() - start_time)
                print_summary(display, stats, elapsed)
                RunHistoryReporter(config.run_history_csv).append(stats, elapsed)
                logging.info("Shutdown complete")
                return 0 if stats.failed == 0 else 1
            finally:
                keyboard.stop()

    except LockError as exc:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).error(str(exc))
        return 1
    except ConfigError as exc:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).error(str(exc))
        return 1
    except FileNotFoundError as exc:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).error(
            f"Required executable not found: {exc.filename}"
        )
        return 1
    except DiskSpaceError:
        logging.critical("Clean shutdown after disk-space exhaustion")
        return 1
    except ForcedTermination:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).critical(
            "Forced termination requested; exiting immediately"
        )
        logging.critical("Forced termination requested; lock and temporary cleanup attempted")
        return 130
    except KeyboardInterrupt:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).warning("Interrupted by user")
        logging.warning("Interrupted by user")
        return 130
    except Exception:
        ConsoleDisplay(use_color=not args.no_color, use_emoji=not args.no_emoji).error("Unexpected fatal error; see log for details")
        logging.exception("Unexpected fatal error")
        return 1
