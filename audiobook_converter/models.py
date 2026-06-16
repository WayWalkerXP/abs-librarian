"""Dataclasses used by converter planning and execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

@dataclass(frozen=True)
class AppConfig:
    """Validated application configuration loaded from the INI file."""

    source_dir: Path
    target_dir: Path
    converted_dir: Path
    max_bitrate_kbps: int
    preferred_codec: str
    fallback_codec: str
    log_file: Path
    use_color: bool
    use_emoji: bool
    extract_cover: bool
    cover_dir: Path | None
    run_history_csv: Path

@dataclass(frozen=True)
class ArtworkStream:
    """Embedded image stream selected for optional sidecar cover extraction."""

    index: int
    extension: str
    disposition: str

@dataclass(frozen=True)
class DramaticAudioMatch:
    """Details explaining why a source was classified as dramatic audio."""

    field: str
    value: str
    phrase: str

@dataclass(frozen=True)
class AudioInfo:
    """Relevant ffprobe data for a source or output audiobook file."""

    path: Path
    bitrate_bps: int
    channels: int
    codec: str
    duration_seconds: float
    chapter_count: int
    metadata: dict[str, str] = field(default_factory=dict)
    artwork_stream: ArtworkStream | None = None

    @property
    def bitrate_kbps(self) -> int:
        """Return the raw bitrate rounded to the nearest whole kilobit per second."""

        return round(self.bitrate_bps / 1000)

    @property
    def normalized_bitrate_kbps(self) -> int:
        """Return the detected bitrate normalized to the nearest 8 kbps increment."""

        return round(self.bitrate_kbps / 8) * 8

@dataclass(frozen=True)
class SingleFileMetadata:
    """Normalized audiobook metadata and conversion controls for one single-file audiobook."""

    author: str
    album: str
    tags: dict[str, str] = field(default_factory=dict)
    asin: str = ""
    target_bitrate: int | None = None
    target_channels: int | None = None
    dramatic_audio: bool | None = None
    author_inferred: bool = False
    album_inferred: bool = False
    bitrate_missing: bool = True
    channels_missing: bool = True
    dramatic_missing: bool = True

    def as_detection_metadata(self) -> dict[str, str]:
        metadata = dict(self.tags)
        metadata.setdefault("artist", self.author)
        metadata.setdefault("album_artist", self.author)
        metadata.setdefault("author", self.author)
        metadata.setdefault("album", self.album)
        metadata.setdefault("title", self.album)
        if self.asin:
            metadata["asin"] = self.asin
        if self.dramatic_audio is not None:
            metadata["dramatic_audio"] = "true" if self.dramatic_audio else "false"
        return metadata

    def as_output_tags(self, dramatic_audio_output: bool | None = None) -> dict[str, str]:
        from .metadata import build_output_tags
        return build_output_tags(
            self.tags,
            fallback_author=self.author,
            fallback_album=self.album,
            overrides={"asin": self.asin} if self.asin else None,
            dramatic_audio=dramatic_audio_output,
        )

@dataclass(frozen=True)
class FolderMetadata:
    """Validated folder-book metadata from representative audio tags and optional YAML."""

    title: str
    author: str
    tags: dict[str, str] = field(default_factory=dict)
    skip: bool = False
    bitrate: int | None = None
    channels: int | None = None
    dramatic_audio: bool | None = None
    title_inferred: bool = False
    author_inferred: bool = False
    bitrate_missing: bool = True
    channels_missing: bool = True
    dramatic_missing: bool = True

    @property
    def asin(self) -> str:
        return self.tags.get("asin", "")

    def as_detection_metadata(self) -> dict[str, str]:
        from .metadata import build_output_tags
        tags = build_output_tags(self.tags, self.author, self.title, dramatic_audio=self.dramatic_audio)
        if self.dramatic_audio is False:
            tags["dramatic_audio"] = "false"
        return tags

    def as_output_tags(self, dramatic_audio_output: bool | None = None) -> dict[str, str]:
        from .metadata import build_output_tags
        return build_output_tags(self.tags, self.author, self.title, dramatic_audio=dramatic_audio_output)

@dataclass(frozen=True)
class FolderTrack:
    """One direct-child audio file in a folder-book with normalized track metadata."""

    path: Path
    info: AudioInfo
    number: int
    title: str

@dataclass(frozen=True)
class ConversionPlan:
    """All derived decisions needed to convert one source file."""

    source_path: Path
    final_path: Path
    temporary_path: Path
    archive_path: Path
    target_bitrate_kbps: int
    output_channels: int
    codec: str
    dramatic_audio_match: DramaticAudioMatch | None = None
    archive_source_path: Path | None = None
    input_paths: tuple[Path, ...] = ()
    chapter_titles: tuple[str, ...] = ()
    output_metadata: dict[str, str] = field(default_factory=dict)
    write_final_metadata: bool = False
    dramatic_audio_output: bool = False

    @property
    def effective_archive_source_path(self) -> Path:
        """Return the source file or folder that should be archived after conversion."""

        return self.archive_source_path or self.source_path

    @property
    def output_channel_description(self) -> str:
        """Return a human-readable output channel layout."""

        return "mono" if self.output_channels == 1 else "stereo"

@dataclass(frozen=True)
class FolderBookPlan:
    """Validated folder-book inputs and the conversion plan for the folder transaction."""

    folder_path: Path
    tracks: tuple[FolderTrack, ...]
    conversion_plan: ConversionPlan
    metadata: FolderMetadata | None = None

@dataclass
class ProcessingStats:
    """Counters displayed in progress updates and the final summary."""

    scanned: int = 0
    processed: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    single_files_processed: int = 0
    folder_books_processed: int = 0
    single_files_converted: int = 0
    folder_books_converted: int = 0
    folder_books_skipped: int = 0
    folder_books_failed: int = 0
    bytes_original: int = 0
    bytes_after_conversion: int = 0

    @property
    def remaining(self) -> int:
        """Return the number of discovered top-level books/items that have not reached a terminal state."""

        return max(self.scanned - self.processed, 0)
