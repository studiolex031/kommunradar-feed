"""Automatisk outbound till bolag som nyss vunnit en svensk offentlig upphandling.

    python scripts/outbound_campaign.py                       # torrkörning: visa dagens plan + 5 exempelmejl
    python scripts/outbound_campaign.py --visa 10             # torrkörning med 10 exempel
    python scripts/outbound_campaign.py --test-to din@adress  # skicka dag 1 + uppföljning 1 och 2 till dig själv
    python scripts/outbound_campaign.py --live                # riktiga utskick, bara om outbound_guard säger ja

En körning gör, i ordning:
  1. Läser stoppsignaler: svar och studsar i inkorgen (IMAP), studs/klagomål/avanmälan hos
     Brevo, köp i Stripe, och stopplistan .github/outbound/svarat.txt.
  2. Hälsokontroll. Studs eller spamklagomål över gränsen -> spärrfil, inget skickas.
  3. Dagens tak enligt uppvärmningen (10/20/40, se outbound_guard.py).
  4. Uppföljningar som är mogna (dag 3 och dag 7), sedan nya första mejl tills taket är nått.
  5. Skickar utspritt 08:30–11:30 svensk tid med 60–180 s mellan mejlen.
  6. Skriver state (.github/outbound/kampanj.json, bara hashar och publika TED-uppgifter) och
     en rapport: siffror i workflow-sammanfattningen, namn och adresser bara i mejlet till REPORT_TO.

Utan --live, eller om någon spärr säger nej, skickas ingenting till prospekt. Läget skrivs ut först.

Endast standardbiblioteket.
"""
import csv, email, hashlib, imaplib, io, json, os, random, re, smtplib, ssl, sys, time
import urllib.parse, urllib.request
from datetime import date, datetime, timedelta
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parseaddr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outbound_guard as G  # noqa: E402
from leadfilter import GRATISMEJL, utanfor_icp  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Stockholm")
except Exception:  # pragma: no cover
    TZ = None

ROOT = G.ROOT
OUT = os.path.join(ROOT, ".github", "outbound")
STATE = os.path.join(OUT, "kampanj.json")
LEGACY_SENT = os.path.join(OUT, "sent.json")
SVARAT = os.path.join(OUT, "svarat.txt")
LEADS_JSON = os.path.join(ROOT, "leads.json")
CONFIG_JS = os.path.join(ROOT, "config.js")

TEMPLATE_VERSION = "v1-2026-11-24"
FU1_DAG, FU2_DAG = 3, 7            # dagar efter första mejlet
LOOKBACK_NYA = int(os.environ.get("OUTBOUND_DAYS", "7"))    # nya vinnare: senaste 3–7 dagarna
LOOKBACK_UPPF = 30                 # uppföljning: bygger om listan ur TED så långt bakåt
FÖNSTER = os.environ.get("OUTBOUND_WINDOW", "08:30-11:30")
JITTER = (60, 180)

AVSÄNDARNAMN = "Alexander på Kommunradar"
SIGNATUR = "Alexander Pålsson, grundare"
FÖRETAG = "Kommunradar · org.nr 19870929-3552 · Rävebergsvägen 130P, 424 67 Angered · hej@kommunradar.online"
INTEGRITET = "https://kommunradar.online/integritet.html"
STOPPRAD = "Svara STOPP/sluta så får du inget mer."
EGNA = {"hej@kommunradar.online", "freeline031@gmail.com"}


# ---------------------------------------------------------------- konfiguration

def läs_config(path=CONFIG_JS):
    """Länkarna ur config.js (samma värden som sajten visar)."""
    try:
        text = open(path, encoding="utf8").read()
    except FileNotFoundError:
        return {}
    return dict(re.findall(r"^\s*(\w+)\s*:\s*'([^']*)'", text, re.M))


CFG = läs_config()
LÄNKAR = {
    "black_week": CFG.get("blackWeekLink", ""),
    "black_week_slut": CFG.get("blackWeekEnds", ""),
    "grundare": CFG.get("founderLink") or "https://buy.stripe.com/7sYeVcbwc5ID9j7fOUg7e03",
    "manad": CFG.get("paymentLink", ""),
    "gratis": "https://kommunradar.online/veckobrev.html",
}

# Priserna är kontrollerade mot Stripe 2026-11-24 (pris-id i HANDOFF.md / stripe_setup.py).
ERBJUDANDEN = {
    "black_week": ("Black Week t.o.m. {slut}: helt år för 4 900 kr (ord. 7 900 kr). Betalas direkt, "
                   "ingen provperiod, bara 10 platser. Ingen moms."),
    "grundare": ("Grundarpris: 490 kr/mån, låst så länge ni är kund. Inget dras de första 7 dagarna "
                 "och ni kan avsluta när som helst. Ingen moms."),
    "manad": ("990 kr/mån. Inget dras de första 7 dagarna och ni kan avsluta när som helst. Ingen moms."),
}
INGÅR = ("Ingår: ett mejl varje morgon med nya svenska upphandlingar från TED som matchar era "
         "bevakningsord och ert län, med köpare, värde när det finns och sista anbudsdag.")


def välj_erbjudande(idag=None, slutsålda=()):
    """Exakt en primär betallänk: Black Week om den gäller, annars grundarpris, annars månadspris."""
    idag = idag or date.today()
    bw_slut = LÄNKAR["black_week_slut"]
    if (LÄNKAR["black_week"] and bw_slut and idag.isoformat() <= bw_slut
            and "black_week" not in slutsålda):
        d = date.fromisoformat(bw_slut)
        return "black_week", ERBJUDANDEN["black_week"].format(slut=f"{d.day}/{d.month}"), LÄNKAR["black_week"]
    if LÄNKAR["grundare"] and "grundare" not in slutsålda:
        return "grundare", ERBJUDANDEN["grundare"], LÄNKAR["grundare"]
    return "manad", ERBJUDANDEN["manad"], LÄNKAR["manad"]


