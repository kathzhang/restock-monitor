#!/usr/bin/env python3
"""Apple pickup check for 11201, nearest 12 returned stores, 512GB Star White, carrier later."""
import argparse
from datetime import datetime
from email.message import EmailMessage
import html
import json
import math
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
from urllib.parse import urlparse, urljoin, parse_qsl, urlencode, urlunparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PRODUCT_URL = 'https://www.apple.com/shop/buy-iphone/iphone-duo/7.6-inch-display-512gb-star-white-unlocked'
PRODUCT_NAME = 'iPhone Duo 512GB Star White'
EXPECTED_PART = 'MK1G4LL/A'
ZIP_CODE = '11201'
MAX_STORES = 12
ARTIFACTS = Path('artifacts/iphone')


class CheckError(RuntimeError):
    pass


def required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise CheckError('Missing GitHub Secret: ' + name)
    return value


def send_email(title, body):
    user, recipient = required('GMAIL_USER'), required('EMAIL_TO')
    password = ''.join(required('GMAIL_APP_PASSWORD').split())
    for name, value in [('GMAIL_USER', user), ('EMAIL_TO', recipient), ('GMAIL_APP_PASSWORD', password)]:
        if not value.isascii():
            raise CheckError(name + ' must contain ASCII characters only')
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = user, recipient, title
    msg.set_content(body)
    with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def send_bark(title, body):
    payload = {'device_key': required('BARK_KEY'), 'title': title, 'body': body,
               'level': 'critical', 'call': '1', 'volume': '10', 'sound': 'alarm',
               'group': 'iPhone-pickup', 'url': PRODUCT_URL}
    request = Request('https://api.day.app/push', data=json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json'}, method='POST')
    with urlopen(request, timeout=30) as response:
        if json.load(response).get('code') != 200:
            raise CheckError('Bark rejected push')


def clean_text(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(value or ''))).split())


def distance_miles(store):
    # Explicit units only: never assume a bare number is miles.
    text = clean_text(store.get('storeDistanceWithUnit'))
    match = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*(mi|miles?|km|kilometers?|kilometres?)\.?', text, re.I)
    if not match:
        raise CheckError('Missing or unrecognized store distance unit')
    value = float(match.group(1))
    if not math.isfinite(value):
        raise CheckError('Invalid store distance')
    return value / 1.609344 if match.group(2).lower().startswith(('km', 'kilo')) else value


def parse_pickup(data, part=EXPECTED_PART):
    """Strict parser: service errors/empty response/unknown fields never mean no stock."""
    if not isinstance(data, dict):
        raise CheckError('Pickup response is not an object')
    head = data.get('head', {})
    if not isinstance(head, dict) or head.get('status', 200) not in (200, '200'):
        raise CheckError('Pickup service reported failure')
    try:
        pickup = data['body']['content']['pickupMessage']
        stores = pickup['stores']
    except (KeyError, TypeError):
        raise CheckError('Pickup response schema changed') from None
    if not isinstance(stores, list) or not stores:
        raise CheckError('No store results; availability is UNKNOWN')
    if pickup.get('location') is not None and str(pickup['location']) != ZIP_CODE:
        raise CheckError('Pickup response ZIP does not match requested ZIP')
    rows, seen = [], set()
    for store in stores:
        if not isinstance(store, dict):
            raise CheckError('Invalid store row')
        store_id, name = store.get('storeNumber'), store.get('storeName')
        if not store_id or not isinstance(name, str) or not name:
            raise CheckError('Store identity missing')
        if store_id in seen:
            continue
        seen.add(store_id)
        distance = distance_miles(store)
        try:
            availability = store['partsAvailability'][part]
            regular = availability['messageTypes']['regular']
            selectable = regular['storeSelectionEnabled']
        except (KeyError, TypeError):
            raise CheckError('Exact SKU pickup selection state missing') from None
        if type(selectable) is not bool:
            raise CheckError('Pickup selection state must be a boolean')
        title = regular.get('storePickupProductTitle')
        if title and clean_text(title) != PRODUCT_NAME:
            raise CheckError('Pickup response product title does not match exact configuration')
        if availability.get('pickupDisplay') == 'unavailable' and selectable:
            raise CheckError('Pickup display conflicts with selectable store')
        # This is the flag Apple's public pickup-dialog code uses to enable a store.
        quote = clean_text(availability.get('pickupSearchQuote') or regular.get('storePickupQuote')
                           or availability.get('storePickupQuote'))
        if selectable and not quote:
            raise CheckError('Selectable store has no pickup quote')
        rows.append({'store_id': store_id, 'name': name, 'distance_miles': round(distance, 2),
                     'available': selectable, 'quote': quote or 'Not selectable for pickup'})
    if not rows:
        raise CheckError('No verifiable store results')
    return sorted(rows, key=lambda row: row['distance_miles'])[:MAX_STORES]


