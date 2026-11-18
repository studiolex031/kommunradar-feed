"""Skickar det första, personliga outbound-mejlet till vinnar-leads.

    python scripts/outbound_send.py --dry-run              # visa mejlen, skicka inget
    python scripts/outbound_send.py --limit 45             # skicka nästa 45 osända
    python scripts/outbound_send.py --limit 45 --days 7    # vidare lookback

Listan byggs av scripts/winner_leads.py (bolag som nyss vunnit en svensk
offentlig upphandling, med den adress de själva angett i TED).

Varför en gräns per körning: en brevlåda som skickar 190 kalla mejl på en gång
blir blockerad av Gmail och hamnar i skräppost hos mottagaren. 40–50 per
vardag är den volym som håller. Workflowen .github/workflows/outbound-vinnare.yml
kör därför en batch per vardag tills listan är slut.

State ligger i .github/outbound/sent.json (hashar, aldrig adresser i klartext)
och committas av workflowen, så ingen får samma mejl två gånger.

Endast standardbiblioteket.
"""
import csv, hashlib, json, os, random, smtplib, ssl, sys, time
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, ".github", "outbound", "sent.json")
LEADS = os.path.join(ROOT, "leads.json")
CSV = os.path.join(ROOT, "vinnar-leads.csv")

AVSANDARE = "Alexander Pålsson, grundare"
ORG = "Kommunradar · org.nr 19870929-3552 · Rävebergsvägen 130P, 424 67 Angered"
SIDA = "https://kommunradar.online/?utm_source=outbound&utm_medium=email&utm_campaign=vinnar"

# Adresser som aldrig ska få utskicket (eget, test, rollkonton hos oss).
SPÄRR = {"freeline031@gmail.com", "hej@kommunradar.online"}


def nyckel(epost):
    return hashlib.sha256(epost.strip().lower().encode()).hexdigest()[:16]


