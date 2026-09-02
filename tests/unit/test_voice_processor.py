import unittest
from amancore.voice.processor import VoiceNoteProcessor

class TestVoiceNoteProcessor(unittest.TestCase):
    def setUp(self):
        self.processor = VoiceNoteProcessor()

    def test_transcribe_empty_bytes(self):
        res = self.processor.transcribe(b"")
        self.assertEqual(res, "")

    def test_transcribe_missing_file(self):
        res = self.processor.transcribe_file("/non/existent/audio.ogg")
        self.assertEqual(res, "")

if __name__ == "__main__":
    unittest.main()
