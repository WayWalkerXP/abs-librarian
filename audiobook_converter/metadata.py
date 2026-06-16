"""Metadata normalization, priority, and dramatic-audio helpers."""
from __future__ import annotations

import re
from typing import Any

from .constants import CONVERSION_CONTROL_KEYS, DRAMATIC_AUDIO_PHRASES
from .models import AudioInfo, DramaticAudioMatch

def first_tag_value(tags: dict[str, str], keys: tuple[str, ...]) -> str:
    """Return the first non-empty normalized tag value for any key."""

    for key in keys:
        value = tags.get(key, "").strip()
        if value:
            return value
    return ""

def build_output_tags(
    descriptive_tags: dict[str, str],
    fallback_author: str,
    fallback_album: str,
    overrides: dict[str, str] | None = None,
    dramatic_audio: bool | None = None,
) -> dict[str, str]:
    """Build normalized final audiobook tags shared by single files and folder books."""

    tags = {key: str(value).strip() for key, value in descriptive_tags.items() if str(value).strip()}
    if overrides:
        for key, value in overrides.items():
            normalized_key = "albumartist" if key == "album_artist" else key
            text = str(value).strip()
            if text:
                tags[normalized_key] = text

    for control_key in CONVERSION_CONTROL_KEYS | {"TARGET_BITRATE", "TARGET_CHANNELS"}:
        tags.pop(control_key, None)
        tags.pop(control_key.casefold(), None)

    author = first_tag_value(tags, ("author", "artist", "albumartist", "album_artist", "composer")) or fallback_author.strip()
    tags.pop("composer", None)
    album = first_tag_value(tags, ("album", "title")) or fallback_album.strip()
    if author:
        tags.setdefault("author", author)
        tags.setdefault("artist", author)
        tags.setdefault("albumartist", author)
    if album:
        tags.setdefault("album", album)
        tags.setdefault("title", album)
    if dramatic_audio is True:
        tags["dramatic_audio"] = "true"
    else:
        tags.pop("dramatic_audio", None)
    return tags

def normalize_match_text(value: str) -> str:
    """Normalize free text before phrase matching."""

    cleaned = re.sub(r"[_\W]+", " ", value.casefold(), flags=re.UNICODE)
    return " ".join(cleaned.split())

def detect_dramatic_audio(source_info: AudioInfo) -> DramaticAudioMatch | None:
    """Detect GraphicAudio-style or full-cast dramatic productions."""

    checks: list[tuple[str, str]] = [(key, value) for key, value in source_info.metadata.items() if value]
    checks.append(("filename", source_info.path.name))
    normalized_phrases = [(phrase, normalize_match_text(phrase)) for phrase in DRAMATIC_AUDIO_PHRASES]

    for field_name, original_value in checks:
        normalized_value = normalize_match_text(original_value)
        compact_value = normalized_value.replace(" ", "")
        for original_phrase, normalized_phrase in normalized_phrases:
            compact_phrase = normalized_phrase.replace(" ", "")
            if normalized_phrase in normalized_value or compact_phrase in compact_value:
                return DramaticAudioMatch(field=field_name, value=original_value, phrase=original_phrase)
    return None
