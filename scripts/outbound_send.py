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
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, ".github", "outbound", "sent.json")
SPÄRR_FIL = os.path.join(ROOT, ".github", "outbound", "SPARRAD")
LEADS = os.path.join(ROOT, "leads.json")
CSV = os.path.join(ROOT, "vinnar-leads.csv")

# Hårda tak. Simply.com spärrade kontot 2026-11-18 efter 149 mejl på två timmar
# och tillåter inte cold mailing alls — men taken gäller även hos en bättre
# leverantör: volymen är det som bränner avsändaren.
MAX_PER_DAG = int(os.environ.get("OUTBOUND_MAX_DAG", "20"))
MAX_PER_TIMME = int(os.environ.get("OUTBOUND_MAX_TIMME", "30"))

# Svar som betyder "kontot är spärrat", inte "den adressen var dålig".
SPÄRR_ORD = ("account has been blocked", "send limit reached", "authentication failed",
             "5.7.8", "4.7.0", "too many messages", "rate limit")

AVSANDARE = "Alexander Pålsson, grundare"
ORG = "Kommunradar · org.nr 19870929-3552 · Rävebergsvägen 130P, 424 67 Angered"
SIDA = "https://kommunradar.online/?utm_source=outbound&utm_medium=email&utm_campaign=vinnar"

# Adresser som aldrig ska få utskicket (eget, test, rollkonton hos oss).
SPÄRR = {"freeline031@gmail.com", "hej@kommunradar.online"}

# Adresser som svarat "sluta"/"nej" står i svarat.txt, en per rad. Den filen
# styr både första utskicket och uppföljningen, så en avanmälan behöver bara
# skrivas på ett ställe.
SVARAT_FIL = os.path.join(ROOT, ".github", "outbound", "svarat.txt")


def las_svarat():
    """Adresser som avanmält sig. Rader som börjar med # ignoreras."""
    try:
        with open(SVARAT_FIL, encoding="utf8") as f:
            return {r.strip().lower() for r in f
                    if r.strip() and not r.strip().startswith("#")}
    except FileNotFoundError:
        return set()


def spärrade():
    return SPÄRR | las_svarat()


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


def är_spärr(fel):
    text = str(fel).lower()
    return any(ordet in text for ordet in SPÄRR_ORD)


def spärra(orsak):
    """Skriver en spärrflagga som stoppar alla senare körningar tills den tas bort."""
    os.makedirs(os.path.dirname(SPÄRR_FIL), exist_ok=True)
    with open(SPÄRR_FIL, "w", encoding="utf8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}\n{orsak}\n")
    print(f"SPÄRRAD: {orsak}")


def spärrad():
    try:
        with open(SPÄRR_FIL, encoding="utf8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def idag_antal(state):
    d = date.today().isoformat()
    return sum(1 for v in state.values() if v.get("datum") == d)


def senaste_timmen(state):
    gräns = datetime.now() - timedelta(hours=1)
    träffar = []
    for v in state.values():
        t = v.get("tid")
        if not t:
            continue
        try:
            if datetime.fromisoformat(t) > gräns:
                träffar.append(t)
        except ValueError:
            continue
    return träffar


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
        f"och ni får sju dagar gratis utan kort. Sedan 490 kr i månaden i grundarpris: {SIDA}",
        f"Vänligen,\n{AVSANDARE}\n{ORG}\nSvara \"sluta\" så skickar vi inga fler mejl.",
    ]
    return ämne, "\n\n".join(stycken)


