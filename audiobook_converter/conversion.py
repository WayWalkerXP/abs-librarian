"""Conversion planning and execution."""
from __future__ import annotations

import csv
import errno
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm

from .constants import (ASIN_MP4_FREEFORM_KEY, CANONICAL_METADATA_VARIANT_KEYS, CONFIG_FILE, CONVERSION_CONTROL_KEYS, CORE_METADATA_LOG_KEYS, DESCRIPTIVE_METADATA_KEYS, DRAMATIC_AUDIO_MP4_FREEFORM_KEY, IGNORED_FOLDER_NAMES, SKIPPED_MARKER, TARGET_BITRATE_MAX_KBPS, TARGET_BITRATE_MIN_KBPS, YAML_DESCRIPTIVE_METADATA_KEYS)
from .errors import ConfigError, DiskSpaceError, ForcedTermination, ProbeError
from .ffmpeg import FFmpegAnalyzer, run_external_command
from .filesystem import is_disk_space_error, sanitize_filename
from .logging_utils import ConsoleDisplay
from .metadata import build_output_tags, detect_dramatic_audio, first_tag_value, normalize_match_text
from .models import AppConfig, AudioInfo, ConversionPlan, DramaticAudioMatch, FolderBookPlan, FolderMetadata, FolderTrack, ProcessingStats, SingleFileMetadata
from .prompts import KeyboardController
from .validation import ValidationManager

class AsinMetadataManager:
    """Read, write, and verify ASIN tags with Mutagen."""

    def read_source_asin(self, path: Path) -> str:
        """Return the first non-empty ASIN tag found in a source file, or an empty string."""

        try:
            audio_file = MutagenFile(path)
        except Exception as exc:
            logging.warning("Mutagen could not read source metadata for %s: %s", path, exc)
            return ""

        try:
            asin = self._extract_asin_from_tags(getattr(audio_file, "tags", None))
        except Exception as exc:
            logging.warning("Mutagen could not read source metadata for %s: %s", path, exc)
            return ""

        if asin:
            logging.info("ASIN found in source metadata for %s: %s", path, asin)
        else:
            logging.info("No ASIN found in source metadata for %s", path)
        return asin

    def preserve_cover_art(self, source_path: Path, output_path: Path) -> str:
        """Copy one primary embedded cover from source to output; return status."""

        try:
            source = MutagenFile(source_path)
            output = MP4(output_path)
            if output.tags is None:
                output.add_tags()
            if output.tags is None:
                raise ValueError("output file has no writable MP4 tags")
            cover = self._extract_cover(source)
            if cover is None:
                logging.info("Embedded cover art absent for %s", source_path)
                return "absent"
            output.tags["covr"] = [cover]
            output.save()
            logging.info("Embedded cover art preserved from %s to %s", source_path, output_path)
            return "preserved"
        except Exception as exc:
            logging.warning("Embedded cover art failed to preserve from %s to %s: %s", source_path, output_path, exc)
            return "failed"

    def _extract_cover(self, source: Any) -> MP4Cover | None:
        tags = getattr(source, "tags", None)
        if not tags:
            return None
        if "covr" in tags and tags["covr"]:
            return tags["covr"][0]
        items = tags.items() if hasattr(tags, "items") else []
        for key, value in items:
            if str(key).startswith("APIC") or value.__class__.__name__ == "APIC":
                data = getattr(value, "data", None)
                mime = str(getattr(value, "mime", "")).casefold()
                if data:
                    fmt = MP4Cover.FORMAT_PNG if "png" in mime else MP4Cover.FORMAT_JPEG
                    return MP4Cover(data, imageformat=fmt)
        return None

    def write_and_verify_output_asin(self, path: Path, asin: str) -> bool:
        """Write an ASIN tag to an M4B output and verify that Mutagen can read it back."""

        expected_asin = asin.strip()
        if not expected_asin:
            logging.info("Skipping blank ASIN write for %s", path)
            return True

        try:
            output_file = MP4(path)
            if output_file.tags is None:
                output_file.add_tags()
            if output_file.tags is None:
                raise ValueError("output file has no writable MP4 tags")
            for key in list(output_file.tags.keys()):
                if self._is_asin_key(key):
                    del output_file.tags[key]
            dataformat = getattr(MP4FreeForm, "FORMAT_UTF8", 1)
            output_file.tags[ASIN_MP4_FREEFORM_KEY] = [
                MP4FreeForm(expected_asin.encode("utf-8"), dataformat=dataformat)
            ]
            output_file.save()
        except Exception as exc:
            logging.error("Mutagen could not write output metadata for %s: %s", path, exc)
            return False

        logging.info("ASIN written to output M4B for %s: %s", path, expected_asin)
        actual_asin = self.read_output_asin(path)
        if actual_asin == expected_asin:
            logging.info("ASIN verification succeeded for %s", path)
            return True

        logging.error(
            "ASIN verification failed for %s: expected %r, found %r",
            path,
            expected_asin,
            actual_asin,
        )
        return False

    def read_output_asin(self, path: Path) -> str:
        """Return the first non-empty ASIN tag found in an M4B output, or an empty string."""

        try:
            output_file = MP4(path)
        except Exception as exc:
            logging.error("Mutagen could not read output metadata for %s: %s", path, exc)
            return ""
        return self._extract_asin_from_tags(output_file.tags)

    def _extract_asin_from_tags(self, tags: Any) -> str:
        if not tags:
            return ""
        items = tags.items() if hasattr(tags, "items") else []
        for key, value in items:
            if not self._is_asin_key(str(key)):
                continue
            asin = self._first_non_empty_value(value)
            if asin:
                return asin
        return ""

    def _is_asin_key(self, key: str) -> bool:
        normalized = key.casefold().strip()
        if normalized == "asin":
            return True
        return any(part == "asin" for part in normalized.split(":"))

    def _first_non_empty_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip().strip("\x00")
        if isinstance(value, (list, tuple)):
            for item in value:
                extracted = self._first_non_empty_value(item)
                if extracted:
                    return extracted
            return ""
        text = getattr(value, "text", None)
        if text is not None:
            extracted = self._first_non_empty_value(text)
            if extracted:
                return extracted
        return str(value).strip()

    def write_and_verify_output_tags(
        self,
        path: Path,
        tags: dict[str, str],
        dramatic_audio: bool = False,
    ) -> bool:
        """Normalize final M4B metadata tags with Mutagen and verify ASIN preservation."""

        try:
            output_file = MP4(path)
            if output_file.tags is None:
                output_file.add_tags()
            if output_file.tags is None:
                raise ValueError("output file has no writable MP4 tags")

            mp4_tags = output_file.tags
            self._remove_existing_metadata_variants(mp4_tags)
            for key in list(mp4_tags.keys()):
                normalized = str(key).casefold()
                if (
                    "target_bitrate" in normalized
                    or "target_channels" in normalized
                    or normalized == DRAMATIC_AUDIO_MP4_FREEFORM_KEY.casefold()
                ):
                    del mp4_tags[key]

            author = first_tag_value(tags, ("author", "artist", "albumartist", "album_artist", "composer"))
            album = first_tag_value(tags, ("album", "title"))
            title = first_tag_value(tags, ("title", "album"))
            asin = tags.get("asin", "").strip()
            self._write_descriptive_mp4_tags(mp4_tags, tags)
            if author:
                mp4_tags["\xa9ART"] = [author]
                mp4_tags["aART"] = [author]
                mp4_tags["----:com.apple.iTunes:author"] = [self._mp4_freeform(author)]
            if album:
                mp4_tags["\xa9alb"] = [album]
            if title:
                mp4_tags["\xa9nam"] = [title]
            if asin:
                mp4_tags[ASIN_MP4_FREEFORM_KEY] = [self._mp4_freeform(asin)]
            if dramatic_audio:
                mp4_tags[DRAMATIC_AUDIO_MP4_FREEFORM_KEY] = [self._mp4_freeform("true")]
            output_file.save()
        except Exception as exc:
            logging.error("Mutagen could not write output metadata for %s: %s", path, exc)
            return False

        expected_asin = tags.get("asin", "").strip()
        if expected_asin and self.read_output_asin(path) != expected_asin:
            logging.error("ASIN verification failed for %s after final metadata pass", path)
            return False
        logging.info("Mutagen final metadata pass succeeded for %s", path)
        return True

    def _remove_existing_metadata_variants(self, mp4_tags: Any) -> None:
        """Remove non-canonical duplicates before writing normalized MP4 metadata."""

        for key in list(mp4_tags.keys()):
            key_text = str(key)
            if key_text in CANONICAL_METADATA_VARIANT_KEYS or self._is_asin_key(key_text):
                del mp4_tags[key]
                logging.info("Removed existing metadata variant: %s", key_text)

    def _mp4_freeform(self, value: str) -> MP4FreeForm:
        dataformat = getattr(MP4FreeForm, "FORMAT_UTF8", 1)
        return MP4FreeForm(value.encode("utf-8"), dataformat=dataformat)

    def _write_descriptive_mp4_tags(self, mp4_tags: Any, tags: dict[str, str]) -> None:
        """Write audiobook-relevant descriptive tags to MP4 atoms/freeforms."""

        standard_map = {
            "subtitle": "\xa9des",
            "genre": "\xa9gen",
            "date": "\xa9day",
            "year": "\xa9day",
            "comment": "\xa9cmt",
            "description": "desc",
        }
        freeform_keys = {
            "narrator": "narrator",
            "series": "series",
            "series-part": "series-part",
            "series_sequence": "series_sequence",
            "sequence": "sequence",
            "publisher": "publisher",
            "language": "language",
            "isbn": "ISBN",
            "synopsis": "synopsis",
            "summary": "summary",
        }
        for source_key, atom in standard_map.items():
            value = tags.get(source_key, "").strip()
            if value:
                mp4_tags[atom] = [value]
        for source_key, freeform_name in freeform_keys.items():
            value = tags.get(source_key, "").strip()
            if value:
                mp4_tags[f"----:com.apple.iTunes:{freeform_name}"] = [self._mp4_freeform(value)]

