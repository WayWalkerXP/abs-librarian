"""Shared constants for the audiobook converter."""
from __future__ import annotations

import subprocess
import threading

CONFIG_FILE = "audiobook_converter.ini"
RUN_HISTORY_CSV = "audiobook_converter_runs.csv"
LOCK_FILE = "audiobook_converter.lock"
EXTERNAL_PROCESS_LOCK = threading.Lock()
ACTIVE_EXTERNAL_PROCESSES: set[subprocess.Popen[bytes]] = set()
METADATA_KEYS = ("artist", "album_artist", "albumartist", "author", "composer", "title", "subtitle", "album", "track", "asin", "isbn", "narrator", "series", "series-part", "series_sequence", "sequence", "genre", "date", "year", "description", "comment", "synopsis", "summary", "publisher", "language", "dramatic_audio")
ASIN_MP4_FREEFORM_KEY = "----:com.apple.iTunes:asin"
DRAMATIC_AUDIO_MP4_FREEFORM_KEY = "----:com.apple.iTunes:DRAMATIC_AUDIO"
CANONICAL_METADATA_VARIANT_KEYS = (
    "\xa9ART",
    "----:com.apple.iTunes:author",
    "aART",
    "----:com.apple.iTunes:albumartist",
    "----:com.apple.iTunes:album_artist",
    "----:com.apple.iTunes:narrator",
    "----:com.apple.iTunes:series",
    "----:com.apple.iTunes:series-part",
    "----:com.apple.iTunes:series_sequence",
    "----:com.apple.iTunes:sequence",
    "----:com.apple.iTunes:publisher",
    "----:com.apple.iTunes:language",
    ASIN_MP4_FREEFORM_KEY,
)
TARGET_BITRATE_MIN_KBPS = 25
TARGET_BITRATE_MAX_KBPS = 384
DRAMATIC_AUDIO_PHRASES = ("graphicaudio", "graphic audio", "dramatic audio", "audio drama", "full cast")
INVALID_FILENAME_CHARS = '<>:"/\\|?*\0'
IGNORED_FOLDER_NAMES = {".git", "__pycache__", "tmp", "temp", "$recycle.bin", "system volume information", "output", "outputs", "archive", "converted"}
SKIPPED_MARKER = "__skipped__.txt"
DESCRIPTIVE_METADATA_KEYS = ("author", "artist", "albumartist", "album_artist", "title", "subtitle", "album", "asin", "isbn", "narrator", "series", "series-part", "series_sequence", "sequence", "genre", "date", "year", "description", "comment", "synopsis", "summary", "publisher", "language", "dramatic_audio")
CORE_METADATA_LOG_KEYS = {"author", "artist", "albumartist", "album_artist", "album", "title", "asin"}
CONVERSION_CONTROL_KEYS = {"target_bitrate", "target_channels", "bitrate", "channels"}
YAML_DESCRIPTIVE_METADATA_KEYS = ("narrator", "asin", "isbn", "series", "series-part", "series_sequence", "sequence", "genre", "date", "year", "description", "comment", "synopsis", "summary", "publisher", "language", "subtitle", "albumartist", "album_artist")
ALLOWED_CHANNELS = (1, 2)
CSV_FIELD_NAMES = ("started_at", "elapsed", "scanned", "processed", "converted", "skipped", "failed", "bytes_original", "bytes_after_conversion", "space_saved_bytes", "space_saved_percent")
