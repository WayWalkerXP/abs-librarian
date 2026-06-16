"""Configuration loading and first-run wizard helpers."""
from __future__ import annotations

import argparse
import configparser
from pathlib import Path

from .constants import RUN_HISTORY_CSV
from .errors import ConfigError
from .models import AppConfig

class ConfigManager:
    """Load and validate configuration from the selected INI file."""

    REQUIRED_SECTIONS = ("paths", "encoding", "general", "display")

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def load(self) -> AppConfig:
        """Read, validate, and normalize the INI configuration."""

        if not self.config_path.exists():
            raise ConfigError(f"Configuration file not found: {self.config_path}")

        parser = configparser.ConfigParser()
        parser.read(self.config_path)

        for section in self.REQUIRED_SECTIONS:
            if section not in parser:
                raise ConfigError(f"Missing required configuration section: [{section}]")

        source_dir = self._required_path(parser, "paths", "source_dir")
        target_dir = self._required_path(parser, "paths", "target_dir")
        converted_dir = self._required_path(parser, "paths", "converted_dir")
        log_file = Path(self._required_value(parser, "general", "log_file")).expanduser().resolve()
        run_history_csv = self._optional_path(parser, "reporting", "run_history_csv", RUN_HISTORY_CSV)

        max_bitrate_kbps = parser.getint("encoding", "max_bitrate", fallback=64)
        if max_bitrate_kbps <= 0:
            raise ConfigError("[encoding] max_bitrate must be greater than zero")

        preferred_codec = self._required_value(parser, "encoding", "codec")
        fallback_codec = self._required_value(parser, "encoding", "fallback_codec")
        use_color = parser.getboolean("display", "use_color", fallback=True)
        use_emoji = parser.getboolean("display", "use_emoji", fallback=True)
        extract_cover = parser.getboolean("artwork", "extract_cover", fallback=False)
        cover_dir: Path | None = None
        if extract_cover:
            cover_dir_value = parser.get("artwork", "cover_dir", fallback="").strip()
            if not cover_dir_value:
                raise ConfigError("Missing required configuration value: [artwork] cover_dir")
            cover_dir = Path(cover_dir_value).expanduser().resolve()

        for directory in (source_dir, target_dir, converted_dir):
            directory.mkdir(parents=True, exist_ok=True)
            if not directory.is_dir():
                raise ConfigError(f"Configured path is not a directory: {directory}")

        # A staging or archive directory inside the source tree can cause the
        # converter to discover its own outputs on later runs, so fail early.
        for derived_dir, label in ((target_dir, "target_dir"), (converted_dir, "converted_dir")):
            if derived_dir == source_dir or source_dir in derived_dir.parents:
                raise ConfigError(f"[paths] {label} must not be inside source_dir")

        log_file.parent.mkdir(parents=True, exist_ok=True)
        run_history_csv.parent.mkdir(parents=True, exist_ok=True)

        return AppConfig(
            source_dir=source_dir,
            target_dir=target_dir,
            converted_dir=converted_dir,
            max_bitrate_kbps=max_bitrate_kbps,
            preferred_codec=preferred_codec,
            fallback_codec=fallback_codec,
            log_file=log_file,
            use_color=use_color,
            use_emoji=use_emoji,
            extract_cover=extract_cover,
            cover_dir=cover_dir,
            run_history_csv=run_history_csv,
        )

    def _required_value(self, parser: configparser.ConfigParser, section: str, key: str) -> str:
        value = parser.get(section, key, fallback="").strip()
        if not value:
            raise ConfigError(f"Missing required configuration value: [{section}] {key}")
        return value

    def _required_path(self, parser: configparser.ConfigParser, section: str, key: str) -> Path:
        return Path(self._required_value(parser, section, key)).expanduser().resolve()

    def _optional_path(self, parser: configparser.ConfigParser, section: str, key: str, default: str) -> Path:
        """Return an optional path, accepting missing sections/options but not blank configured values."""

        if parser.has_option(section, key):
            value = parser.get(section, key, fallback="").strip()
            if not value:
                raise ConfigError(f"Missing required configuration value: [{section}] {key}")
        else:
            value = default
        return Path(value).expanduser().resolve()

class ConfigurationWizard:
    """Create a first-run configuration when the selected INI file is missing."""

    PROMPTS: tuple[tuple[str, tuple[tuple[str, str | None], ...]], ...] = (
        ("paths", (("source_dir", None), ("target_dir", None), ("converted_dir", None))),
        ("encoding", (("max_bitrate", "64"), ("codec", "libfdk_aac"), ("fallback_codec", "aac"))),
        ("general", (("log_file", "audiobook_converter.log"),)),
        ("display", (("use_color", "true"), ("use_emoji", "true"),)),
        ("artwork", (("extract_cover", "false"),)),
    )

    TEMPLATE_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("paths", ("source_dir", "target_dir", "converted_dir")),
        ("encoding", ("max_bitrate", "codec", "fallback_codec")),
        ("general", ("log_file",)),
        ("display", ("use_color", "use_emoji")),
        ("artwork", ("extract_cover", "cover_dir")),
        ("reporting", ("run_history_csv",)),
    )

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path

    def run(self) -> bool:
        """Run the wizard and return True when processing should continue."""

        print(f"No configuration file was found at: {self.config_path}")
        print("Starting the interactive configuration wizard.\n")
        parser = self._collect_values()
        print("\nPlease review the generated configuration:\n")
        print(self._to_ini(parser))
        response = input("Are these settings correct? [Y/n] ").strip().casefold()
        if response in {"", "y", "yes"}:
            self._write(parser)
            print(f"\nConfiguration written to:\n    {self.config_path}\n")
            return True

        self.write_template()
        print(f"\nConfiguration template written to:\n    {self.config_path}\n")
        print("Please edit the file and rerun the converter.")
        return False

    def _collect_values(self) -> configparser.ConfigParser:
        parser = configparser.ConfigParser()
        extract_cover = False

        for section, prompts in self.PROMPTS:
            parser[section] = {}
            print(f"[{section}]")
            for key, default in prompts:
                value = self._prompt_value(key, default)
                parser[section][key] = value
                if section == "artwork" and key == "extract_cover":
                    extract_cover = value.casefold() in {"1", "yes", "y", "true", "on"}
            if section == "artwork" and extract_cover:
                parser[section]["cover_dir"] = self._prompt_value("cover_dir", None)
            print()

        parser["reporting"] = {"run_history_csv": RUN_HISTORY_CSV}
        return parser

    def _prompt_value(self, key: str, default: str | None) -> str:
        prompt = f"{key}"
        if default is not None:
            prompt += f" [{default}]"
        prompt += ": "
        value = input(prompt).strip()
        if value:
            return value
        return default or ""

    def _to_ini(self, parser: configparser.ConfigParser) -> str:
        lines: list[str] = []
        for section in parser.sections():
            lines.append(f"[{section}]")
            for key, value in parser[section].items():
                lines.append(f"{key} = {value}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _write(self, parser: configparser.ConfigParser) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as config_file:
            parser.write(config_file)

    def write_template(self) -> None:
        parser = configparser.ConfigParser()
        for section, keys in self.TEMPLATE_SECTIONS:
            parser[section] = {key: "" for key in keys}
        self._write(parser)
