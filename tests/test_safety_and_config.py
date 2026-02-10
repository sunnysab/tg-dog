import os
import pathlib
import tempfile
import unittest

from core.actions import _safe_destination, _safe_output_name
from core.config import ConfigError, load_config, resolve_profile
from core.ipc import is_socket_owner_only


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

    def test_load_config_rejects_non_string_daemon_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = pathlib.Path(tmp) / 'config_invalid_token.yaml'
            config_path.write_text(
                '\n'.join(
                    [
                        'daemon_token: 12345',
                        'profiles:',
                        '  work:',
                        '    api_id: 123',
                        '    api_hash: hash',
                        '    phone_number: "+10000000000"',
                    ]
                ),
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ConfigError, r"'daemon_token' must be a string"):
                load_config(str(config_path))

    def test_is_socket_owner_only_checks_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            socket_path = pathlib.Path(tmp) / 'daemon.sock'
            socket_path.write_text('', encoding='utf-8')

            os.chmod(socket_path, 0o600)
            self.assertTrue(is_socket_owner_only(str(socket_path)))

            os.chmod(socket_path, 0o644)
            self.assertFalse(is_socket_owner_only(str(socket_path)))


if __name__ == '__main__':
    unittest.main()
