import pathlib
import tempfile
import unittest

from plugins.vmomo_music import plugin as vmomo_plugin


class _DummyFile:
    def __init__(self, name=None, ext=None, mime_type=None):
        self.name = name
        self.ext = ext
        self.mime_type = mime_type


class _DummyMessage:
    def __init__(self, message_id: int, file_obj):
        self.id = message_id
        self.file = file_obj


class VmomoMusicSafetyTests(unittest.TestCase):
    def test_safe_media_destination_sanitizes_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = pathlib.Path(tmp)
            message = _DummyMessage(10, _DummyFile(name='song.mp3', ext='.mp3', mime_type='audio/mpeg'))

            destination = vmomo_plugin._safe_media_destination(output_dir, message, '../evil.mp3')

            self.assertEqual(destination.parent, output_dir.resolve())
            self.assertEqual(destination.name, 'evil.mp3')

    def test_safe_media_destination_uses_fallback_when_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = pathlib.Path(tmp)
            message = _DummyMessage(42, _DummyFile(name='..', ext='.mp3', mime_type='audio/mpeg'))

            destination = vmomo_plugin._safe_media_destination(output_dir, message, None)

            self.assertEqual(destination.parent, output_dir.resolve())
            self.assertEqual(destination.name, '42.mp3')


if __name__ == '__main__':
    unittest.main()