def med_ref(länk, lead_id, steg):
    """Stripe-betallänkar tar client_reference_id: köpet kan då knytas till leadet utan e-post i URL:en."""
    if "buy.stripe.com" not in länk:
        return länk
    return f"{länk}?client_reference_id=kr_{lead_id}_{steg}"


# ---------------------------------------------------------------- hjälpfunktioner

def nyckel(epost):
    """Samma 16-teckens hash som outbound_send.py, så de två listorna går att jämföra."""
    return hashlib.sha256((epost or "").strip().lower().encode()).hexdigest()[:16]


def maska(epost):
    """För publika loggar: a***@bolag.se."""
    epost = (epost or "").strip().lower()
    if "@" not in epost:
        return "***"
    lokal, dom = epost.split("@", 1)
    return f"{lokal[:1]}***@{dom}"


EPOST_RE = re.compile(r"^[a-z0-9._%+'-]+@[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$")


def normalisera(epost):
    """Gemener, utan blanksteg och mailto:, eller "" om adressen inte är giltig."""
    e = (epost or "").strip().lower().replace("mailto:", "").strip(" .;,<>")
    if not EPOST_RE.match(e) or ".." in e:
        return ""
    if e.rsplit("@", 1)[1] in {"example.com", "example.se", "test.se", "domain.com"}:
        return ""
    return e


def har_mx(dom, _cache={}):
    """MX-post via DNS-over-HTTPS. None = vet inte (nätfel), då släpps adressen igenom."""
    if dom in _cache:
        return _cache[dom]
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": dom, "type": "MX"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/dns-json"}),
                                    timeout=8) as r:
            svar = json.load(r)
        ok = svar.get("Status") == 0 and any(a.get("type") == 15 for a in svar.get("Answer") or [])
    except Exception:
        ok = None
    _cache[dom] = ok
    return ok


ADRESSRANG = [  # lägre = bättre. Personlig adress på notisen först, anbudsfunktion sist.
    (re.compile(r"^(sales|salj|forsaljning|offert|order|vd|ceo)\b"), 1),
    (re.compile(r"^(info|kontakt|contact|hej|hello|post|mail|office|kontoret)\b"), 2),
    (re.compile(r"^(anbud|upphandling|upphandlingar|tender|offentlig)"), 3),
]


def adressrang(epost, adresstyp):
    lokal = epost.split("@", 1)[0]
    for mönster, rang in ADRESSRANG:
        if mönster.match(lokal):
            return rang
    return 0 if adresstyp == "personlig" else 2


def target_reason(rad, rang):
    typ = {0: "personlig kontaktadress", 1: "sälj-/offertadress", 2: "bolagets allmänna adress",
           3: "anbudsadress (ingen bättre kontakt i notisen)"}[rang]
    delar = [f"{typ} angiven för vinnaren i TED {rad.get('ted', '?')}",
             "SMB-filter ok (ej koncern, myndighet, börsbolag eller anbudsbyrå)"]
    if rad.get("bransch"):
        delar.append(f"bransch {rad['bransch']}")
    if rad.get("anbud") not in ("", None):
        delar.append(f"{rad['anbud']} anbud i upphandlingen")
    return "; ".join(delar)


# ---------------------------------------------------------------- state och suppression

