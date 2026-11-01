"""Kommunradar-feed: hämtar svenska upphandlingar från TED Search API v3 (gratis, ingen nyckel)
och skriver leads.json som sajten och det dagliga mejlutskicket läser.
  python feed.py            -> uppdaterar leads.json
  python feed.py --probe    -> skriver ut ett rått svar
Endast standardbiblioteket, så GitHub Actions behöver inga beroenden."""
import sys, json, datetime as dt, urllib.request

URL = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["publication-number", "notice-title", "buyer-name", "buyer-city", "publication-date",
          "deadline-receipt-tender-date-lot", "notice-type", "classification-cpv",
          "place-of-performance", "estimated-value-lot", "estimated-value-cur-lot"]
DAYS = 45
MAX_PAGES = 40  # 40 x 100 notices — well above Sweden's monthly volume

LAN = {"SE110": "Stockholm", "SE121": "Uppsala", "SE122": "Södermanland", "SE123": "Östergötland",
       "SE124": "Örebro", "SE125": "Västmanland", "SE211": "Jönköping", "SE212": "Kronoberg",
       "SE213": "Kalmar", "SE214": "Gotland", "SE221": "Blekinge", "SE224": "Skåne", "SE231": "Halland",
       "SE232": "Västra Götaland", "SE311": "Värmland", "SE312": "Dalarna", "SE313": "Gävleborg",
       "SE321": "Västernorrland", "SE322": "Jämtland", "SE331": "Västerbotten", "SE332": "Norrbotten"}

CPV = {"03": "Jordbruk & skog", "09": "Bränsle & energi", "14": "Gruvprodukter", "15": "Livsmedel",
       "16": "Jordbruksmaskiner", "18": "Kläder & skor", "19": "Textil & läder", "22": "Trycksaker & böcker",
       "24": "Kemikalier", "30": "Datorer & kontorsutrustning", "31": "El & belysning", "32": "Telekom & AV",
       "33": "Medicinteknik & läkemedel", "34": "Fordon & transportmedel", "35": "Säkerhet & räddning",
       "37": "Sport & fritidsutrustning", "38": "Labb & mätinstrument", "39": "Möbler & inredning",
       "41": "Vatten", "42": "Industrimaskiner", "43": "Bygg- & anläggningsmaskiner", "44": "Byggmaterial",
       "45": "Bygg & anläggning", "48": "Programvara & system", "50": "Service & underhåll",
       "51": "Installation", "55": "Hotell, restaurang & måltider", "60": "Transporter", "63": "Resor & logistik",
       "64": "Post & telekomtjänster", "65": "Energi- & vattentjänster", "66": "Finans & försäkring",
       "70": "Fastighetstjänster", "71": "Arkitekt- & teknikkonsult", "72": "IT-tjänster",
       "73": "Forskning & utveckling", "75": "Offentlig förvaltning", "76": "Olja & gas",
       "77": "Park, skog & grönyta", "79": "Företagstjänster", "80": "Utbildning", "85": "Vård & omsorg",
       "90": "Avfall, städ & miljö", "92": "Kultur & fritid", "98": "Övriga tjänster"}


# Peppol/e-faktura score used by the internal radar.html view.
KW = {"e-faktura": 25, "peppol": 30, "faktura": 15, "ekonomisystem": 25, "affärssystem": 20,
      "inköp": 10, "upphandlingssystem": 20, "integration": 10, "digitalisering": 10, "molntjänst": 8}
SCORE_CPV = {"72": 20, "48": 20, "79": 8}


def score(n):
    s, hay = 0, (n["title"] + " " + n["buyer"]).lower()
    s += sum(p for k, p in KW.items() if k in hay)
    s += max([p for c, p in SCORE_CPV.items() if any(x.startswith(c) for x in n["cpv"])] or [0])
    if any(w in hay for w in ("kommun", "region", "stad")): s += 10
    return min(s, 100)


