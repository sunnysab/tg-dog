import unittest

from plugins.random_daily_sender import plugin as random_daily_plugin
from plugins.vmomo_music import plugin as vmomo_plugin
from plugins.webhook_listener import plugin as webhook_plugin


class PluginArgDefaultTests(unittest.TestCase):
    def test_vmomo_parse_defaults(self):
        parsed = vmomo_plugin._parse_args(['--query', 'hello'])
        self.assertEqual(parsed.target, vmomo_plugin.DEFAULT_TARGET)
        self.assertEqual(parsed.choice, vmomo_plugin.DEFAULT_CHOICE)
        self.assertEqual(parsed.timeout, vmomo_plugin.DEFAULT_TIMEOUT)
        self.assertEqual(parsed.max_wait, vmomo_plugin.DEFAULT_MAX_WAIT)
        self.assertEqual(parsed.max_pages, vmomo_plugin.DEFAULT_MAX_PAGES)
        self.assertEqual(parsed.output, vmomo_plugin.DEFAULT_OUTPUT)
        self.assertIsNone(parsed.keyword)
        self.assertFalse(parsed.list_only)
        self.assertIsNone(parsed.filename)

        options = vmomo_plugin._options_from_namespace(parsed)
        self.assertEqual(options.query, 'hello')
        self.assertEqual(options.timeout, vmomo_plugin.DEFAULT_TIMEOUT)

    def test_random_daily_parse_defaults(self):
        parsed = random_daily_plugin._parse_args(['--target', '@bot', '--text', '/sign'])
        self.assertEqual(parsed.window, random_daily_plugin.DEFAULT_WINDOW)
        self.assertEqual(parsed.min_interval_hours, random_daily_plugin.DEFAULT_MIN_INTERVAL_HOURS)
        self.assertEqual(parsed.expect_timeout, random_daily_plugin.DEFAULT_EXPECT_TIMEOUT)
        self.assertEqual(parsed.state, random_daily_plugin.DEFAULT_STATE_PATH)
        self.assertIsNone(parsed.expect_text)
        self.assertIsNone(parsed.expect_keyword)

        options = random_daily_plugin._options_from_namespace(parsed)
        self.assertEqual(options.target, '@bot')
        self.assertEqual(options.text, '/sign')

    def test_webhook_parse_defaults(self):
        parsed = webhook_plugin._parse_args(['--target', '@chat', '--url', 'https://example.com'])
        self.assertEqual(parsed.method, 'POST')
        self.assertEqual(parsed.timeout, 10)
        self.assertEqual(parsed.retry, 2)
        self.assertEqual(parsed.retry_delay, 1.0)
        self.assertEqual(parsed.header, [])


if __name__ == '__main__':
    unittest.main()
