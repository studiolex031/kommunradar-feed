"""Säljleads: bolag som nyligen vann en svensk offentlig upphandling, med den kontaktadress de själva angav i TED.

    python scripts/winner_leads.py --days 3            # skriver vinnar-leads.csv
    python scripts/winner_leads.py --days 3 --mail     # mejlar listan till REPORT_TO (SMTP-hemligheterna)
    python scripts/winner_leads.py --probe             # rått TED-svar för felsökning

Filen innehåller kontaktuppgifter och ska aldrig checkas in: repot är publikt. Därför mejlas listan i stället för
att committas eller laddas upp som artefakt. Storbolag och koncerner filtreras bort, och varje rad märks med om
adressen är generisk (info@, kontakt@ …) eller personlig, så att den som skickar kan välja rättslig grund.
Endast standardbiblioteket.
"""
import csv, html, io, json, os, re, smtplib, ssl, sys, time, urllib.error, urllib.request
from datetime import date, timedelta
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from feed import CPV, LAN, retry_after  # noqa: E402

URL = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["publication-number", "publication-date", "notice-title", "buyer-name", "buyer-country-sub",
          "classification-cpv", "winner-name", "received-submissions-type-val", "received-submissions-type-code",
          "organisation-name-tenderer", "organisation-email-tenderer", "organisation-city-tenderer",
          "organisation-internet-address-tenderer"]
GENERIC = re.compile(r"^(info|kontakt|contact|hej|hello|post|mail|order|offert|anbud|sales|salj|forsaljning|"
                     r"kundservice|kundtjanst|support|reception|admin|office|kontoret|ekonomi|faktura)\b", re.I)
# Bolag som redan har egna anbudsavdelningar och inte är målgruppen (5–150 anställda).
BIG = re.compile(r"\b(peab|ncc|skanska|veidekke|jm|svevia|ramboll|sweco|wsp|afry|tyréns|iss|sodexo|compass|coor|"
                 r"samhall|forenede|stena|ragn-sells|prezero|ab volvo|scania|siemens|atea|tietoevry|cgi|telia|"
                 r"tele2|vattenfall|eon|e\.on|fortum|attendo|azets|omexom|ge healthcare|securitas|g4s|avarn|bravida|caverion|instalco|assemblin)\b", re.I)


