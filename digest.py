"""Daglig bevakning: mejlar varje betalande kund nya upphandlingar som matchar deras bevakning.

Stripe är kundregistret: aktiva prenumerationer + svaren från betalsidan (bevakningsord, län).
Operatören kan skriva över per kund med metadata på prenumerationen: keywords="städ, fönsterputs", lan="skane".

  python digest.py --prev prev.json            # skickar mejl
  python digest.py --prev prev.json --dry-run  # visar vad som skulle skickas
  python digest.py --weekly [--dry-run]        # gratis veckobrev: senaste 7 dagarnas träffar (körs måndagar)
Miljö: STRIPE_SECRET_KEY, SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS, MAIL_FROM, SITE_URL, PORTAL_URL,
REPLY_TO (standard hej@kommunradar.online), PRO_URL (köplänk i veckobrevet, standard SITE_URL/#pris)

Två nivåer i samma Stripe-konto, skilda åt med produktens metadata tier:
  pro        (standard) dagligt mejl + provmejl dag 1, 3 och 6
  veckobrev  gratis 0 kr-prenumeration utan kort: ett mejl i veckan med de bästa träffarna och en länk till Pro.
             Dagen efter anmälan skickar den dagliga körningen ett välkomstmejl med senaste veckans träffar.
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
WEEKLY_MAX = 10   # så många träffar visas i veckobrevet; resten är skälet att uppgradera
FREE = "veckobrev"


def stripe_get(path, params=None):
    url = "https://api.stripe.com/v1/" + path + ("?" + urllib.parse.urlencode(params or {}, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + os.environ["STRIPE_SECRET_KEY"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def product_tier(p):
    """'veckobrev' for the free weekly product (metadata tier, or the name when made by hand), else 'pro'."""
    tier = (p.get("metadata") or {}).get("tier") or ""
    return FREE if tier == FREE or (not tier and FREE in (p.get("name") or "").lower()) else "pro"


def kommunradar_products():
    """{product id: tier} for Kommunradar products (created by stripe_setup.py or named so in the Dashboard)."""
    ids, after = {}, None
    while True:
        page = stripe_get("products", {"limit": 100, **({"starting_after": after} if after else {})})
        ids |= {p["id"]: product_tier(p) for p in page["data"]
                if (p.get("metadata") or {}).get("app") == "kommunradar" or "kommunradar" in (p.get("name") or "").lower()}
        if not page.get("has_more"): return ids
        after = page["data"][-1]["id"]


def subscribers():
    """Yield {email, keywords, lan, status, trial_start, tier, created} for every active or trialing Kommunradar
    subscription (other products in the same Stripe account are skipped). A subscription with any Pro item is Pro."""
    products = kommunradar_products()
    for status in ("active", "trialing"):
        after = None
        while True:
            params = {"status": status, "limit": 100, "expand[]": "data.customer"}
            if after: params["starting_after"] = after
            page = stripe_get("subscriptions", params)
            for sub in page["data"]:
                tiers = {products[p] for it in sub["items"]["data"] if (p := (it.get("price") or {}).get("product")) in products}
                if not tiers: continue
                sessions = stripe_get("checkout/sessions", {"subscription": sub["id"], "limit": 1})["data"]
                answers = read_answers(sessions[0].get("custom_fields") or []) if sessions else {}
                meta = sub.get("metadata") or {}
                customer = sub["customer"] if isinstance(sub["customer"], dict) else {}
                email = customer.get("email") or (sessions[0].get("customer_details") or {}).get("email") if sessions else customer.get("email")
                if email:
                    yield {"email": email, "keywords": meta.get("keywords") or answers.get("bevakning", ""),
                           "lan": meta.get("lan") or answers.get("lan", "alla"),
                           "status": sub.get("status") or status, "trial_start": sub.get("trial_start"),
                           "tier": "pro" if "pro" in tiers else FREE, "created": sub.get("created")}
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


def rows_html(leads):
    def row(l):
        deadline_str = f' · <span style="color:#c2410c">sista dag {html.escape(l["deadline"])}</span>' if l.get("deadline") else ""
        return (
            f'<tr><td style="padding:14px 0;border-bottom:1px solid #e5e7eb">'
            f'<a href="{html.escape(l["url"])}" style="color:#0b1020;font-weight:700;font-size:16px;text-decoration:none">{html.escape(l["title"])}</a>'
            f'<div style="color:#475569;font-size:13px;margin-top:4px">{html.escape(l["buyer"])}{" · " + html.escape(l["region"]) if l.get("region") else ""}'
            f'{" · <b>" + money(l.get("value_sek")) + "</b>" if l.get("value_sek") else ""}'
            f'{deadline_str}</div></td></tr>'
        )
    return "".join(row(l) for l in leads)


def render(leads, sub, site, portal):
    rows = rows_html(leads[:MAX_PER_MAIL])
    more = f'<p style="color:#475569">+ {len(leads) - MAX_PER_MAIL} till på <a href="{site}">kommunradar</a>.</p>' if len(leads) > MAX_PER_MAIL else ""
    return f"""<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:640px;margin:auto">
