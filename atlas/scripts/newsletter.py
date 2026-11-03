#!/usr/bin/env python3
"""Skapar veckans utgåva av gratisbrevet i atlas/dist/veckobrev/ (HTML, text och ämnesrad).

    python atlas/scripts/newsletter.py

Filerna skickas inte härifrån: de granskas och klistras in i MailerLite.
"""
import collections
import html
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build

SITE = build.SITE
BASE = build.BASE
TOP = 5
SMALL = 5
SMALL_MAX_SEK = 15_000_000
MIN_DAYS_LEFT = 10
MIN_FACT_BIDS = 100
OUT = build.DIST / "veckobrev"
DISCLAIMER = ("Data från TED, bearbetad av Kommunradar. Bara upphandlingar över EU:s tröskelvärden ingår. "
              "Kommunradar är inte en myndighet och är inte ansluten till EU eller Upphandlingsmyndigheten.")


def new_this_week(leads, today):
    since = today - timedelta(days=7)
    rows = []
    for l in leads:
        pub = build.parse_date(l.get("published"))
        if pub and since <= pub <= today:
            rows.append(l)
    return rows


def pick_top(rows, today, n=TOP, max_value=None, exclude=()):
    """Största värdena med tid kvar, med högst två per köpare och bransch så att listan blir varierad."""
    ok = [l for l in rows if l.get("value_sek") and (l["_deadline"] - today).days >= MIN_DAYS_LEFT
          and (max_value is None or l["value_sek"] <= max_value) and l["id"] not in exclude]
    ok.sort(key=lambda l: (-l["value_sek"], l["id"]))
    picked, buyers, cats = [], collections.Counter(), collections.Counter()
    for l in ok:
        if buyers[l["_buyer"]] < 2 and cats[l["_cat"]] < 2:
            picked.append(l)
            buyers[l["_buyer"]] += 1
            cats[l["_cat"]] += 1
        if len(picked) == n:
            break
    return picked


def lan_counts(rows):
    c = collections.Counter(x for l in rows for x in l["_lans"])
    return sorted(((lan, c.get(lan, 0)) for lan in build.LAN.values()), key=lambda x: (-x[1], x[0]))


def weekly_fact(awards, today):
    """Bransch med lågt antal anbud. Veckan avgör vilken av de fem lägsta som visas."""
    groups = collections.defaultdict(list)
    for a in awards:
        if a["cat"]:
            groups[a["cat"]].append(a)
    ranked = []
    for cat, rows in groups.items():
        s = build.stats(rows)
        if s["with_bids"] >= MIN_FACT_BIDS:
            ranked.append((s["median"], -s["single"], cat, s))
    ranked.sort(key=lambda x: x[:3])
    _, _, cat, s = ranked[today.isocalendar()[1] % min(5, len(ranked))]
    return cat, s


