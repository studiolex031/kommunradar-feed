"""Uppföljning till vinnar-leads: mejl 2 (dag 4) och mejl 3 (dag 9).

    python scripts/followup_send.py --dry-run     # visa mejlen, skicka inget
    python scripts/followup_send.py --limit 20    # skicka nästa 20 som är mogna

Mejl 1 skickas av scripts/outbound_send.py. Det här skriptet rör bara bolag som
faktiskt fått mejl 1 (finns i sent.json), som inte svarat (svarat.txt) och som
inte redan fått nästa steg (followup.json).

Varför uppföljning: de flesta svar på kall B2B-utskick kommer efter påminnelsen,
inte efter första mejlet. Ett mejl och sedan tystnad lämnar pengarna på bordet.

Samma tak som första utskicket: 20 per dygn, 30 per timme, och samma brytare vid
leverantörsspärr. State ligger i .github/outbound/followup.json (hashar, aldrig
adresser i klartext) och committas av workflowen.

Endast standardbiblioteket.
"""
import csv, json, os, random, smtplib, ssl, sys, time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outbound_send as O
from leadfilter import for_stor

ROOT = O.ROOT
FOLLOWUP_STATE = os.path.join(ROOT, ".github", "outbound", "followup.json")
SVARAT = os.path.join(ROOT, ".github", "outbound", "svarat.txt")

# Dagar mellan mejlen. Dag 4 och dag 9 räknat från mejl 1.
STEG2_DAGAR = 4
STEG3_DAGAR = 5

# Priset står i mejl 2 och 3. Första mejlet sålde bara "gratis" — det var ett fel:
# priset är det enda vi vet att konkurrenterna inte matchar, och det ska stå tidigt.
PRIS = "490 kr i månaden (grundarpris)"

# Uppföljningen har ett eget tak, högre än första utskicket: hela listan på 190
# blev mogna samma dag (de skickades samma dag), och med 20/dag hade de sista
# fått "dag 4"-mejlet på dag 16 — då är det inte längre en påminnelse.
# Brevo tillåter 300/dygn, så 50/dag ligger långt under gränsen. Det som
# begränsar är domänens rykte, inte leverantören.
MAX_PER_DAG = int(os.environ.get("FOLLOWUP_MAX_DAG", "50"))
MAX_PER_TIMME = int(os.environ.get("FOLLOWUP_MAX_TIMME", "60"))


