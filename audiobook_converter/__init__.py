"""Audiobook converter package."""

from .cli import main
from .config import AppConfig, ConfigManager
from .conversion import AudiobookConverter, ConversionPlanner, choose_codec
from .errors import ConfigError, ForcedTermination
from .ffmpeg import FFmpegAnalyzer
from .filesystem import sanitize_filename
from .metadata import build_output_tags, detect_dramatic_audio, first_tag_value
from .models import AudioInfo, ConversionPlan, DramaticAudioMatch, FolderBookPlan, FolderMetadata, FolderTrack, ProcessingStats, SingleFileMetadata
from .prompts import KeyboardController

__all__ = [
    "AppConfig",
    "AudioInfo",
    "AudiobookConverter",
    "ConfigError",
    "ConfigManager",
    "ConversionPlan",
    "ConversionPlanner",
    "DramaticAudioMatch",
    "FFmpegAnalyzer",
    "FolderBookPlan",
    "FolderMetadata",
    "FolderTrack",
    "ForcedTermination",
    "KeyboardController",
    "ProcessingStats",
    "SingleFileMetadata",
    "build_output_tags",
    "choose_codec",
    "detect_dramatic_audio",
    "first_tag_value",
    "main",
    "sanitize_filename",
]