<div style="background:#0b1020;color:#fff;padding:22px 24px;border-radius:14px 14px 0 0"><b style="font-size:20px">KOMMUNRADAR</b>
<div style="color:#fbbf24;font-size:28px;font-weight:900;margin-top:8px">{len(leads)} nya upphandlingar för dig</div>
<div style="color:#94a3b8;font-size:13px">Bevakning: {html.escape(sub["keywords"] or "alla branscher")} · {html.escape(LAN_KEYS.get(sub["lan"]) or "hela Sverige")}</div></div>
<table style="width:100%;border-collapse:collapse;padding:0 24px">{rows}</table>{more}
<p style="color:#94a3b8;font-size:12px;margin-top:24px">Källa: TED (EU:s officiella upphandlingsdatabas). Svara på mejlet för att ändra din bevakning.
{f'<a href="{portal}" style="color:#94a3b8">Hantera prenumeration</a>' if portal else ''}</p></div>"""


# Provperioden: tre korta mejl till den som testar. Dagen räknas från provperiodens start; morgonkörningen dagen
# efter registreringen är dag 1. Bara prenumerationer som fortfarande provar får mejlen, så den som redan har
# betalat får aldrig "testet slutar i morgon". Ingen egen databas behövs: dagen avgör vilket mejl som går ut.
SIGNATURE = "\n\nAlexander Pålsson\nKommunradar.online"
ONBOARDING = {
    1: ("Välkommen till Kommunradar – så får du träffar som passar",
        "Hej,\n\nTack för att du testar Kommunradar. Varje morgon får du ett mejl med nya offentliga upphandlingar "
        "från TED som matchar dina bevakningsord och ditt län.\n\nTre enkla saker som maximerar dina affärschanser direkt:\n"
        "1. Använd ord som upphandlaren faktiskt skriver (t.ex. \"lokalvård\" eller \"städentreprenad\" i stället för bara \"städfirma\").\n"
        "2. Lägg till 3–5 synonymer för era tjänster för att inte missa affärer med oväntad rubricering.\n"
        "3. Bevaka även grannlänen om ni kan leverera där – många små och medelstora bolag kammar hem sina mest lönsamma avtal strax utanför hemkommunen.\n\n"
        "💡 Vill du ha en snabbare genomgång av förfrågningsunderlag och krav? Kolla in vår Android-app Blueberry Station (https://kommunradar.online/app/) som läser underlag med AI och ger go/no-go direkt i mobilen.\n\n"
        "Svara bara på detta mejl så justerar jag era sökord och län manuellt åt er." + SIGNATURE),
    3: ("Får du rätt upphandlingar? (Snabb koll)",
        "Hej,\n\nDu har nu fått morgonrapporterna i några dagar. Hur ser träffbilden ut för er verksamhet?\n\n"
        "Svara direkt med en siffra eller ett ord så justerar jag inställningarna åt er idag:\n"
        "1. \"Perfekt\" – vi rullar på som det är.\n"
        "2. \"För brett / för många\" – jag smalnar av era sökord.\n"
        "3. \"För få träffar\" – jag breddar sökorden eller lägger till närliggande län.\n\n"
        "Kom ihåg: En enda vunnen offentlig affär betalar prenumerationen mångdubbelt under flera år framöver." + SIGNATURE),
    6: ("Ditt test av Kommunradar slutar i morgon – säkra kontinuerlig bevakning",
        "Hej,\n\nDitt gratistest av Kommunradar slutar i morgon bitti. Därefter övergår det automatiskt till ordinarie prenumeration (990 kr/mån, ingen moms och ingen bindningstid).\n\n"
        "💰 Vill ni sänka månadskostnaden och säkra kassaflödet? Vi har även ett årsabonnemang för 7 900 kr/år (motsvarar 658 kr/mån – ni sparar 3 980 kr). Svara bara på detta mejl om ni föredrar årsfaktura/årsabonnemang så ordnar jag det direkt.\n\n"
        "Vill du avsluta eller ändra något innan provperioden löper ut gör du det enkelt{portal} eller genom att svara här.\n\n"
        "Har du inte hittat rätt affär ännu? Svara med en rad om vad ni söker, så kollar jag historiken och förslår exakta söktermer." + SIGNATURE),
}


def onboarding_mail(sub, today, portal=""):
    """(subject, text) for this morning's trial mail, or None. today is a datetime.date."""
    start = sub.get("trial_start")
    if sub.get("status") != "trialing" or not start or sub.get("tier", "pro") != "pro":
        return None
    day = (today - dt.datetime.fromtimestamp(int(start), dt.timezone.utc).date()).days
    if day not in ONBOARDING:
        return None
    subject, text = ONBOARDING[day]
    return subject, text.replace("{portal}", f" här: {portal}" if portal else "")


