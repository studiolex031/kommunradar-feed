"""Vercel serverless endpoint for Kommunradar's prefilled Stripe Checkout.

Required server-only environment:
  STRIPE_SECRET_KEY
  STRIPE_PRO_PRICE_ID
Optional:
  STRIPE_EXPECT_LIVE=true
  CHECKOUT_ALLOWED_ORIGINS=https://kommunradar.online

No Stripe writes occur until a visitor explicitly submits the checkout form.
"""
import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

SITE_ORIGIN = "https://kommunradar.online"
TRIAL_DAYS = 7
PRICE_AMOUNT = 99000
MAX_BODY = 16_384
MAX_KEYWORDS = 200
RATE_WINDOW = 60
RATE_LIMIT = 8
_REQUESTS = {}

COUNTIES = {
    "alla": "alla",
    "stockholm": "stockholm",
    "uppsala": "uppsala",
    "sodermanland": "sodermanland",
    "ostergotland": "ostergotland",
    "orebro": "orebro",
    "vastmanland": "vastmanland",
    "jonkoping": "jonkoping",
    "kronoberg": "kronoberg",
    "kalmar": "kalmar",
    "gotland": "gotland",
    "blekinge": "blekinge",
    "skane": "skane",
    "halland": "halland",
    "vastragotaland": "vastragotaland",
    "varmland": "varmland",
    "dalarna": "dalarna",
    "gavleborg": "gavleborg",
    "vasternorrland": "vasternorrland",
    "jamtland": "jamtland",
    "vasterbotten": "vasterbotten",
    "norrbotten": "norrbotten",
}
COUNTY_LABELS = {
    "hela sverige": "alla",
    "sodermanland": "sodermanland",
    "örebro": "orebro",
    "västmanland": "vastmanland",
    "jönköping": "jonkoping",
    "östergötland": "ostergotland",
    "västra götaland": "vastragotaland",
    "västernorrland": "vasternorrland",
    "jämntland": "jamtland",
    "jämtland": "jamtland",
    "västerbotten": "vasterbotten",
    "norrbotten": "norrbotten",
    "gävleborg": "gavleborg",
    "skåne": "skane",
    "blekinge": "blekinge",
    "gotland": "gotland",
    "halland": "halland",
    "kalmar": "kalmar",
    "kronoberg": "kronoberg",
    "dalarna": "dalarna",
    "värmland": "varmland",
    "uppsala": "uppsala",
    "stockholm": "stockholm",
}

def _fold(value):
    value = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))

def normalize_checkout_input(data):
    if not isinstance(data, dict):
        raise ValueError("Ogiltig förfrågan.")

    raw_keywords = str(data.get("keywords") or "").strip()
    if len(raw_keywords) > MAX_KEYWORDS:
        raise ValueError("Bevakningsorden får vara högst 200 tecken.")

    if any(ord(ch) < 32 and ch not in "\t\n\r" for ch in raw_keywords):
        raise ValueError("Bevakningsorden innehåller ogiltiga tecken.")

    terms = []
    for term in re.split(r"[,;\n]+", raw_keywords):
        term = re.sub(r"\s+", " ", term).strip()
        if not term:
            continue
        if len(term) < 2 or len(term) > 60:
            raise ValueError("Varje bevakningsord måste vara 2–60 tecken.")
        if term.lower() not in [item.lower() for item in terms]:
            terms.append(term)
    if len(terms) > 8:
        raise ValueError("Ange högst 8 bevakningsord.")

    raw_county = str(data.get("lan") or "alla").strip()
    folded = _fold(raw_county)
    county = COUNTY_LABELS.get(folded, folded.replace(" ", ""))
    if county not in COUNTIES:
        raise ValueError("Välj ett giltigt län.")

    return {
        "keywords": ", ".join(terms),
        "lan": county,
    }

def build_session_params(price_id, values, origin):
    success_url = origin + "/tack.html?session_id={CHECKOUT_SESSION_ID}"
    return {
        "mode": "subscription",
        "line_items[0][price]": price_id,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": origin + "/#pris",
        "billing_address_collection": "required",
        "payment_method_collection": "always",
        "payment_method_types[0]": "card",
        "payment_method_types[1]": "link",
        "allow_promotion_codes": "true",
        "locale": "sv",
        "consent_collection[terms_of_service]": "required",
        "tax_id_collection[enabled]": "true",
        "tax_id_collection[required]": "never",
        "subscription_data[trial_period_days]": str(TRIAL_DAYS),
        "subscription_data[metadata][app]": "kommunradar",
        "subscription_data[metadata][keywords]": values["keywords"],
        "subscription_data[metadata][lan]": values["lan"],
        "metadata[app]": "kommunradar",
        "metadata[source]": "website-prefilled-checkout",
        "metadata[keywords]": values["keywords"],
        "metadata[lan]": values["lan"],
        "expires_at": str(int(time.time()) + 3600),
    }