def läs_json(path, standard):
    try:
        with open(path, encoding="utf8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return standard


def läs_state(path=None):
    s = läs_json(path or STATE, {})
    s.setdefault("version", 1)
    s.setdefault("leads", {})
    s.setdefault("dagar", {})
    return s


def skriv_state(s, path=None):
    path = path or STATE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def läs_svarat(path=None):
    path = path or SVARAT
    """Stopplistan: adresser och/eller 16-teckens hashar (en per rad, # = kommentar)."""
    adresser, hashar = set(), set()
    try:
        for r in open(path, encoding="utf8"):
            r = r.split("#", 1)[0].strip().lower()
            if not r:
                continue
            if re.fullmatch(r"[0-9a-f]{16}", r):
                hashar.add(r)
            elif "@" in r:
                adresser.add(r)
                hashar.add(nyckel(r))
            elif r.startswith("@"):
                adresser.add(r)
    except FileNotFoundError:
        pass
    return adresser, hashar


def stoppade_domäner(state):
    """Domäner där någon svarat nej/studsat/köpt: ingen annan på samma bolag får mejl."""
    return {l["dh"] for l in state["leads"].values()
            if l.get("dh") and l.get("status") not in ("active", "completed")}


def domänhash(epost):
    d = epost.rsplit("@", 1)[-1]
    return "" if d in GRATISMEJL else hashlib.sha256(d.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- leads

def bygg_leads(rader, state, legacy, svarat_hashar, mx=None):
    """Vinnarrader från winner_leads.collect -> (valda, bortfiltrerade[(rad, orsak)])."""
    mx = mx or har_mx
    valda, bort = [], []
    sedda_e, sedda_org, sedda_dom = set(), set(), set()
    stoppdom = stoppade_domäner(state)
    kontaktade_dom = {l.get("dh") for l in state["leads"].values() if l.get("dh")}
    for rad in rader:
        e = normalisera(rad.get("epost"))
        if not e:
            bort.append((rad, "ogiltig e-post")); continue
        h = nyckel(e)
        dh = domänhash(e)
        orsak = utanfor_icp(rad.get("bolag"), e)
        if orsak:
            bort.append((rad, orsak)); continue
        if e in EGNA:
            bort.append((rad, "egen adress")); continue
        if h in svarat_hashar:
            bort.append((rad, "stopplistan")); continue
        if h in legacy:
            bort.append((rad, "redan kontaktad i tidigare utskick")); continue
        if h in state["leads"]:
            bort.append((rad, "redan i kampanjen")); continue
        if dh and dh in stoppdom:
            bort.append((rad, "någon på samma bolag har svarat/stoppat")); continue
        if dh and dh in kontaktade_dom:
            bort.append((rad, "bolaget redan kontaktat via annan adress")); continue
        org = (rad.get("orgnr") or "").strip()
        if h in sedda_e or (org and org in sedda_org) or (dh and dh in sedda_dom):
            bort.append((rad, "dubblett")); continue
        if mx and mx(e.rsplit("@", 1)[1]) is False:
            bort.append((rad, "domänen tar inte emot e-post (ingen MX)")); continue
        sedda_e.add(h); sedda_dom.add(dh)
        if org:
            sedda_org.add(org)
        rang = adressrang(e, rad.get("adresstyp", ""))
        valda.append({**rad, "epost": e, "lead_id": h, "dh": dh, "rang": rang,
                      "target_reason": target_reason(rad, rang)})
    valda.sort(key=lambda r: (r["rang"], -(int(r["publicerad"].replace("-", "")) if r.get("publicerad") else 0),
                              r["anbud"] if r.get("anbud") not in ("", None) else 99))
    return valda, bort


def öppna_upphandlingar(path=None, idag=None):
    path = path or LEADS_JSON
    idag = (idag or date.today()).isoformat()
    data = läs_json(path, {})
    return [l for l in data.get("leads", []) if not l.get("deadline") or l["deadline"] >= idag]


def matchande(rad, öppna):
    """(antal, bästa exempel, beskrivning) bland öppna upphandlingar för bolagets bransch/län."""
    bransch, lan = (rad.get("bransch") or "").strip(), (rad.get("lan") or "").strip()

    def i_lan(l):
        return bool(lan) and lan in (l.get("regions") or [l.get("region", "")])

    def i_bransch(l):
        return bool(bransch) and bransch in (l.get("categories") or [])

    for urval, besk in (([l for l in öppna if i_bransch(l) and i_lan(l)], f"inom {bransch} i {lan}"),
                        ([l for l in öppna if i_bransch(l)], f"inom {bransch}"),
                        ([l for l in öppna if i_lan(l)], f"i {lan}")):
        if urval:
            urval.sort(key=lambda l: l.get("published", ""), reverse=True)
            return len(urval), urval[0], besk
    return 0, None, ""


# ---------------------------------------------------------------- mallar

def kort_titel(t, n=48):
    t = re.sub(r"\s+", " ", (t or "").strip().strip('"'))
    if len(t) <= n:
        return t
    return t[:n].rsplit(" ", 1)[0].rstrip(",.;:–-") + "…"


def ämnesrad(rad):
    titel = re.sub(r"^(upphandling|ramavtal|avtal)\s+(av|avseende|gällande|för)\s+", "",
                   (rad.get("upphandling") or "").strip(), flags=re.I)
    titel = kort_titel(titel[:1].lower() + titel[1:] if titel[:2].istitle() else titel)
    if len(titel) < 8 and rad.get("bransch"):
        titel = rad["bransch"].lower()
    return f"Nästa upphandling efter {titel}?"


def fot(rad):
    return (f"{SIGNATUR}\n{FÖRETAG}\n\n"
            f"Varför fick ni det här? Adressen står som kontakt för vinnaren i den publika TED-notisen "
            f"{rad.get('ted', '')}. Så hanterar vi uppgifter: {INTEGRITET}\n{STOPPRAD}")


def mejl(rad, steg, öppna, idag=None, slutsålda=()):
    """(ämne, text, erbjudande) för steg 1 (dag 1), 2 (dag 3) eller 3 (dag 7)."""
    idag = idag or date.today()
    lid = rad.get("lead_id") or nyckel(rad.get("epost", ""))
    namn, erbj, länk = välj_erbjudande(idag, slutsålda)
    länk = med_ref(länk, lid, steg)
    gratis = LÄNKAR["gratis"]
    upph = (rad.get("upphandling") or "upphandlingen").strip()
    köpare = (rad.get("kopare") or "").strip()
    antal, ex, besk = matchande(rad, öppna)
    ämne = ämnesrad(rad)

    if steg == 1:
        if antal:
            läge = f"Just nu finns {antal} öppna upphandlingar {besk} i vår lista."
        else:
            läge = f"Just nu finns {len(öppna)} öppna svenska upphandlingar i vår lista."
        stycken = [
            "Hej,",
            f"grattis till att ni vann \"{upph}\"" + (f" hos {köpare}" if köpare else "") +
            ". Jag såg tilldelningen i TED.",
            "Det svåra brukar sällan vara själva anbudet, utan att få syn på nästa relevanta "
            "upphandling i tid.",
            "Kommunradar är ett dagligt mejl med nya svenska upphandlingar från TED, filtrerat på "
            f"er bransch och ert län. {läge}",
            f"{erbj}\n{länk}\n{INGÅR}",
            f"Hellre börja gratis? Veckobrevet med veckans upphandlingar, inget kort: {gratis}",
            "Vänliga hälsningar",
        ]
    elif steg == 2:
        ämne = "Re: " + ämne
        if ex:
            exempel = (f"Här är en öppen upphandling {besk} som liknar det ni vann:\n\n"
                       f"• {kort_titel(ex.get('title'), 90)}, {ex.get('buyer', '').strip()}"
                       + (f". Sista anbudsdag {ex['deadline']}" if ex.get("deadline") else "") +
                       (f".\n  {ex['url']}" if ex.get("url") else "."))
        else:
            exempel = f"Just nu finns {len(öppna)} öppna svenska upphandlingar i vår lista."
        stycken = [
            "Hej igen,",
            "en kort uppföljning. " + exempel,
            f"Den sortens träffar får ni varje morgon med Kommunradar. {erbj}\n{länk}",
            f"Eller gratis veckobrev: {gratis}",
            "Hälsningar",
        ]
    else:
        ämne = "Re: " + ämne
        bevakning = " i ".join(x for x in ((rad.get("bransch") or "").lower(), rad.get("lan") or "") if x) \
            or "era upphandlingar"
        stycken = [
            "Hej,",
            f"sista mejlet från mig: vill ni ha en bevakning på {bevakning}?",
            f"Gratis veckobrev: {gratis}\nEller dagligt mejl: {erbj}\n{länk}",
            "Hör ni inte av er skickar jag inget mer.",
            "Hälsningar",
        ]
    return ämne, "\n\n".join(stycken) + "\n" + fot(rad), namn


def bygg_meddelande(rad, steg, öppna, från, svar_till, till=None, test=False, idag=None):
    ämne, text, erbj = mejl(rad, steg, öppna, idag)
    msg = EmailMessage()
    msg["Subject"] = ("[TEST] " if test else "") + ämne
    msg["From"] = formataddr((AVSÄNDARNAMN, från))
    msg["To"] = till or rad["epost"]
    msg["Reply-To"] = svar_till
    msg["Date"] = formatdate(localtime=True)
    dom = G.domän(från) or "kommunradar.online"
    lid = rad.get("lead_id") or nyckel(rad["epost"])
    msg["Message-ID"] = f"<kr-{lid}-{steg}{'-test' if test else ''}@{dom}>"
    if steg > 1:
        msg["In-Reply-To"] = msg["References"] = f"<kr-{lid}-1{'-test' if test else ''}@{dom}>"
    msg["List-Unsubscribe"] = f"<mailto:{svar_till}?subject=STOPP>"
    msg["X-Kommunradar-Kampanj"] = f"vinnare/{TEMPLATE_VERSION}/steg{steg}"
    msg.set_content(text, charset="utf-8")
    return msg, erbj


# ---------------------------------------------------------------- stoppsignaler

STOPP_RE = re.compile(r"\b(stopp|stop|sluta|avsluta|avregistrera|avanmäl|ta bort|unsubscribe|remove me|"
                      r"nej tack|inte intresserad|ej intresserad|inga fler|no thanks|not interested)\b", re.I)
INTRESSE_RE = re.compile(r"\b(intresserad|låter (bra|intressant)|berätta mer|ring mig|ring gärna|"
                         r"hur fungerar|vill gärna|kan ni|demo|testa)\b", re.I)
AUTO_ÄMNE = re.compile(r"^(autosvar|automatiskt svar|automatic reply|auto(matic)?[- ]?reply|frånvaro|"
                       r"out of office|abwesenheit|fravær|poissa)", re.I)
CITAT = re.compile(r"^\s*(>|från:|from:|skickat:|sent:|den .{0,80} skrev|on .{0,80} wrote|-{3,}\s*original)",
                   re.I | re.M)


def _text(msg):
    delar = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get_content_type() == "text/plain" and not part.get_filename():
            try:
                delar.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
    if not delar:
        for part in (msg.walk() if msg.is_multipart() else [msg]):
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True) or b""
                delar.append(re.sub(r"<[^>]+>", " ", html.decode(part.get_content_charset() or "utf-8", "replace")))
    return "\n".join(delar)


def egen_text(brödtext):
    """Bara det mottagaren själv skrev: allt före citatet, utan vår egen stopprad."""
    m = CITAT.search(brödtext)
    t = brödtext[:m.start()] if m else brödtext
    return t.replace(STOPPRAD, "")[:3000]


def klassa(msg):
    """('studs'|'auto'|'stopp'|'intresse'|'svar', [adresser som berörs])."""
    från = parseaddr(msg.get("From", ""))[1].lower()
    ämne = str(make_header(decode_header(msg.get("Subject", ""))))
    ctype = msg.get_content_type()
    if (ctype == "multipart/report" or re.match(r"(mailer-daemon|postmaster)@", från)
            or re.search(r"(undeliverable|delivery status notification|returned mail|kunde inte levereras|"
                         r"olevererbart|mail delivery failed)", ämne, re.I)):
        text = msg.as_string()
        mott = set(m.lower() for m in re.findall(r"(?:final|original)-recipient:\s*rfc822;\s*<?([^\s>]+)",
                                                  text, re.I))
        if not mott:
            mott = set(m.lower() for m in re.findall(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+", text))
        return "studs", sorted(mott)
    auto = msg.get("Auto-Submitted", "no").lower()
    if (auto and auto != "no") or msg.get("X-Autoreply") or msg.get("X-Autorespond") or AUTO_ÄMNE.match(ämne):
        return "auto", [från]
    text = egen_text(_text(msg))
    if STOPP_RE.search(text) or STOPP_RE.search(ämne.replace("Re:", "")):
        return "stopp", [från]
    if INTRESSE_RE.search(text):
        return "intresse", [från]
    return "svar", [från]


def läs_inkorg(dagar=14):
    """Svar och studsar ur inkorgen (bara läsning, inget flaggas eller flyttas)."""
    host, anv, lösen = (os.environ.get(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS"))
    if not (host and anv and lösen):
        return None
    sedan = (date.today() - timedelta(days=dagar)).strftime("%d-%b-%Y")
    ut = []
    imap = imaplib.IMAP4_SSL(host, int(os.environ.get("IMAP_PORT", "993")),
                             ssl_context=ssl.create_default_context())
    try:
        imap.login(anv, lösen)
        imap.select(os.environ.get("IMAP_FOLDER", "INBOX"), readonly=True)
        _, data = imap.search(None, "SINCE", sedan)
        for num in (data[0] or b"").split()[-500:]:
            _, d = imap.fetch(num, "(BODY.PEEK[])")
            if d and isinstance(d[0], tuple):
                ut.append(klassa(email.message_from_bytes(d[0][1])))
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return ut


def brevo_händelser(dagar=14):
    """[(typ, epost)] för studs, spamklagomål, avanmälan och blockerade hos Brevo. None = ej konfigurerat."""
    nyckel_ = os.environ.get("BREVO_API_KEY")
    if not nyckel_:
        return None
    typer = {"hardBounces": "studs", "spam": "klagomal", "unsubscribed": "stopp", "blocked": "stopp",
             "invalid": "studs"}
    ut = []
    for ev, typ in typer.items():
        url = ("https://api.brevo.com/v3/smtp/statistics/events?" +
               urllib.parse.urlencode({"limit": 2500, "days": dagar, "event": ev}))
        req = urllib.request.Request(url, headers={"api-key": nyckel_, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                for e in json.load(r).get("events", []) or []:
                    if e.get("email"):
                        ut.append((typ, e["email"].lower()))
        except Exception as e:
            print(f"  Brevo {ev}: kunde inte läsas ({str(e)[:80]})")
    return ut


def stripe_köp(dagar=30):
    """(client_reference_id:n, e-posthashar, slutsålda erbjudanden) ur Stripe. None = ej konfigurerat."""
    key = os.environ.get("STRIPE_SECRET_KEY") or os.environ.get("STRIPE_READ_KEY")
    if not key:
        return None
    sedan = int((datetime.now() - timedelta(days=dagar)).timestamp())
    refs, hashar = set(), set()
    url = ("https://api.stripe.com/v1/checkout/sessions?" +
           urllib.parse.urlencode({"limit": 100, "status": "complete", "created[gte]": sedan}))
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            for s in json.load(r).get("data", []):
                if s.get("client_reference_id"):
                    refs.add(s["client_reference_id"])
                e = (s.get("customer_details") or {}).get("email")
                if e:
                    hashar.add(nyckel(e))
    except Exception as e:
        print(f"  Stripe: kunde inte läsas ({str(e)[:80]})")
    slut = set()
    for namn in ("black_week", "grundare"):
        länk = LÄNKAR[namn]
        if not länk:
            continue
        try:
            req = urllib.request.Request("https://api.stripe.com/v1/payment_links?limit=100",
                                         headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                for pl in json.load(r).get("data", []):
                    if pl.get("url") == länk:
                        rest = (pl.get("restrictions") or {}).get("completed_sessions") or {}
                        if not pl.get("active") or (rest and rest.get("count", 0) >= rest.get("limit", 1e9)):
                            slut.add(namn)
        except Exception:
            pass
    return refs, hashar, slut


PRIO = {"customer": 6, "complaint": 5, "bounced": 4, "unsubscribed": 3, "interested": 2, "replied": 1,
        "blocked": 3}


def stoppa(lead, status, orsak, nu=None):
    """Sätter stoppstatus, men skriver aldrig över en allvarligare."""
    if lead.get("status") in PRIO and PRIO[lead["status"]] >= PRIO[status]:
        return False
    lead["status"] = status
    lead["stop_reason"] = orsak
    lead["stopped_at"] = (nu or datetime.now()).isoformat(timespec="seconds")
    return True


def tillämpa_signaler(state, inkorg, brevo, stripe, svarat_hashar):
    """Uppdaterar state med alla stoppsignaler. Returnerar räknare per typ."""
    leads = state["leads"]
    per_dom = {}
    for lid, l in leads.items():
        if l.get("dh"):
            per_dom.setdefault(l["dh"], []).append(lid)
    räkna = {"stopp": 0, "studs": 0, "svar": 0, "intresse": 0, "klagomal": 0, "kund": 0, "auto": 0}

    def träffar(adress):
        h = nyckel(adress)
        ids = [h] if h in leads else []
        dh = domänhash(adress) if "@" in adress else ""
        return ids + [i for i in per_dom.get(dh, []) if i not in ids]

    for lid, l in leads.items():
        if lid in svarat_hashar and stoppa(l, "blocked", "stopplistan svarat.txt"):
            räkna["stopp"] += 1
    for typ, adresser in inkorg or []:
        if typ == "auto":
            räkna["auto"] += 1
            continue
        status = {"studs": "bounced", "stopp": "unsubscribed", "intresse": "interested", "svar": "replied"}[typ]
        for a in adresser:
            # en studs gäller bara exakt den adressen; ett svar stoppar hela bolaget
            ids = ([nyckel(a)] if nyckel(a) in leads else []) if typ == "studs" else träffar(a)
            for i in ids:
                if stoppa(leads[i], status, f"inkorg: {typ}"):
                    räkna[typ] += 1
    for typ, a in brevo or []:
        h = nyckel(a)
        if h in leads:
            status = {"studs": "bounced", "klagomal": "complaint", "stopp": "unsubscribed"}[typ]
            if stoppa(leads[h], status, f"brevo: {typ}"):
                räkna[typ] += 1
    if stripe:
        refs, hashar, _ = stripe
        ref_ids = {r.split("_")[1] for r in refs if r.startswith("kr_") and r.count("_") >= 2}
        for lid, l in leads.items():
            if lid in hashar or lid in ref_ids:
                if stoppa(l, "customer", "köp i Stripe"):
                    räkna["kund"] += 1
    return räkna


# ---------------------------------------------------------------- planering

def mogna_uppföljningar(state, idag=None):
    """[(lead_id, steg)] mogna idag, äldst först. Steg 2 = dag 3, steg 3 = dag 7."""
    idag = idag or date.today()
    jobb = []
    for lid, l in state["leads"].items():
        if l.get("status") != "active" or not l.get("sent_at"):
            continue
        dagar = (idag - date.fromisoformat(l["sent_at"][:10])).days
        if not l.get("followup1_at"):
            if dagar >= FU1_DAG:
                jobb.append((dagar, lid, 2))
        elif not l.get("followup2_at"):
            sedan_fu1 = (idag - date.fromisoformat(l["followup1_at"][:10])).days
            if dagar >= FU2_DAG and sedan_fu1 >= 2:
                jobb.append((dagar, lid, 3))
    jobb.sort(key=lambda x: (-x[0], x[1]))
    return [(lid, steg) for _, lid, steg in jobb]


def lokal_tid():
    return datetime.now(TZ) if TZ else datetime.now()


def fönster(nu=None):
    nu = nu or lokal_tid()
    a, b = FÖNSTER.split("-")
    start = nu.replace(hour=int(a[:2]), minute=int(a[3:5]), second=0, microsecond=0)
    slut = nu.replace(hour=int(b[:2]), minute=int(b[3:5]), second=0, microsecond=0)
    return start, slut


# ---------------------------------------------------------------- sändning

class Sändare:
    def __init__(self, env=os.environ):
        self.host, self.port = env["SMTP_HOST"], int(env.get("SMTP_PORT") or 587)
        self.anv, self.lösen = env["SMTP_USER"], env["SMTP_PASS"]
        self.från = env["MAIL_FROM"]
        self.svar_till = env.get("REPLY_TO") or "hej@kommunradar.online"
        fel = G.sänddomän_fel(self.host, self.från)
        if fel:
            raise SystemExit("Sändning nekad: " + "; ".join(fel))

    def skicka(self, msg):
        if self.port == 465:
            s = smtplib.SMTP_SSL(self.host, self.port, timeout=60, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(self.host, self.port, timeout=60)
            s.starttls(context=ssl.create_default_context())
        try:
            s.login(self.anv, self.lösen)
            s.send_message(msg)
        finally:
            try:
                s.quit()
            except Exception:
                pass


def avvisad_adress(fel):
    """Permanent fel för just den adressen (5xx på mottagaren), inte för avsändaren."""
    if isinstance(fel, smtplib.SMTPRecipientsRefused):
        return all(500 <= kod < 600 for kod, _ in fel.recipients.values())
    return False


# ---------------------------------------------------------------- rapport

def sammanfattning(state, plan, bort, räkna, skickade, läge, tak, dag_nr, h):
    leads = state["leads"].values()
    status = {}
    for l in leads:
        status[l.get("status", "?")] = status.get(l.get("status", "?"), 0) + 1
    intresse = status.get("interested", 0)
    filtrerade = {}
    for _, orsak in bort:
        filtrerade[orsak] = filtrerade.get(orsak, 0) + 1
    return {
        "datum": date.today().isoformat(), "lage": läge, "sandningsdag": dag_nr, "dagstak": tak,
        "planerade": len(plan), "skickade": skickade,
        "filtrerade": filtrerade, "signaler_idag": räkna, "status_totalt": status,
        "halsa_7d": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in h.items()},
        "pipeline": {"aktiva_i_sekvens": status.get("active", 0), "intresserade_svar": intresse,
                     "kunder": status.get("customer", 0),
                     "om_alla_intresserade_koper_kr": intresse * 4900},
        "template_version": TEMPLATE_VERSION,
    }


def skriv_publik_rapport(s, katalog):
    """Bara siffror. Inga namn, adresser eller bolag — repot och dess loggar är publika."""
    os.makedirs(katalog, exist_ok=True)
    with open(os.path.join(katalog, f"rapport-{s['datum']}.json"), "w", encoding="utf8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    sum_fil = os.environ.get("GITHUB_STEP_SUMMARY")
    if sum_fil:
        with open(sum_fil, "a", encoding="utf8") as f:
            f.write(f"## Outbound vinnare {s['datum']} ({s['lage']})\n\n"
                    f"Sändningsdag {s['sandningsdag']}, tak {s['dagstak']}. "
                    f"Planerade {s['planerade']}, skickade {sum(s['skickade'].values())} "
                    f"({s['skickade']}).\n\n"
                    f"Hälsa 7 d: {s['halsa_7d']}\n\nSignaler: {s['signaler_idag']}\n\n"
                    f"Status totalt: {s['status_totalt']}\n\nFiltrerade: {s['filtrerade']}\n")


def privat_rapport(s, rader, sändare):
    """Rapport med namn och adresser, bara till REPORT_TO (Alexanders egen adress)."""
    till = os.environ.get("REPORT_TO")
    if not till or not sändare:
        return
    msg = EmailMessage()
    msg["Subject"] = (f"Outbound vinnare {s['datum']}: {sum(s['skickade'].values())} skickade, "
                      f"{s['signaler_idag'].get('intresse', 0)} intresserade, {s['lage']}")
    msg["From"] = formataddr(("Kommunradar outbound", sändare.från))
    msg["To"] = till
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["steg", "status", "bolag", "epost", "target_reason", "upphandling",
                                        "kopare", "bransch", "lan", "ted", "orgnr", "erbjudande"],
                       extrasaction="ignore")
    w.writeheader()
    w.writerows(rader)
    msg.set_content(json.dumps(s, ensure_ascii=False, indent=1) +
                    "\n\nIntresserade och övriga svar: se inkorgen hej@kommunradar.online. "
                    "Nödstopp: se docs/outbound-vinnare.md.\n")
    msg.add_attachment(buf.getvalue().encode("utf-8-sig"), maintype="text", subtype="csv",
                       filename=f"outbound-{s['datum']}.csv")
    sändare.skicka(msg)


# ---------------------------------------------------------------- huvudflöde

def hämta_vinnare(dagar):
    import winner_leads
    return winner_leads.collect(dagar)


def kör(args, env=os.environ, hämta=hämta_vinnare, sov=time.sleep):
    live_begärt = "--live" in args
    test_till = args[args.index("--test-to") + 1] if "--test-to" in args else ""
    visa = int(args[args.index("--visa") + 1]) if "--visa" in args else 5

    live, fel, info = G.läge(env)
    if live_begärt and not live:
        print("::error::--live begärt men spärrarna säger nej:")
        for f in fel:
            print("  -", f)
        return 2
    läge = "LIVE" if live_begärt else ("TEST" if test_till else "TORRKÖRNING")
    print(f"Läge: {läge}")
    if not live_begärt:
        for f in fel:
            print("  (för live saknas)", f)

    state = läs_state()
    legacy = set(läs_json(LEGACY_SENT, {}).keys())
    _, svarat_hashar = läs_svarat()
    öppna = öppna_upphandlingar()

    # 1. stoppsignaler
    inkorg = brevo = stripe = None
    if läge != "TEST":
        try:
            inkorg = läs_inkorg()
        except Exception as e:
            print(f"  Inkorgen kunde inte läsas: {str(e)[:120]}")
            if live_begärt:
                print("::error::Utan svarsläsning skickas inget (svar måste kunna stoppa uppföljning).")
                return 3
        brevo = brevo_händelser()
        stripe = stripe_köp()
    räkna = tillämpa_signaler(state, inkorg, brevo, stripe, svarat_hashar)
    slutsålda = stripe[2] if stripe else set()

    # 2. hälsa och tak
    h = G.hälsa(state["leads"])
    beslut, orsak = G.hälsobeslut(h)
    if beslut == "stopp" and live_begärt:
        G.spärra(orsak)
        skriv_state(state)
        return 4
    start = env.get("OUTBOUND_WARMUP_START") or date.today().isoformat()
    dag_nr = G.sändningsdag(state["dagar"].keys(), date.fromisoformat(start))
    tak = G.dagstak(dag_nr, beslut, klagomål_kända=brevo is not None,
                    tak=int(env.get("OUTBOUND_MAX_DAG") or G.FULLT_TAK))
    redan = sum(state["dagar"].get(date.today().isoformat(), {}).values())
    kvar = max(0, tak - redan)
    print(f"Sändningsdag {dag_nr}, tak {tak}, redan skickat i dag {redan}. Hälsa: {h} -> {beslut} {orsak}")

    # 3. leads: nya vinnare + ombyggd lista för uppföljning
    rader_nya = hämta(LOOKBACK_NYA)
    nya, bort = bygg_leads(rader_nya, state, legacy, svarat_hashar)
    uppf = mogna_uppföljningar(state)
    index = {}
    if uppf:
        for r in hämta(LOOKBACK_UPPF):
            e = normalisera(r.get("epost"))
            if e:
                index.setdefault(nyckel(e), {**r, "epost": e})
    plan = []
    for lid, steg in uppf:
        if lid in index:
            plan.append((steg, {**index[lid], "lead_id": lid,
                                "target_reason": state["leads"][lid].get("target_reason", "")}))
        else:
            # Hittas inte längre i TED-fönstret: avsluta hellre än att gissa adressen.
            state["leads"][lid]["status"] = "completed"
            state["leads"][lid]["stop_reason"] = "lead saknas i TED-fönstret"
    plan += [(1, r) for r in nya]
    plan = plan[:kvar] if live_begärt else plan
    print(f"{len(rader_nya)} vinnare hämtade, {len(nya)} kvalificerade, {len(bort)} bortfiltrerade, "
          f"{len(uppf)} uppföljningar mogna. Plan i dag: {len(plan)}.")

    # 4a. test: bara till Alexanders egen adress
    if test_till:
        tillåtna = {x.strip().lower() for x in (env.get("OUTBOUND_TEST_TO", ""), env.get("REPORT_TO", "")) if x}
        if test_till.strip().lower() not in tillåtna:
            print("::error::--test-to måste vara OUTBOUND_TEST_TO eller REPORT_TO (din egen adress).")
            return 5
        sändare = Sändare(env)
        exempel = nya[0] if nya else EXEMPEL_LEAD
        for steg in (1, 2, 3):
            msg, _ = bygg_meddelande(exempel, steg, öppna, sändare.från, sändare.svar_till,
                                     till=test_till, test=True)
            sändare.skicka(msg)
            print(f"  TEST steg {steg} skickat till {maska(test_till)}: {msg['Subject']}")
        return 0

    # 4b. torrkörning: visa exempel, skriv inget
    if not live_begärt:
        print(f"\n=== {min(visa, len(plan))} exempelmejl (inget skickas) ===")
        från = env.get("MAIL_FROM") or "alexander@outreach.kommunradar.online"
        for steg, rad in plan[:visa]:
            msg, erbj = bygg_meddelande(rad, steg, öppna, från, env.get("REPLY_TO") or "hej@kommunradar.online")
            print("=" * 72)
            print(f"Till: {maska(rad['epost'])}  ({rad.get('bolag')})  steg {steg}  erbjudande: {erbj}")
            print(f"target_reason: {rad.get('target_reason')}")
            print(f"Ämne: {msg['Subject']}\nList-Unsubscribe: {msg['List-Unsubscribe']}\n")
            print(msg.get_content())
        s = sammanfattning(state, plan, bort, räkna, {}, läge, tak, dag_nr, h)
        skriv_publik_rapport(s, env.get("OUTBOUND_REPORT_DIR", os.path.join(ROOT, "dist", "outbound")))
        return 0

    # 4c. live
    sändare = Sändare(env)
    nu = lokal_tid()
    start_t, slut_t = fönster(nu)
    if nu < start_t:
        vänta = (start_t - nu).total_seconds()
        if vänta > 75 * 60:
            print("För tidigt — nästa schemalagda körning tar det.")
            skriv_state(state)
            return 0
        print(f"Väntar {int(vänta)} s till {FÖNSTER.split('-')[0]}.")
        sov(vänta)
    elif nu >= slut_t:
        print(f"Efter {FÖNSTER.split('-')[1]} — inget skickas i dag.")
        skriv_state(state)
        return 0

    idag = date.today().isoformat()
    skickade = {"steg1": 0, "steg2": 0, "steg3": 0}
    avvisade = i_rad = 0
    privata = []
    for i, (steg, rad) in enumerate(plan):
        if G.spärrad():
            print("Spärrfil dök upp — avbryter.")
            break
        if lokal_tid() >= fönster()[1]:
            print("Sändfönstret är slut — resten tas nästa vardag.")
            break
        lid = rad["lead_id"]
        if steg > 1 and state["leads"].get(lid, {}).get("status") != "active":
            continue
        msg, erbj = bygg_meddelande(rad, steg, öppna, sändare.från, sändare.svar_till)
        nu_iso = datetime.now().isoformat(timespec="seconds")
        try:
            sändare.skicka(msg)
        except Exception as e:
            if G.är_spärrsvar(e) or isinstance(e, smtplib.SMTPAuthenticationError):
                G.spärra(f"leverantörssvar: {str(e)[:300]}")
                break
            if avvisad_adress(e):
                avvisade += 1
                i_rad += 1
                l = state["leads"].setdefault(lid, {"lead_id": lid, "dh": rad.get("dh", "")})
                l.setdefault("sent_at", nu_iso)  # räknas i studskvoten
                stoppa(l, "bounced", "avvisad vid sändning")
                print(f"  avvisad: {maska(rad['epost'])}")
                if i_rad >= 3 or (i >= 9 and avvisade / (i + 1) > 0.10):
                    G.spärra(f"{avvisade} avvisade adresser i körningen")
                    break
                skriv_state(state)
                continue
            print(f"  fel för {maska(rad['epost'])}: {str(e)[:120]}")
            continue
        i_rad = 0
        if steg == 1:
            state["leads"][lid] = {
                "lead_id": lid, "dh": rad.get("dh", ""), "ted": rad.get("ted", ""),
                "kategori": rad.get("bransch", ""), "lan": rad.get("lan", ""), "cpv": rad.get("cpv", ""),
                "target_reason": rad.get("target_reason", ""), "template_version": TEMPLATE_VERSION,
                "erbjudande": erbj, "sent_at": nu_iso, "followup1_at": "", "followup2_at": "",
                "status": "active"}
        else:
            l = state["leads"][lid]
            l["followup1_at" if steg == 2 else "followup2_at"] = nu_iso
            if steg == 3:
                l["status"] = "completed"
                l["stop_reason"] = "sekvensen klar"
        skickade[f"steg{steg}"] += 1
        dagen = state["dagar"].setdefault(idag, {})  # skapas först när något faktiskt gått iväg
        dagen[f"steg{steg}"] = dagen.get(f"steg{steg}", 0) + 1
        skriv_state(state)
        privata.append({**rad, "steg": steg, "status": "skickad", "erbjudande": erbj})
        print(f"  {i + 1}/{len(plan)} steg {steg} -> {maska(rad['epost'])} ({rad.get('bolag')})")
        if i + 1 < len(plan):
            sov(random.uniform(*JITTER))

    skriv_state(state)
    s = sammanfattning(state, plan, bort, räkna, skickade, läge, tak, dag_nr, h)
    skriv_publik_rapport(s, env.get("OUTBOUND_REPORT_DIR", os.path.join(ROOT, "dist", "outbound")))
    try:
        privat_rapport(s, privata, sändare)
    except Exception as e:
        print(f"  Rapportmejlet misslyckades: {str(e)[:120]}")
    return 0


EXEMPEL_LEAD = {"bolag": "Exempelbolaget AB", "epost": "test@example.invalid", "lead_id": "0000000000000000",
                "upphandling": "Lokalvård förskolor 2027", "kopare": "Exempelkommun", "bransch": "Avfall, städ & miljö",
                "lan": "Västra Götaland", "ted": "000000-2026", "target_reason": "testexempel"}


if __name__ == "__main__":
    sys.exit(kör(sys.argv[1:]))
