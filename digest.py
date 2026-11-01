"""Daglig bevakning: mejlar varje betalande kund nya upphandlingar som matchar deras bevakning.

Stripe är kundregistret: aktiva prenumerationer + svaren från betalsidan (bevakningsord, län).
Operatören kan skriva över per kund med metadata på prenumerationen: keywords="städ, fönsterputs", lan="skane".

  python digest.py --prev prev.json            # skickar mejl
  python digest.py --prev prev.json --dry-run  # visar vad som skulle skickas
Miljö: STRIPE_SECRET_KEY, SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, MAIL_FROM, SITE_URL, PORTAL_URL
"""
import os, re, sys, ssl, json, html, smtplib, unicodedata, datetime as dt, urllib.request, urllib.parse
from email.message import EmailMessage

LAN_KEYS = {"alla": "", "stockholm": "Stockholm", "uppsala": "Uppsala", "sodermanland": "Södermanland",
            "ostergotland": "Östergötland", "orebro": "Örebro", "vastmanland": "Västmanland", "jonkoping": "Jönköping",
            "kronoberg": "Kronoberg", "kalmar": "Kalmar", "gotland": "Gotland", "blekinge": "Blekinge", "skane": "Skåne",
            "halland": "Halland", "vastragotaland": "Västra Götaland", "varmland": "Värmland", "dalarna": "Dalarna",
            "gavleborg": "Gävleborg", "vasternorrland": "Västernorrland", "jamtland": "Jämtland",
            "vasterbotten": "Västerbotten", "norrbotten": "Norrbotten"}
MAX_PER_MAIL = 40