def las_followup():
    try:
        with open(FOLLOWUP_STATE, encoding="utf8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def skriv_followup(s):
    os.makedirs(os.path.dirname(FOLLOWUP_STATE), exist_ok=True)
    with open(FOLLOWUP_STATE, "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)


def las_svarat():
    """Adresser som svarat, en per rad. Rader som börjar med # ignoreras."""
    try:
        with open(SVARAT, encoding="utf8") as f:
            return {r.strip().lower() for r in f
                    if r.strip() and not r.strip().startswith("#")}
    except FileNotFoundError:
        return set()


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


def plan(rader, sent, fstate, svarat, idag=None):
    """Vilka som är mogna för nästa steg, mest försenade först.

    Returnerar [(dagar_sedan_förra_mejlet, rad, steg)].
    """
    idag = idag or date.today()
    jobb = []
    for rad in rader:
        epost = rad["epost"].strip().lower()
        if epost in O.spärrade() or epost in svarat:
            continue
        if for_stor(rad["bolag"], epost):
            continue  # för stort bolag, se leadfilter.py
        h = O.nyckel(epost)
        if h not in sent:
            continue  # har aldrig fått mejl 1
        f = fstate.get(h)
        if f is None:
            dagar = (idag - date.fromisoformat(sent[h]["datum"])).days
            if dagar >= STEG2_DAGAR:
                jobb.append((dagar, rad, 2))
        elif f.get("steg") == 2:
            dagar = (idag - date.fromisoformat(f["datum"])).days
            if dagar >= STEG3_DAGAR:
                jobb.append((dagar, rad, 3))
    jobb.sort(key=lambda x: -x[0])
    return jobb


def _exempel(rad, oppna):
    ex = O.exempel(rad, oppna)
    if ex:
        return f"Just nu finns {ex['antal']} öppna upphandlingar {ex['plats']}, till exempel:\n\n{ex['text']}"
    return "Just nu ligger över 1 500 svenska upphandlingar öppna — och nya publiceras varje dag."


def bygg(rad, oppna, steg):
    """Ämne och brödtext för steg 2 eller 3."""
    upphandling = (rad.get("upphandling") or "upphandlingen").strip()
    kopare = (rad.get("kopare") or "").strip()
    ämne = f"Re: Grattis till er vinst — {upphandling[:70]}"
    vinst = upphandling + (f" hos {kopare}" if kopare else "")

    if steg == 2:
        stycken = [
            "Hej,",
            f"Jag skrev till er om vinsten i {vinst}. Kort version:",
            "Kommunradar bevakar de svenska offentliga upphandlingarna och mejlar varje "
            "morgon de som matchar er bransch och ert län — köpare, uppskattat värde och "
            "sista anbudsdag.",
            _exempel(rad, oppna),
            f"Har ni redan ett system för bevakning är vi ingen ersättning för det — vi är "
            f"ett mejl på morgonen för {PRIS}, ingen inloggning och inget att implementera.",
            "Om det inte är relevant: svara \"nej\", så hör jag inte av mig igen.\n"
            f"Är det relevant: sju dagar gratis, inget kort — {O.SIDA}",
        ]
    else:
        stycken = [
            "Hej,",
            "Sista mejlet från mig om det här.",
            f"Ni vann {vinst}.",
            _exempel(rad, oppna),
            f"Vi kostar {PRIS}. Ett mejl på morgonen med de upphandlingar som matchar er "
            "bransch och ert län — köpare, värde och sista anbudsdag.",
            "Vill ni ha nästa liknande affär i mejlen i stället för att leta själva? "
            f"Sju dagar gratis, inget kort — {O.SIDA}",
            "Svarar ni inte hör jag inte av mig igen.",
        ]

    stycken.append(f"Vänligen,\n{O.AVSANDARE}\n{O.ORG}\nSvara \"sluta\" så skickar vi inga fler mejl.")
    return ämne, "\n\n".join(stycken)


def skicka(jobb, limit, oppna, fstate):
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    anv, lösen = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    från = os.environ.get("MAIL_FROM", anv)
    svar_till = os.environ.get("REPLY_TO") or från

    att_skicka = jobb[:limit]
    if not att_skicka:
        print("Inget moget för uppföljning i dag.")
        return []

    try:
        smtp = smtplib.SMTP(host, port, timeout=90)
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(anv, lösen)
    except smtplib.SMTPAuthenticationError as e:
        O.spärra(f"inloggning nekad: {e}")
        raise

    skickade = []
    try:
        for i, (_, rad, steg) in enumerate(att_skicka, 1):
            if len(senaste_timmen(fstate)) >= MAX_PER_TIMME:
                print(f"  Timtaket {MAX_PER_TIMME}/h nått — resten sparas till nästa körning.")
                break
            ämne, text = bygg(rad, oppna, steg)
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
                if O.är_spärr(e):
                    O.spärra(str(e)[:400])
                    raise
                print(f"  HOPPADE ÖVER {rad['epost']}: {e}")
                continue
            fstate[O.nyckel(rad["epost"])] = {
                "steg": steg,
                "datum": date.today().isoformat(),
                "tid": datetime.now().isoformat(timespec="seconds"),
                "bolag": rad["bolag"],
            }
            skriv_followup(fstate)
            skickade.append((rad, steg))
            print(f"  {i}/{len(att_skicka)}  steg {steg}  {rad['bolag']} <{rad['epost']}>")
            if i < len(att_skicka):
                time.sleep(random.uniform(4, 9))
    finally:
        try:
            smtp.quit()
        except Exception:
            pass
    return skickade


def rapport(skickade, kvar):
    to = os.environ.get("REPORT_TO")
    if not to or not skickade:
        return
    från = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"])
    svar_till = os.environ.get("REPLY_TO") or från
    msg = EmailMessage()
    msg["Subject"] = f"Uppföljning: {len(skickade)} mejl skickade ({date.today().isoformat()})"
    msg["From"] = från
    msg["To"] = to
    rader = "\n".join(f"steg {steg} — {r['bolag']} <{r['epost']}>" for r, steg in skickade)
    msg.set_content(
        f"{len(skickade)} uppföljningsmejl skickade i dag. {kvar} mogna kvar.\n\n"
        f"{rader}\n\n"
        f"Svar hanteras i {SVARAT}: lägg adressen där, en per rad.\n"
    )
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context())
    smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg)
    smtp.quit()


