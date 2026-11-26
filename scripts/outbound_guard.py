"""Spärrarna framför den automatiska outbound-kampanjen (scripts/outbound_campaign.py).

    python scripts/outbound_guard.py            # visa status: läge, uppvärmning, hälsa, DNS
    python scripts/outbound_guard.py --stopp "orsak"   # nödstopp: skriver .github/outbound/SPARRAD

Allt här svarar på en fråga: får kampanjen skicka riktiga mejl just nu, och i så fall hur många?
Svaret är "nej" om minsta villkor saknas. Då kör kampanjen som torrkörning (visar mejlen,
skickar inget) i stället för att gissa.

Villkor för riktiga utskick (alla måste vara uppfyllda):
  1. OUTBOUND_ENABLED, OUTBOUND_PROSPECT_EMAILS_ENABLED och OUTBOUND_APPROVED är exakt "true".
  2. Ingen spärrfil (.github/outbound/SPARRAD). Den skrivs av nödstoppet, av en
     leverantörsvarning och av hälsokontrollen nedan, och tas bara bort för hand.
  3. Sänddomänen är INTE Simply.com-webbhotellet (kontot spärrades 2026-11-18) och inte
     huvuddomänen kommunradar.online, utan en egen subdomän eller domän hos Brevo/Mailgun/
     Postmark/SES/Resend.
  4. SPF och DMARC finns i DNS för sänddomänen, och DKIM om OUTBOUND_DKIM_SELECTOR är satt.
  5. OUTBOUND_WARMUP_START är satt (första sändningsdagen, ÅÅÅÅ-MM-DD).
  6. Svarsläsning (IMAP_HOST/IMAP_USER/IMAP_PASS) är konfigurerad: utan den kan kampanjen inte
     se svar, studsar och "STOPP", och då får ingen uppföljning gå ut.
  7. Hälsan de senaste 7 dagarna: studs < 5 % och högst 1 spamklagomål. Över det skrivs spärrfilen.

Uppvärmning räknas i sändningsdagar (dagar då kampanjen faktiskt skickade), inte kalenderdagar:
  dag 1–3: 10/dag, dag 4–7: 20/dag, dag 8+: 40/dag — men bara om studs < 3 %, inga spamklagomål
  och inga spärrsignaler. Annars stannar taket på 20. Taket gäller ALLA mejl kampanjen skickar
  samma dag (första mejl + uppföljningar), eftersom det är domänens totala volym som bränner den.

Endast standardbiblioteket.
"""
import json, os, re, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPÄRR_FIL = os.path.join(ROOT, ".github", "outbound", "SPARRAD")

FLAGGOR = ("OUTBOUND_ENABLED", "OUTBOUND_PROSPECT_EMAILS_ENABLED", "OUTBOUND_APPROVED")
HUVUDDOMÄN = "kommunradar.online"
FÖRBJUDNA_VÄRDAR = ("simply.com", "simply.se", "smtp.simply")

# Uppvärmningstrappan: (till och med sändningsdag, tak)
TRAPPA = ((3, 10), (7, 20))
FULLT_TAK = 40
HÅLL_TAK = 20
BREVO_DAGSTAK = 300
P1P2_RESERV = 50
P1P2_STATE = os.path.join(ROOT, ".github", "leverantorsregistret", "leveranser.json")

# Hälsogränser över de senaste 7 dagarna. Under MIN_UNDERLAG skickade mejl säger en
# kvot ingenting, då räknas bara absoluta tal (klagomål).
MIN_UNDERLAG = 20
STUDS_RAMP = 0.03    # under detta får trappan gå vidare till 40
STUDS_STOPP = 0.05   # över detta stoppas hela kampanjen
KLAGOMÅL_STOPP = 2   # så många spamklagomål på 7 dagar stoppar kampanjen

# Svar från SMTP-servern som betyder "avsändaren är spärrad", inte "adressen är dålig".
SPÄRR_ORD = ("account has been blocked", "account suspended", "send limit reached", "sending paused",
             "authentication failed", "5.7.8", "5.7.1 service unavailable", "4.7.0", "too many messages",
             "rate limit", "reputation", "blacklisted", "blocklisted", "spamhaus")


def flagga(namn):
    return os.environ.get(namn, "").strip().lower() == "true"


