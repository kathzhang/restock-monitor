#!/usr/bin/env python3
"""Single-run monitor. Credentials are supplied by GitHub Actions secrets via env."""
import argparse
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from email.message import EmailMessage
from urllib.request import Request, urlopen

PRODUCT_URL = 'https://www.vancleefarpels.com/us/en/collections/jewelry/alhambra/vcard35600---vintage-alhambra-bracelet-5-motifs.html'
PRODUCT_NAME = 'Van Cleef & Arpels Vintage Alhambra bracelet, 5 motifs — VCARD35600'
ARTIFACTS = Path('artifacts')


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError('Missing environment variable: ' + name)
    return value


def send_email(title, body):
    sender = required('GMAIL_USER')
    password = required('GMAIL_APP_PASSWORD').replace(' ', '')
    recipient = required('EMAIL_TO')
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = title
    msg.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30,
                          context=ssl.create_default_context()) as smtp:
        smtp.login(sender, password)
        smtp.send_message(msg)


def send_bark(title, body):
    # JSON POST is equivalent to URL query parameters; the key never enters the URL/log.
    payload = {
        'device_key': required('BARK_KEY'),
        'title': title,
        'body': body,
        'level': 'critical',
        'call': '1',
        'volume': '10',
        'sound': 'alarm',
        'group': 'VCA-restock',
        'url': PRODUCT_URL,
    }
    request = Request('https://api.day.app/push',
                      data=json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    if result.get('code') != 200:
        # Do not print response bodies, which might contain private data.
        raise RuntimeError('Bark rejected the push')


def button_visible(page, label):
    """Check ALL matching buttons/links; hidden first duplicates must not mask later ones."""
    pattern = re.compile(r'^\s*' + r'\s+'.join(map(re.escape, label.split())) + r'\s*$', re.I)
    for role in ('button', 'link'):
        candidates = page.get_by_role(role, name=pattern, include_hidden=True)
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            if not candidate.is_visible():
                continue
            # Playwright considers opacity:0 visible; explicitly exclude transparent ancestors.
            if candidate.evaluate('''el => {
                for (let n = el; n instanceof Element; n = n.parentElement) {
                    const s = getComputedStyle(n);
                    if (Number(s.opacity) === 0 || s.contentVisibility === 'hidden') return false;
                }
                return true;
            }'''):
                return True
    return False


def read_state(page):
    # ADD TO BAG takes priority even if both buttons are visible or it is disabled.
    if button_visible(page, 'ADD TO BAG'):
        return 'IN_STOCK'
    if button_visible(page, 'ORDER BY PHONE'):
        return 'OUT_OF_STOCK'
    return 'UNKNOWN'


def save_screenshot(page):
    ARTIFACTS.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(ARTIFACTS / 'failure.png'), full_page=True, timeout=15000)
        print('Screenshot: artifacts/failure.png', flush=True)
    except Exception as exc:
        print('Screenshot failed: ' + type(exc).__name__, flush=True)


def detect_stock(timeout=45):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale='en-US', timezone_id='America/New_York',
                                      viewport={'width': 1440, 'height': 1100})
        page = context.new_page()
        try:
            response = page.goto(PRODUCT_URL, wait_until='domcontentloaded', timeout=60000)
            if response is None or response.status >= 400:
                raise RuntimeError('Product page HTTP error')
            # Observe stability during the existing hydration grace period, rather
            # than waiting eight seconds before starting the stability check.
            started = time.monotonic()
            deadline = started + timeout
            previous = None
            stable_since = time.monotonic()
            while time.monotonic() < deadline:
                state = read_state(page)
                if state != previous:
                    previous, stable_since = state, time.monotonic()
                if (state != 'UNKNOWN' and time.monotonic() - started >= 8
                        and time.monotonic() - stable_since >= 3):
                    print('Page check seconds: {:.3f}'.format(time.monotonic() - started), flush=True)
                    return state
                page.wait_for_timeout(500)
            raise RuntimeError('Neither stock button is visible')
        except Exception:
            save_screenshot(page)
            raise
        finally:
            browser.close()


def notify_stock():
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    title = '【补货提醒】VCA VCARD35600 — ADD TO BAG 可见'
    body = f'{PRODUCT_NAME}\n检测时间（UTC）：{stamp}\nADD TO BAG 按钮可见，请打开网页核实并购买。\n{PRODUCT_URL}'
    failed = False
    # Start both transports immediately; one slow service cannot delay the other.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(sender, title, body): name
                   for name, sender in [('Bark', send_bark), ('Gmail', send_email)]}
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
                print(name + ': accepted by service', flush=True)
            except Exception as exc:
                failed = True
                print(name + ': failed (' + type(exc).__name__ + ')', flush=True)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--test-email', action='store_true', help='Send only a test email; no browser or Bark')
    modes.add_argument('--test-bark', action='store_true', help='Send a critical Bark test; it may ring loudly')
    args = parser.parse_args(argv)
    try:
        if args.test_email:
            send_email('【测试】VCA 补货监控邮件', '邮件通道测试成功。这不是补货通知。\n' + PRODUCT_URL)
            print('Test email accepted by Gmail')
            return 0
        if args.test_bark:
            send_bark('【测试】VCA 重要警报', '这是响铃测试，不代表补货。')
            print('Test push accepted by Bark')
            return 0
        state = detect_stock()
        print('Stock state: ' + state, flush=True)
        if state == 'IN_STOCK':
            return notify_stock()
        return 0
    except Exception as exc:
        # Never dump SMTP, HTTP exception text or credentials into Actions logs.
        print('Monitor failed: ' + type(exc).__name__, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