def fetch(page=1, limit=100):
    since = (dt.date.today() - dt.timedelta(days=DAYS)).strftime("%Y%m%d")
    body = json.dumps({"query": f"buyer-country=SWE AND publication-date>={since}",
                       "fields": FIELDS, "page": page, "limit": limit}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def txt(v):  # TED returnerar ofta {språk: [värden]} eller listor
    if isinstance(v, dict):
        v = v.get("swe") or v.get("eng") or next(iter(v.values()), "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")


def as_list(v):
    return v if isinstance(v, list) else ([v] if v else [])


def num(v):
    try: return float(v)
    except (TypeError, ValueError): return None


def normalize(x):
    cpv = sorted({txt(c) for c in as_list(x.get("classification-cpv")) if txt(c)})
    places = [txt(p) for p in as_list(x.get("place-of-performance"))]
    # TED contains placeholder values (e.g. 99 999 999 999 999); anything above 5 bn SEK is treated as unknown.
    # Only SEK amounts are summed; a lot in another currency makes the total unknown rather than wrong.
    amounts, currencies = as_list(x.get("estimated-value-lot")), as_list(x.get("estimated-value-cur-lot"))
    values = [v for v, cur in zip((num(a) for a in amounts), currencies + ["SEK"] * (len(amounts) - len(currencies)))
              if v and v <= 5e9 and txt(cur).upper() == "SEK"]
    if len(values) < len([a for a in amounts if num(a) and num(a) <= 5e9]): values = []
    regions = list(dict.fromkeys(LAN[p] for p in places if p in LAN))
    deadlines = sorted(txt(d)[:10] for d in as_list(x.get("deadline-receipt-tender-date-lot")) if txt(d))
    title = txt(x.get("notice-title"))
    pid = x.get("publication-number")
    return {"id": pid,
            "title": title.split(" – ", 2)[-1] if title.startswith("Sverige – ") else title,
            "buyer": txt(x.get("buyer-name")), "city": txt(x.get("buyer-city")),
            "region": regions[0] if regions else "", "regions": regions,
            "published": txt(x.get("publication-date"))[:10],
            "deadline": deadlines[0] if deadlines else "", "deadlines": deadlines,
            "type": txt(x.get("notice-type")),
            "cpv": cpv, "categories": sorted({CPV[c[:2]] for c in cpv if c[:2] in CPV}),
            "value_sek": round(sum(values)) if values and sum(values) <= 5e9 else None,  # many-lot frameworks sum to implausible totals
            "url": f"https://ted.europa.eu/sv/notice/-/detail/{pid}"}


def is_open(n, today):
    """Only calls for tender (cn-*) with at least one lot still open: what a supplier can still bid on."""
    last = max(n.get("deadlines") or [n["deadline"]])
    return n["type"].startswith("cn") and (not last or last >= today)


def main():
    if "--probe" in sys.argv:
        print(json.dumps(fetch(limit=3), ensure_ascii=False, indent=1)[:4000]); return
    raw, page = [], 1
    while page <= MAX_PAGES:
        notices = fetch(page).get("notices", [])
        raw += notices
        if len(notices) < 100: break
        page += 1
    today = dt.date.today().isoformat()
    seen, out = set(), []
    for x in raw:
        n = normalize(x)
        if n["id"] in seen or not is_open(n, today): continue
        n["deadline"] = next((d for d in n.pop("deadlines", []) if d >= today), n["deadline"])  # earliest open lot
        n["score"] = score(n); seen.add(n["id"]); out.append(n)
    out.sort(key=lambda n: (n["published"], n["id"]), reverse=True)
    json.dump({"updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "source": "TED (ted.europa.eu)",
               "count": len(out), "leads": out}, open("leads.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"{len(raw)} notiser hämtade, {len(out)} öppna anbudsförfrågningar")


if __name__ == "__main__":
    main()