def las_state():
    try:
        with open(STATE, encoding="utf8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def skriv_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)


def las_oppna():
    """Öppna upphandlingar ur leads.json, för det konkreta exemplet i mejlet."""
    try:
        with open(LEADS, encoding="utf8") as f:
            return json.load(f).get("leads", [])
    except FileNotFoundError:
        return []


def exempel(rad, oppna):
    """En verklig, öppen upphandling som matchar bolagets län — annars bransch."""
    if not oppna:
        return None
    lan = rad.get("lan", "").strip()
    bransch = rad.get("bransch", "").strip()

    def i_lan(l):
        return bool(lan) and lan in (l.get("regions") or [l.get("region", "")])

    def i_bransch(l):
        return bool(bransch) and bransch in (l.get("categories") or [])

    # Helst samma bransch OCH samma län, annars samma bransch, annars bara länet.
    träffar = [l for l in oppna if i_lan(l) and i_bransch(l)]
    plats = f"i {lan}" + (f" inom {bransch}" if bransch else "")
    if not träffar:
        träffar = [l for l in oppna if i_bransch(l)]
        plats = f"inom {bransch}"
    if not träffar:
        träffar = [l for l in oppna if i_lan(l)]
        plats = f"i {lan}"
    if not träffar:
        return None
    träffar.sort(key=lambda l: l.get("published", ""), reverse=True)
    l = träffar[0]
    text = f"• {l.get('title', '').strip()} — {l.get('buyer', '').strip()}"
    if l.get("deadline"):
        text += f", sista dag {l['deadline']}"
    if l.get("value_sek"):
        text += f", ca {l['value_sek'] // 1000000} mkr" if l["value_sek"] >= 1000000 else f", ca {l['value_sek'] // 1000} tkr"
    return {"text": text, "antal": len(träffar), "plats": plats}


def bygg(rad, oppna):
    """Ämne och brödtext för ett bolag."""
    upphandling = (rad.get("upphandling") or "upphandlingen").strip()
    kopare = (rad.get("kopare") or "").strip()
    ämne = f"Grattis till er vinst — {upphandling[:70]}"

    stycken = [
        "Hej,",
        f"Grattis till er vinst i {upphandling}" + (f" hos {kopare}" if kopare else "") +
        " — vi såg beslutet i TED och tänkte att ni redan kan vara ute efter nästa.",
        "Vi driver Kommunradar. Vi bevakar alla svenska offentliga upphandlingar över EU:s "
        "tröskelvärden och mejlar de som matchar en viss bransch och ett visst län. Kunder får "
        "nyckeln varje morgon, med köpare, uppskattat värde och sista anbudsdag.",
    ]

    ex = exempel(rad, oppna)
    if ex:
        stycken.append(
            f"Just nu finns {ex['antal']} öppna upphandlingar {ex['plats']}, till exempel:\n\n{ex['text']}"
        )
    else:
        stycken.append(
            "Just nu ligger över 1 500 svenska upphandlingar öppna — och nya publiceras varje dag."
        )

    stycken += [
        f"Vill ni ha nästa liknande affär i mejlen i stället? Det tar en minut att svara ja, "
        f"och ni får sju dagar gratis utan kort: {SIDA}",
        f"Vänligen,\n{AVSANDARE}\n{ORG}\nSvara \"sluta\" så skickar vi inga fler mejl.",
    ]
    return ämne, "\n\n".join(stycken)


def skicka(rader, limit, oppna, state):
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    anv, lösen = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    från = os.environ.get("MAIL_FROM", anv)

    att_skicka = [r for r in rader
                  if r["epost"].strip().lower() not in SPÄRR and nyckel(r["epost"]) not in state][:limit]
    if not att_skicka:
        print("Inget kvar att skicka — alla i listan har redan fått mejlet.")
        return []

    smtp = smtplib.SMTP(host, port, timeout=90)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(anv, lösen)
    skickade = []
    try:
        for i, rad in enumerate(att_skicka, 1):
            ämne, text = bygg(rad, oppna)
            msg = EmailMessage()
            msg["Subject"] = ämne
            msg["From"] = formataddr(("Alexander på Kommunradar", från))
            msg["To"] = rad["epost"]
            msg["Reply-To"] = från
            msg["List-Unsubscribe"] = f"<mailto:{från}?subject=sluta>"
            msg.set_content(text, charset="utf-8")
            try:
                smtp.send_message(msg)
            except Exception as e:  # en dålig adress ska inte stoppa batchen
                print(f"  HOPPADE ÖVER {rad['epost']}: {e}")
                continue
            state[nyckel(rad["epost"])] = {"datum": date.today().isoformat(), "bolag": rad["bolag"]}
            skriv_state(state)
            skickade.append(rad)
            print(f"  {i}/{len(att_skicka)}  {rad['bolag']} <{rad['epost']}>")
            if i < len(att_skicka):
                time.sleep(random.uniform(4, 9))
    finally:
        smtp.quit()
    return skickade


def rapport(skickade, kvar):
    """Kort sammanfattning till REPORT_TO, så att varje batch syns i mejlen."""
    to = os.environ.get("REPORT_TO")
    if not to or not skickade:
        return
    msg = EmailMessage()
    msg["Subject"] = f"Outbound: {len(skickade)} mejl skickade till vinnare ({date.today().isoformat()})"
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"])
    msg["To"] = to
    rader = "\n".join(f"{r['bolag']} <{r['epost']}> — {r['upphandling'][:60]}" for r in skickade)
    msg.set_content(
        f"{len(skickade)} mejl skickade i dag. {kvar} kvar i listan.\n\n"
        f"{rader}\n\n"
        "Svara \"sluta\" hanteras manuellt: lägg adressen i SPÄRR i scripts/outbound_send.py.\n"
    )
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg)
    smtp.quit()


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 45
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3

    if "--csv" in sys.argv:
        path = sys.argv[sys.argv.index("--csv") + 1]
    else:
        path = CSV
        if not os.path.exists(path) or "--fresh" in sys.argv:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import winner_leads
            rader = winner_leads.collect(days)
            open(path, "w", encoding="utf-8-sig").write(winner_leads.to_csv(rader))
    with open(path, encoding="utf-8-sig") as f:
        rader = list(csv.DictReader(f))

    oppna = las_oppna()
    state = las_state()
    kvar = [r for r in rader if nyckel(r["epost"]) not in state and r["epost"].strip().lower() not in SPÄRR]

    if "--dry-run" in sys.argv:
        print(f"{len(rader)} i listan, {len(kvar)} osända. Visar {min(limit, len(kvar))}:\n")
        for rad in kvar[:limit]:
            ämne, text = bygg(rad, oppna)
            print("=" * 70)
            print(f"Till: {rad['epost']}  ({rad['adresstyp']})")
            print(f"Ämne: {ämne}\n")
            print(text)
        return

    print(f"{len(rader)} i listan, {len(kvar)} osända. Skickar högst {limit}.")
    skickade = skicka(rader, limit, oppna, state)
    kvar_efter = len(kvar) - len(skickade)
    print(f"\nKlart: {len(skickade)} skickade. {kvar_efter} kvar till nästa körning.")
    if skickade:
        print("Skickade till: " + ", ".join(r["bolag"] for r in skickade))
    if "--report" in sys.argv:
        rapport(skickade, kvar_efter)


if __name__ == "__main__":
    main()