def verify_product(page):
    """Verify JSON-LD from this exact configuration, not a related item or cart button."""
    candidates = page.locator('script[type="application/ld+json"]').all_text_contents()
    products = []
    def walk(obj):
        if isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, dict):
            kind = obj.get('@type')
            if kind == 'Product' or isinstance(kind, list) and 'Product' in kind:
                products.append(obj)
            if '@graph' in obj:
                walk(obj['@graph'])
    for text in candidates:
        try:
            walk(json.loads(text))
        except json.JSONDecodeError:
            continue
    for product in products:
        if clean_text(product.get('name')) != PRODUCT_NAME:
            continue
        if clean_text(product.get('color')) != 'Star White':
            continue
        offers = product.get('offers', [])
        if isinstance(offers, dict):
            offers = [offers]
        for offer in offers:
            if isinstance(offer, dict) and offer.get('sku') == EXPECTED_PART + '+unlocked':
                return EXPECTED_PART
    raise CheckError('Exact model/color/storage/unlocked SKU could not be verified')


def diagnostics(page, message):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / 'error.txt').write_text(message, encoding='utf-8')
    try:
        page.screenshot(path=str(ARTIFACTS / 'failure.png'), full_page=True, timeout=15000)
    except Exception:
        print('Screenshot unavailable; inspect error.txt', flush=True)