def fetch(query, page=1, limit=100):
    body = json.dumps({"query": query, "fields": FIELDS, "page": page, "limit": limit}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500 or attempt == 5: raise
            time.sleep(min(retry_after(e.headers.get("Retry-After")) or 5 * 2 ** attempt, 120))


def values(v, decode=False):
    """TED gives {lang: [..]}, a list, or a scalar. Return a flat list of strings.
    decode=True unescapes HTML entities (names and titles only; e-mail and URLs stay literal)."""
    if isinstance(v, dict):
        v = v.get("swe") or v.get("eng") or next(iter(v.values()), [])
    if not isinstance(v, list):
        v = [v] if v else []
    return [(html.unescape(str(x)) if decode else str(x)).strip() for x in v if str(x or "").strip()]


def clean_title(t):
    """TED titles read "Sverige – <CPV-rubrik> – <titel>"; keep the procurement's own title."""
    parts = t.split(" – ", 2)
    return parts[-1].strip() if t.startswith("Sverige – ") and len(parts) == 3 else t.strip()


def norm(name):
    return re.sub(r"[^a-z0-9åäö]", "", name.casefold())


def rows_from_notice(n):
    """One row per winning company that has an e-mail in the notice."""
    winners = list(dict.fromkeys(values(n.get("winner-name"), True)))
    names, emails = values(n.get("organisation-name-tenderer"), True), values(n.get("organisation-email-tenderer"))
    cities, webs = values(n.get("organisation-city-tenderer")), values(n.get("organisation-internet-address-tenderer"))
    # Tenderer fields are parallel lists; pair by position only when they line up, otherwise trust nothing.
    contact, ambiguous = {}, set()
    if names and len(names) == len(emails):
        for i, name in enumerate(names):
            key, entry = norm(name), {"email": emails[i].lower(),
                                      "city": cities[i] if len(cities) == len(names) else "",
                                      "web": webs[i] if len(webs) == len(names) else ""}
            # Two different companies with the same key ("A & B AB" / "A B AB"): trust neither address.
            if key in contact and contact[key]["email"] != entry["email"]:
                ambiguous.add(key)
            contact.setdefault(key, entry)
    for key in ambiguous:
        contact.pop(key, None)
    bids = [int(v) for v, c in zip(values(n.get("received-submissions-type-val")),
                                   values(n.get("received-submissions-type-code"))) if c == "tenders" and v.isdigit()]
    cpv = (values(n.get("classification-cpv")) or ["00"])[0]
    out = []
    for w in winners:
        c = contact.get(norm(w))
        if not c or "@" not in c["email"] or BIG.search(w): continue
        local = c["email"].split("@")[0]
        out.append({"bolag": w, "epost": c["email"], "adresstyp": "generisk" if GENERIC.match(local) else "personlig",
                    "ort": c["city"], "webb": c["web"], "upphandling": clean_title((values(n.get("notice-title"), True) or [""])[0])[:140],
                    "kopare": (values(n.get("buyer-name"), True) or [""])[0], "lan": LAN.get((values(n.get("buyer-country-sub")) or [""])[0], ""),
                    "bransch": CPV.get(cpv[:2], ""), "anbud": max(bids) if bids else "",
                    "vinnare": len(winners), "ted": n.get("publication-number", ""),
                    "publicerad": str(n.get("publication-date", ""))[:10]})
    return out


def collect(days):
    since = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    query = f"organisation-country-buyer=SWE AND notice-type IN (can-standard, can-social) AND publication-date>={since}"
    rows, seen, page = [], set(), 1
    while page <= 20:
        notices = fetch(query, page).get("notices", [])
        for n in notices:
            for r in rows_from_notice(n):
                if r["epost"] in seen: continue
                seen.add(r["epost"]); rows.append(r)
        if len(notices) < 100: break
        page += 1; time.sleep(1)
    # Generic addresses first (can be contacted on B2B grounds), then fewest bids (most to gain from more tenders).
    rows.sort(key=lambda r: (r["adresstyp"] != "generisk", r["anbud"] if r["anbud"] != "" else 99))
    return rows


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["bolag"])
    w.writeheader(); w.writerows(rows)
    return buf.getvalue()


def mail(rows, days):
    to = os.environ["REPORT_TO"]
    msg = EmailMessage()
    msg["Subject"] = f"Kommunradar: {len(rows)} nya vinnar-leads (senaste {days} dagarna)"
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"]); msg["To"] = to
    lines = [f"{r['bolag']} | {r['epost']} ({r['adresstyp']}) | {r['upphandling']} | {r['kopare']} | "
             f"{r['anbud']} anbud | TED {r['ted']}" for r in rows]
    msg.set_content("Nya vinnare med kontaktadress i TED. CSV bifogad.\n\n" + "\n".join(lines or ["Inga nya i dag."]))
    msg.add_attachment(to_csv(rows).encode("utf-8-sig"), maintype="text", subtype="csv",
                       filename=f"vinnar-leads-{date.today().isoformat()}.csv")
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context()); smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg); smtp.quit()


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    if "--probe" in sys.argv:
        q = "organisation-country-buyer=SWE AND notice-type=can-standard"
        print(json.dumps(fetch(q, limit=2), ensure_ascii=False, indent=1)[:5000]); return
    rows = collect(days)
    print(f"{len(rows)} vinnare med e-post ({sum(r['adresstyp'] == 'generisk' for r in rows)} generiska)")
    if "--mail" in sys.argv:
        mail(rows, days); print("Mejlad till REPORT_TO")
    else:
        open("vinnar-leads.csv", "w", encoding="utf-8-sig").write(to_csv(rows)); print("Skrev vinnar-leads.csv")


if __name__ == "__main__":
    main()
