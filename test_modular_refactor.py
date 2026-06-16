import configparser
from pathlib import Path

from audiobook_converter.config import ConfigManager
from audiobook_converter.ffmpeg import build_ffmpeg_command
from audiobook_converter.metadata import build_output_tags, detect_dramatic_audio
from audiobook_converter.models import AudioInfo
from audiobook_converter.validation import validate_target_bitrate, validate_target_channels
from audiobook_converter.conversion import ConversionPlanner


def write_config(path: Path, source: Path, target: Path, converted: Path) -> None:
    parser = configparser.ConfigParser()
    parser["paths"] = {"source_dir": str(source), "target_dir": str(target), "converted_dir": str(converted)}
    parser["encoding"] = {"max_bitrate": "64", "codec": "libfdk_aac", "fallback_codec": "aac"}
    parser["general"] = {"log_file": str(path.parent / "converter.log")}
    parser["display"] = {"use_color": "true", "use_emoji": "true"}
    parser["artwork"] = {"extract_cover": "false"}
    with path.open("w") as handle:
        parser.write(handle)


def test_config_loading_defaults(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    converted = tmp_path / "converted"
    config_path = tmp_path / "audiobook_converter.ini"
    write_config(config_path, source, target, converted)

    config = ConfigManager(config_path).load()

    assert config.source_dir == source.resolve()
    assert config.target_dir == target.resolve()
    assert config.converted_dir == converted.resolve()
    assert config.max_bitrate_kbps == 64
    assert config.run_history_csv.name == "audiobook_converter_runs.csv"


def test_bitrate_validation_boundaries():
    assert validate_target_bitrate(25)
    assert validate_target_bitrate(384)
    assert not validate_target_bitrate(24)
    assert not validate_target_bitrate(385)
    assert not validate_target_bitrate(None)


def test_channel_validation():
    assert validate_target_channels(1)
    assert validate_target_channels(2)
    assert not validate_target_channels(0)
    assert not validate_target_channels(6)
    assert not validate_target_channels(None)


def test_metadata_priority_and_control_tag_filtering():
    tags = build_output_tags(
        {"composer": "Jane Author", "title": "Book", "TARGET_BITRATE": "128", "target_channels": "2"},
        fallback_author="",
        fallback_album="",
        overrides={"album_artist": "Override Author", "asin": "B012345678"},
        dramatic_audio=True,
    )

    assert tags["author"] == "Override Author"
    assert tags["albumartist"] == "Override Author"
    assert tags["asin"] == "B012345678"
    assert tags["dramatic_audio"] == "true"
    assert "composer" not in tags
    assert "TARGET_BITRATE" not in tags
    assert "target_channels" not in tags


def test_dramatic_audio_detection_from_metadata_and_filename():
    info = AudioInfo(
        path=Path("/books/ordinary.m4b"),
        bitrate_bps=128000,
        channels=2,
        codec="aac",
        duration_seconds=60,
        chapter_count=1,
        metadata={"publisher": "GraphicAudio"},
    )

    match = detect_dramatic_audio(info)

    assert match is not None
    assert match.field == "publisher"
    assert match.phrase == "graphicaudio"


def test_output_path_helper_behavior(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    converted = tmp_path / "converted"
    config_path = tmp_path / "audiobook_converter.ini"
    write_config(config_path, source, target, converted)
    config = ConfigManager(config_path).load()
    source_file = source / "Original.mp3"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_bytes(b"")
    info = AudioInfo(
        path=source_file,
        bitrate_bps=128000,
        channels=1,
        codec="mp3",
        duration_seconds=60,
        chapter_count=0,
        metadata={"artist": "A:Author", "title": "T/Title"},
    )

    plan = ConversionPlanner(config, "aac").create_plan(info)

    assert plan is not None
    assert plan.final_path == target / "A Author - T Title.m4b"
    assert plan.archive_path == converted / "Original.mp3"


def test_ffmpeg_command_construction():
    command = build_ffmpeg_command(Path("input.mp3"), Path("output.m4b"), "aac", 64, 1)

    assert command == [
        "ffmpeg", "-hide_banner", "-y", "-i", "input.mp3",
        "-map", "0", "-c:a", "aac", "-b:a", "64k", "-ac", "1",
        "-c:v", "copy", "-map_chapters", "0", "output.m4b",
    ]