def check_stock(document=False):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale='en-US', timezone_id='America/New_York',
                                      viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        try:
            response = page.goto(PRODUCT_URL, wait_until='domcontentloaded', timeout=60000)
            if response is None or response.status != 200:
                raise CheckError('Product page did not return HTTP 200')
            part = verify_product(page)
            print('Verified exact configuration: ' + part + ' + unlocked', flush=True)
            # Resolve the endpoint advertised by Apple's own page; do not use proxies or bypasses.
            path = page.evaluate('window.fulfillmentBootstrap && window.fulfillmentBootstrap.pickupURL')
            if not isinstance(path, str):
                raise CheckError('Apple pickup endpoint missing')
            endpoint = urljoin(PRODUCT_URL, path)
            parsed = urlparse(endpoint)
            if parsed.scheme != 'https' or parsed.netloc != 'www.apple.com' or parsed.path != '/shop/fulfillment-messages':
                raise CheckError('Unexpected pickup endpoint')
            params = {
                'parts.0': part, 'cppart': 'UNLOCKED/US', 'purchaseOption': 'fullPrice',
                'location': ZIP_CODE,
            }
            if document:
                query = dict(parse_qsl(parsed.query))
                query.update(params)
                target = urlunparse(parsed._replace(query=urlencode(query)))
                stock_page = context.new_page()
                response = stock_page.goto(target, wait_until='domcontentloaded', timeout=45000)
                if response is None:
                    raise CheckError('Pickup document returned no response')
            else:
                response = context.request.get(endpoint, params={**params, 'mts.0': 'regular'}, timeout=45000)
            if response.status != 200:
                raise CheckError('Apple pickup query HTTP ' + str(response.status) + '; inventory UNKNOWN')
            if 'json' not in response.headers.get('content-type', '').lower():
                raise CheckError('Apple returned non-JSON; inventory UNKNOWN')
            data = response.json()
            # Public stock data only; do not persist cookies, headers or Secrets.
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            (ARTIFACTS / 'pickup-response.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            rows = parse_pickup(data, part)
            (ARTIFACTS / 'result.json').write_text(json.dumps({
                'product': PRODUCT_NAME, 'zip': ZIP_CODE, 'max_stores': MAX_STORES,
                'coverage': 'Apple returned stores only; not a complete store census', 'stores': rows,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            return rows
        except Exception as exc:
            # Only our controlled CheckError strings are safe to persist.
            message = str(exc) if isinstance(exc, CheckError) else type(exc).__name__
            diagnostics(page, message)
            raise
        finally:
            browser.close()


def classify_visible_store(name, distance_text, quote, enabled):
    """A visible store row is authoritative only for that store, never the whole radius."""
    name, quote = clean_text(name), clean_text(quote)
    if not name.startswith('Apple ') or type(enabled) is not bool:
        raise CheckError('Visible store identity/selection state missing')
    distance = distance_miles({'storeDistanceWithUnit': distance_text})
    if re.fullmatch(r'Currently unavailable(?: for pickup)?', quote, re.I):
        if enabled:
            raise CheckError('Visible pickup quote conflicts with enabled store')
        available = False
    elif enabled and re.match(r'^(?:Available(?:\s|$)|Pick\s?up(?:\s|:)|Ready for pickup)', quote, re.I):
        available = True
    else:
        raise CheckError('Unrecognized visible pickup quote or conflicting selection state')
    return {'store_id': name, 'name': name, 'distance_miles': round(distance, 2),
            'available': available, 'quote': quote}


def read_visible_stores(overlay):
    rows = []
    for option in overlay.locator('.rf-productlocator-storeoption').all():
        if not option.is_visible():
            continue
        left = option.locator('.form-selector-left-col')
        right = option.locator('.form-selector-right-col')
        lines = [clean_text(line) for line in left.inner_text().splitlines() if clean_text(line)]
        names = [line for line in lines if line.startswith('Apple ')]
        distances = [line for line in lines if re.fullmatch(r'[0-9.]+\s*(?:mi|miles?|km)', line, re.I)]
        if len(names) != 1 or len(distances) != 1:
            raise CheckError('Visible store name/distance schema changed')
        quote = clean_text(right.inner_text())
        quote = re.sub(r'\s*In-Store Pickup\s*$', '', quote, flags=re.I)
        control = option.get_by_role('radio')
        if control.count() != 1:
            raise CheckError('Visible store selection control missing')
        row = classify_visible_store(names[0], distances[0], quote, control.is_enabled())
        rows.append(row)
    if not rows:
        raise CheckError('No visible verifiable store results')
    return sorted(rows, key=lambda row: row['distance_miles'])[:MAX_STORES]


def check_stock_ui(headed=False):
    """Use the public pickup dialog. Never substitute shipping/Add to Bag for pickup."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(locale='en-US', timezone_id='America/New_York',
                                viewport={'width': 1440, 'height': 1000})
        page.set_default_timeout(20000)
        failures = []
        def observe(response):
            if '/shop/fulfillment-messages' in response.url and response.status != 200:
                failures.append(response.status)
        page.on('response', observe)
        try:
            response = page.goto(PRODUCT_URL, wait_until='domcontentloaded', timeout=60000)
            if response is None or response.status != 200:
                raise CheckError('Product page did not return HTTP 200')
            verify_product(page)
            page.get_by_role('button', name=re.compile(r'Check Availability')).last.click()
            overlay = page.locator('.rf-productlocator-overlay')
            overlay.wait_for(state='visible')
            white = overlay.get_by_role('radio', name='Star White', exact=True)
            capacity = overlay.get_by_role('radio', name=re.compile(r'^512GB'))
            white.check()
            capacity.check()
            location = overlay.get_by_role('combobox', name='City or Zip', exact=True)
            location.fill(ZIP_CODE)
            location.press('Enter')
            overlay.get_by_role('heading', name=re.compile(r'Pick it up at an Apple Store near:\s*' + ZIP_CODE + r'$')).wait_for()
            overlay.locator('.rf-productlocator-ispickuploading').wait_for(state='hidden')
            toggle = overlay.get_by_role('button', name=re.compile(r'Not available today at .* stores'))
            if toggle.count() and toggle.get_attribute('aria-expanded') == 'false':
                toggle.click()
            overlay.locator('.rf-productlocator-storeoption').first.wait_for(state='visible')
            if not white.is_checked() or not capacity.is_checked() or location.input_value() != ZIP_CODE:
                raise CheckError('Visible dialog configuration/ZIP could not be verified')
            rows = read_visible_stores(overlay)
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            (ARTIFACTS / 'result.json').write_text(json.dumps({
                'product': PRODUCT_NAME, 'zip': ZIP_CODE, 'max_stores': MAX_STORES,
                'source': 'visible pickup dialog',
                'coverage': 'Apple displayed stores only; not a complete store census', 'stores': rows,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            page.screenshot(path=str(ARTIFACTS / 'pickup-dialog.png'), full_page=True)
            return rows
        except Exception as exc:
            detail = str(exc) if isinstance(exc, CheckError) else type(exc).__name__
            if failures:
                detail += '; page pickup request HTTP ' + ','.join(map(str, sorted(set(failures))))
            diagnostics(page, detail)
            raise CheckError(detail) from None
        finally:
            browser.close()


def notify(rows):
    now = datetime.now(ZoneInfo('America/New_York')).isoformat(timespec='seconds')
    title = '【到店取货提醒】iPhone Duo 白色 512GB'
    lines = [PRODUCT_NAME, 'Connect on your own later / Full price',
             f'ZIP {ZIP_CODE}，Apple 返回门店中最近 {MAX_STORES} 家', '检测时间（纽约）：' + now, '']
    for row in rows:
        lines.append(f"{row['name']}（{row['distance_miles']:g} mi）\n{row['quote']}")
    lines.extend(['', PRODUCT_URL, '请打开网页确认并下单；本通知不会保留库存。'])
    body = '\n'.join(lines)
    failures = 0
    for name, sender in [('Bark', send_bark), ('Gmail', send_email)]:
        try:
            sender(title, body)
            print(name + ': accepted by service', flush=True)
        except Exception as exc:
            failures += 1
            detail = str(exc) if isinstance(exc, CheckError) else type(exc).__name__
            print(name + ': failed: ' + detail, flush=True)
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--test-email', action='store_true')
    modes.add_argument('--test-bark', action='store_true')
    modes.add_argument('--check-only', action='store_true', help='Query stock but send no notifications')
    parser.add_argument('--ui', action='store_true', help='Use visible pickup dialog')
    parser.add_argument('--headed', action='store_true', help='Show isolated browser; requires --ui')
    parser.add_argument('--document', action='store_true', help='Diagnose public pickup URL as browser document')
    args = parser.parse_args(argv)
    if args.headed and not args.ui:
        parser.error('--headed requires --ui')
    try:
        if args.test_email or args.test_bark:
            sender = send_email if args.test_email else send_bark
            sender('【测试】iPhone Duo 取货监控', '这是通道测试，不代表有货。\n' + PRODUCT_URL)
            print('Test accepted by service', flush=True)
            return 0
        rows = check_stock_ui(headed=args.headed) if args.ui else check_stock(document=True) if args.document else check_stock()
        print('Coverage: Apple returned stores only; not guaranteed exhaustive', flush=True)
        for row in rows:
            print(f"{row['name']} | {row['distance_miles']:g} mi | "
                  f"{'AVAILABLE' if row['available'] else 'UNAVAILABLE'} | {row['quote']}", flush=True)
        available = [row for row in rows if row['available']]
        print('Pickup state: ' + ('AVAILABLE' if available else 'UNAVAILABLE_IN_RETURNED_STORES'), flush=True)
        if available and not args.check_only:
            return notify(available)
        return 0
    except Exception as exc:
        detail = str(exc) if isinstance(exc, CheckError) else type(exc).__name__
        print('Pickup state: UNKNOWN — ' + detail, file=sys.stderr, flush=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