class ConversionPlanner:
    """Apply filename, duplicate, and bitrate rules for a source file."""

    def __init__(self, config: AppConfig, codec: str) -> None:
        self.config = config
        self.codec = codec

    def create_plan(
        self,
        source_info: AudioInfo,
        dramatic_match: DramaticAudioMatch | None = None,
        target_bitrate_override: int | None = None,
        target_channels_override: int | None = None,
        output_metadata: dict[str, str] | None = None,
        dramatic_audio_output: bool = False,
    ) -> ConversionPlan | None:
        """Return a conversion plan, or None when bitrate rules require a skip."""

        if dramatic_match is None:
            dramatic_match = detect_dramatic_audio(source_info)
        target_bitrate_kbps = target_bitrate_override or self._target_bitrate(source_info, dramatic_match)
        if target_bitrate_kbps is None:
            return None
        output_channels = target_channels_override or (2 if dramatic_match is not None and source_info.channels > 1 else 1)

        output_name = self._output_filename(source_info)
        final_path = self.config.target_dir / output_name
        temporary_path = final_path.with_name(f"{final_path.stem}.tmp{final_path.suffix}")
        archive_path = self.config.converted_dir / source_info.path.relative_to(self.config.source_dir)

        return ConversionPlan(
            source_path=source_info.path,
            final_path=final_path,
            temporary_path=temporary_path,
            archive_path=archive_path,
            target_bitrate_kbps=target_bitrate_kbps,
            output_channels=output_channels,
            codec=self.codec,
            dramatic_audio_match=dramatic_match,
            output_metadata=output_metadata or {},
            write_final_metadata=bool(output_metadata),
            dramatic_audio_output=dramatic_audio_output,
        )

    def create_folder_plan(
        self,
        folder_path: Path,
        tracks: tuple[FolderTrack, ...],
        metadata: FolderMetadata | None,
    ) -> ConversionPlan | None:
        """Return a conversion plan for a validated folder-book."""

        bitrate_source = tracks[len(tracks) // 2].info
        detection_source = bitrate_source
        if metadata is not None:
            detection_source = AudioInfo(
                path=folder_path,
                bitrate_bps=bitrate_source.bitrate_bps,
                channels=bitrate_source.channels,
                codec=bitrate_source.codec,
                duration_seconds=bitrate_source.duration_seconds,
                chapter_count=bitrate_source.chapter_count,
                metadata=metadata.as_detection_metadata(),
                artwork_stream=bitrate_source.artwork_stream,
            )
        if metadata and metadata.dramatic_audio is True:
            dramatic_match = DramaticAudioMatch("DRAMATIC_AUDIO", "true", "explicit tag")
        elif metadata and metadata.dramatic_audio is False:
            dramatic_match = None
        else:
            dramatic_match = detect_dramatic_audio(detection_source)
        target_bitrate_kbps = metadata.bitrate if metadata and metadata.bitrate else self._target_bitrate(bitrate_source, dramatic_match)
        if target_bitrate_kbps is None:
            return None

        if metadata and metadata.channels:
            output_channels = metadata.channels
        else:
            output_channels = 2 if dramatic_match is not None and bitrate_source.channels > 1 else 1

        dramatic_audio_output = bool(metadata and (metadata.dramatic_audio is True or (metadata.dramatic_audio is None and dramatic_match is not None)))
        if metadata is not None:
            output_name = f"{sanitize_filename(metadata.author)} - {sanitize_filename(metadata.title)}.m4b"
            output_metadata = metadata.as_output_tags(dramatic_audio_output)
        else:
            output_name = self._output_filename(tracks[0].info)
            output_metadata = {key: value for key, value in tracks[0].info.metadata.items() if key != "track"}
            if output_metadata.get("title"):
                output_metadata["album"] = output_metadata["title"]

        final_path = self.config.target_dir / output_name
        temporary_path = final_path.with_name(f"{final_path.stem}.tmp{final_path.suffix}")
        archive_path = self.config.converted_dir / folder_path.relative_to(self.config.source_dir)
        total_duration = sum(track.info.duration_seconds for track in tracks)
        synthetic_source = AudioInfo(
            path=folder_path,
            bitrate_bps=bitrate_source.bitrate_bps,
            channels=bitrate_source.channels,
            codec=bitrate_source.codec,
            duration_seconds=total_duration,
            chapter_count=len(tracks),
            metadata=metadata.as_detection_metadata() if metadata is not None else (output_metadata or tracks[0].info.metadata),
        )
        return ConversionPlan(
            source_path=synthetic_source.path,
            final_path=final_path,
            temporary_path=temporary_path,
            archive_path=archive_path,
            target_bitrate_kbps=target_bitrate_kbps,
            output_channels=output_channels,
            codec=self.codec,
            dramatic_audio_match=dramatic_match,
            archive_source_path=folder_path,
            input_paths=tuple(track.path for track in tracks),
            chapter_titles=tuple(track.title for track in tracks),
            output_metadata=output_metadata,
            write_final_metadata=bool(output_metadata),
            dramatic_audio_output=dramatic_audio_output,
        )

    def _target_bitrate(self, source_info: AudioInfo, dramatic_match: DramaticAudioMatch | None) -> int | None:
        """Choose a target bitrate from normalized 8 kbps source buckets."""

        source_kbps = source_info.normalized_bitrate_kbps
        max_bitrate = self.config.max_bitrate_kbps

        if source_info.channels > 1 and dramatic_match is not None:
            return 128 if source_kbps >= 128 else 64

        if source_info.channels > 1:
            if source_kbps >= 128:
                return min(64, max_bitrate)
            if source_kbps >= 64:
                return min(max(round(source_kbps / 2), 1), max_bitrate)
            return None

        if source_kbps < 32:
            return None
        if source_kbps < 64:
            return min(source_kbps, max_bitrate)
        return min(64, max_bitrate)

    def _output_filename(self, source_info: AudioInfo) -> str:
        metadata = source_info.metadata
        author = self._first_metadata_value(metadata, ("artist", "album_artist", "author", "composer"))
        title = self._first_metadata_value(metadata, ("title", "album"))

        if not author:
            author = "Unknown Author"
        if not title:
            title = source_info.path.stem

        return f"{sanitize_filename(author)} - {sanitize_filename(title)}.m4b"

    def _first_metadata_value(self, metadata: dict[str, str], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = metadata.get(key, "").strip()
            if value:
                return value
        return ""

class CoverArtExtractor:
    """Best-effort embedded cover extraction to sidecar image files."""

    def __init__(self, config: AppConfig, display: ConsoleDisplay, dry_run: bool) -> None:
        self.config = config
        self.display = display
        self.dry_run = dry_run

    def plan_cover_path(self, source_info: AudioInfo) -> Path | None:
        """Return the configured sidecar cover path, if extraction is enabled and artwork exists."""

        if not self.config.extract_cover:
            logging.info("Cover extraction disabled by configuration")
            return None
        if source_info.artwork_stream is None:
            logging.info("No embedded cover art found in %s", source_info.path)
            return None
        if self.config.cover_dir is None:
            logging.warning("Cover extraction enabled without a configured cover_dir")
            return None
        stem = sanitize_filename(source_info.path.stem)
        return self.config.cover_dir / f"{stem}.{source_info.artwork_stream.extension}"

    def extract(self, source_info: AudioInfo) -> None:
        """Extract the selected embedded cover, logging warnings without failing conversion."""

        cover_path = self.plan_cover_path(source_info)
        if cover_path is None:
            return

        assert source_info.artwork_stream is not None
        if self.dry_run:
            self.display.info(f"Would extract cover art to: {cover_path}")
            logging.info("Dry run cover extraction plan for %s: %s", source_info.path, cover_path)
            return

        temporary_path: Path | None = None
        try:
            if cover_path.exists():
                warning = f"Cover already exists; not overwriting: {cover_path}"
                self.display.warning(warning)
                logging.warning(warning)
                return

            cover_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = cover_path.with_name(f"{cover_path.stem}.tmp{cover_path.suffix}")
            temporary_path.unlink(missing_ok=True)
            command = [
                "ffmpeg",
                "-hide_banner",
                "-y",
                "-i",
                str(source_info.path),
                "-map",
                f"0:{source_info.artwork_stream.index}",
                "-frames:v",
                "1",
                "-update",
                "1",
                str(temporary_path),
            ]
            result = run_external_command(command)
            if result.returncode != 0:
                temporary_path.unlink(missing_ok=True)
                warning = f"Cover extraction failed for {source_info.path.name}; continuing conversion"
                self.display.warning(warning)
                logging.warning("%s: %s", warning, result.stderr.strip())
                return

            if not temporary_path.exists():
                warning = f"Cover extraction produced no file for {source_info.path.name}; continuing conversion"
                self.display.warning(warning)
                logging.warning(warning)
                return
            os.link(temporary_path, cover_path)
            temporary_path.unlink()
            self.display.info(f"Extracted cover art: {cover_path}")
            logging.info(
                "Extracted %s stream %s from %s to %s",
                source_info.artwork_stream.disposition,
                source_info.artwork_stream.index,
                source_info.path,
                cover_path,
            )
        except Exception as exc:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logging.exception("Failed to clean temporary cover output %s", temporary_path)
            warning = f"Cover extraction failed for {source_info.path.name}; continuing conversion"
            self.display.warning(warning)
            logging.warning("%s: %s", warning, exc, exc_info=True)

class AudiobookConverter:
    """Coordinate discovery, per-file transactions, progress, and user controls."""

    def __init__(
        self,
        config: AppConfig,
        display: ConsoleDisplay,
        analyzer: FFmpegAnalyzer,
        planner: ConversionPlanner,
        validator: ValidationManager,
        cover_extractor: CoverArtExtractor,
        asin_metadata: AsinMetadataManager,
        dry_run: bool,
        keyboard: KeyboardController,
        folder_books_enabled: bool = True,
    ) -> None:
        self.config = config
        self.display = display
        self.analyzer = analyzer
        self.planner = planner
        self.validator = validator
        self.cover_extractor = cover_extractor
        self.asin_metadata = asin_metadata
        self.dry_run = dry_run
        self.keyboard = keyboard
        self.folder_books_enabled = folder_books_enabled
        self.stats = ProcessingStats()

    def run(self) -> ProcessingStats:
        """Process every discovered file and honor pause/quit requests between transactions."""

        logging.info("Starting audiobook conversion; dry_run=%s", self.dry_run)
        items = self._discover_items()
        self.stats.scanned = len(items)
        self.display.info(f"Found {self.stats.scanned} books to process.", "scan")
        logging.info("Discovered %s books to process", self.stats.scanned)

        for path in items:
            if path.is_dir():
                self._process_one_folder(path)
            else:
                self._process_one_file(path)
            if self._handle_between_file_controls():
                break

        logging.info("Finished audiobook conversion")
        return self.stats

    def _discover_items(self) -> list[Path]:
        """Discover only direct source children that can be processed as books."""

        logging.info("Discovering direct children under %s", self.config.source_dir)
        items: list[Path] = []
        for path in sorted(self.config.source_dir.iterdir()):
            if path.is_file():
                items.append(path)
                continue
            if not path.is_dir():
                continue
            if self._is_ignored_folder(path):
                logging.info("Ignoring system/converter folder: %s", path)
                continue
            if not self.folder_books_enabled:
                logging.info("Folder processing disabled. Ignoring folder: %s", path)
                continue
            items.append(path)
        return items

    def _is_ignored_folder(self, path: Path) -> bool:
        name = path.name.casefold()
        if name.startswith(".") or name in IGNORED_FOLDER_NAMES:
            return True
        resolved = path.resolve()
        for configured in (self.config.target_dir, self.config.converted_dir):
            try:
                if resolved == configured.resolve():
                    return True
            except OSError:
                continue
        return False

    def _process_one_folder(self, folder_path: Path) -> None:
        """Validate and process a direct-child folder as one audiobook transaction."""

        plan: ConversionPlan | None = None
        self.stats.folder_books_processed += 1

        # Capture terminal settings before folder processing so they can be
        # restored regardless of how this transaction ends.  Folder books run
        # many subprocesses which can corrupt terminal state.
        saved_terminal: object = None
        terminal_fd: int | None = None
        if os.name != "nt" and sys.stdin.isatty():
            try:
                import termios

                terminal_fd = sys.stdin.fileno()
                saved_terminal = termios.tcgetattr(terminal_fd)
                logging.info("Terminal settings captured before folder-book processing: %s", folder_path.name)
            except Exception:
                logging.warning("Could not capture terminal settings before folder-book processing", exc_info=True)

        logging.info("Folder-book processing started: %s", folder_path.name)
        try:
            self.display.info(f"Scanning folder: {folder_path.name}", "scan")
            logging.info("Folder-book discovered: %s", folder_path)
            folder_book = self._prepare_folder_book(folder_path)
            if folder_book is None:
                return
            plan = folder_book.conversion_plan
            source_info = self._folder_source_info(folder_book)
            if folder_book.metadata is not None:
                self._log_folder_metadata(folder_path, folder_book.metadata, plan)
            self._log_bitrate_decision(folder_path, source_info, plan)

            if plan.final_path.exists():
                self._skip_folder(folder_path, "Output already exists.", [f"Existing output: {plan.final_path}"])
                return

            source_asin = self._folder_source_asin(folder_book)

            if self.dry_run:
                self._describe_folder_dry_run(folder_book, source_info)
                if source_asin:
                    self.display.info(f"Would preserve ASIN: {source_asin}")
                    logging.info("Dry run: would preserve folder-book ASIN for %s: %s", folder_path, source_asin)
                self._skip(f"Dry run: planned folder-book conversion for {folder_path.name}")
                return

            self._convert_validate_and_archive(source_info, plan, source_asin)
        except DiskSpaceError:
            if plan is not None:
                self._cleanup_temporary_output(plan)
            logging.critical("Stopping immediately because disk-space exhaustion was detected", exc_info=True)
            self.display.critical("Critical error: disk space exhausted. Stopping processing immediately.")
            raise
        except ForcedTermination:
            raise
        except Exception as exc:
            if plan is not None:
                self._cleanup_temporary_output(plan)
            self._fail_folder(folder_path, f"Unexpected folder-book failure: {exc}")
            logging.exception("Folder-level failure for %s; continuing with next item", folder_path)
        finally:
            logging.info("Folder-book processing ended: %s", folder_path.name)
            if saved_terminal is not None and terminal_fd is not None:
                try:
                    import termios

                    termios.tcsetattr(terminal_fd, termios.TCSADRAIN, saved_terminal)
                    logging.info("Terminal settings restored after folder-book processing: %s", folder_path.name)
                except Exception:
                    logging.warning(
                        "Failed to restore terminal settings after folder-book processing: %s",
                        folder_path.name,
                        exc_info=True,
                    )
                    self.keyboard.restore_terminal()
            self._mark_processed()

    def _prepare_folder_book(self, folder_path: Path) -> FolderBookPlan | None:
        audio_paths = self._discover_folder_audio_files(folder_path)
        logging.info("Audio files discovered for folder-book %s: %s", folder_path, len(audio_paths))

        if not audio_paths:
            _, yaml_errors = self._load_folder_metadata(folder_path)
            self._skip_folder(folder_path, "No audio files found.", yaml_errors)
            return None

        representative_metadata, representative_errors = self._extract_representative_book_metadata(audio_paths[0])
        if representative_errors and representative_metadata is not None:
            self._skip_folder(folder_path, "Invalid representative audio-file metadata.", representative_errors)
            return None
        yaml_metadata, yaml_errors = self._load_folder_metadata(folder_path)
        if yaml_errors:
            self._skip_folder(folder_path, "YAML validation failed.", yaml_errors)
            return None
        metadata = self._merge_folder_metadata(representative_metadata, yaml_metadata)
        if yaml_metadata is not None:
            logging.info("Using representative audio-file tags with metadata.yaml overrides/fill-ins.")
        elif metadata is not None:
            logging.info("Using metadata from representative audio tags.")
        missing_metadata_fields = self._missing_required_metadata(metadata)
        if missing_metadata_fields:
            details = [f"Missing required metadata: {field}" for field in missing_metadata_fields]
            logging.warning("Skipping book. Missing required metadata: %s", ", ".join(missing_metadata_fields))
            self._skip_folder(folder_path, "Missing required metadata.", details)
            return None
        if metadata and metadata.skip:
            self._skip_folder(folder_path, "Folder intentionally skipped by metadata YAML.", [])
            return None

        tracks: list[FolderTrack] = []
        issues: list[str] = []
        for audio_path in audio_paths:
            try:
                info = self.analyzer.probe(audio_path)
                number = self._extract_track_number(info)
                if number is None:
                    if len(audio_paths) == 1:
                        number = 1
                    else:
                        issues.append(f"{audio_path.name}: Missing or invalid track number")
                        continue
                title = info.metadata.get("title", "").strip() or f"Chapter {number}"
                tracks.append(FolderTrack(audio_path, info, number, title))
                logging.info("Track number extracted for %s: %s", audio_path, number)
            except ProbeError as exc:
                issues.append(f"{audio_path.name}: {exc}")

        if len(audio_paths) > 1:
            issues.extend(self._validate_track_numbers(tracks))
        elif not tracks and not issues:
            issues.append(f"{audio_paths[0].name}: Missing or invalid track number")

        if issues:
            self._skip_folder(folder_path, "Track validation failed.", issues)
            return None

        tracks.sort(key=lambda track: track.number)
        plan = self.planner.create_folder_plan(folder_path, tuple(tracks), metadata)
        if plan is None:
            middle_info = tracks[len(tracks) // 2].info
            self._skip_folder(
                folder_path,
                "Bitrate below threshold.",
                [f"Middle track normalized bitrate: {middle_info.normalized_bitrate_kbps} kbps"],
            )
            return None
        logging.info("Folder-book validation complete: %s", folder_path)
        return FolderBookPlan(folder_path, tuple(tracks), plan, metadata)

    def _merge_folder_metadata(
        self,
        representative: FolderMetadata | None,
        yaml_metadata: FolderMetadata | None,
    ) -> FolderMetadata | None:
        """Merge representative audio tags with metadata.yaml values taking precedence."""

        if representative is None:
            return yaml_metadata
        if yaml_metadata is None:
            return representative

        title = yaml_metadata.title or representative.title
        author = yaml_metadata.author or representative.author
        tags = build_output_tags(
            representative.tags,
            fallback_author=representative.author,
            fallback_album=representative.title,
            overrides=yaml_metadata.tags,
            dramatic_audio=yaml_metadata.dramatic_audio if yaml_metadata.dramatic_audio is not None else representative.dramatic_audio,
        )
        return FolderMetadata(
            title=title,
            author=author,
            tags=build_output_tags(tags, author, title),
            skip=yaml_metadata.skip,
            bitrate=yaml_metadata.bitrate if yaml_metadata.bitrate is not None else representative.bitrate,
            channels=yaml_metadata.channels if yaml_metadata.channels is not None else representative.channels,
            dramatic_audio=yaml_metadata.dramatic_audio if yaml_metadata.dramatic_audio is not None else representative.dramatic_audio,
            title_inferred=not bool(title),
            author_inferred=not bool(author),
            bitrate_missing=yaml_metadata.bitrate is None and representative.bitrate is None,
            channels_missing=yaml_metadata.channels is None and representative.channels is None,
            dramatic_missing=yaml_metadata.dramatic_audio is None and representative.dramatic_audio is None,
        )

    def _folder_source_asin(self, folder_book: FolderBookPlan) -> str:
        """Return the ASIN to preserve for a folder-book conversion."""

        if folder_book.metadata and folder_book.metadata.asin.strip():
            asin = folder_book.metadata.asin.strip()
            logging.info("Using folder-book metadata ASIN for %s: %s", folder_book.folder_path, asin)
            return asin

        discovered_asins: dict[str, Path] = {}
        for track in folder_book.tracks:
            asin = self.asin_metadata.read_source_asin(track.path)
            if asin and asin not in discovered_asins:
                discovered_asins[asin] = track.path

        if not discovered_asins:
            logging.info("No ASIN found in folder-book source metadata for %s", folder_book.folder_path)
            return ""

        if len(discovered_asins) > 1:
            logging.warning(
                "Multiple ASIN values found in folder-book %s; preserving first in track order: %s",
                folder_book.folder_path,
                ", ".join(discovered_asins),
            )

        asin, source_path = next(iter(discovered_asins.items()))
        logging.info("Using folder-book source ASIN from %s: %s", source_path, asin)
        return asin

    def _extract_representative_book_metadata(self, audio_path: Path) -> tuple[FolderMetadata | None, list[str]]:
        """Read folder-book metadata from one representative audio file."""

        try:
            audio_file = MutagenFile(audio_path)
        except Exception as exc:
            logging.warning("Mutagen could not read representative metadata for %s: %s", audio_path, exc)
            return None, [f"{audio_path.name}: Mutagen metadata read failed: {exc}"]
        if audio_file is None:
            return None, [f"{audio_path.name}: Mutagen could not identify audio file"]

        tags = getattr(audio_file, "tags", None)
        descriptive_tags = self._extract_audiobook_metadata_tags(tags)
        title = first_tag_value(descriptive_tags, ("album", "title"))
        author = first_tag_value(descriptive_tags, ("artist", "albumartist", "author", "composer"))
        bitrate_value = self._read_txxx_frame(tags, "TARGET_BITRATE")
        channels_value = self._read_txxx_frame(tags, "TARGET_CHANNELS")

        errors: list[str] = []
        bitrate = self._parse_folder_target_bitrate(bitrate_value, "TARGET_BITRATE", errors)
        channels = self._normalize_channels(channels_value, errors, field_name="TARGET_CHANNELS")
        dramatic_value = self._read_txxx_frame(tags, "DRAMATIC_AUDIO")
        dramatic_audio = self._parse_optional_bool(dramatic_value, "DRAMATIC_AUDIO", errors)
        if errors:
            logging.info("Invalid representative tag metadata in %s: %s", audio_path, errors)

        if not title and not author and bitrate is None and not descriptive_tags:
            return None, errors
        output_tags = build_output_tags(descriptive_tags, title and author or author, title, dramatic_audio=dramatic_audio)
        return FolderMetadata(
            title=title,
            author=author,
            tags=output_tags,
            bitrate=bitrate,
            channels=channels,
            dramatic_audio=dramatic_audio,
            title_inferred=not bool(title),
            author_inferred=not bool(author),
            bitrate_missing=not bool(bitrate_value.strip()),
            channels_missing=not bool(channels_value.strip()),
            dramatic_missing=not bool(dramatic_value.strip()),
        ), errors

    def _read_standard_text_frame(self, tags: Any, keys: tuple[str, ...]) -> str:
        """Return the first non-empty Mutagen text-frame value for any key."""

        if not tags:
            return ""
        for key in keys:
            value = self._metadata_value(tags.get(key) if hasattr(tags, "get") else None)
            if value:
                return value
        return ""

    def _read_txxx_frame(self, tags: Any, description: str) -> str:
        """Read TXXX/freeform frames by description case-insensitively."""

        if not tags:
            return ""
        wanted = description.casefold()
        items = tags.items() if hasattr(tags, "items") else []
        for key, value in items:
            normalized_key = str(key).casefold()
            if normalized_key in {f"txxx:{wanted}", f"----:com.apple.itunes:{wanted}", wanted}:
                extracted = self._metadata_value(value)
                if extracted:
                    return extracted
            desc = getattr(value, "desc", "")
            if isinstance(desc, str) and desc.casefold() == wanted:
                extracted = self._metadata_value(getattr(value, "text", value))
                if extracted:
                    return extracted
        return ""

    def _extract_audiobook_metadata_tags(self, tags: Any) -> dict[str, str]:
        """Extract only audiobook-relevant descriptive metadata from Mutagen tags."""

        aliases: dict[str, tuple[str, ...]] = {
            "title": ("TIT2", "\xa9nam", "title"),
            "subtitle": ("TIT3", "subtitle"),
            "album": ("TALB", "\xa9alb", "album"),
            "artist": ("TPE1", "\xa9ART", "artist"),
            "albumartist": ("TPE2", "aART", "albumartist", "album_artist"),
            "author": ("author", "----:com.apple.iTunes:author"),
            "series": ("series", "----:com.apple.iTunes:series"),
            "series-part": ("series-part", "series_part", "series_sequence", "sequence", "book", "book_number"),
            "genre": ("TCON", "\xa9gen", "genre"),
            "date": ("TDRC", "TYER", "\xa9day", "date", "year"),
            "description": ("desc", "description"),
            "comment": ("COMM", "\xa9cmt", "comment"),
            "synopsis": ("synopsis", "ldes"),
            "summary": ("summary",),
            "publisher": ("TPUB", "publisher"),
            "language": ("TLAN", "language"),
            "asin": ("ASIN", "asin", "----:com.apple.iTunes:asin"),
            "isbn": ("ISBN", "isbn"),
        }
        extracted: dict[str, str] = {}
        narrator = self._extract_narrator_metadata(tags)
        if narrator:
            extracted["narrator"] = narrator
        for normalized_key, keys in aliases.items():
            value = self._read_standard_text_frame(tags, keys)
            if not value:
                for key in keys:
                    value = self._read_txxx_frame(tags, key)
                    if value:
                        break
            if value:
                extracted[normalized_key] = value
        return extracted

    def _read_id3_txxx_frame(self, tags: Any, description: str) -> str:
        """Return an ID3 TXXX frame value by description without MP4 freeform aliases."""

        if not tags:
            return ""
        wanted = description.casefold()
        items = tags.items() if hasattr(tags, "items") else []
        for key, value in items:
            if str(key).casefold() == f"txxx:{wanted}":
                extracted = self._metadata_value(value)
                if extracted:
                    return extracted
            desc = getattr(value, "desc", "")
            if isinstance(desc, str) and desc.casefold() == wanted:
                extracted = self._metadata_value(getattr(value, "text", value))
                if extracted:
                    return extracted
        return ""

    def _read_mp4_freeform_tag(self, tags: Any, key: str) -> str:
        """Return a named MP4 freeform tag value by exact normalized key."""

        if not tags or not hasattr(tags, "get"):
            return ""
        return self._metadata_value(tags.get(key))

    def _extract_narrator_metadata(self, tags: Any) -> str:
        """Normalize audiobook narrator metadata using explicit priority rules."""

        txxx_narrator = self._read_id3_txxx_frame(tags, "NARRATOR")
        mp4_narrator = self._read_mp4_freeform_tag(tags, "----:com.apple.iTunes:narrator")
        composer = self._read_standard_text_frame(tags, ("TCOM", "\xa9wrt", "composer"))

        if txxx_narrator:
            if composer and txxx_narrator != composer:
                logging.warning(
                    "Conflicting narrator metadata: TXXX:NARRATOR=%r differs from TCOM=%r; using TXXX:NARRATOR",
                    txxx_narrator,
                    composer,
                )
            return txxx_narrator
        if mp4_narrator:
            return mp4_narrator
        return composer

    def _metadata_value(self, value: Any) -> str:
        """Normalize common Mutagen tag value containers into a single string."""

        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip().strip("\x00")
        if isinstance(value, (list, tuple)):
            for item in value:
                extracted = self._metadata_value(item)
                if extracted:
                    return extracted
            return ""
        text = getattr(value, "text", None)
        if text is not None:
            extracted = self._metadata_value(text)
            if extracted:
                return extracted
        return str(value).strip()

    def _parse_positive_int(self, value: str, field_name: str, errors: list[str]) -> int | None:
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            errors.append(f"Invalid {field_name} value; expected integer > 0.")
            return None
        if parsed <= 0:
            errors.append(f"Invalid {field_name} value; expected integer > 0.")
            return None
        return parsed

    def _parse_folder_target_bitrate(self, value: str, field_name: str, errors: list[str]) -> int | None:
        """Validate folder-book bitrate controls with the same range as single files."""

        parsed = self._parse_positive_int(value, field_name, errors)
        if parsed is None:
            return None
        if parsed < TARGET_BITRATE_MIN_KBPS or parsed > TARGET_BITRATE_MAX_KBPS:
            errors.append(
                f"Invalid {field_name} value: {parsed}; expected "
                f"{TARGET_BITRATE_MIN_KBPS}-{TARGET_BITRATE_MAX_KBPS} kbps."
            )
            return None
        return parsed

    def _normalize_channels(self, value: str, errors: list[str], field_name: str = "channels") -> int | None:
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if normalized in {"1", "mono", "m"}:
            return 1
        if normalized in {"2", "stereo", "s"}:
            return 2
        errors.append(f"Invalid {field_name} value; expected 1/mono/m or 2/stereo/s.")
        return None

    def _extract_single_file_metadata(self, path: Path) -> tuple[SingleFileMetadata | None, list[str]]:
        """Read single-file audiobook metadata and control tags with Mutagen."""

        try:
            audio_file = MutagenFile(path)
        except Exception as exc:
            logging.warning("Mutagen could not read single-file metadata for %s: %s", path, exc)
            return None, [f"Mutagen metadata read failed: {exc}"]
        if audio_file is None:
            return None, ["Mutagen could not identify audio file"]

        tags = getattr(audio_file, "tags", None)
        descriptive_tags = self._extract_audiobook_metadata_tags(tags)
        author = first_tag_value(descriptive_tags, ("artist", "albumartist", "author", "composer"))
        if not author:
            author = self._read_standard_text_frame(tags, ("TPE2", "aART", "albumartist", "album_artist"))
        author_inferred = not bool(author)
        if not author:
            author = "Unknown Author"

        album = first_tag_value(descriptive_tags, ("album", "title"))
        if not album:
            album = self._read_standard_text_frame(tags, ("TIT1", "\xa9grp", "grouping"))
        album_inferred = not bool(album)
        if not album:
            album = path.stem

        descriptive_tags.setdefault("author", author)
        descriptive_tags.setdefault("artist", author)
        descriptive_tags.setdefault("albumartist", author)
        descriptive_tags.setdefault("album", album)
        descriptive_tags.setdefault("title", album)

        asin = descriptive_tags.get("asin", "") or self._read_txxx_frame(tags, "ASIN")
        bitrate_value = self._read_txxx_frame(tags, "TARGET_BITRATE")
        channels_value = self._read_txxx_frame(tags, "TARGET_CHANNELS")
        dramatic_value = self._read_txxx_frame(tags, "DRAMATIC_AUDIO")

        errors: list[str] = []
        target_bitrate = self._parse_target_bitrate(bitrate_value, errors)
        target_channels = self._parse_target_channels(channels_value, errors)
        dramatic_audio = self._parse_optional_bool(dramatic_value, "DRAMATIC_AUDIO", errors)

        return SingleFileMetadata(
            author=author,
            album=album,
            tags=descriptive_tags,
            asin=asin,
            target_bitrate=target_bitrate,
            target_channels=target_channels,
            dramatic_audio=dramatic_audio,
            author_inferred=author_inferred,
            album_inferred=album_inferred,
            bitrate_missing=not bool(bitrate_value.strip()),
            channels_missing=not bool(channels_value.strip()),
            dramatic_missing=not bool(dramatic_value.strip()),
        ), errors

    def _parse_target_bitrate(self, value: str, errors: list[str]) -> int | None:
        if not value.strip():
            return None
        try:
            parsed = int(value.strip())
        except ValueError:
            errors.append(f"Invalid TARGET_BITRATE value: {value}")
            return None
        if parsed < TARGET_BITRATE_MIN_KBPS or parsed > TARGET_BITRATE_MAX_KBPS:
            errors.append(f"Invalid TARGET_BITRATE value: {value}")
            return None
        return parsed

    def _parse_target_channels(self, value: str, errors: list[str]) -> int | None:
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if normalized in {"1", "mono", "m"}:
            return 1
        if normalized in {"2", "stereo", "s"}:
            return 2
        errors.append(f"Invalid TARGET_CHANNELS value: {value}")
        return None

    def _parse_optional_bool(self, value: str, field_name: str, errors: list[str]) -> bool | None:
        normalized = value.strip().casefold()
        if not normalized:
            return None
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n"}:
            return False
        errors.append(f"Invalid {field_name} value: {value}")
        return None

    def _missing_required_metadata(self, metadata: FolderMetadata | None) -> list[str]:
        missing: list[str] = []
        if metadata is None or not metadata.title.strip():
            missing.append("title")
        if metadata is None or not metadata.author.strip():
            missing.append("author")
        if metadata is None or metadata.bitrate is None:
            missing.append("target_bitrate")
        return missing

    def _load_folder_metadata(self, folder_path: Path) -> tuple[FolderMetadata | None, list[str]]:
        candidates = [path for path in (folder_path / "metadata.yaml", folder_path / "metadata.yml") if path.exists()]
        if len(candidates) > 1:
            return None, ["Both metadata.yaml and metadata.yml are present; only one is allowed."]
        if not candidates:
            return None, []

        metadata_path = candidates[0]
        logging.info("Loading folder-book YAML metadata: %s", metadata_path)
        values: dict[str, str] = {}
        errors: list[str] = []
        for line_number, raw_line in enumerate(metadata_path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                errors.append(f"{metadata_path.name}:{line_number}: Expected 'key: value'.")
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip().strip('"\'')
            if key:
                values[key] = value
        if errors:
            return None, errors

        skip_value = values.get("skip", "false").casefold()
        if skip_value not in {"true", "false", "yes", "no", "1", "0", ""}:
            errors.append("Invalid skip value; expected boolean.")
        bitrate_value = values.get("bitrate", "").strip() or values.get("target_bitrate", "").strip()
        bitrate = self._parse_folder_target_bitrate(bitrate_value, "target_bitrate", errors)
        channels_value = values.get("channels", values.get("target_channels", ""))
        channels = self._normalize_channels(channels_value, errors)
        dramatic_value = values.get("dramatic_audio", values.get("DRAMATIC_AUDIO", ""))
        dramatic_audio = self._parse_optional_bool(dramatic_value, "DRAMATIC_AUDIO", errors)
        if errors:
            return None, errors

        descriptive = {key: values.get(key, "").strip() for key in YAML_DESCRIPTIVE_METADATA_KEYS if values.get(key, "").strip()}
        if values.get("title", "").strip():
            descriptive["title"] = values["title"].strip()
            descriptive["album"] = values["title"].strip()
        if values.get("author", "").strip():
            descriptive["author"] = values["author"].strip()
            descriptive["artist"] = values["author"].strip()
        return FolderMetadata(
            title=values.get("title", "").strip(),
            author=values.get("author", "").strip(),
            tags=build_output_tags(descriptive, values.get("author", ""), values.get("title", ""), dramatic_audio=dramatic_audio),
            skip=skip_value in {"true", "yes", "1"},
            bitrate=bitrate,
            channels=channels,
            dramatic_audio=dramatic_audio,
            title_inferred=not bool(values.get("title", "").strip()),
            author_inferred=not bool(values.get("author", "").strip()),
            bitrate_missing=not bool(bitrate_value),
            channels_missing=not bool(channels_value.strip()),
            dramatic_missing=not bool(dramatic_value.strip()),
        ), []

    def _optional_positive_int(self, values: dict[str, str], key: str, errors: list[str]) -> int | None:
        value = values.get(key, "").strip()
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            errors.append(f"Invalid {key} value; expected integer > 0.")
            return None
        if parsed <= 0:
            errors.append(f"Invalid {key} value; expected integer > 0.")
            return None
        return parsed

    def _optional_folder_target_bitrate(self, values: dict[str, str], key: str, errors: list[str]) -> int | None:
        parsed = self._optional_positive_int(values, key, errors)
        if parsed is None:
            return None
        if parsed < TARGET_BITRATE_MIN_KBPS or parsed > TARGET_BITRATE_MAX_KBPS:
            errors.append(
                f"Invalid {key} value: {parsed}; expected "
                f"{TARGET_BITRATE_MIN_KBPS}-{TARGET_BITRATE_MAX_KBPS} kbps."
            )
            return None
        return parsed

    def _discover_folder_audio_files(self, folder_path: Path) -> list[Path]:
        audio_paths: list[Path] = []
        for child in sorted(folder_path.iterdir()):
            if not child.is_file() or child.name == SKIPPED_MARKER or child.name in {"metadata.yaml", "metadata.yml"}:
                continue
            try:
                self.analyzer.probe(child)
            except ProbeError:
                logging.info("Ignoring non-audio direct child in folder-book %s: %s", folder_path, child)
                continue
            audio_paths.append(child)
        return audio_paths

    def _extract_track_number(self, info: AudioInfo) -> int | None:
        raw = info.metadata.get("track", "").strip()
        match = re.match(r"^(\d+)(?:\s*/\s*\d+)?$", raw)
        if not match:
            return None
        number = int(match.group(1))
        return number if number > 0 else None

    def _validate_track_numbers(self, tracks: list[FolderTrack]) -> list[str]:
        issues: list[str] = []
        seen: dict[int, Path] = {}
        for track in tracks:
            if track.number in seen:
                issues.append(f"{track.path.name}: Duplicate track number {track.number} (also {seen[track.number].name})")
            else:
                seen[track.number] = track.path
        numbers = sorted(seen)
        if numbers:
            expected = list(range(numbers[0], numbers[-1] + 1))
            if numbers != expected:
                missing = sorted(set(expected) - set(numbers))
                issues.append(f"Missing track number(s): {', '.join(str(number) for number in missing)}")
            if numbers[0] != 1:
                issues.append("Track numbers must start at 1.")
        return issues

    def _folder_source_info(self, folder_book: FolderBookPlan) -> AudioInfo:
        middle_info = folder_book.tracks[len(folder_book.tracks) // 2].info
        return AudioInfo(
            path=folder_book.folder_path,
            bitrate_bps=middle_info.bitrate_bps,
            channels=middle_info.channels,
            codec=middle_info.codec,
            duration_seconds=sum(track.info.duration_seconds for track in folder_book.tracks),
            chapter_count=len(folder_book.tracks),
            metadata=folder_book.conversion_plan.output_metadata or middle_info.metadata,
        )

    def _describe_folder_dry_run(self, folder_book: FolderBookPlan, source_info: AudioInfo) -> None:
        self._describe_dry_run(source_info, folder_book.conversion_plan)
        self.display.info("Would include tracks:")
        for track in folder_book.tracks:
            self.display.info(f"  {track.number}: {track.path.name} -> {track.title}")
        logging.info("Dry run folder-book plan: %s", folder_book)

    def _write_skipped_marker(self, folder_path: Path, reason: str, details: list[str]) -> None:
        if self.dry_run:
            logging.info("Dry run: would write %s for %s", SKIPPED_MARKER, folder_path)
            return
        lines = [f"Skipped: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "", f"Folder: {folder_path.name}", "", f"Reason: {reason}"]
        if details:
            lines.extend(["", "Problem files:", *details])
        (folder_path / SKIPPED_MARKER).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _skip_folder(self, folder_path: Path, reason: str, details: list[str]) -> None:
        self.stats.folder_books_skipped += 1
        self._write_skipped_marker(folder_path, reason, details)
        if any("Invalid" in detail for detail in details) or "Invalid" in reason:
            self.display.error(f"Invalid folder-book metadata for {folder_path.name}: {reason}")
            for detail in details:
                self.display.error(detail)
        self._skip(f"Skipped folder: {folder_path.name} ({reason})")
        logging.warning("Folder-book skipped: %s; reason=%s; details=%s", folder_path, reason, details)

    def _fail_folder(self, folder_path: Path, reason: str) -> None:
        self.stats.folder_books_failed += 1
        self._write_skipped_marker(folder_path, reason, [])
        self._fail(f"Failed folder: {folder_path.name} ({reason})")

    def _process_one_file(self, path: Path) -> None:
        """Run one complete file transaction and never let non-critical failures stop the batch."""

        plan: ConversionPlan | None = None
        self.stats.single_files_processed += 1
        try:
            self.display.info(f"Scanning: {path.name}", "scan")
            logging.info("Discovered file: %s", path)

            try:
                source_info = self.analyzer.probe(path)
                self._log_probe_result(path, source_info)
                single_metadata, metadata_errors = self._extract_single_file_metadata(path)
                if single_metadata is None:
                    self._skip(f"Skipped: {path.name} ({'; '.join(metadata_errors)})")
                    logging.warning("Skipping %s because Mutagen metadata could not be read: %s", path, metadata_errors)
                    return
                self._log_single_file_metadata(path, single_metadata)
                if metadata_errors:
                    for error in metadata_errors:
                        self.display.error(error)
                        logging.error("%s: %s", path, error)
                    self._skip(f"Skipped: invalid metadata control tag ({path.name})")
                    return

                source_info = AudioInfo(
                    path=source_info.path,
                    bitrate_bps=source_info.bitrate_bps,
                    channels=source_info.channels,
                    codec=source_info.codec,
                    duration_seconds=source_info.duration_seconds,
                    chapter_count=source_info.chapter_count,
                    metadata=single_metadata.as_detection_metadata(),
                    artwork_stream=source_info.artwork_stream,
                )
                source_asin = single_metadata.asin
                automatic_dramatic_match = None
                if single_metadata.dramatic_missing:
                    automatic_dramatic_match = detect_dramatic_audio(source_info)
                    dramatic_match = automatic_dramatic_match
                elif single_metadata.dramatic_audio is True:
                    dramatic_match = DramaticAudioMatch("DRAMATIC_AUDIO", "true", "explicit tag")
                else:
                    dramatic_match = None
                self._log_dramatic_audio_detection(path, dramatic_match)
            except ProbeError as exc:
                self._skip(f"Skipped: {path.name} ({exc})")
                logging.warning("Skipping unreadable or unsupported file %s: %s", path, exc)
                return

            plan = self.planner.create_plan(
                source_info,
                dramatic_match,
                target_bitrate_override=single_metadata.target_bitrate,
                target_channels_override=single_metadata.target_channels,
                output_metadata=single_metadata.as_output_tags(single_metadata.dramatic_audio is True or automatic_dramatic_match is not None),
                dramatic_audio_output=(single_metadata.dramatic_audio is True or automatic_dramatic_match is not None),
            )
            if plan is None:
                self._skip(
                    f"Skipped: bitrate below threshold ({source_info.normalized_bitrate_kbps} kbps normalized)"
                )
                logging.warning(
                    "Skipping %s because normalized bitrate is below threshold: raw=%s kbps normalized=%s kbps",
                    path,
                    source_info.bitrate_kbps,
                    source_info.normalized_bitrate_kbps,
                )
                return

            self._log_bitrate_decision(path, source_info, plan)

            if plan.final_path.exists():
                self._skip(f"Skipped: output already exists ({plan.final_path.name})")
                logging.warning("Skipping %s because output already exists: %s", path, plan.final_path)
                return

            if self.dry_run:
                self._describe_dry_run(source_info, plan)
                if source_asin:
                    self.display.info(f"Would preserve ASIN: {source_asin}")
                    logging.info("Dry run: would preserve ASIN for %s: %s", path, source_asin)
                self.cover_extractor.extract(source_info)
                self._skip(f"Dry run: planned conversion for {path.name}")
                return

            self.cover_extractor.extract(source_info)
            self._convert_validate_and_archive(source_info, plan, source_asin)
        except DiskSpaceError:
            if plan is not None:
                self._cleanup_temporary_output(plan)
            logging.critical("Stopping immediately because disk-space exhaustion was detected", exc_info=True)
            self.display.critical("Critical error: disk space exhausted. Stopping processing immediately.")
            raise
        except ForcedTermination:
            raise
        except Exception as exc:
            if plan is not None:
                self._cleanup_temporary_output(plan)
            self._fail(f"Failed: {path.name} ({exc})")
            logging.exception("File-level failure for %s; continuing with next file", path)
        finally:
            # A terminal state is reached only after logging, cleanup, counters,
            # and any conversion/archive transaction work are complete.
            self._mark_processed()

    def _log_probe_result(self, path: Path, source_info: AudioInfo) -> None:
        self.display.info(f"Detected bitrate: {source_info.bitrate_kbps} kbps")
        self.display.info(f"Normalized bitrate: {source_info.normalized_bitrate_kbps} kbps")
        logging.info(
            "Probe result for %s: raw_bitrate=%s kbps, normalized_bitrate=%s kbps, channels=%s, codec=%s, duration=%.2f, chapters=%s",
            path,
            source_info.bitrate_kbps,
            source_info.normalized_bitrate_kbps,
            source_info.channels,
            source_info.codec,
            source_info.duration_seconds,
            source_info.chapter_count,
        )

    def _log_dramatic_audio_detection(self, path: Path, match: DramaticAudioMatch | None) -> None:
        if match is None:
            logging.info("Dramatic audio not detected for %s", path)
            return
        logging.info(
            "Dramatic audio detected for %s from %s=%r using phrase %r",
            path,
            match.field,
            match.value,
            match.phrase,
        )
        self.display.info(f"Dramatic audio detected from {match.field}: {match.value}")

    def _log_single_file_metadata(self, path: Path, metadata: SingleFileMetadata) -> None:
        """Display and log Mutagen-derived metadata and control tag sources."""

        if metadata.author_inferred:
            self.display.warning(f"Author missing. Using fallback: {metadata.author}")
        else:
            self.display.info(f"Author: {metadata.author}")

        if metadata.album_inferred:
            self.display.warning(f"Album missing. Using filename: {metadata.album}")
        else:
            self.display.info(f"Album: {metadata.album}")

        self.display.info(f"ASIN: {metadata.asin or 'Not Present'}")
        preserved_fields = {
            key: value
            for key, value in metadata.tags.items()
            if key not in {"author", "artist", "albumartist", "album", "title"} and value
        }
        if preserved_fields:
            self.display.info(f"Preserving audiobook metadata fields: {', '.join(sorted(preserved_fields))}")
        logging.info("Audiobook-relevant source metadata used for %s: %s", path, metadata.tags)

        if metadata.bitrate_missing:
            self.display.warning("TARGET_BITRATE not present. Using automatic bitrate selection.")
            bitrate_source = "automatic"
        else:
            self.display.info(f"Target Bitrate Override: {metadata.target_bitrate} kbps")
            bitrate_source = f"override={metadata.target_bitrate} kbps"

        if metadata.channels_missing:
            self.display.warning("TARGET_CHANNELS not present. Using automatic channel selection.")
            channels_source = "automatic"
        else:
            self.display.info(f"Target Channels Override: {metadata.target_channels}")
            channels_source = f"override={metadata.target_channels}"

        if metadata.dramatic_missing:
            self.display.warning("DRAMATIC_AUDIO not present. Using automatic dramatic audio detection.")
            dramatic_status = "automatic detection"
        elif metadata.dramatic_audio:
            self.display.info("Dramatic Audio Status: true")
            dramatic_status = "explicit true"
        else:
            self.display.info("Dramatic Audio Status: false")
            dramatic_status = "explicit false"

        logging.info(
            "Single-file Mutagen metadata for %s: author=%r inferred=%s; album=%r inferred=%s; asin=%r; target_bitrate_source=%s; target_channels_source=%s; dramatic_audio_status=%s",
            path,
            metadata.author,
            metadata.author_inferred,
            metadata.album,
            metadata.album_inferred,
            metadata.asin or "Not Present",
            bitrate_source,
            channels_source,
            dramatic_status,
        )

    def _log_folder_metadata(self, path: Path, metadata: FolderMetadata, plan: ConversionPlan) -> None:
        """Display and log merged folder-book metadata and control tag sources."""

        if metadata.author_inferred:
            self.display.warning(f"Author missing. Using fallback: {metadata.author}")
        else:
            self.display.info(f"Author: {metadata.author}")

        if metadata.title_inferred:
            self.display.warning(f"Album missing. Using folder/name fallback: {metadata.title}")
        else:
            self.display.info(f"Album: {metadata.title}")

        self.display.info(f"ASIN: {metadata.asin or 'Not Present'}")
        preserved_fields = {
            key: value
            for key, value in metadata.tags.items()
            if key not in CORE_METADATA_LOG_KEYS and key not in CONVERSION_CONTROL_KEYS and value
        }
        if preserved_fields:
            self.display.info(f"Preserving audiobook metadata fields: {', '.join(sorted(preserved_fields))}")
        logging.info("Folder-book metadata used for %s: %s", path, metadata.tags)

        if metadata.bitrate_missing:
            self.display.warning("TARGET_BITRATE not present. Using automatic bitrate selection.")
            bitrate_source = "automatic"
        else:
            self.display.info(f"Target Bitrate Override: {metadata.bitrate} kbps")
            bitrate_source = f"override={metadata.bitrate} kbps"

        if metadata.channels_missing:
            self.display.warning("TARGET_CHANNELS not present. Using automatic channel selection.")
            channels_source = "automatic"
        else:
            self.display.info(f"Target Channels Override: {metadata.channels}")
            channels_source = f"override={metadata.channels}"

        if metadata.dramatic_missing:
            if plan.dramatic_audio_match is None:
                self.display.warning("DRAMATIC_AUDIO not present. Using automatic dramatic audio detection.")
                dramatic_status = "automatic detection; not detected"
            else:
                self.display.info(
                    f"Dramatic Audio Status: automatic true from {plan.dramatic_audio_match.field}: {plan.dramatic_audio_match.value}"
                )
                dramatic_status = f"automatic true from {plan.dramatic_audio_match.field}={plan.dramatic_audio_match.value!r}"
        elif metadata.dramatic_audio:
            self.display.info("Dramatic Audio Status: true")
            dramatic_status = "explicit true"
        else:
            self.display.info("Dramatic Audio Status: false")
            dramatic_status = "explicit false"

        logging.info(
            "Folder-book metadata for %s: author=%r inferred=%s; album=%r inferred=%s; asin=%r; target_bitrate_source=%s; target_channels_source=%s; dramatic_audio_status=%s",
            path,
            metadata.author,
            metadata.author_inferred,
            metadata.title,
            metadata.title_inferred,
            metadata.asin or "Not Present",
            bitrate_source,
            channels_source,
            dramatic_status,
        )

    def _log_bitrate_decision(self, path: Path, source_info: AudioInfo, plan: ConversionPlan) -> None:
        self.display.info(f"Output channels: {plan.output_channel_description} ({plan.output_channels})")
        self.display.info(f"Target bitrate: {plan.target_bitrate_kbps} kbps")
        logging.info(
            "Conversion decision for %s: raw=%s kbps, normalized=%s kbps, source_channels=%s, output_channels=%s, target=%s kbps",
            path,
            source_info.bitrate_kbps,
            source_info.normalized_bitrate_kbps,
            source_info.channels,
            plan.output_channels,
            plan.target_bitrate_kbps,
        )

    def _describe_dry_run(self, source_info: AudioInfo, plan: ConversionPlan) -> None:
        self.display.info(f"Would convert: {plan.source_path.name} -> {plan.final_path}", "convert")
        self.display.info(
            f"Would use codec {plan.codec} at {plan.target_bitrate_kbps} kbps "
            f"{plan.output_channel_description}"
        )
        self.display.info(
            f"Would validate duration, bitrate, {plan.output_channel_description} audio, "
            f"and {source_info.chapter_count} chapter(s)"
        )
        self.display.info(f"Would archive original to: {plan.archive_path}", "archive")
        logging.info("Dry run plan: %s", plan)

    def _convert_validate_and_archive(self, source_info: AudioInfo, plan: ConversionPlan, source_asin: str = "") -> None:
        self.display.info(f"Converting: {plan.final_path.name}", "convert")
        logging.info("Converting %s to temporary output %s", plan.source_path, plan.temporary_path)

        self.keyboard.register_temp_file(plan.temporary_path)
        try:
            self._cleanup_temporary_output(plan)
            command = self._ffmpeg_command(plan)
            result = run_external_command(command)
            if result.returncode != 0:
                self._cleanup_temporary_output(plan)
                if is_disk_space_error(result.stderr) or is_disk_space_error(result.stdout):
                    raise DiskSpaceError(
                        result.stderr.strip() or result.stdout.strip() or "ffmpeg reported disk-space exhaustion"
                    )
                self._fail("Failed: ffmpeg returned non-zero exit code")
                logging.error("FFmpeg failed for %s: %s", plan.source_path, result.stderr.strip())
                return

            logging.info("FFmpeg conversion completed for %s", plan.source_path)
            if not self.validator.validate(source_info, plan, plan.temporary_path):
                self._cleanup_temporary_output(plan)
                self._fail("Failed: validation failed")
                return

            try:
                self._promote_temporary_output(plan)
                logging.info("Promoted temporary output to final output: %s", plan.final_path)
            except OSError as exc:
                self._cleanup_temporary_output(plan)
                if is_disk_space_error(exc):
                    raise DiskSpaceError(str(exc)) from exc
                self._fail("Failed: could not promote temporary output")
                logging.exception("Could not promote %s to %s", plan.temporary_path, plan.final_path)
                return

            artwork_source = plan.input_paths[0] if plan.input_paths else plan.source_path
            cover_status = self.asin_metadata.preserve_cover_art(artwork_source, plan.final_path)
            if cover_status == "preserved":
                self.display.info("Embedded cover art preserved")
            elif cover_status == "absent":
                self.display.info("No embedded cover art present")
            else:
                self.display.warning("Embedded cover art failed to preserve; continuing")

            if plan.write_final_metadata:
                if not self.asin_metadata.write_and_verify_output_tags(
                    plan.final_path,
                    plan.output_metadata,
                    dramatic_audio=plan.dramatic_audio_output,
                ):
                    self._cleanup_final_output_after_metadata_failure(plan)
                    self._fail("Failed: Mutagen metadata normalization failed")
                    return
                self.display.info("Final metadata normalized with Mutagen")
                if source_asin:
                    self.display.info(f"Preserved ASIN: {source_asin}")
            elif source_asin:
                if not self.asin_metadata.write_and_verify_output_asin(plan.final_path, source_asin):
                    self._cleanup_final_output_after_metadata_failure(plan)
                    self._fail("Failed: ASIN metadata preservation failed")
                    return
                self.display.info(f"Preserved ASIN: {source_asin}")

            if plan.input_paths:
                original_size = sum(input_path.stat().st_size for input_path in plan.input_paths)
            else:
                original_size = plan.source_path.stat().st_size
            converted_size = plan.final_path.stat().st_size

            try:
                self._archive_original(plan)
            except OSError as exc:
                if is_disk_space_error(exc):
                    raise DiskSpaceError(str(exc)) from exc
                self._fail("Failed: could not archive original after conversion")
                logging.exception("Could not archive original %s to %s", plan.source_path, plan.archive_path)
                return

            self.stats.converted += 1
            if plan.input_paths:
                self.stats.folder_books_converted += 1
            else:
                self.stats.single_files_converted += 1
            self.stats.bytes_original += original_size
            self.stats.bytes_after_conversion += converted_size
            self.display.success("Conversion successful")
            self.display.info("Archived original", "archive")
            logging.info("Conversion and archive successful for %s", plan.source_path)
        finally:
            try:
                plan.temporary_path.with_suffix(".ffmetadata").unlink(missing_ok=True)
            except OSError:
                logging.exception("Failed to clean folder metadata temporary file for %s", plan.temporary_path)
            self.keyboard.unregister_temp_file(plan.temporary_path)

    def _promote_temporary_output(self, plan: ConversionPlan) -> None:
        """Move the validated temporary file into place without overwriting.

        Temporary outputs are expected to be created directly in the configured
        target directory alongside their final output names.  The duplicate
        output check immediately before promotion preserves no-overwrite
        behavior even though os.replace itself would replace an existing file.
        """

        target_dir = self.config.target_dir.resolve()
        temporary_parent = plan.temporary_path.parent.resolve()
        final_parent = plan.final_path.parent.resolve()
        paths_share_target_dir = (
            temporary_parent == target_dir and final_parent == target_dir
        )
        if not paths_share_target_dir:
            raise OSError(
                errno.EINVAL,
                "temporary and final outputs must both be in the configured target directory",
                str(plan.temporary_path),
            )

        if plan.final_path.exists():
            raise FileExistsError(
                errno.EEXIST,
                "refusing to overwrite existing output",
                str(plan.final_path),
            )

        try:
            os.replace(plan.temporary_path, plan.final_path)
            logging.info(
                "Promoted temporary output using os.replace: %s -> %s",
                plan.temporary_path,
                plan.final_path,
            )
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            logging.warning(
                "os.replace reported a cross-device promotion for %s -> %s; falling back to shutil.move",
                plan.temporary_path,
                plan.final_path,
            )
            shutil.move(plan.temporary_path, plan.final_path)

    def _ffmpeg_command(self, plan: ConversionPlan) -> list[str]:
        if plan.input_paths:
            metadata_path = self._write_folder_ffmetadata(plan)
            command = ["ffmpeg", "-hide_banner", "-y", "-i", str(metadata_path)]
            for input_path in plan.input_paths:
                command.extend(["-i", str(input_path)])
            if len(plan.input_paths) == 1:
                command.extend(["-map", "1:a:0"])
            else:
                concat_inputs = "".join(f"[{index}:a:0]" for index in range(1, len(plan.input_paths) + 1))
                command.extend([
                    "-filter_complex",
                    f"{concat_inputs}concat=n={len(plan.input_paths)}:v=0:a=1[a]",
                    "-map",
                    "[a]",
                ])
            command.extend([
                "-map_metadata",
                "0",
                "-map_chapters",
                "0",
                "-vn",
                "-ac",
                str(plan.output_channels),
                "-c:a",
                plan.codec,
                "-b:a",
                f"{plan.target_bitrate_kbps}k",
                "-f",
                "mp4",
                str(plan.temporary_path),
            ])
            return command

        return [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            str(plan.source_path),
            "-map",
            "0:a:0",
            "-map_metadata",
            "0",
            "-map_chapters",
            "0",
            "-vn",
            "-ac",
            str(plan.output_channels),
            "-c:a",
            plan.codec,
            "-b:a",
            f"{plan.target_bitrate_kbps}k",
            "-f",
            "mp4",
            str(plan.temporary_path),
        ]

    def _write_folder_ffmetadata(self, plan: ConversionPlan) -> Path:
        metadata_path = plan.temporary_path.with_suffix(".ffmetadata")
        lines = [";FFMETADATA1"]
        for key, value in plan.output_metadata.items():
            if value:
                lines.append(f"{key}={self._escape_ffmetadata(value)}")
        start_ms = 0
        durations: list[int] = []
        for input_path in plan.input_paths:
            try:
                durations.append(round(self.analyzer.probe(input_path).duration_seconds * 1000))
            except ProbeError:
                durations.append(0)
        for title, duration_ms in zip(plan.chapter_titles, durations):
            end_ms = start_ms + max(duration_ms, 1)
            lines.extend([
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={self._escape_ffmetadata(title)}",
            ])
            start_ms = end_ms
        metadata_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return metadata_path

    def _escape_ffmetadata(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("\n", " ").replace("=", "\\=").replace(";", "\\;").replace("#", "\\#")

    def _archive_original(self, plan: ConversionPlan) -> None:
        if plan.archive_path.exists():
            raise FileExistsError(f"Archive destination already exists: {plan.archive_path}")
        plan.archive_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(plan.effective_archive_source_path), str(plan.archive_path))
        logging.info("Archived original to %s", plan.archive_path)

    def _cleanup_final_output_after_metadata_failure(self, plan: ConversionPlan) -> None:
        try:
            plan.final_path.unlink(missing_ok=True)
            logging.info("Cleaned final output after ASIN metadata failure: %s", plan.final_path)
        except OSError as exc:
            if is_disk_space_error(exc):
                raise DiskSpaceError(str(exc)) from exc
            logging.exception("Failed to clean final output after ASIN metadata failure: %s", plan.final_path)

    def _cleanup_temporary_output(self, plan: ConversionPlan) -> None:
        try:
            plan.temporary_path.unlink(missing_ok=True)
            plan.temporary_path.with_suffix(".ffmetadata").unlink(missing_ok=True)
        except OSError as exc:
            if is_disk_space_error(exc):
                raise DiskSpaceError(str(exc)) from exc
            logging.exception("Failed to clean temporary output %s", plan.temporary_path)

    def _skip(self, message: str) -> None:
        self.stats.skipped += 1
        self.display.warning(message)

    def _fail(self, message: str) -> None:
        self.stats.failed += 1
        self.display.error(message)

    def _mark_processed(self) -> None:
        self.stats.processed += 1
        self._display_progress()

    def _display_progress(self) -> None:
        self.display.info(
            "Progress:\n"
            f"{self.stats.processed}/{self.stats.scanned} top-level books processed | "
            f"{self.stats.remaining} remaining | "
            f"{self.stats.converted} converted | "
            f"{self.stats.skipped} skipped | "
            f"{self.stats.failed} failed",
            "summary",
        )
        logging.info(
            "Progress: %s/%s processed; %s remaining; %s converted; %s skipped; %s failed",
            self.stats.processed,
            self.stats.scanned,
            self.stats.remaining,
            self.stats.converted,
            self.stats.skipped,
            self.stats.failed,
        )

    def _handle_between_file_controls(self) -> bool:
        """Honor pause and quit requests only between completed file transactions."""

        if self.keyboard.pause_requested:
            self.display.warning("Pause requested.\nPress Enter to continue processing...")
            logging.info("Processing paused after current file transaction")
            with self.keyboard.prompt_section():
                input()
            self.keyboard.clear_pause()
            logging.info("Processing resumed after pause")

        if self.keyboard.quit_requested:
            self.display.warning("Quit requested.\nDo you want to stop processing now? [y/N]:")
            logging.info("Prompting for graceful quit confirmation")
            with self.keyboard.prompt_section():
                response = input().strip().casefold()
            if response == "y":
                logging.info("User confirmed graceful quit")
                return True
            logging.info("User declined graceful quit with response: %r", response)
            self.keyboard.clear_quit()
        return False

def choose_codec(analyzer: FFmpegAnalyzer, config: AppConfig, display: ConsoleDisplay) -> str:
    """Select the configured encoder, falling back only when necessary."""

    encoders = analyzer.available_audio_encoders()
    if config.preferred_codec in encoders:
        logging.info("Using configured codec: %s", config.preferred_codec)
        return config.preferred_codec

    warning = f"Configured codec {config.preferred_codec!r} is unavailable; trying fallback {config.fallback_codec!r}"
    display.warning(warning)
    logging.warning(warning)

    if config.fallback_codec in encoders:
        logging.info("Using fallback codec: %s", config.fallback_codec)
        return config.fallback_codec

    raise ConfigError(
        f"Neither configured codec {config.preferred_codec!r} nor fallback codec "
        f"{config.fallback_codec!r} is available in FFmpeg"
    )
