import base64, json, os, urllib.request
from datetime import date
from . import data, stripe_sync

FROM = "Kommunradar <hej@kommunradar.online>"
TEST_TO = "hej@kommunradar.online"
RETURN_URL = "https://kommunradar.online/"


def post_json(path, payload):
    key = os.environ.get("LR_RESEND_API_KEY") or os.environ.get("RESEND_API_KEY")
    if not key:
        raise RuntimeError("Saknar LR_RESEND_API_KEY/RESEND_API_KEY")
    request = urllib.request.Request("https://api.resend.com/" + path,
                                     data=json.dumps(payload).encode(),
                                     headers={"Authorization": "Bearer " + key,
                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def portal_lank(customer_id):
    url = stripe_sync.stripe_post("billing_portal/sessions",
                                  {"customer": customer_id, "return_url": RETURN_URL})["url"]
    return url


def meddelande(plan, rader, avsluta, prov=False):
    rubrik = "nya vinnare" if plan == "p1" else "avtal som löper ut"
    intervall = "veckans" if plan == "p1" else "månadens"
    subject = f"Leverantörsregistret: {intervall} {rubrik}"
    if prov:
        subject = "TEST " + subject
    text = (f"Hej,\n\n"
            f"Här kommer {intervall} {rubrik} från Leverantörsregistret. "
            f"Bilagan innehåller {len(rader)} rader.\n\n"
            f"Källa: {data.KALLA}\n\n"
            f"Avsluta eller ändra din prenumeration när som helst: {avsluta}\n\n"
            f"Vänliga hälsningar,\nKommunradar\n")
    return subject, text


def filnamn(plan):
    dag = date.today().isoformat()
    return ("leverantorsregistret-nya-vinnare-" if plan == "p1"
            else "leverantorsregistret-avtal-som-loper-ut-") + dag + ".xlsx"


def send_email(subscriber, plan, rader, xlsx_bytes, dry_run=False, test_to=TEST_TO,
               post=None, portal_url=None):
    send = post or post_json
    mottagare = test_to if dry_run else subscriber.get("email")
    if not mottagare:
        raise RuntimeError("Prenumeranten saknar e-postadress")
    if dry_run and mottagare != TEST_TO:
        raise RuntimeError("Torrkörning får bara skickas till hej@kommunradar.online")
    if not dry_run and not subscriber.get("customer_id"):
        raise RuntimeError("Prenumeranten saknar Stripe-kund-ID för avslutslänk")
    avsluta = portal_url or (RETURN_URL if dry_run else portal_lank(subscriber.get("customer_id", "")))
    subject, text = meddelande(plan, rader, avsluta, prov=dry_run)
    payload = {"from": FROM, "to": [mottagare], "subject": subject, "text": text,
               "reply_to": "hej@kommunradar.online",
               "attachments": [{"filename": filnamn(plan),
                                "content": base64.b64encode(xlsx_bytes).decode("ascii")}]}
    result = send("emails", payload)
    return {"id": (result or {}).get("id", ""), "to": mottagare, "subject": subject,
            "rader": len(rader), "avsluta": avsluta}