def las_lista():
    """Listan med bolag att följa upp.

    Lokalt finns `vinnar-leads.csv`. I molnet gör den aldrig det — den innehåller
    e-postadresser och checkas aldrig in i ett publikt repo. Då byggs listan om
    från TED i stället, samma källa som byggde den från början: samma bolag, samma
    adresser, ingen personuppgift i git. Fönstret måste vara bredare än dag 9,
    eftersom kön på 50/dygn gör att sista steget 3 går ut först runt dag 14.
    """
    path = os.environ.get("FOLLOWUP_CSV", O.CSV)
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    import winner_leads
    dagar = int(os.environ.get("FOLLOWUP_DAYS", "21"))
    print(f"Ingen CSV — hämtar vinnare från TED, senaste {dagar} dagarna.")
    rader = winner_leads.collect(dagar)
    print(f"TED gav {len(rader)} rader.")
    return rader


def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else MAX_PER_DAG
    torr = "--dry-run" in sys.argv

    rader = las_lista()
    oppna = O.las_oppna()
    sent = O.las_state()
    fstate = las_followup()
    svarat = las_svarat()

    if not torr and "--force" not in sys.argv:
        flagga = O.spärrad()
        if flagga:
            print("Körningen stoppad — kontot spärrades vid ett tidigare försök:\n" + flagga)
            print(f"Ta bort {O.SPÄRR_FIL} när spärren är hävd, eller kör med --force.")
            return

    jobb = plan(rader, sent, fstate, svarat)
    stora = sum(1 for r in rader if for_stor(r["bolag"], r["epost"]))

    redan_idag = idag_antal(fstate)
    if not torr:
        kvar_idag = max(0, MAX_PER_DAG - redan_idag)
        if kvar_idag == 0:
            print(f"Dagens tak nått: {redan_idag}/{MAX_PER_DAG} uppföljningar i dag. Inget skickas.")
            return
        limit = min(limit, kvar_idag)

    if torr:
        print(f"{len(rader)} i listan, {len(sent)} har fått mejl 1, "
              f"{len(jobb)} mogna för uppföljning, {len(svarat)} har svarat, "
              f"{stora} för stora. I dag: {redan_idag}/{MAX_PER_DAG}. "
              f"Visar {min(limit, len(jobb))}:\n")
        for dagar, rad, steg in jobb[:limit]:
            ämne, text = bygg(rad, oppna, steg)
            print("=" * 70)
            print(f"Till: {rad['epost']}  (steg {steg}, {dagar} dagar sedan förra mejlet)")
            print(f"Ämne: {ämne}\n")
            print(text)
        return

    print(f"{len(jobb)} mogna för uppföljning. Skickar högst {limit}.")
    skickade = skicka(jobb, limit, oppna, fstate)
    kvar_efter = len(jobb) - len(skickade)
    print(f"\nKlart: {len(skickade)} uppföljningar skickade. {kvar_efter} mogna kvar.")
    if skickade:
        print("Skickade till: " + ", ".join(r["bolag"] for r, _ in skickade))
    if "--report" in sys.argv:
        rapport(skickade, kvar_efter)


if __name__ == "__main__":
    main()
