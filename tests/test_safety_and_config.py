import pathlib
import tempfile
import unittest

from core.actions import _safe_destination, _safe_output_name
from core.config import ConfigError, load_config, resolve_profile


class SafetyAndConfigTests(unittest.TestCase):
    def test_load_config_rejects_non_mapping_task_item(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = pathlib.Path(tmp) / 'config_invalid_tasks.yaml'
            config_path.write_text(
                '\n'.join(
                    [
                        'profiles:',
                        '  work:',
                        '    api_id: 123',
                        '    api_hash: hash',
                        '    phone_number: "+10000000000"',
                        'tasks:',
                        '  - action_type: send',
                        '  - broken_item',
                    ]
                ),
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ConfigError, r'tasks\[2\]'):
                load_config(str(config_path))

    def test_resolve_profile_rejects_invalid_api_id(self):
        config = {
            'profiles': {
                'work': {
                    'api_id': None,
                    'api_hash': 'hash',
                    'phone_number': '+10000000000',
                }
            }
        }

        with self.assertRaisesRegex(ConfigError, r"invalid 'api_id'"):
            resolve_profile(config, 'work')

    def test_safe_destination_blocks_parent_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp) / 'downloads'
            base.mkdir(parents=True, exist_ok=True)

            safe_name = _safe_output_name('../evil.mp3', fallback='fallback.mp3')
            self.assertEqual(safe_name, 'evil.mp3')

            safe_path = _safe_destination(base, safe_name)
            self.assertEqual(safe_path.parent, base.resolve())

            with self.assertRaises(ValueError):
                _safe_destination(base, '../evil.mp3')


if __name__ == '__main__':
    unittest.main()
