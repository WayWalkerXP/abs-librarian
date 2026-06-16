"""Validation helpers for settings and converted output files."""
from __future__ import annotations

import logging
from pathlib import Path

from .constants import TARGET_BITRATE_MAX_KBPS, TARGET_BITRATE_MIN_KBPS
from .errors import ProbeError
from .ffmpeg import FFmpegAnalyzer
from .models import AudioInfo, ConversionPlan

class ValidationManager:
    """Validate converted M4B files before originals are archived."""

    BITRATE_TOLERANCE_RATIO = 0.20
    DURATION_TOLERANCE_SECONDS = 2.0
    DURATION_TOLERANCE_RATIO = 0.01

    def __init__(self, analyzer: FFmpegAnalyzer) -> None:
        self.analyzer = analyzer

    def validate(self, source_info: AudioInfo, plan: ConversionPlan, output_path: Path) -> bool:
        """Return True when the converted file satisfies all critical checks."""

        if not output_path.exists():
            logging.error("Validation failed; output file does not exist: %s", output_path)
            return False

        try:
            output_info = self.analyzer.probe(output_path)
        except ProbeError as exc:
            logging.error("Validation failed; output is not readable: %s", exc)
            return False

        if output_info.channels != plan.output_channels:
            logging.error(
                "Validation failed; expected %s audio (%s channel(s)), found %s channel(s)",
                plan.output_channel_description,
                plan.output_channels,
                output_info.channels,
            )
            return False

        if not self._bitrate_matches(output_info.bitrate_bps, plan.target_bitrate_kbps * 1000):
            logging.error(
                "Validation failed; expected approximately %s kbps, found %s kbps",
                plan.target_bitrate_kbps,
                output_info.bitrate_kbps,
            )
            return False

        if not self._duration_matches(source_info.duration_seconds, output_info.duration_seconds):
            logging.error(
                "Validation failed; source duration %.2fs differs from output duration %.2fs",
                source_info.duration_seconds,
                output_info.duration_seconds,
            )
            return False

        if output_info.chapter_count != source_info.chapter_count:
            logging.error(
                "Validation failed; source has %s chapter(s), output has %s chapter(s)",
                source_info.chapter_count,
                output_info.chapter_count,
            )
            return False

        self._warn_about_missing_metadata(source_info, output_info)
        logging.info("Validation successful: %s", output_path)
        return True

    def _bitrate_matches(self, actual_bps: int, expected_bps: int) -> bool:
        tolerance = max(5_000, round(expected_bps * self.BITRATE_TOLERANCE_RATIO))
        return abs(actual_bps - expected_bps) <= tolerance

    def _duration_matches(self, source_seconds: float, output_seconds: float) -> bool:
        tolerance = max(self.DURATION_TOLERANCE_SECONDS, source_seconds * self.DURATION_TOLERANCE_RATIO)
        return abs(source_seconds - output_seconds) <= tolerance

    def _warn_about_missing_metadata(self, source_info: AudioInfo, output_info: AudioInfo) -> None:
        for key, source_value in source_info.metadata.items():
            if source_value and not output_info.metadata.get(key):
                logging.warning("Metadata appears missing in output: %s", key)


def validate_target_bitrate(value: int | None) -> bool:
    """Return True when an explicit target bitrate is allowed by current rules."""
    return value is not None and TARGET_BITRATE_MIN_KBPS <= value <= TARGET_BITRATE_MAX_KBPS

def validate_target_channels(value: int | None) -> bool:
    """Return True when an explicit target channel count is allowed by current rules."""
    return value in {1, 2}