def _stripe_request(key, method, path, params=None):
    encoded = urllib.parse.urlencode(params or {}).encode("utf-8")
    url = "https://api.stripe.com/v1/" + path
    if method == "GET" and encoded:
        url += "?" + encoded.decode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded if method == "POST" else None,
        method=method,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))

def _verified_price(key, price_id):
    price = _stripe_request(key, "GET", "prices/" + urllib.parse.quote(price_id, safe=""), {"expand[]": "product"})
    recurring = price.get("recurring") or {}
    if (
        price.get("active") is not True
        or price.get("currency") != "sek"
        or price.get("unit_amount") != PRICE_AMOUNT
        or recurring.get("interval") != "month"
        or recurring.get("interval_count", 1) != 1
    ):
        raise ValueError("Den konfigurerade Stripe-produkten matchar inte 990 kr per månad.")
    product = price.get("product") or {}
    if isinstance(product, str):
        product = _stripe_request(key, "GET", "products/" + urllib.parse.quote(product, safe=""))
    metadata = product.get("metadata") or {}
    if product.get("active") is not True or (
        metadata.get("app") != "kommunradar"
        and "kommunradar" not in str(product.get("name") or "").lower()
    ):
        raise ValueError("Stripe-priset tillhör inte en aktiv Kommunradar-produkt.")
    return price

def _allowed_origins():
    raw = os.environ.get("CHECKOUT_ALLOWED_ORIGINS", SITE_ORIGIN)
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}

def _rate_limited(ip):
    now = time.time()
    recent = [stamp for stamp in _REQUESTS.get(ip, []) if now - stamp < RATE_WINDOW]
    if len(recent) >= RATE_LIMIT:
        _REQUESTS[ip] = recent
        return True
    recent.append(now)
    _REQUESTS[ip] = recent
    return False

class handler(BaseHTTPRequestHandler):
    server_version = "KommunradarCheckout/1.0"

    def log_message(self, fmt, *args):
        # Do not log submitted search terms, customer data, or Stripe responses.
        return

    def _send(self, status, payload, origin=None):
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if status != 204:
            self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin not in _allowed_origins():
            self._send(403, {"error": "Origin tillåts inte."})
            return
        self._send(204, {}, origin)

    def do_POST(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin not in _allowed_origins():
            self._send(403, {"error": "Origin tillåts inte."})
            return

        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._send(415, {"error": "Förfrågan måste vara JSON."}, origin)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length < 2 or length > MAX_BODY:
            self._send(413, {"error": "Förfrågan har fel storlek."}, origin)
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Ogiltig förfrågan.")
            if payload.get("website"):
                self._send(400, {"error": "Förfrågan kunde inte verifieras."}, origin)
                return
            loaded_at = int(payload.get("pageLoadedAt", 0))
            if loaded_at <= 0 or int(time.time() * 1000) - loaded_at < 1200:
                self._send(400, {"error": "Ladda om sidan och försök igen."}, origin)
                return
            values = normalize_checkout_input(payload)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Ogiltig förfrågan."
            self._send(400, {"error": message}, origin)
            return

        ip = self.headers.get("x-real-ip") or self.headers.get("x-vercel-forwarded-for") or self.client_address[0]
        if _rate_limited(ip):
            self._send(429, {"error": "För många försök. Vänta en minut och försök igen."}, origin)
            return

        key = os.environ.get("STRIPE_SECRET_KEY", "")
        price_id = os.environ.get("STRIPE_PRO_PRICE_ID", "")
        expect_live = os.environ.get("STRIPE_EXPECT_LIVE", "true").lower() == "true"
        if not key.startswith(("sk_", "rk_")) or not price_id.startswith("price_"):
            self._send(503, {"error": "Checkout är inte konfigurerad ännu."}, origin)
            return
        if expect_live and not key.startswith(("sk_live_", "rk_live_")):
            self._send(503, {"error": "Checkout är inte konfigurerad för livebetalningar."}, origin)
            return

        try:
            _verified_price(key, price_id)
            result = _stripe_request(key, "POST", "checkout/sessions", build_session_params(price_id, values, SITE_ORIGIN))
            checkout_url = result.get("url", "")
            if result.get("mode") != "subscription" or not checkout_url.startswith("https://checkout.stripe.com/"):
                raise RuntimeError("Stripe returnerade en ogiltig Checkout-session.")
            self._send(200, {"url": checkout_url}, origin)
        except urllib.error.HTTPError:
            self._send(502, {"error": "Stripe kunde inte skapa checkout just nu. Försök igen senare."}, origin)
        except (urllib.error.URLError, TimeoutError):
            self._send(502, {"error": "Stripe kunde inte nås just nu. Försök igen senare."}, origin)
        except Exception:
            self._send(502, {"error": "Checkout kunde inte startas. Försök igen senare."}, origin)
