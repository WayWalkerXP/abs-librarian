"""FFmpeg/ffprobe command helpers."""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import ACTIVE_EXTERNAL_PROCESSES, EXTERNAL_PROCESS_LOCK, METADATA_KEYS
from .errors import ProbeError
from .models import ArtworkStream, AudioInfo

@dataclass(frozen=True)
class CommandResult:
    """Decoded subprocess result that is safe for unexpected byte sequences."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str

def run_external_command(command: list[str]) -> CommandResult:
    """Run an external command and decode captured output without UnicodeDecodeError.

    FFmpeg and ffprobe sometimes emit bytes that are not valid UTF-8.  Capturing
    bytes and decoding with replacement keeps a bad diagnostic line from ending
    the whole batch.  POSIX children run in a separate session so the first
    Ctrl+C can request a graceful quit without interrupting the active file
    transaction.
    """

    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=(os.name != "nt"),
    )
    with EXTERNAL_PROCESS_LOCK:
        ACTIVE_EXTERNAL_PROCESSES.add(process)
    try:
        stdout_bytes, stderr_bytes = process.communicate()
    except BaseException:
        terminate_external_process(process)
        raise
    finally:
        with EXTERNAL_PROCESS_LOCK:
            ACTIVE_EXTERNAL_PROCESSES.discard(process)

    stdout_text = stdout_bytes.decode("utf-8", errors="replace") if stdout_bytes else ""
    stderr_text = stderr_bytes.decode("utf-8", errors="replace") if stderr_bytes else ""
    return CommandResult(command, process.returncode, stdout_text, stderr_text)

def terminate_external_process(process: subprocess.Popen[bytes]) -> None:
    """Best-effort termination for an in-flight external command."""

    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except Exception:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except Exception:
            logging.exception("Failed to kill external process: %s", process.args)

def terminate_active_external_processes() -> None:
    """Best-effort termination for all external commands known to be running."""

    with EXTERNAL_PROCESS_LOCK:
        processes = tuple(ACTIVE_EXTERNAL_PROCESSES)
    for process in processes:
        terminate_external_process(process)

class FFmpegAnalyzer:
    """Wrapper around ffprobe and FFmpeg capability checks."""

    def available_audio_encoders(self) -> set[str]:
        """Return the set of audio encoder names reported by FFmpeg."""

        result = run_external_command(["ffmpeg", "-hide_banner", "-encoders"])
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg -encoders failed: {result.stderr.strip()}")

        encoders: set[str] = set()
        for line in result.stdout.splitlines():
            # Encoder rows look like: " A..... aac                  AAC ...".
            stripped = line.strip()
            if not stripped or len(stripped) < 8:
                continue
            flags = stripped.split(maxsplit=1)[0]
            if flags.startswith("A") and len(stripped.split()) >= 2:
                encoders.add(stripped.split()[1])
        return encoders

    def probe(self, path: Path) -> AudioInfo:
        """Analyze a file with ffprobe and return normalized audio information."""

        command = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            "-show_chapters",
            str(path),
        ]
        result = run_external_command(command)
        if result.returncode != 0:
            raise ProbeError(result.stderr.strip() or "ffprobe failed")

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProbeError("ffprobe returned invalid JSON") from exc

        audio_stream = self._primary_audio_stream(data)
        if audio_stream is None:
            raise ProbeError("ffprobe found no audio stream")

        bitrate_bps = self._extract_bitrate(data, audio_stream)
        if bitrate_bps is None or bitrate_bps <= 0:
            raise ProbeError("audio bitrate could not be determined")

        channels = self._safe_int(audio_stream.get("channels"), default=0)
        if channels <= 0:
            raise ProbeError("channel count could not be determined")

        duration_seconds = self._extract_duration(data, audio_stream)
        if duration_seconds <= 0:
            raise ProbeError("duration could not be determined")

        return AudioInfo(
            path=path,
            bitrate_bps=bitrate_bps,
            channels=channels,
            codec=str(audio_stream.get("codec_name", "unknown")),
            duration_seconds=duration_seconds,
            chapter_count=len(data.get("chapters", [])),
            metadata=self._extract_metadata(data, audio_stream),
            artwork_stream=self._select_artwork_stream(data),
        )

    def _primary_audio_stream(self, data: dict[str, Any]) -> dict[str, Any] | None:
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                return stream
        return None

    def _extract_bitrate(self, data: dict[str, Any], audio_stream: dict[str, Any]) -> int | None:
        for value in (audio_stream.get("bit_rate"), data.get("format", {}).get("bit_rate")):
            bitrate = self._safe_int(value, default=0)
            if bitrate > 0:
                return bitrate
        return None

    def _extract_duration(self, data: dict[str, Any], audio_stream: dict[str, Any]) -> float:
        for value in (audio_stream.get("duration"), data.get("format", {}).get("duration")):
            try:
                duration = float(value)
            except (TypeError, ValueError):
                continue
            if duration > 0:
                return duration
        return 0.0

    def _extract_metadata(self, data: dict[str, Any], audio_stream: dict[str, Any]) -> dict[str, str]:
        metadata: dict[str, str] = {}
        combined_tags: dict[str, Any] = {}
        combined_tags.update(audio_stream.get("tags", {}))
        combined_tags.update(data.get("format", {}).get("tags", {}))

        casefolded_tags = {str(key).casefold(): str(value).strip() for key, value in combined_tags.items()}
        for key in METADATA_KEYS:
            value = casefolded_tags.get(key.casefold(), "")
            if value:
                metadata[key] = value
        return metadata

    def _select_artwork_stream(self, data: dict[str, Any]) -> ArtworkStream | None:
        """Return the preferred embedded cover stream, if ffprobe reported one."""

        candidates: list[tuple[int, ArtworkStream]] = []
        for stream in data.get("streams", []):
            if stream.get("codec_type") != "video":
                continue
            disposition = stream.get("disposition", {}) or {}
            tags = {str(key).casefold(): str(value).casefold() for key, value in stream.get("tags", {}).items()}
            attached_pic = self._safe_int(disposition.get("attached_pic"), default=0) == 1
            title = tags.get("title", "")
            comment = tags.get("comment", "")
            if not attached_pic and "cover" not in title and "cover" not in comment:
                continue

            index = self._safe_int(stream.get("index"), default=-1)
            if index < 0:
                continue
            extension = self._artwork_extension(str(stream.get("codec_name", "")))
            disposition_name = "front cover" if "front" in comment or "front" in title else "attached picture"
            priority = 0 if "front" in comment or "front" in title else 1
            candidates.append((priority, ArtworkStream(index=index, extension=extension, disposition=disposition_name)))

        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1].index))
        return candidates[0][1]

    def _artwork_extension(self, codec_name: str) -> str:
        """Map common embedded image codecs to sidecar filename extensions."""

        normalized = codec_name.casefold()
        if normalized in {"png", "apng"}:
            return "png"
        if normalized in {"mjpeg", "jpeg", "jpg"}:
            return "jpg"
        return "jpg"

    def _safe_int(self, value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


def build_ffmpeg_command(input_path: Path, output_path: Path, codec: str, bitrate_kbps: int, channels: int) -> list[str]:
    """Build the single-file conversion command used by the converter."""
    return [
        "ffmpeg", "-hide_banner", "-y", "-i", str(input_path),
        "-map", "0", "-c:a", codec, "-b:a", f"{bitrate_kbps}k",
        "-ac", str(channels), "-c:v", "copy", "-map_chapters", "0",
        str(output_path),
    ]
