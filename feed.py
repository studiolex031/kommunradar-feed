"""Kommunradar-feed: hämtar riktiga svenska upphandlingar från TED Search API v3 (gratis, ingen nyckel),
poängsätter dem för Peppol/e-faktura-försäljning och skriver leads.json som appen läser.
  python feed.py            -> uppdaterar leads.json
  python feed.py --probe    -> skriver ut ett rått svar, använd vid första körningen
OBS: fältnamnen i FIELDS är de jag förväntar mig från TED v3. Kör --probe först och justera vid behov."""
import sys, json, datetime as dt, requests

URL = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["publication-number", "notice-title", "buyer-name", "publication-date",
          "deadline-receipt-tender-date-lot", "notice-type", "classification-cpv", "links"]
DAYS = 30

def fetch(page=1, limit=100):
    since = (dt.date.today() - dt.timedelta(days=DAYS)).strftime("%Y%m%d")
    body = {"query": f"buyer-country=SWE AND publication-date>={since}",
            "fields": FIELDS, "page": page, "limit": limit}
    r = requests.post(URL, json=body, timeout=30)
    r.raise_for_status()
    return r.json()

def txt(v):  # TED returnerar ofta {språk: [värden]} eller listor
    if isinstance(v, dict):
        v = v.get("swe") or v.get("eng") or next(iter(v.values()), "")
    if isinstance(v, list):
        v = v[0] if v else ""
    return str(v or "")

KW = {"e-faktura": 25, "peppol": 30, "faktura": 15, "ekonomisystem": 25, "affärssystem": 20,
      "inköp": 10, "upphandlingssystem": 20, "integration": 10, "digitalisering": 10, "molntjänst": 8}
CPV = {"72": 20, "48": 20, "79": 8}

def score(n):
    s, hay = 0, (n["title"] + " " + n["buyer"]).lower()
    s += sum(p for k, p in KW.items() if k in hay)
    s += max([p for c, p in CPV.items() if any(x.startswith(c) for x in n["cpv"])] or [0])
    if any(w in hay for w in ("kommun", "region", "stad")): s += 10
    return min(s, 100)

def main():
    data = fetch()
    if "--probe" in sys.argv:
        print(json.dumps(data, ensure_ascii=False, indent=1)[:4000]); return
    out = []
    for x in data.get("notices", []):
        cpv = x.get("classification-cpv") or []
        n = {"id": x.get("publication-number"), "title": txt(x.get("notice-title")),
             "buyer": txt(x.get("buyer-name")), "published": txt(x.get("publication-date")),
             "deadline": txt(x.get("deadline-receipt-tender-date-lot")),
             "cpv": [txt(c) for c in (cpv if isinstance(cpv, list) else [cpv])],
             "url": f"https://ted.europa.eu/sv/notice/-/detail/{x.get('publication-number')}"}
        n["score"] = score(n); out.append(n)
    out.sort(key=lambda n: -n["score"])
    json.dump({"updated": dt.datetime.utcnow().isoformat() + "Z", "count": len(out), "leads": out},
              open("leads.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"{len(out)} upphandlingar, bästa poäng {out[0]['score'] if out else 0}")

if __name__ == "__main__":
    main()
