import unittest

from core.plugins import get_plugin_cli_help


class PluginHelpTests(unittest.TestCase):
    def test_plugin_help_for_typer_plugin(self):
        help_text = get_plugin_cli_help('vmomo_music')
        self.assertIn('Usage:', help_text)
        self.assertIn('--help', help_text)

    def test_plugin_help_for_runner_only_plugin(self):
        help_text = get_plugin_cli_help('echo')
        self.assertIn('does not expose a Typer CLI', help_text)
        self.assertIn('run/main', help_text)


if __name__ == '__main__':
    unittest.main()