def days_since(ts, today):
    """Whole days from a Stripe timestamp to today (a datetime.date); None when unknown."""
    if not ts: return None
    return (today - dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).date()).days


def weekly_hits(leads, sub, today):
    """(hits, fallback) for the free weekly mail: tenders published the last 7 days that match, biggest first.
    With no keyword hits, the week's biggest tenders in the subscriber's county are sent instead (fallback=True),
    so the mail is never empty while there is anything at all to show."""
    since = (today - dt.timedelta(days=7)).isoformat()
    recent = [l for l in leads if (l.get("published") or "") >= since]
    words = keywords(sub["keywords"])
    hits, fallback = [l for l in recent if matches(l, words, sub["lan"])], False
    if not hits and words:  # strict: "biggest in your county" must really be in the county
        region = LAN_KEYS.get(sub["lan"], "")
        hits, fallback = [l for l in recent if not region or region in (l.get("regions") or [l.get("region")])], True
    hits.sort(key=lambda l: (-(l.get("value_sek") or 0), l.get("deadline") or "9999"))
    return hits, fallback


def render_weekly(hits, sub, fallback, welcome, site, pro_url, portal):
    shown, area = hits[:WEEKLY_MAX], html.escape(LAN_KEYS.get(sub["lan"]) or "hela Sverige")
    if fallback:
        head = f"Veckans största upphandlingar i {area}"
        intro = f'Inga nya upphandlingar matchade <b>{html.escape(sub["keywords"])}</b> den här veckan, så här är de största i {area}.'
    else:
        head = f"{len(hits)} nya upphandlingar för dig senaste veckan"
        intro = ("Välkommen! Här är senaste veckans upphandlingar som matchar din bevakning. Nästa veckobrev kommer på måndag."
                 if welcome else "Här är veckans nya upphandlingar som matchar din bevakning, de största först.")
    more = len(hits) - len(shown)
    upsell = (f'<b>{more} till</b> matchar din bevakning. ' if more > 0 else "") + \
        "Med Kommunradar Pro får du varje ny träff samma morgon den publiceras, i stället för en gång i veckan."
    return f"""<div style="font-family:system-ui,Segoe UI,sans-serif;max-width:640px;margin:auto">
<div style="background:#0b1020;color:#fff;padding:22px 24px;border-radius:14px 14px 0 0"><b style="font-size:20px">KOMMUNRADAR · VECKOBREV</b>
<div style="color:#fbbf24;font-size:26px;font-weight:900;margin-top:8px">{html.escape(head)}</div>
<div style="color:#94a3b8;font-size:13px">Bevakning: {html.escape(sub["keywords"] or "alla branscher")} · {area}</div></div>
<p style="color:#334155;font-size:15px">{intro}</p>
<table style="width:100%;border-collapse:collapse">{rows_html(shown)}</table>
<div style="background:#fef3c7;border-radius:12px;padding:18px 20px;margin-top:20px;color:#0b1020">{upsell}
<div style="margin-top:12px"><a href="{html.escape(pro_url)}" style="background:#0b1020;color:#fbbf24;font-weight:800;padding:12px 18px;border-radius:10px;text-decoration:none;display:inline-block">Få alla träffar varje morgon →</a></div></div>
<p style="color:#94a3b8;font-size:12px;margin-top:24px">Källa: TED (EU:s officiella upphandlingsdatabas), bara upphandlingar över EU:s tröskelvärden.
Du får det här för att du anmälde dig till Kommunradars gratis veckobrev. Svara på mejlet för att ändra bevakningsord eller län.
Vill du inte ha fler veckobrev? Svara "avsluta"{f' eller avsluta själv i <a href="{html.escape(portal)}" style="color:#94a3b8">kundportalen</a>' if portal else ''}.</p></div>"""


