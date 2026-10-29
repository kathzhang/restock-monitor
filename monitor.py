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
CART_URL = 'https://www.vancleefarpels.com/us/en/secure/checkout/shopping-bag.html'
PRODUCT_SKU = 'VCARD35600'


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise ValueError('Missing environment variable: ' + name)
    return value


def bark_enabled():
    """VCA-only runtime switch; email-only unless explicitly enabled."""
    value = os.environ.get('VCA_BARK_ENABLED', 'false').strip().lower()
    if value not in ('true', 'false'):
        raise ValueError('VCA_BARK_ENABLED must be true or false')
    return value == 'true'


def auto_cart_enabled():
    value = os.environ.get('VCA_AUTO_ADD_TO_BAG', 'false').strip().lower()
    if value not in ('true', 'false'):
        raise ValueError('VCA_AUTO_ADD_TO_BAG must be true or false')
    return value == 'true'


def attempt_add_to_bag(page):
    """One bounded add attempt; never click checkout, retry clicks, or export cookies."""
    result = {'status': 'FAILED', 'sku': PRODUCT_SKU, 'scope': 'temporary-cloud-session'}
    cart_item = 'li.base-js-sb-product-item[data-sku="' + PRODUCT_SKU + '"]'
    try:
        result['stage'] = 'verify_product'
        # Guard against wrong-product redirects and stale page state.
        page.get_by_text(PRODUCT_SKU, exact=True).wait_for(state='visible', timeout=3000)
        if not page.url.startswith(PRODUCT_URL):
            raise RuntimeError('Unexpected product page')
        # A new cloud session may show consent over the add button. Only reject
        # optional cookies; do not accept all or force a click through an overlay.
        for name in ('ALLOW TECHNICAL COOKIES', 'Reject All', 'Reject all', 'Reject all cookies', 'Continue without accepting'):
            reject = page.get_by_text(name, exact=True)
            if reject.count() == 1 and reject.is_visible():
                reject.click(timeout=2000)
                break
        result['stage'] = 'find_button'
        buttons = page.get_by_role('button', name=re.compile(r'^\s*ADD\s+TO\s+BAG\s*$', re.I))
        actionable = None
        for index in range(buttons.count()):
            candidate = buttons.nth(index)
            if candidate.is_visible() and candidate.is_enabled() and candidate.evaluate('''el => {
                for (let n = el; n instanceof Element; n = n.parentElement) {
                    const s = getComputedStyle(n);
                    if (Number(s.opacity) === 0 || s.contentVisibility === 'hidden') return false;
                }
                return true;
            }'''):
                actionable = candidate
                break
        if actionable is None:
            raise RuntimeError('No actionable add button')
        # Existing mini-bag SKU means verify the bag rather than increase quantity.
        existing = page.locator('li.vca-smm-item[data-sku="' + PRODUCT_SKU + '"]').count() > 0
        if not existing:
            result['stage'] = 'click_add'
            actionable.click(timeout=4000, no_wait_after=True)
            # Wait for visible confirmation from the actual mini-bag, not generic text.
            result['stage'] = 'wait_mini_bag'
            page.locator('li.vca-smm-item[data-sku="' + PRODUCT_SKU + '"]').wait_for(
                state='attached', timeout=6000)
        result['stage'] = 'verify_cart'
        response = page.goto(CART_URL, wait_until='domcontentloaded', timeout=10000)
        if response is None or response.status >= 400:
            raise RuntimeError('Cart page HTTP error')
        page.locator(cart_item).wait_for(state='visible', timeout=5000)
        result['status'] = 'ALREADY_IN_BAG' if existing else 'ADDED'
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    ARTIFACTS.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(ARTIFACTS / 'cart-result.png'), full_page=True, timeout=5000)
    except Exception:
        pass
    (ARTIFACTS / 'cart-result.json').write_text(json.dumps(result), encoding='utf-8')
    print('Cloud cart result: ' + json.dumps(result), flush=True)
    return result


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


def detect_stock(timeout=45, on_in_stock=None):
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
                    if state == 'IN_STOCK' and on_in_stock is not None:
                        on_in_stock(page)
                    return state
                page.wait_for_timeout(500)
            raise RuntimeError('Neither stock button is visible')
        except Exception:
            save_screenshot(page)
            raise
        finally:
            browser.close()


def notify_stock(cart_result=None):
    stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
    title = '【补货提醒】VCA VCARD35600 — ADD TO BAG 可见'
    body = f'{PRODUCT_NAME}\n检测时间（UTC）：{stamp}\nADD TO BAG 按钮可见，请打开网页核实并购买。\n{PRODUCT_URL}'
    if cart_result is not None:
        labels = {'ADDED': '已在云端临时会话加入购物车并核对商品编号',
                  'ALREADY_IN_BAG': '云端购物车已有该商品，未重复添加',
                  'FAILED': '云端加购未能确认成功，请自行打开商品页购买'}
        body += '\n\n加购结果：' + labels.get(cart_result['status'], '未知')
        body += ('\n购物车入口：' + CART_URL +
                 '\n注意：这是 GitHub 临时浏览器的独立购物车，不与手机或 Chrome 同步。'
                 '普通链接不会携带云端购物车；任务结束后该会话不保留。'
                 '加入购物车不代表锁定库存；未结账、未付款。')
    failed = False
    channels = [('Gmail', send_email)]
    if bark_enabled():
        channels.append(('Bark', send_bark))
    else:
        print('Bark: disabled by VCA_BARK_ENABLED', flush=True)
    # Start both transports immediately; one slow service cannot delay the other.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(sender, title, body): name
                   for name, sender in channels}
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
            if not bark_enabled():
                print('Bark test skipped: VCA_BARK_ENABLED is false')
                return 0
            send_bark('【测试】VCA 重要警报', '这是响铃测试，不代表补货。')
            print('Test push accepted by Bark')
            return 0
        cart_result = None
        def add_to_cart(page):
            nonlocal cart_result
            try:
                cart_result = attempt_add_to_bag(page)
            except Exception as exc:
                # Diagnostic write failure must not suppress the stock email.
                cart_result = {'status': 'FAILED', 'error_type': type(exc).__name__}
        state = detect_stock(on_in_stock=add_to_cart if auto_cart_enabled() else None)
        print('Stock state: ' + state, flush=True)
        if state == 'IN_STOCK':
            return notify_stock(cart_result)
        return 0
    except Exception as exc:
        # Never dump SMTP, HTTP exception text or credentials into Actions logs.
        print('Monitor failed: ' + type(exc).__name__, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
