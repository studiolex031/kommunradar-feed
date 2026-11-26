import json, os, re, unicodedata, urllib.parse, urllib.request
from . import data

APP = "leverantorsregistret"
BELOPP = {"p1": 99000, "p2": 199000}


def fold(value):
    return unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode().lower().replace(" ", "").replace("-", "").replace("_", "")


def stripe_get(path, params=None):
    url = "https://api.stripe.com/v1/" + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["STRIPE_SECRET_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def stripe_post(path, params):
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=body,
                                 headers={"Authorization": "Bearer " + os.environ["STRIPE_SECRET_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def normalize_plan(value):
    text = fold(value)
    if text in ("p1", "nyavinnare", "nyavinnarevarjevecka"):
        return "p1"
    if text in ("p2", "avtalloperut", "avtalsomloperut"):
        return "p2"
    return ""


def giltig_pris(item, plan):
    price = item.get("price") or {}
    if not price:
        return True
    if str(price.get("currency", "")).lower() != "sek":
        return False
    if price.get("unit_amount") not in (None, BELOPP[plan]):
        return False
    recurring = price.get("recurring") or {}
    if recurring and (str(recurring.get("interval", "")).lower() != "month"
                      or int(recurring.get("interval_count", 1)) != 1):
        return False
    return True


def lan_key(value):
    text = fold(value)
    if text in ("", "alla", "all"):
        return None
    for code, name in data.LAN.items():
        if text == fold(name) or text == fold(code):
            return code
    return None


def bransch_key(value):
    match = re.search(r"(\d{2})", str(value or ""))
    return match.group(1) if match and match.group(1) in data.CPV else None


def read_answers(fields):
    out = {"bransch": None, "lan": None}
    for field in fields or []:
        value = ((field.get("text") or {}).get("value")
                 or (field.get("dropdown") or {}).get("value")
                 or (field.get("select") or {}).get("value")
                 or field.get("value") or "")
        key = fold(field.get("key"))
        label = fold((field.get("label") or {}).get("custom"))
        if "bransch" in key or "bransch" in label:
            out["bransch"] = out["bransch"] or bransch_key(value)
        elif "lan" in key or "lan" in label:
            out["lan"] = out["lan"] or lan_key(value)
        else:
            out["lan"] = out["lan"] or lan_key(value)
    return out


def product_plans(get):
    plans, after = {}, None
    while True:
        params = {"limit": 100, **({"starting_after": after} if after else {})}
        page = get("products", params)
        for product in page.get("data", []):
            metadata = product.get("metadata") or {}
            if metadata.get("app") == APP:
                plan = normalize_plan(metadata.get("plan") or product.get("name"))
                if plan:
                    plans[product.get("id")] = plan
        if not page.get("has_more"):
            return plans
        after = page["data"][-1]["id"]


def subscribers(get=None):
    api = get or stripe_get
    products = product_plans(api)
    result = []
    seen = set()
    for status in ("active", "trialing"):
        after = None
        while True:
            params = {"status": status, "limit": 100, "expand[]": "data.customer",
                      **({"starting_after": after} if after else {})}
            page = api("subscriptions", params)
            for subscription in page.get("data", []):
                subscription_id = subscription.get("id", "")
                if subscription_id in seen:
                    continue
                seen.add(subscription_id)
                metadata = subscription.get("metadata") or {}
                if metadata.get("paused") == "1":
                    continue
                app, plan = metadata.get("app"), normalize_plan(metadata.get("plan"))
                if not app or not plan:
                    for item in subscription.get("items", {}).get("data", []):
                        product_id = ((item.get("price") or {}).get("product") or {})
                        product_id = product_id.get("id") if isinstance(product_id, dict) else product_id
                        if product_id in products:
                            app, plan = APP, products[product_id]
                            break
                if app != APP or plan not in ("p1", "p2"):
                    continue
                items = subscription.get("items", {}).get("data", [])
                if not all(giltig_pris(item, plan) for item in items):
                    continue
                sessions = api("checkout/sessions", {"subscription": subscription["id"], "limit": 1}).get("data", [])
                answers = read_answers(sessions[0].get("custom_fields") or []) if sessions else read_answers([])
                customer = subscription.get("customer")
                customer = customer if isinstance(customer, dict) else {}
                email = customer.get("email")
                if not email and sessions:
                    email = (sessions[0].get("customer_details") or {}).get("email")
                if not email:
                    continue
                result.append({"id": subscription.get("id", ""), "email": email, "plan": plan,
                               "bransch": metadata.get("bransch") or answers["bransch"],
                               "lan": metadata.get("lan") or answers["lan"],
                               "customer_id": customer.get("id", ""), "status": status,
                               "created": subscription.get("created", 0)})
            if not page.get("has_more"):
                break
            after = page["data"][-1]["id"]
    return result
