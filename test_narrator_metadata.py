import contextlib
import io
import logging
import unittest

from audiobook_converter import AudiobookConverter, ForcedTermination, KeyboardController, build_output_tags


class TextFrame:
    def __init__(self, text, desc=""):
        self.text = text
        self.desc = desc


class NarratorMetadataTests(unittest.TestCase):
    def setUp(self):
        self.converter = AudiobookConverter.__new__(AudiobookConverter)

    def test_txxx_narrator_wins_over_matching_composer(self):
        tags = {"TXXX:NARRATOR": ["Jane Doe"], "TCOM": ["Jane Doe"]}

        extracted = self.converter._extract_audiobook_metadata_tags(tags)

        self.assertEqual(extracted, {"narrator": "Jane Doe"})

    def test_txxx_narrator_wins_over_conflicting_composer_and_warns(self):
        tags = {"TXXX:NARRATOR": ["Jane Doe"], "TCOM": ["John Composer"]}

        with self.assertLogs(level=logging.WARNING) as log:
            extracted = self.converter._extract_audiobook_metadata_tags(tags)

        self.assertEqual(extracted, {"narrator": "Jane Doe"})
        self.assertIn("Conflicting narrator metadata", "\n".join(log.output))

    def test_mp4_narrator_freeform_wins_before_composer(self):
        tags = {"----:com.apple.iTunes:narrator": [b"Jane Doe"], "TCOM": ["John Composer"]}

        extracted = self.converter._extract_audiobook_metadata_tags(tags)

        self.assertEqual(extracted, {"narrator": "Jane Doe"})

    def test_composer_falls_back_to_canonical_narrator_only(self):
        tags = {"TCOM": ["Jane Doe"]}

        extracted = self.converter._extract_audiobook_metadata_tags(tags)

        self.assertEqual(extracted, {"narrator": "Jane Doe"})
        self.assertNotIn("composer", extracted)

    def test_output_tags_drop_composer_after_using_author_fallback(self):
        output = build_output_tags({"composer": "Jane Doe", "title": "Sample"}, "", "")

        self.assertEqual(output["author"], "Jane Doe")
        self.assertNotIn("composer", output)


class KeyboardControllerFeedbackTests(unittest.TestCase):
    def test_pause_request_prints_immediate_feedback_once(self):
        controller = KeyboardController()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            controller.request_pause()
            controller.request_pause()

        self.assertEqual(
            output.getvalue(),
            "⚠️ Pause requested.\n"
            "Current book will finish processing before pausing.\n",
        )

    def test_quit_request_prints_immediate_feedback_once(self):
        controller = KeyboardController()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            controller.request_quit("keyboard")
            controller.best_effort_cleanup = lambda: None
            with self.assertRaises(ForcedTermination):
                controller.request_quit("Ctrl+C")

        self.assertEqual(
            output.getvalue(),
            "⚠️ Quit requested.\n"
            "Current book will finish processing before prompting for exit.\n",
        )


if __name__ == "__main__":
    unittest.main()
