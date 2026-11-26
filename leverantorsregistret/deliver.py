import base64, os, smtplib, ssl
from datetime import date
from email.message import EmailMessage
from . import data, stripe_sync

FROM = "Kommunradar <hej@kommunradar.online>"
TEST_TO = "hej@kommunradar.online"
RETURN_URL = "https://kommunradar.online/"


def smtp_post(path, payload):
    """Skicka samma payload som tidigare gick till Resend via befintlig Brevo SMTP."""
    if path != "emails":
        raise RuntimeError(f"Okänd e-posttyp: {path}")
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    if not host or not user or not password:
        raise RuntimeError("Saknar SMTP_HOST/SMTP_USER/SMTP_PASS")

    msg = EmailMessage()
    msg["From"] = os.environ.get("MAIL_FROM") or payload["from"]
    msg["To"] = ", ".join(payload["to"])
    msg["Subject"] = payload["subject"]
    reply_to = os.environ.get("REPLY_TO") or payload.get("reply_to")
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(payload["text"])
    for attachment in payload.get("attachments", []):
        msg.add_attachment(base64.b64decode(attachment["content"]),
                           maintype="application",
                           subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           filename=attachment["filename"])

    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(user, password)
        smtp.send_message(msg)
    return {"id": ""}


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
    send = post or smtp_post
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
