"""Dagliga utkast för LinkedIn och övriga sociala medier för Kommunradar.

    python scripts/social_daily.py --dry-run    # skriver utkast i social-out/, mejlar inget
    python scripts/social_daily.py             # mejlar färdiga utkast till REPORT_TO

Innehållet kommer ur leads.json (TED-data). Postar INGET automatiskt — LinkedIn kräver
manuell publicering (eller LinkedIn API-nycklar i framtiden). Utkasten är klara att
kopiera och klistra in, med hashtags och CTA.

X hanteras av x_daily.py (postar automatiskt). Detta script fyller gapet för LinkedIn.
"""
import json, os, sys, time, urllib.request
from collections import Counter
from datetime import date, timedelta
from email.message import EmailMessage
import smtplib, ssl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHS = ["jan", "feb", "mars", "april", "maj", "juni", "juli", "aug", "sep", "okt", "nov", "dec"]
URL = "https://kommunradar.online"
OUT = os.path.join(ROOT, "social-out")


def load_leads():
    for path in (os.path.join(ROOT, "leads.json"),):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("leads"):
                return d["leads"]
        except (OSError, ValueError):
            pass
    # Fallback: hämta från GitHub
    try:
        with urllib.request.urlopen("https://raw.githubusercontent.com/studiolex031/kommunradar-feed/main/leads.json", timeout=30) as r:
            d = json.load(r)
        return d.get("leads", [])
    except Exception:
        return []


def kort_datum(iso):
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return ""
    return f"{d.day} {MONTHS[d.month - 1]}"


def pick(leads, today):
    open_ = [l for l in leads if str(l.get("type", "")).startswith("cn")]
    if not open_:
        return None
    day = max(l["published"] for l in open_)
    new = [l for l in open_ if l["published"] == day]
    by_region = today.toordinal() % 2 == 0
    keys = (lambda l: (l.get("regions") or [l.get("region")]) if by_region else l.get("categories", []))
    counts = Counter(k for l in new for k in keys(l) if k)
    top = [k for k, n in counts.most_common(5) if n >= 2] or [k for k, _ in counts.most_common(1)]
    if not top:
        return None
    focus = top[(today.toordinal() // 2) % len(top)]
    items = [l for l in new if focus in keys(l)]
    items.sort(key=lambda l: (l.get("deadline") or "9999", l["title"]))
    return {"kind": "län" if by_region else "bransch", "focus": focus, "day": day,
            "total": len(new), "n": len(items), "items": items}


def mkr(v):
    if not v:
        return ""
    if v >= 1e9:
        return f"{v/1e9:.1f} mdr kr".replace(".", ",")
    if v >= 1e6:
        return f"{round(v/1e6)} mkr"
    return f"{round(v/1e3)} tkr"


def linkedin_post(pick_, today):
    if not pick_:
        return None
    items = pick_["items"][:5]
    focus = pick_["focus"]
    kind = pick_["kind"]
    total = pick_["total"]
    lines = []
    lines.append(f"{total} nya upphandlingar publicerades i TED i går. {pick_['n']} av dem i {kind}en {focus}.")
    lines.append("")
    lines.append("Tre som sticker ut:")
    for l in items[:3]:
        val = mkr(l.get("value_sek"))
        lines.append(f"• {l['title'][:90]}{'…' if len(l['title'])>90 else ''}")
        lines.append(f"  Köpare: {l['buyer']}{(' · ' + val) if val else ''}")
    lines.append("")
    lines.append("Hälften av Sveriges upphandlingar i TED får 3 anbud eller färre. Fältet är ofta tomt — det är din chans.")
    lines.append("")
    lines.append("Kommunradar mejlar de som matchar din bransch och ditt län varje morgon, med köpare, värde och sista anbudsdag. 7 dagar gratis, ingen bindningstid.")
    lines.append("")
    lines.append("Länk i kommentarerna (se nedan):")
    lines.append("")
    lines.append("#upphandling #offentligsektor #småföretag #entreprenör #affärer")
    return "\n".join(lines)


def facebook_post(pick_, today):
    if not pick_:
        return None
    items = pick_["items"][:3]
    focus = pick_["focus"]
    total = pick_["total"]
    lines = []
    lines.append(f"{total} nya upphandlingar igår — {pick_['n']} i {focus}.")
    lines.append("")
    for l in items:
        lines.append(f"   {l['title'][:80]}")
        lines.append(f"   {l['buyer']}{(' · ' + mkr(l.get('value_sek'))) if l.get('value_sek') else ''}")
    lines.append("")
    lines.append("Få dem i mejlen varje morgon: kommunradar.online — 7 dagar gratis.")
    return "\n".join(lines)


def main():
    dry = "--dry-run" in sys.argv
    leads = load_leads()
    today = date.today()
    p = pick(leads, today)
    if not p:
        print("Inga upphandlingar att posta om i dag."); return
    li = linkedin_post(p, today)
    fb = facebook_post(p, today)

    os.makedirs(OUT, exist_ok=True)
    (open(os.path.join(OUT, "linkedin.txt"), "w", encoding="utf-8")).write(li)
    (open(os.path.join(OUT, "facebook.txt"), "w", encoding="utf-8")).write(fb)

    print("LinkedIn:\n" + li + "\n\n" + "="*60 + "\nFacebook/Instagram:\n" + fb)

    if dry:
        print("\n(dry-run: mejlar inget)")
        return

    to = os.environ.get("REPORT_TO")
    if not to:
        print("REPORT_TO saknas — mejlar inget"); return
    msg = EmailMessage()
    msg["Subject"] = f"Kommunradar sociala medier {today.isoformat()} — LinkedIn + Facebook utkast"
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"]); msg["To"] = to
    body = ("UTKAST FÖR MANUELL PUBLICERING (kopiera och klistra in)\n"
            "X postas automatiskt av x_daily.py.\n\n"
            "========== LINKEDIN ==========\n" + li + "\n\n"
            "========== FACEBOOK / INSTAGRAM ==========\n" + fb + "\n")
    msg.set_content(body)
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context()); smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg); smtp.quit()
    print("Mejlat till REPORT_TO")


if __name__ == "__main__":
    main()