def render(leads, awards, today):
    rows = new_this_week(leads, today)
    top = pick_top(rows, today)
    small = pick_top(rows, today, SMALL, SMALL_MAX_SEK, {l["id"] for l in top})
    if not top:
        raise SystemExit("Inga nya upphandlingar med värde den här veckan: ingen utgåva skapad.")
    counts = lan_counts(rows)
    cat, s = weekly_fact(awards, today)
    cat_url = f"{SITE}{BASE}/bransch/{build.slug(cat)}/"
    fact = (f"Inom {cat} fick {build.pct(s['single'])} av upphandlingarna bara ett anbud, och medianen är {build.num(s['median'])}. "
            "Få anbud betyder inte att affären är lätt: det kan också bero på snäva krav eller en stark befintlig leverantör.")
    subject = f"{len(rows)} nya upphandlingar den här veckan"
    intro = f"Den här veckan har {len(rows)} nya upphandlingar publicerats i TED. Här är ett urval med minst {MIN_DAYS_LEFT} dagar kvar."
    offer = "Vill du ha träffar på dina egna sökord varje morgon? " + build.OFFER

    e = build.esc
    def items(chosen):
        return "".join(
            f'<tr><td style="padding:12px 0;border-bottom:1px solid #e5e7eb"><a href="{e(l["url"])}" style="color:#1d4ed8;font-weight:700">{e(l["title"])}</a>'
            f'<br><span style="color:#4b5563;font-size:14px">{e(l["_buyer"])} · uppskattat {e(build.mkr(l["value_sek"]))} · sista anbudsdag {e(build.fdate(l["_deadline"]))}</span></td></tr>'
            for l in chosen)
    small_html = (f'<h2 style="font-size:19px;margin:24px 0 8px">Mindre affärer</h2><table role="presentation" width="100%">{items(small)}</table>'
                  if small else "")
    lan_links = " · ".join(
        f'<a href="{SITE}{BASE}/lan/{build.slug(lan)}/" style="color:#1d4ed8">{e(lan)}</a> ({n})' for lan, n in counts)
    doc = f"""<!doctype html><html lang="sv"><head><meta charset="utf-8"><title>{e(subject)}</title></head>
<body style="margin:0;background:#f3f4f6"><table role="presentation" width="100%"><tr><td align="center" style="padding:16px">
<table role="presentation" width="100%" style="max-width:620px;background:#fff;border-radius:10px;font:16px/1.5 Arial,sans-serif;color:#111827"><tr><td style="padding:24px">
<p style="font-weight:800;margin:0 0 16px">KOMMUNRADAR · VECKANS UPPHANDLINGAR</p>
<p>{e(intro)}</p>
<h2 style="font-size:19px;margin:24px 0 8px">Största affärerna</h2><table role="presentation" width="100%">{items(top)}</table>
{small_html}
<h2 style="font-size:19px;margin:24px 0 8px">Nya per län</h2><p style="font-size:15px">{lan_links}</p>
<h2 style="font-size:19px;margin:24px 0 8px">Veckans siffra</h2><p>{e(fact)} <a href="{cat_url}" style="color:#1d4ed8">Se hela statistiken</a>.</p>
<p style="background:#eef2ff;border-radius:8px;padding:14px">{e(offer)} <a href="{SITE}/" style="color:#1d4ed8;font-weight:700">Se hur det fungerar</a>.</p>
<p style="font-size:13px;color:#6b7280">{e(DISCLAIMER)}</p>
<p style="font-size:13px;color:#6b7280"><a href="{{$unsubscribe}}" style="color:#6b7280">Avregistrera dig</a></p>
</td></tr></table></td></tr></table></body></html>
"""
    text = [subject, "", intro, ""]
    for heading, chosen in (("STÖRSTA AFFÄRERNA", top), ("MINDRE AFFÄRER", small)):
        if chosen:
            text += [heading, ""]
        for l in chosen:
            text += [l["title"], f'{l["_buyer"]} · uppskattat {build.mkr(l["value_sek"])} · sista anbudsdag {build.fdate(l["_deadline"])}', l["url"], ""]
    text += ["NYA PER LÄN", ", ".join(f"{lan} ({n})" for lan, n in counts), f"{SITE}{BASE}/", "", "VECKANS SIFFRA", fact, cat_url, "",
             offer, f"{SITE}/", "", DISCLAIMER, "", "Avregistrera dig: {$unsubscribe}", ""]
    return {"subject": subject, "html": doc, "text": html.unescape("\n".join(text)), "new": len(rows), "top": len(top), "small": len(small)}


def main():
    awards, leads = build.load()
    r = render(leads, awards, build.TODAY)
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = build.TODAY.isoformat()
    (OUT / f"{stamp}.html").write_text(r["html"])
    (OUT / f"{stamp}.txt").write_text(r["text"])
    (OUT / f"{stamp}-amne.txt").write_text(r["subject"] + "\n")
    print(f"Utgåva {stamp}: {r['subject']} ({r['top']} stora, {r['small']} mindre av {r['new']} nya)")


if __name__ == "__main__":
    main()
