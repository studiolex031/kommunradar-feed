"""Skapar Kommunradar Pro i Stripe — idempotent, går att köra flera gånger.

    STRIPE_SECRET_KEY=sk_test_... python scripts/stripe_setup.py --site https://kommunradar.se --trial-days 7

Skapar (eller återanvänder): produkt, månadspris 990 kr exkl. moms, och en Payment Link där kunden
anger bevakningsord och län. Skriver ut länken — klistra in den i config.js.
"""
import argparse, json, os, sys, urllib.error, urllib.parse, urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from digest import LAN_KEYS  # noqa: E402

API = 'https://api.stripe.com/v1/'


def call(key, path, params=None, method='POST'):
    encoded = urllib.parse.urlencode(params or {}, doseq=True)
    url = API + path + ('?' + encoded if method == 'GET' and encoded else '')
    req = urllib.request.Request(url, data=encoded.encode() if method != 'GET' else None, method=method,
                                 headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/x-www-form-urlencoded'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f'Stripe-fel på {path}: {e.read().decode()}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--site', required=True, help='publik adress till sajten, t.ex. https://kommunradar.se')
    ap.add_argument('--price-sek', type=int, default=990)
    ap.add_argument('--trial-days', type=int, default=7)
    ap.add_argument('--require-terms', action='store_true', help='kräver att kunden godkänner villkoren i kassan (sätt villkors-URL i Stripe först)')
    ap.add_argument('--moms', action='store_true', help='Stripe Tax lägger på moms (25 %%) i kassan — kräver momsregistrering i Stripe → Tax')
    a = ap.parse_args()
    key = os.environ.get('STRIPE_SECRET_KEY', '')
    if not key.startswith(('sk_', 'rk_')): sys.exit('Sätt STRIPE_SECRET_KEY.')
    print('Stripe-läge:', 'LIVE' if '_live_' in key else 'TEST')

    prices = call(key, 'prices', {'lookup_keys[]': 'kommunradar_pro_monthly', 'active': 'true'}, 'GET')['data']
    if prices and prices[0]['unit_amount'] == a.price_sek * 100:
        price = prices[0]
    else:
        product = prices[0]['product'] if prices else call(key, 'products', {
            'name': 'Kommunradar Pro',
            'description': 'Daglig bevakning av offentliga upphandlingar, filtrerad på din bransch och ditt län.',
            'metadata[app]': 'kommunradar'})['id']
        price = call(key, 'prices', {'product': product, 'currency': 'sek', 'unit_amount': a.price_sek * 100,
                                     'recurring[interval]': 'month', 'tax_behavior': 'exclusive',
                                     'lookup_key': 'kommunradar_pro_monthly', 'transfer_lookup_key': 'true'})
    print('Pris:', price['id'], f'{a.price_sek} kr/mån exkl. moms')

    links = [l for l in call(key, 'payment_links', {'active': 'true', 'limit': 100}, 'GET')['data']
             if (l.get('metadata') or {}).get('app') == 'kommunradar' and (l.get('metadata') or {}).get('price') == price['id']
             and bool((l.get('automatic_tax') or {}).get('enabled')) == a.moms]
    if links:
        link = links[0]
    else:
        params = {'line_items[0][price]': price['id'], 'line_items[0][quantity]': 1,
                  'metadata[app]': 'kommunradar', 'metadata[price]': price['id'],
                  'billing_address_collection': 'required', 'tax_id_collection[enabled]': 'true',
                  'allow_promotion_codes': 'true',
                  'after_completion[type]': 'redirect', 'after_completion[redirect][url]': a.site.rstrip('/') + '/tack.html',
                  'custom_fields[0][key]': 'bevakning', 'custom_fields[0][type]': 'text',
                  'custom_fields[0][label][type]': 'custom', 'custom_fields[0][label][custom]': 'Bevakningsord (t.ex. städ, IT-konsult)',
                  'custom_fields[1][key]': 'lan', 'custom_fields[1][type]': 'dropdown',
                  'custom_fields[1][label][type]': 'custom', 'custom_fields[1][label][custom]': 'Län'}
        for i, (value, label) in enumerate(LAN_KEYS.items()):
            params[f'custom_fields[1][dropdown][options][{i}][value]'] = value
            params[f'custom_fields[1][dropdown][options][{i}][label]'] = label or 'Hela Sverige'
        if a.trial_days: params['subscription_data[trial_period_days]'] = a.trial_days
        if a.require_terms: params['consent_collection[terms_of_service]'] = 'required'
        if a.moms: params['automatic_tax[enabled]'] = 'true'
        link = call(key, 'payment_links', params)
    print('\nPayment Link:', link['url'])
    print("Klistra in den i config.js: window.KOMMUNRADAR = { paymentLink: '" + link['url'] + "' }")
    print('\nAktivera även kundportalen: Stripe Dashboard → Settings → Billing → Customer portal, och sätt PORTAL_URL.')


if __name__ == '__main__':
    main()