def stripe_get(path, params=None):
    url = "https://api.stripe.com/v1/" + path + ("?" + urllib.parse.urlencode(params or {}, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["STRIPE_SECRET_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def kommunradar_products():
    """Product ids that are Kommunradar (created by stripe_setup.py or named so in the Dashboard)."""
    ids, after = set(), None
    while True:
        page = stripe_get("products", {"limit": 100, **({"starting_after": after} if after else {})})
        ids |= {p["id"] for p in page["data"]
                if (p.get("metadata") or {}).get("app") == "kommunradar" or "kommunradar" in (p.get("name") or "").lower()}
        if not page.get("has_more"): return ids
        after = page["data"][-1]["id"]


def subscribers():
    """Yield {email, keywords, lan} for every active or trialing Kommunradar subscription
    (other products in the same Stripe account are skipped)."""
    products = kommunradar_products()
    for status in ("active", "trialing"):
        after = None
        while True:
            params = {"status": status, "limit": 100, "expand[]": "data.customer"}
            if after: params["starting_after"] = after
            page = stripe_get("subscriptions", params)
            for sub in page["data"]:
                if not any((it.get("price") or {}).get("product") in products for it in sub["items"]["data"]): continue
                sessions = stripe_get("checkout/sessions", {"subscription": sub["id"], "limit": 1})["data"]
                answers = read_answers(sessions[0].get("custom_fields") or []) if sessions else {}
                meta = sub.get("metadata") or {}
                customer = sub["customer"] if isinstance(sub["customer"], dict) else {}
                email = customer.get("email") or (sessions[0].get("customer_details") or {}).get("email") if sessions else customer.get("email")
                if email:
                    yield {"email": email, "keywords": meta.get("keywords") or answers.get("bevakning", ""),
                           "lan": meta.get("lan") or answers.get("lan", "alla")}
            if not page.get("has_more"): break
            after = page["data"][-1]["id"]


def fold(text):
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower().replace(" ", "")


def read_answers(fields):
    """Bevakningsord and län from the checkout's custom fields — whether created by stripe_setup.py
    (keys "bevakning"/"lan") or by hand in the Stripe Dashboard (any key; län recognised by label or value)."""
    out = {}
    for f in fields:
        value = (f.get("text") or {}).get("value") or (f.get("dropdown") or {}).get("value") or ""
        label = fold((f.get("label") or {}).get("custom") or f.get("key"))
        is_keyword = f.get("key") == "bevakning" or label.startswith("bevakning")
        if not is_keyword and (f.get("key") == "lan" or label.startswith("lan")
                               or fold(value) in {fold(v) for v in LAN_KEYS.values() if v}):
            county = next((k for k, v in LAN_KEYS.items() if fold(value) in (k, fold(v))), "alla")
            out.setdefault("lan", county)
        elif value:
            out.setdefault("bevakning", value)
    return out


def keywords(raw):
    return [k.strip().lower() for k in re.split(r"[,;\n]+", raw or "") if len(k.strip()) >= 2]


def matches(lead, words, lan):
    region = LAN_KEYS.get(lan, "")
    regions = lead.get("regions") or ([lead["region"]] if lead.get("region") else [])
    if region and regions and region not in regions: return False  # unknown region is kept
    if not words: return True
    hay = " ".join([lead.get("title", ""), lead.get("buyer", ""), lead.get("city", ""), " ".join(lead.get("categories", []))]).lower()
    return any(w in hay for w in words)


def new_leads(current, prev_path):
    try:
        prev = {l["id"] for l in json.load(open(prev_path, encoding="utf8"))["leads"]}
    except (OSError, ValueError, KeyError):
        since = (dt.date.today() - dt.timedelta(days=1)).isoformat()  # first run: yesterday + today
        return [l for l in current if l.get("published", "") >= since]
    return [l for l in current if l["id"] not in prev]


def money(v):
    if not v: return ""
    return f"{v / 1e6:.1f} mkr".replace(".", ",") if v >= 1e6 else f"{v / 1e3:.0f} tkr"


def render(leads, sub, site, portal):
    rows = "".join(
        f'<tr><td style="padding:14px 0;border-bottom:1px solid #e5e7eb">'
        f'<a href="{html.escape(l["url"])}" style="color:#0b1020;font-weight:700;font-size:16px;text-decoration:none">{html.escape(l["title"])}</a>'
        f'<div style="color:#475569;font-size:13px;margin-top:4px">{html.escape(l["buyer"])}{" · " + html.escape(l["region"]) if l.get("region") else ""}'
        f'{" · <b>" + money(l.get("value_sek")) + "</b>" if l.get("value_sek") else ""}'
        f'{" · <span style=\'color:#c2410c\'>sista dag " + html.escape(l["deadline"]) + "</span>" if l.get("deadline") else ""}</div></td></tr>'
        for l in leads[:MAX_PER_MAIL])
    more = f'<p style="color:#475569">+ {len(leads) - MAX_PER_MAIL} till på <a href="{site}">kommunradar</a>.</p>' if len(leads) > MAX_PER_MAIL else ""
    return f"""<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:640px;margin:auto">
<div style="background:#0b1020;color:#fff;padding:22px 24px;border-radius:14px 14px 0 0"><b style="font-size:20px">KOMMUNRADAR</b>
<div style="color:#fbbf24;font-size:28px;font-weight:900;margin-top:8px">{len(leads)} nya upphandlingar för dig</div>
<div style="color:#94a3b8;font-size:13px">Bevakning: {html.escape(sub["keywords"] or "alla branscher")} · {html.escape(LAN_KEYS.get(sub["lan"]) or "hela Sverige")}</div></div>
<table style="width:100%;border-collapse:collapse;padding:0 24px">{rows}</table>{more}
<p style="color:#94a3b8;font-size:12px;margin-top:24px">Källa: TED (EU:s officiella upphandlingsdatabas). Svara på mejlet för att ändra din bevakning.
{f'<a href="{portal}" style="color:#94a3b8">Hantera prenumeration</a>' if portal else ''}</p></div>"""


def main():
    dry = "--dry-run" in sys.argv
    prev = sys.argv[sys.argv.index("--prev") + 1] if "--prev" in sys.argv else "prev.json"
    leads = new_leads(json.load(open("leads.json", encoding="utf8"))["leads"], prev)
    site, portal = os.environ.get("SITE_URL", ""), os.environ.get("PORTAL_URL", "")
    print(f"{len(leads)} nya upphandlingar sedan förra körningen")
    if not leads or not os.environ.get("STRIPE_SECRET_KEY"):
        print("Inget att skicka (inga nya upphandlingar eller ingen STRIPE_SECRET_KEY)."); return
    smtp = None
    if not dry:
        smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    sent = 0
    for sub in subscribers():
        hits = [l for l in leads if matches(l, keywords(sub["keywords"]), sub["lan"])]
        if not hits: continue
        msg = EmailMessage()
        msg["Subject"] = f"{len(hits)} nya upphandlingar: {hits[0]['title'][:60]}"
        msg["From"] = os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", "")); msg["To"] = sub["email"]
        msg.set_content("\n".join(f"{l['title']} — {l['buyer']} — {l['url']}" for l in hits[:MAX_PER_MAIL]))
        msg.add_alternative(render(hits, sub, site, portal), subtype="html")
        if dry: print(f"[dry-run] {sub['email']}: {len(hits)} träffar")
        else: smtp.send_message(msg)
        sent += 1
    if smtp: smtp.quit()
    print(f"{sent} mejl {'skulle skickas' if dry else 'skickade'}")


if __name__ == "__main__":
    main()