def weekly_message(sub, hits, fallback, welcome, site, pro_url, portal, reply_to):
    msg = EmailMessage()
    if welcome: msg["Subject"] = "Välkommen! Här är veckans upphandlingar för dig"
    elif fallback: msg["Subject"] = f"Veckans största upphandlingar: {hits[0]['title'][:60]}"
    else: msg["Subject"] = f"{len(hits)} nya upphandlingar i veckan: {hits[0]['title'][:60]}"
    msg["From"] = os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", "")); msg["To"] = sub["email"]
    if reply_to:
        msg["Reply-To"] = reply_to
        msg["List-Unsubscribe"] = f"<mailto:{reply_to}?subject=avsluta>" + (f", <{portal}>" if portal else "")
    msg.set_content("\n".join(f"{l['title']} — {l['buyer']} — {l['url']}" for l in hits[:WEEKLY_MAX])
                    + f"\n\nFå alla träffar varje morgon med Kommunradar Pro: {pro_url}"
                    + "\n\nVill du inte ha fler veckobrev? Svara \"avsluta\"" + (f" eller avsluta i kundportalen: {portal}" if portal else "."))
    msg.add_alternative(render_weekly(hits, sub, fallback, welcome, site, pro_url, portal), subtype="html")
    return msg


def weekly_recipients(subs):
    """Free subscribers who are not also Pro customers (they already get every match daily)."""
    pro = {s["email"].lower() for s in subs if s.get("tier", "pro") == "pro"}
    return [s for s in subs if s.get("tier") == FREE and s["email"].lower() not in pro]


def smtp_connect():
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    return smtp


def check():
    """Verify the secrets without emailing anyone: Stripe answers, SMTP accepts the login."""
    ok = True
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    try:
        products = kommunradar_products()
        subs = list(subscribers())
        free = sum(1 for s in subs if s.get("tier") == FREE)
        print(f"Stripe OK ({'LIVE' if '_live_' in key else 'TEST'}): {len(products)} Kommunradar-produkt(er), "
              f"{len(subs) - free} Pro-prenumeranter (aktiva/provande), {free} på gratis veckobrev")
        if not products: print("  OBS: ingen Kommunradar-produkt ännu — kör workflowen Stripe-uppsättning")
    except Exception as e:  # noqa: BLE001 — report and continue to the SMTP check
        ok = False; print(f"Stripe FEL: {type(e).__name__}: {getattr(e, 'code', '')} {getattr(e, 'reason', e)}")
    try:
        smtp_connect().quit(); print(f"SMTP OK: inloggning på {os.environ['SMTP_HOST']} lyckades")
    except Exception as e:  # noqa: BLE001
        ok = False; print(f"SMTP FEL: {type(e).__name__}: {e}")
    portal = os.environ.get("PORTAL_URL", "")
    print("PORTAL_URL:", "saknas" if not portal else "satt")
    return ok


def send_weekly(smtp, dry, recipients, current, today, welcome):
    """Send the free weekly mail to each recipient that has something to show. Returns the number sent."""
    site, portal = os.environ.get("SITE_URL", ""), os.environ.get("PORTAL_URL", "")
    pro_url = os.environ.get("PRO_URL") or (site.rstrip("/") + "/#pris" if site else "https://kommunradar.online/#pris")
    reply_to = os.environ.get("REPLY_TO", "hej@kommunradar.online")
    sent = 0
    for sub in recipients:
        hits, fallback = weekly_hits(current, sub, today)
        if not hits: continue
        msg = weekly_message(sub, hits, fallback, welcome, site, pro_url, portal, reply_to)
        if dry: print(f"[dry-run] veckobrev till {sub['email']}: {msg['Subject']}")
        else: smtp.send_message(msg)
        sent += 1
    return sent


