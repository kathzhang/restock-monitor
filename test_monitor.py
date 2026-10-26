"""Offline browser fixtures + mocked notification transports. No live notifications."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from playwright.sync_api import sync_playwright
import monitor


class VisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.page = self.browser.new_page()

    def tearDown(self):
        self.page.close()

    def state(self, html):
        self.page.set_content(html)
        return monitor.read_state(self.page)

    def test_hidden_add_visible_phone(self):
        self.assertEqual(self.state('<button style="display:none">ADD TO BAG</button>'
                                    '<button>ORDER BY PHONE</button>'), 'OUT_OF_STOCK')

    def test_visible_add_hidden_phone(self):
        self.assertEqual(self.state('<button>ADD TO BAG</button>'
                                    '<button style="visibility:hidden">ORDER BY PHONE</button>'), 'IN_STOCK')

    def test_hidden_first_duplicate(self):
        self.assertEqual(self.state('<button hidden>ADD TO BAG</button>'
                                    '<button>ADD TO BAG</button>'), 'IN_STOCK')

    def test_both_visible_add_wins(self):
        self.assertEqual(self.state('<button>ADD TO BAG</button><button>ORDER BY PHONE</button>'), 'IN_STOCK')

    def test_both_hidden_unknown(self):
        self.assertEqual(self.state('<div style="display:none"><button>ADD TO BAG</button>'
                                    '<button>ORDER BY PHONE</button></div>'), 'UNKNOWN')

    def test_text_alone_is_not_button(self):
        self.assertEqual(self.state('<div>ADD TO BAG</div><script>"ORDER BY PHONE"</script>'), 'UNKNOWN')

    def test_opacity_zero_ancestor(self):
        self.assertEqual(self.state('<div style="opacity:0"><button>ADD TO BAG</button></div>'
                                    '<a href="#">ORDER BY PHONE</a>'), 'OUT_OF_STOCK')

    def test_disabled_visible_add_counts(self):
        self.assertEqual(self.state('<button disabled>ADD TO BAG</button>'), 'IN_STOCK')

    def test_case_whitespace_and_link(self):
        self.assertEqual(self.state('<a href="#"> add <span>to</span> bag </a>'), 'IN_STOCK')

    def test_detection_unknown_saves_real_png(self):
        # Exercise real detect_stock and screenshot without any outbound website request.
        original = self.browser.new_context
        def context_factory(**kwargs):
            ctx = original(**kwargs)
            ctx.route('**/*', lambda route: route.fulfill(status=200, body='<h1>Blocked</h1>'))
            return ctx
        fake_browser = MagicMock()
        fake_browser.new_context.side_effect = context_factory
        fake_pw = MagicMock()
        fake_pw.chromium.launch.return_value = fake_browser
        manager = MagicMock()
        manager.__enter__.return_value = fake_pw
        # The initial 8s wait is skipped, timeout=0 goes directly to the error screenshot.
        from playwright.sync_api import Page
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(monitor, 'ARTIFACTS', Path(tmp)), \
             patch('playwright.sync_api.sync_playwright', return_value=manager), \
             patch.object(Page, 'wait_for_timeout'):
            with self.assertRaises(RuntimeError):
                monitor.detect_stock(timeout=0)
            self.assertEqual((Path(tmp) / 'failure.png').read_bytes()[:8], b'\x89PNG\r\n\x1a\n')



class NotificationTests(unittest.TestCase):
    def test_bark_payload(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"code":200}'
        with patch.dict(os.environ, {'BARK_KEY': 'fake-test-key'}), \
             patch.object(monitor, 'urlopen', return_value=response) as request:
            monitor.send_bark('test', 'body')
        req = request.call_args.args[0]
        payload = json.loads(req.data)
        self.assertEqual(req.full_url, 'https://api.day.app/push')
        self.assertEqual(payload['level'], 'critical')
        self.assertEqual(payload['call'], '1')
        self.assertEqual(payload['device_key'], 'fake-test-key')

    def test_email_uses_app_password_and_recipient(self):
        smtp = MagicMock()
        with patch.dict(os.environ, {'GMAIL_USER': 'sender@example.com',
                                     'GMAIL_APP_PASSWORD': 'abcd efgh ijkl mnop',
                                     'EMAIL_TO': 'recipient@example.com'}), \
             patch.object(monitor.smtplib, 'SMTP_SSL', return_value=smtp):
            monitor.send_email('title', 'body')
        client = smtp.__enter__.return_value
        client.login.assert_called_once_with('sender@example.com', 'abcdefghijklmnop')
        self.assertEqual(client.send_message.call_args.args[0]['To'], 'recipient@example.com')

    def test_email_test_no_browser_or_bark(self):
        with patch.object(monitor, 'send_email') as email, \
             patch.object(monitor, 'detect_stock') as detect, \
             patch.object(monitor, 'send_bark') as bark:
            self.assertEqual(monitor.main(['--test-email']), 0)
            email.assert_called_once()
            detect.assert_not_called()
            bark.assert_not_called()

    def test_bark_failure_still_sends_email(self):
        with patch.object(monitor, 'send_bark', side_effect=RuntimeError), \
             patch.object(monitor, 'send_email') as email:
            self.assertEqual(monitor.notify_stock(), 1)
            email.assert_called_once()

    def test_email_failure_does_not_hide_bark(self):
        with patch.object(monitor, 'send_email', side_effect=RuntimeError), \
             patch.object(monitor, 'send_bark') as bark:
            self.assertEqual(monitor.notify_stock(), 1)
            bark.assert_called_once()

    def test_unknown_returns_exit_one(self):
        with patch.object(monitor, 'detect_stock', side_effect=RuntimeError), \
             patch.object(monitor, 'notify_stock') as notify:
            self.assertEqual(monitor.main([]), 1)
            notify.assert_not_called()

    def test_no_stock_does_not_notify(self):
        with patch.object(monitor, 'detect_stock', return_value='OUT_OF_STOCK'), \
             patch.object(monitor, 'notify_stock') as notify:
            self.assertEqual(monitor.main([]), 0)
            notify.assert_not_called()


if __name__ == '__main__':
    unittest.main()