def skicka(rader, limit, oppna, state):
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    anv, lösen = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    från = os.environ.get("MAIL_FROM", anv)
    svar_till = os.environ.get("REPLY_TO") or från

    att_skicka = [r for r in rader
                  if r["epost"].strip().lower() not in spärrade() and nyckel(r["epost"]) not in state][:limit]
    if not att_skicka:
        print("Inget kvar att skicka — alla i listan har redan fått mejlet.")
        return []

    try:
        smtp = smtplib.SMTP(host, port, timeout=90)
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(anv, lösen)
    except smtplib.SMTPAuthenticationError as e:
        spärra(f"inloggning nekad: {e}")
        raise

    skickade = []
    try:
        for i, rad in enumerate(att_skicka, 1):
            if len(senaste_timmen(state)) >= MAX_PER_TIMME:
                print(f"  Timtaket {MAX_PER_TIMME}/h nått — resten sparas till nästa körning.")
                break
            ämne, text = bygg(rad, oppna)
            msg = EmailMessage()
            msg["Subject"] = ämne
            msg["From"] = formataddr(("Alexander på Kommunradar", från))
            msg["To"] = rad["epost"]
            msg["Reply-To"] = svar_till
            msg["List-Unsubscribe"] = f"<mailto:{svar_till}?subject=sluta>"
            msg.set_content(text, charset="utf-8")
            try:
                smtp.send_message(msg)
            except Exception as e:
                # En död adress ska inte stoppa batchen — men en spärr ska stoppa allt.
                if är_spärr(e):
                    spärra(str(e)[:400])
                    raise
                print(f"  HOPPADE ÖVER {rad['epost']}: {e}")
                continue
            state[nyckel(rad["epost"])] = {
                "datum": date.today().isoformat(),
                "tid": datetime.now().isoformat(timespec="seconds"),
                "bolag": rad["bolag"],
            }
            skriv_state(state)
            skickade.append(rad)
            print(f"  {i}/{len(att_skicka)}  {rad['bolag']} <{rad['epost']}>")
            if i < len(att_skicka):
                time.sleep(random.uniform(4, 9))
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
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
        "Svara \"sluta\" hanteras manuellt: lägg adressen i .github/outbound/svarat.txt.\n"
    )
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg)
    smtp.quit()


def spara_lista(path, nya):
    """Skriver listan utan att tappa bolag som redan finns i den.

    --fresh hämtar nya vinnare ur TED, men filen måste vara kumulativ:
    uppföljningen (followup_send.py) läser bolag som skickades för dagar sedan,
    och de finns inte i ett fönster på sju dagar.
    """
    gamla = []
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            gamla = list(csv.DictReader(f))
    sedda = {r["epost"].strip().lower() for r in gamla}
    alla = gamla + [r for r in nya if r["epost"].strip().lower() not in sedda]
    fält = list(nya[0].keys()) if nya else (list(gamla[0].keys()) if gamla else ["bolag"])
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fält)
        w.writeheader()
        w.writerows(alla)
    return len(alla) - len(gamla)


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else MAX_PER_DAG
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    torr = "--dry-run" in sys.argv

    if "--csv" in sys.argv:
        path = sys.argv[sys.argv.index("--csv") + 1]
    else:
        path = CSV
        if not os.path.exists(path) or "--fresh" in sys.argv:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import winner_leads
            rader = winner_leads.collect(days)
            nya = spara_lista(path, rader)
            print(f"{nya} nya leads tillagda i {os.path.basename(path)}.")
    with open(path, encoding="utf-8-sig") as f:
        rader = list(csv.DictReader(f))

    oppna = las_oppna()
    state = las_state()

    if not torr and "--force" not in sys.argv:
        flagga = spärrad()
        if flagga:
            print("Körningen stoppad — kontot spärrades vid ett tidigare försök:\n" + flagga)
            print(f"Ta bort {SPÄRR_FIL} när spärren är hävd, eller kör med --force.")
            return

    redan_idag = idag_antal(state)
    kvar_idag = max(0, MAX_PER_DAG - redan_idag)
    if not torr:
        if kvar_idag == 0:
            print(f"Dagens tak nått: {redan_idag}/{MAX_PER_DAG} mejl i dag. Inget skickas.")
            return
        limit = min(limit, kvar_idag)

    kvar = [r for r in rader if nyckel(r["epost"]) not in state and r["epost"].strip().lower() not in spärrade()]

    if torr:
        print(f"{len(rader)} i listan, {len(kvar)} osända. "
              f"I dag: {redan_idag}/{MAX_PER_DAG}. Visar {min(limit, len(kvar))}:\n")
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