def weekly_main(dry):
    """Monday run: the free weekly mail. Those who signed up yesterday or today are skipped — the daily run
    sends them a welcome with the same content, so nobody gets it twice."""
    current = json.load(open("leads.json", encoding="utf8"))["leads"]
    if not os.environ.get("STRIPE_SECRET_KEY"):
        if dry: print("Inget att skicka (ingen STRIPE_SECRET_KEY)."); return
        sys.exit("STRIPE_SECRET_KEY saknas.")
    today = dt.datetime.now(dt.timezone.utc).date()
    recipients = [s for s in weekly_recipients(list(subscribers()))
                  if (d := days_since(s.get("created"), today)) is None or d >= 2]
    smtp = None if dry or not recipients else smtp_connect()
    sent = send_weekly(smtp, dry, recipients, current, today, welcome=False)
    if smtp: smtp.quit()
    print(f"{sent} veckobrev {'skulle skickas' if dry else 'skickade'} ({len(recipients)} gratisprenumeranter)")


def main():
    if "--check" in sys.argv: sys.exit(0 if check() else 1)
    dry = "--dry-run" in sys.argv
    if "--weekly" in sys.argv: return weekly_main(dry)
    prev = sys.argv[sys.argv.index("--prev") + 1] if "--prev" in sys.argv else "prev.json"
    current = json.load(open("leads.json", encoding="utf8"))["leads"]
    leads = new_leads(current, prev)
    site, portal = os.environ.get("SITE_URL", ""), os.environ.get("PORTAL_URL", "")
    print(f"{len(leads)} nya upphandlingar sedan förra körningen")
    if not dry and not os.environ.get("STRIPE_SECRET_KEY"):
        # Fail so the workflow stops before committing leads.json — otherwise these leads would never be sent.
        sys.exit("STRIPE_SECRET_KEY saknas; avbryter utan att markera upphandlingarna som skickade.")
    if not os.environ.get("STRIPE_SECRET_KEY"):
        print("Inget att skicka (ingen STRIPE_SECRET_KEY)."); return
    everyone = list(subscribers())
    subs = [s for s in everyone if s.get("tier", "pro") == "pro"]
    today = dt.datetime.now(dt.timezone.utc).date()
    welcome = [(s, m) for s in subs if (m := onboarding_mail(s, today, portal))]
    # Gratis veckobrev: morgonen efter anmälan får man direkt senaste veckans träffar, sedan varje måndag.
    free_welcome = [s for s in weekly_recipients(everyone) if days_since(s.get("created"), today) == 1]
    if not leads and not welcome and not free_welcome:
        print("Inget att skicka (inga nya upphandlingar och inga mejl till provkunder)."); return
    smtp = None
    if not dry:
        smtp = smtp_connect()
    reply_to = os.environ.get("REPLY_TO", "hej@kommunradar.online")
    sent = send_weekly(smtp, dry, free_welcome, current, today, welcome=True)
    for sub, (subject, text) in welcome:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", "")); msg["To"] = sub["email"]
        if reply_to: msg["Reply-To"] = reply_to
        msg.set_content(text)
        if dry: print(f"[dry-run] provmejl till {sub['email']}: {subject}")
        else: smtp.send_message(msg)
        sent += 1
    for sub in subs:
        if not leads: break
        hits = [l for l in leads if matches(l, keywords(sub["keywords"]), sub["lan"])]
        if not hits: continue
        for start in range(0, len(hits), MAX_PER_MAIL):  # every match is delivered, MAX_PER_MAIL per message
            batch = hits[start:start + MAX_PER_MAIL]
            msg = EmailMessage()
            msg["Subject"] = f"{len(batch)} nya upphandlingar: {batch[0]['title'][:60]}"
            msg["From"] = os.environ.get("MAIL_FROM", os.environ.get("SMTP_USER", "")); msg["To"] = sub["email"]
            if reply_to: msg["Reply-To"] = reply_to
            msg.set_content("\n".join(f"{l['title']} — {l['buyer']} — {l['url']}" for l in batch))
            msg.add_alternative(render(batch, sub, site, portal), subtype="html")
            if dry: print(f"[dry-run] {sub['email']}: {len(batch)} träffar")
            else: smtp.send_message(msg)
            sent += 1
    if smtp: smtp.quit()
    print(f"{sent} mejl {'skulle skickas' if dry else 'skickade'}")


if __name__ == "__main__":
    main()