def spärrad():
    try:
        with open(SPÄRR_FIL, encoding="utf8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def spärra(orsak):
    """Nödstoppet. Stoppar alla senare körningar tills filen tas bort för hand."""
    os.makedirs(os.path.dirname(SPÄRR_FIL), exist_ok=True)
    with open(SPÄRR_FIL, "w", encoding="utf8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}\n{orsak}\n")
    print(f"::error::KAMPANJEN STOPPAD: {orsak}")


def är_spärrsvar(fel):
    text = str(fel).lower()
    return any(o in text for o in SPÄRR_ORD)


def domän(adress):
    adress = (adress or "").strip().lower()
    if "<" in adress:
        adress = adress.split("<", 1)[1].split(">", 1)[0]
    return adress.rsplit("@", 1)[-1] if "@" in adress else ""


def sänddomän_fel(smtp_host, mail_from):
    """Regel 1: aldrig Simply, aldrig huvuddomänen. Tom lista = ok."""
    fel = []
    host = (smtp_host or "").lower()
    d = domän(mail_from)
    if not host:
        fel.append("SMTP_HOST saknas")
    elif any(f in host for f in FÖRBJUDNA_VÄRDAR):
        fel.append(f"SMTP_HOST {host} är Simply.com — förbjudet (kontot spärrat 2026-11-18)")
    if not d:
        fel.append("MAIL_FROM saknas")
    elif d == HUVUDDOMÄN:
        fel.append(f"MAIL_FROM ligger på huvuddomänen {HUVUDDOMÄN} — använd en egen sänddomän, "
                   f"t.ex. outreach.{HUVUDDOMÄN}")
    return fel


def dns_txt(namn, timeout=10):
    """TXT-poster via DNS-over-HTTPS (Cloudflare). Tom lista om inget svar."""
    url = "https://cloudflare-dns.com/dns-query?" + urllib.parse.urlencode({"name": namn, "type": "TXT"})
    req = urllib.request.Request(url, headers={"Accept": "application/dns-json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            svar = json.load(r)
    except Exception:
        return None
    return [a.get("data", "").replace('" "', "").strip('"') for a in svar.get("Answer", []) or []]


def dns_status(mail_from, dkim_selector="", txt=dns_txt):
    """{'spf': bool, 'dmarc': bool, 'dkim': bool|None} för sänddomänen."""
    d = domän(mail_from)
    if not d:
        return {"spf": False, "dmarc": False, "dkim": None}
    spf = txt(d) or []
    dmarc = txt(f"_dmarc.{d}") or []
    ut = {"spf": any(r.lower().startswith("v=spf1") for r in spf),
          "dmarc": any(r.lower().startswith("v=dmarc1") for r in dmarc),
          "dkim": None}
    if dkim_selector:
        dk = txt(f"{dkim_selector}._domainkey.{d}") or []
        ut["dkim"] = any("p=" in r or "k=rsa" in r.lower() for r in dk)
    return ut


def sändningsdag(dagar_med_utskick, start, idag=None):
    """Vilken sändningsdag i uppvärmningen idag är (1 = första dagen något skickas)."""
    idag = idag or date.today()
    tidigare = {d for d in dagar_med_utskick if start.isoformat() <= d < idag.isoformat()}
    return len(tidigare) + 1


def hälsa(leads, idag=None, dagar=7):
    """Studs- och klagomålsläge över de senaste `dagar` dagarna, ur kampanjens state."""
    idag = idag or date.today()
    gräns = (idag - timedelta(days=dagar)).isoformat()
    skickade = studs = klagomål = 0
    for l in leads.values():
        for fält in ("sent_at", "followup1_at", "followup2_at"):
            if (l.get(fält) or "")[:10] >= gräns:
                skickade += 1
        if (l.get("stopped_at") or "")[:10] >= gräns:
            if l.get("status") == "bounced":
                studs += 1
            elif l.get("status") == "complaint":
                klagomål += 1
    kvot = studs / skickade if skickade else 0.0
    return {"skickade": skickade, "studs": studs, "klagomal": klagomål, "studskvot": kvot}


def hälsobeslut(h):
    """('stopp'|'håll'|'ok', orsak)."""
    if h["klagomal"] >= KLAGOMÅL_STOPP:
        return "stopp", f"{h['klagomal']} spamklagomål på 7 dagar"
    if h["skickade"] >= MIN_UNDERLAG and h["studskvot"] >= STUDS_STOPP:
        return "stopp", f"studskvot {h['studskvot']:.1%} på 7 dagar (gräns {STUDS_STOPP:.0%})"
    if h["klagomal"] > 0:
        return "håll", f"{h['klagomal']} spamklagomål — taket stannar på {HÅLL_TAK}"
    if h["skickade"] >= MIN_UNDERLAG and h["studskvot"] >= STUDS_RAMP:
        return "håll", f"studskvot {h['studskvot']:.1%} — taket stannar på {HÅLL_TAK}"
    return "ok", ""


def dagstak(dag_nr, beslut, klagomål_kända=True, tak=FULLT_TAK):
    """Dagens tak enligt uppvärmningstrappan och hälsan."""
    for t_o_m, gräns in TRAPPA:
        if dag_nr <= t_o_m:
            return min(gräns, tak)
    if beslut != "ok" or not klagomål_kända:
        return min(HÅLL_TAK, tak)
    return min(FULLT_TAK, tak)


def p1p2_idag(dag=None, path=P1P2_STATE):
    dag = dag or date.today().isoformat()
    try:
        with open(path, encoding="utf8") as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError):
        return 0
    return sum(1 for v in (data.get("leveranser") or {}).values()
               if str(v.get("tid", ""))[:10] == dag)


def brevo_plats(p1p2, dagstak=None, reserv=None):
    try:
        gräns = int(dagstak if dagstak is not None else os.environ.get("BREVO_DAGSTAK", BREVO_DAGSTAK))
    except (TypeError, ValueError):
        gräns = BREVO_DAGSTAK
    try:
        skydd = int(reserv if reserv is not None else os.environ.get("P1P2_RESERV", P1P2_RESERV))
    except (TypeError, ValueError):
        skydd = P1P2_RESERV
    return max(0, gräns - p1p2 - skydd)


def läge(env=None, dns=None):
    """Får vi skicka riktiga mejl? Returnerar (live: bool, fel: [str], info: dict)."""
    env = env if env is not None else os.environ
    dns = dns or dns_status
    fel = []
    flaggor = {f: env.get(f, "").strip().lower() == "true" for f in FLAGGOR}
    if not all(flaggor.values()):
        saknas = [f for f, v in flaggor.items() if not v]
        fel.append("flaggor ej satta: " + ", ".join(saknas))
    if (s := spärrad()):
        fel.append("spärrfil finns: " + s.replace("\n", " — "))
    fel += sänddomän_fel(env.get("SMTP_HOST"), env.get("MAIL_FROM"))
    for k in ("SMTP_USER", "SMTP_PASS"):
        if not env.get(k):
            fel.append(f"{k} saknas")
    start = env.get("OUTBOUND_WARMUP_START", "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start):
        fel.append("OUTBOUND_WARMUP_START saknas (ÅÅÅÅ-MM-DD)")
    if not all(env.get(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS")):
        fel.append("svarsläsning saknas (IMAP_HOST/IMAP_USER/IMAP_PASS)")
    info = {"flaggor": flaggor}
    # DNS kollas bara när resten ser rätt ut — annars är det brus.
    if env.get("MAIL_FROM") and not sänddomän_fel(env.get("SMTP_HOST", "x"), env.get("MAIL_FROM")):
        d = dns(env.get("MAIL_FROM"), env.get("OUTBOUND_DKIM_SELECTOR", ""))
        info["dns"] = d
        if not d["spf"]:
            fel.append(f"SPF saknas för {domän(env['MAIL_FROM'])}")
        if not d["dmarc"]:
            fel.append(f"DMARC saknas för _dmarc.{domän(env['MAIL_FROM'])}")
        if d["dkim"] is False:
            fel.append("DKIM-nyckeln hittades inte för OUTBOUND_DKIM_SELECTOR")
    return (not fel), fel, info


def kontroll(env=None):
    """Provar varje inställning utan att skicka något. Returnerar [(namn, ok, detalj)]."""
    import imaplib, smtplib, ssl
    env = env if env is not None else os.environ
    ut = []
    fel = sänddomän_fel(env.get("SMTP_HOST"), env.get("MAIL_FROM"))
    ut.append(("sänddomän (inte Simply, inte huvuddomänen)", not fel, "; ".join(fel) or domän(env.get("MAIL_FROM"))))
    if not fel:
        d = dns_status(env["MAIL_FROM"], env.get("OUTBOUND_DKIM_SELECTOR", ""))
        ut.append(("SPF", d["spf"], domän(env["MAIL_FROM"])))
        ut.append(("DMARC", d["dmarc"], "_dmarc." + domän(env["MAIL_FROM"])))
        ut.append(("DKIM", d["dkim"] is True, "OUTBOUND_DKIM_SELECTOR saknas" if d["dkim"] is None
                   else f"{env.get('OUTBOUND_DKIM_SELECTOR')}._domainkey.{domän(env['MAIL_FROM'])}"))
    # SMTP: anslut och logga in, skicka ingenting
    if env.get("SMTP_HOST") and env.get("SMTP_USER") and env.get("SMTP_PASS") and not fel:
        try:
            port = int(env.get("SMTP_PORT") or 587)
            if port == 465:
                s = smtplib.SMTP_SSL(env["SMTP_HOST"], port, timeout=30, context=ssl.create_default_context())
            else:
                s = smtplib.SMTP(env["SMTP_HOST"], port, timeout=30)
                s.starttls(context=ssl.create_default_context())
            s.login(env["SMTP_USER"], env["SMTP_PASS"])
            s.quit()
            ut.append(("SMTP-inloggning", True, env["SMTP_HOST"]))
        except Exception as e:
            ut.append(("SMTP-inloggning", False, str(e)[:160]))
    else:
        ut.append(("SMTP-inloggning", False, "OUTREACH_SMTP_* saknas eller sänddomänen är fel"))
    # IMAP: logga in och öppna inkorgen skrivskyddat
    if all(env.get(k) for k in ("IMAP_HOST", "IMAP_USER", "IMAP_PASS")):
        try:
            m = imaplib.IMAP4_SSL(env["IMAP_HOST"], int(env.get("IMAP_PORT") or 993),
                                  ssl_context=ssl.create_default_context())
            m.login(env["IMAP_USER"], env["IMAP_PASS"])
            typ, data = m.select(env.get("IMAP_FOLDER", "INBOX"), readonly=True)
            m.logout()
            ut.append(("IMAP-inloggning (svarsläsning)", typ == "OK", f"{env['IMAP_HOST']}, {data[0].decode()} mejl"))
        except Exception as e:
            ut.append(("IMAP-inloggning (svarsläsning)", False, str(e)[:160]))
    else:
        ut.append(("IMAP-inloggning (svarsläsning)", False, "IMAP_HOST/IMAP_USER/IMAP_PASS saknas"))
    # Brevo API (valfritt)
    if env.get("BREVO_API_KEY"):
        try:
            req = urllib.request.Request("https://api.brevo.com/v3/account",
                                         headers={"api-key": env["BREVO_API_KEY"], "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                json.load(r)
            ut.append(("Brevo API (studs/spam)", True, "nyckeln fungerar"))
        except Exception as e:
            ut.append(("Brevo API (studs/spam)", False, str(e)[:160]))
    else:
        ut.append(("Brevo API (studs/spam)", False, "valfri: utan den stannar taket på 20/dag"))
    ut.append(("OUTBOUND_TEST_TO", bool(env.get("OUTBOUND_TEST_TO")), "din egen adress för testläget"))
    ut.append(("OUTBOUND_WARMUP_START", bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", env.get("OUTBOUND_WARMUP_START", ""))),
               "sätts först inför live"))
    for f in FLAGGOR:
        ut.append((f, env.get(f, "").strip().lower() == "true", "sätts först när du godkänt live"))
    ut.append(("spärrfil", not spärrad(), spärrad().replace("\n", " — ") or "ingen"))
    return ut


def main():
    if "--kontroll" in sys.argv:
        rader = kontroll()
        for namn, ok, detalj in rader:
            print(f"{'OK  ' if ok else 'SAKNAS'}  {namn}: {detalj}")
        sum_fil = os.environ.get("GITHUB_STEP_SUMMARY")
        if sum_fil:
            with open(sum_fil, "a", encoding="utf8") as f:
                f.write("## Outbound-kontroll\n\n| | Kontroll | Detalj |\n|---|---|---|\n")
                for namn, ok, detalj in rader:
                    f.write(f"| {'✅' if ok else '❌'} | {namn} | {detalj} |\n")
        return
    if "--stopp" in sys.argv:
        i = sys.argv.index("--stopp")
        orsak = sys.argv[i + 1] if len(sys.argv) > i + 1 else "manuellt nödstopp"
        spärra(orsak)
        return
    live, fel, info = läge()
    print("LÄGE:", "LIVE" if live else "TORRKÖRNING")
    for f in fel:
        print("  -", f)
    print(json.dumps(info, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
