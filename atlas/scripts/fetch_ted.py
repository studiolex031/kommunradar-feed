#!/usr/bin/env python3
"""Hämtar svenska tilldelningsbeslut från TED till data/awards.json (rådata för atlasen)."""
import json, sys, time, urllib.error, urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL = "https://api.ted.europa.eu/v3/notices/search"
FIELDS = ["publication-number", "publication-date", "notice-title", "buyer-name", "buyer-city", "buyer-country-sub",
          "classification-cpv", "winner-name", "contract-conclusion-date", "contract-duration-period-lot",
          "received-submissions-type-val", "received-submissions-type-code", "total-value", "total-value-cur", "winner-size", "notice-type"]


def page(query, token=None):
    body = {"query": query, "fields": FIELDS, "limit": 250, "paginationMode": "ITERATION"}
    if token:
        body["iterationNextToken"] = token
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 and e.code < 500:
                sys.exit(f"TED {e.code}: {e.read()[:300]}")
            time.sleep(10 * (attempt + 1))
        except OSError:  # tillfälligt nätverksfel
            time.sleep(10 * (attempt + 1))
    sys.exit("TED svarar inte")


def main():
    since = (date.today() - timedelta(days=int(sys.argv[1]) if len(sys.argv) > 1 else 1095)).strftime("%Y%m%d")
    query = f"organisation-country-buyer=SWE AND notice-type IN (can-standard, can-social) AND publication-date>={since}"
    rows, token = [], None
    while True:
        d = page(query, token)
        for n in d.get("notices", []):
            n.pop("links", None)
            t = n.get("notice-title") or {}
            n["notice-title"] = t.get("swe") or t.get("eng") or ""
            rows.append(n)
        print(len(rows), "av", d.get("totalNoticeCount"), flush=True)
        token = d.get("iterationNextToken")
        if not token or not d.get("notices"):
            break
        time.sleep(1.5)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "awards.json").write_text(json.dumps(rows, ensure_ascii=False))
    print("KLART", len(rows))


if __name__ == "__main__":
    main()
