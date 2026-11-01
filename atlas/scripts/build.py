#!/usr/bin/env python3
"""Bygger Anbudsatlasen: statiska sidor under dist/upphandlingar/ från TED-data.

    python atlas/scripts/fetch_ted.py 1095     # tilldelningsbeslut (några minuter, kör veckovis)
    python atlas/scripts/build.py              # öppna upphandlingar läses från leads.json i repots rot
"""
import collections
import html
import json
import re
import shutil
import statistics
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SITE = "https://kommunradar.online"
BASE = "/upphandlingar"
TODAY = date.today()
TED_NOTICE = "https://ted.europa.eu/sv/notice/-/detail/"
MONTHS = ["januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti", "september", "oktober",
          "november", "december"]

# En sida skapas bara när underlaget räcker för att säga något – annars blir den tunn.
MIN_BUYER = 10
MIN_COMBO = 12
MIN_RANK = 20
MIN_RANK_COMBO = 8

LAN = {"SE110": "Stockholm", "SE121": "Uppsala", "SE122": "Södermanland", "SE123": "Östergötland", "SE124": "Örebro",
       "SE125": "Västmanland", "SE211": "Jönköping", "SE212": "Kronoberg", "SE213": "Kalmar", "SE214": "Gotland",
       "SE221": "Blekinge", "SE224": "Skåne", "SE231": "Halland", "SE232": "Västra Götaland", "SE311": "Värmland",
       "SE312": "Dalarna", "SE313": "Gävleborg", "SE321": "Västernorrland", "SE322": "Jämtland",
       "SE331": "Västerbotten", "SE332": "Norrbotten"}
# Reservnamn för CPV-avdelningar som just nu saknas i det öppna flödet.
CPV_FALLBACK = {"03": "Jordbruk & livsmedelsråvaror", "14": "Gruvprodukter & mineraler", "16": "Jordbruksmaskiner",
                "19": "Läder & textil", "41": "Vatten", "76": "Olje- & gastjänster", "98": "Övriga tjänster"}
# Bolagsnamn visas bara med tydlig bolagsform: enskilda firmor kan bära en privatpersons namn.
COMPANY = re.compile(r"\b(AB|Aktiebolag|Aktiebolaget|HB|Handelsbolag|KB|Kommanditbolag|ek\.? ?för\.?|ekonomisk förening"
                     r"|Oy|Oyj|ApS|A/S|AS|ASA|GmbH|Ltd|Limited|LLC|Inc|BV|B\.V\.|S\.A\.|SA|Sp\. z o\.o\.)(?![\w])", re.I)


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def slug(s):
    s = s.lower().replace("&", " och ").replace("å", "a").replace("ä", "a").replace("ö", "o")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:70].rstrip("-")


def swe(v):
    if not isinstance(v, dict) or not v:
        return []
    x = v.get("swe") or next(iter(v.values()))
    return x if isinstance(x, list) else [x]


def clean_buyer(name):
    name = re.sub(r"\s+", " ", name.split(",")[0]).strip()
    return re.sub(r"\s+Myndighet$", "", name).strip(" .")


def clean_title(t):
    t = re.sub(r"\s+", " ", t.split(" – ")[-1]).strip().strip('"”')
    return t if len(t) <= 90 else t[:89].rsplit(" ", 1)[0].rstrip(" ,-–") + "…"


def parse_date(s):
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def fdate(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fnum(n):
    return f"{n:,}".replace(",", " ")


def num(x):
    return (f"{x:.1f}".replace(".", ",") if x != int(x) else str(int(x)))


def mkr(v):
    return f"{v / 1e9:.1f} mdr kr".replace(".", ",") if v >= 1e9 else (
        f"{v / 1e6:.0f} mkr" if v >= 1e6 else f"{v / 1e3:.0f} tkr")


def category_map(leads):
    votes = collections.defaultdict(collections.Counter)
    for l in leads:
        if l.get("cpv") and l.get("categories"):
            votes[l["cpv"][0][:2]][l["categories"][0]] += 1
    return {k: v.most_common(1)[0][0] for k, v in votes.items()}


def load():
    leads_doc = json.loads((ROOT.parent / "leads.json").read_text())
    leads = leads_doc["leads"]
    cats = category_map(leads)
    awards = []
    for r in json.loads((ROOT / "data" / "awards.json").read_text()):
        buyer = clean_buyer((swe(r.get("buyer-name")) or [""])[0])
        if not buyer:
            continue
        vals, codes = r.get("received-submissions-type-val") or [], r.get("received-submissions-type-code") or []
        # Delar utan anbud blev aldrig tilldelade och säger inget om hur många som konkurrerade om affären.
        lot_bids = [int(v) for v, c in zip(vals, codes) if c == "tenders" and str(v).isdigit() and int(v) > 0]
        cpv = (r.get("classification-cpv") or ["00"])[0][:2]
        value = r.get("total-value") if (r.get("total-value-cur") or [""])[0] == "SEK" else None
        concl = [d for d in map(parse_date, r.get("contract-conclusion-date") or []) if d]
        pub = parse_date(r.get("publication-date"))
        ends = None
        dur = r.get("contract-duration-period-lot") or []
        if concl and dur and dur[0].get("unit") in ("YEAR", "MONTH"):
            try:
                months = int(dur[0]["value"]) * (12 if dur[0]["unit"] == "YEAR" else 1)
            except ValueError:
                months = 0
            if 0 < months <= 180:
                ends = concl[0] + timedelta(days=round(months * 30.44))
        winners = list(dict.fromkeys(w.strip() for w in swe(r.get("winner-name"))))
        awards.append({
            "ref": r.get("publication-number"), "title": clean_title(r.get("notice-title") or ""), "buyer": buyer,
            "lan": LAN.get((r.get("buyer-country-sub") or [""])[0]), "cat": cats.get(cpv) or CPV_FALLBACK.get(cpv),
            "bids": statistics.median(lot_bids) if lot_bids else None, "value": value, "pub": pub, "ends": ends,
            "winners": winners,
        })
    # Samma köpare stavas olika: slå ihop skiftlägesvarianter under den vanligaste stavningen.
    spell = collections.defaultdict(collections.Counter)
    for a in awards:
        spell[a["buyer"].casefold()][a["buyer"]] += 1
    for a in awards:
        a["buyer"] = spell[a["buyer"].casefold()].most_common(1)[0][0]
    for l in leads:
        b = clean_buyer(l.get("buyer") or "")
        l["_buyer"] = spell[b.casefold()].most_common(1)[0][0] if b.casefold() in spell else b
        l["_cat"] = (l.get("categories") or [None])[0]
        l["_lans"] = [x for x in (l.get("regions") or [l.get("region")]) if x]
        l["_deadline"] = parse_date(l.get("deadline"))
    # Delar av samma upphandling annonseras ibland separat: visa dem som en rad.
    unique = {}
    for l in sorted(leads, key=lambda l: l["id"]):
        if l["_deadline"] and l["_deadline"] >= TODAY:
            key = (l["title"].casefold(), l["_buyer"].casefold(), l["_deadline"])
            if key in unique:
                unique[key]["_lans"] = list(dict.fromkeys(unique[key]["_lans"] + l["_lans"]))
            else:
                unique[key] = l
    leads = sorted(unique.values(), key=lambda l: l["_deadline"])
    return awards, leads


def stats(rows):
    bids = [a["bids"] for a in rows if a["bids"] is not None]
    suppliers = {w.casefold() for a in rows for w in a["winners"]}
    values = [a["value"] for a in rows if a["value"]]
    pubs = [a["pub"] for a in rows if a["pub"]]
    return {
        "n": len(rows), "with_bids": len(bids),
        "median": statistics.median(bids) if bids else None,
        "single": sum(b == 1 for b in bids) / len(bids) if bids else None,
        "suppliers": len(suppliers),
        "value": statistics.median(values) if values else None,
        "first": min(pubs) if pubs else None,
    }


def pct(x):
    return "–" if x is None else f"{round(x * 100)} %"


def top_winners(rows, n=8):
    wins = collections.Counter()
    for a in rows:
        for w in a["winners"]:
            if COMPANY.search(w):
                wins[w] += 1
    return wins.most_common(n)


CSS = """
:root{--ink:#070b18;--ink2:#0e1530;--line:#ffffff1a;--mut:#9aa6c4;--txt:#f4f6fb;--y:#fbbf24;--c:#22d3ee}
*{box-sizing:border-box}body{margin:0;background:var(--ink);color:var(--txt);font:17px/1.6 "Inter Tight",system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:#a5f3fc}.w{max-width:1040px;margin:auto;padding:0 18px}
header{display:flex;justify-content:space-between;align-items:center;padding:20px 0;gap:12px}
.logo{display:flex;gap:10px;align-items:center;font-weight:900;letter-spacing:-.02em;font-size:19px;text-decoration:none;color:var(--txt)}
.radar{width:30px;height:30px;border-radius:50%;background:conic-gradient(from 0deg,#22d3ee00 0 270deg,#22d3ee 360deg),#0e1530;border:2px solid #22d3ee66}
.btn{display:inline-block;border-radius:12px;padding:12px 18px;font-weight:800;text-decoration:none;background:var(--y);color:#111;white-space:nowrap}
.crumbs{font-size:14px;color:var(--mut);margin:8px 0 18px}.crumbs a{color:var(--mut)}
h1{font-size:clamp(32px,6vw,52px);line-height:1.08;letter-spacing:-.025em;margin:0 0 16px}
h2{font-size:clamp(23px,3.4vw,30px);line-height:1.2;letter-spacing:-.015em;margin:44px 0 12px}
.lead{font-size:20px;color:#dfe5f4;max-width:50em}.mut{color:var(--mut)}.small{font-size:14px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:26px 0}
.tile{border:1px solid var(--line);background:var(--ink2);border-radius:14px;padding:16px}
.tile b{display:block;font-size:32px;line-height:1.1;font-variant-numeric:tabular-nums}.tile span{font-size:14px;color:var(--mut)}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:14px}
table{width:100%;border-collapse:collapse;font-size:16px;background:var(--ink2)}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:0}th{font-size:13px;color:var(--mut);font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.links{display:flex;flex-wrap:wrap;gap:8px;padding:0;list-style:none}.links a{display:block;border:1px solid var(--line);background:var(--ink2);border-radius:10px;padding:7px 12px;text-decoration:none;color:var(--txt);font-size:15px}
.cta{margin:48px 0;padding:26px;border-radius:18px;background:linear-gradient(120deg,#1e2a5e,#0e1530);border:1px solid #6366f155}
.cta h2{margin-top:0}.note{border-left:3px solid var(--c);padding:4px 14px;color:#dfe5f4;margin:18px 0}
@media(max-width:520px){.logo{font-size:16px;gap:7px}.radar{width:24px;height:24px}header .btn{padding:9px 11px;font-size:14px}}
footer{border-top:1px solid var(--line);margin-top:50px;padding:24px 0 40px;color:var(--mut);font-size:14px}footer a{color:var(--mut)}
"""
HIDE_EXPIRED = ("<script>document.querySelectorAll('[data-deadline]').forEach(function(r){"
                "if(new Date(r.dataset.deadline+'T23:59:59')<new Date())r.remove()})</script>")
OFFER = "7 dagar gratis (kort krävs, inget dras förrän dag 8). Sedan 990 kr/mån, ingen moms, ingen bindningstid."


def page(path, title, desc, crumbs, body, dataset=None):
    url = f"{SITE}{path.rstrip('/')}/"
    trail = [("Kommunradar", "/"), ("Anbudsatlasen", f"{BASE}/")] + crumbs
    ld = [{"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": f"{SITE}{u}"} for i, (n, u) in enumerate(trail)]}]
    if dataset:
        ld.append({"@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc, "url": url,
                   "dateModified": TODAY.isoformat(), "inLanguage": "sv", "isBasedOn": "https://ted.europa.eu/",
                   "measurementTechnique": f"{SITE}{BASE}/metod/",
                   "creator": {"@type": "Organization", "name": "Kommunradar", "url": SITE}})
    crumb_html = " › ".join(f'<a href="{esc(u)}">{esc(n)}</a>' for n, u in trail[:-1]) + f" › {esc(trail[-1][0])}" \
        if crumbs else '<a href="/">Kommunradar</a> › Anbudsatlasen'
    doc = f"""<!doctype html>
<html lang="sv"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}"><link rel="canonical" href="{esc(url)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{esc(url)}"><meta property="og:type" content="website"><meta property="og:locale" content="sv_SE">
<meta name="theme-color" content="#070b18"><link rel="icon" href="/favicon.svg">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;700;800;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/atlas.css">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace('</', '<\\/')}</script></head>
<body><div class="w"><header><a class="logo" href="/"><span class="radar"></span>KOMMUNRADAR</a><a class="btn" href="/#pris">Prova 7 dagar gratis</a></header>
<nav class="crumbs" aria-label="Brödsmulor">{crumb_html}</nav>
<main>{body}
<aside class="cta"><h2>Få nya upphandlingar i mejlen varje morgon</h2><p>Kommunradar matchar nya upphandlingar över EU:s tröskelvärden mot dina bevakningsord och ditt län. {OFFER}</p><a class="btn" href="/">Se hur det fungerar</a></aside>
</main>
<footer>Data från <a href="https://ted.europa.eu/" rel="nofollow">TED</a>, Europeiska unionens databas för upphandlingar, bearbetad av Kommunradar. Bara upphandlingar som publiceras i TED ingår, alltså i regel över EU:s tröskelvärden. Kommunradar är inte en myndighet och är inte ansluten till EU eller Upphandlingsmyndigheten. Uppdaterad {fdate(TODAY)}. <a href="{BASE}/metod/">Så räknar vi</a> · <a href="/villkor.html">Villkor</a> · <a href="/integritet.html">Integritet</a></footer></div>{HIDE_EXPIRED}</body></html>
"""
    out = DIST / path.lstrip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc)
    PAGES.append(path)


PAGES = []


def tiles(s):
    items = [(num(s["median"]) if s["median"] is not None else "–", "anbud i mitten av alla upphandlingar (median)"),
             (pct(s["single"]), "fick bara ett anbud"), (fnum(s["suppliers"]), "olika leverantörer har vunnit"),
             (fnum(s["n"]), "tilldelade upphandlingar sedan " + (f"{MONTHS[s['first'].month - 1]} {s['first'].year}" if s["first"] else "–"))]
    return '<div class="tiles">' + "".join(f'<div class="tile"><b>{v}</b><span>{esc(t)}</span></div>' for v, t in items) + "</div>"


def compare(s, nat):
    """Mening som jämför med riket, bara när skillnaden går att stå för."""
    if s["median"] is None or s["with_bids"] < 8:
        return ""
    if s["median"] < nat["median"]:
        return f"Det är färre anbud än i riket som helhet, där medianen är {num(nat['median'])}."
    if s["median"] > nat["median"]:
        return f"Det är fler anbud än i riket som helhet, där medianen är {num(nat['median'])}."
    return f"Det är samma nivå som i riket som helhet."


def open_table(rows, empty, limit=12):
    if not rows:
        return f'<p class="mut">{esc(empty)}</p>'
    trs = "".join(
        f'<tr data-deadline="{l["_deadline"].isoformat()}"><td><a href="{esc(l["url"])}" rel="nofollow noopener" target="_blank">{esc(l["title"])}</a><div class="mut small">{esc(l["_buyer"])}</div></td>'
        f'<td class="n">{"–" if not l.get("value_sek") else mkr(l["value_sek"])}</td><td class="n"><time datetime="{l["_deadline"].isoformat()}">{fdate(l["_deadline"])}</time></td></tr>'
        for l in rows[:limit])
    more = f'<p class="mut small">Visar de {limit} med närmast sista anbudsdag av {fnum(len(rows))} öppna.</p>' if len(rows) > limit else ""
    return f'<div class="scroll"><table><thead><tr><th>Upphandling</th><th class="n">Uppskattat värde</th><th class="n">Sista anbudsdag</th></tr></thead><tbody>{trs}</tbody></table></div>{more}'


def rank_table(first, rows):
    trs = "".join(
        f'<tr><td><a href="{esc(u)}">{esc(n)}</a></td><td class="n">{num(s["median"])}</td><td class="n">{pct(s["single"])}</td><td class="n">{fnum(s["suppliers"])}</td><td class="n">{fnum(s["n"])}</td></tr>'
        if u else
        f'<tr><td>{esc(n)}</td><td class="n">{num(s["median"])}</td><td class="n">{pct(s["single"])}</td><td class="n">{fnum(s["suppliers"])}</td><td class="n">{fnum(s["n"])}</td></tr>'
        for n, u, s in rows)
    return (f'<div class="scroll"><table><thead><tr><th>{esc(first)}</th><th class="n">Anbud (median)</th><th class="n">Ett anbud</th>'
            f'<th class="n">Olika vinnare</th><th class="n">Upphandlingar</th></tr></thead><tbody>{trs}</tbody></table></div>')


def winners_table(rows):
    w = top_winners(rows)
    if len(w) < 3:
        return ""
    trs = "".join(f'<tr><td>{esc(n)}</td><td class="n">{c}</td></tr>' for n, c in w)
    return f'<h2>Leverantörer som vinner oftast</h2><div class="scroll"><table><thead><tr><th>Leverantör</th><th class="n">Tilldelningar</th></tr></thead><tbody>{trs}</tbody></table></div><p class="mut small">Bara bolag med tydlig bolagsform visas. Ramavtal kan ha flera vinnare.</p>'


def winner_label(winners):
    """Högst två bolagsnamn och antalet övriga vinnare, inklusive dem vi inte visar med namn."""
    named = [w for w in winners if COMPANY.search(w)][:2]
    hidden = len(winners) - len(named)
    if not named:
        return f"{hidden} vinnare" if hidden else "–"
    return ", ".join(named) + (f" +{hidden}" if hidden else "")


def recent_table(rows, n=8):
    rows = sorted((a for a in rows if a["pub"] and a["title"]), key=lambda a: a["pub"], reverse=True)[:n]
    trs = ""
    for a in rows:
        who = winner_label(a["winners"])
        trs += (f'<tr><td><a href="{TED_NOTICE}{esc(a["ref"])}" rel="nofollow noopener" target="_blank">{esc(a["title"])}</a><div class="mut small">{esc(a["buyer"])}</div></td>'
                f'<td>{esc(who)}</td><td class="n">{"–" if a["bids"] is None else num(a["bids"])}</td><td class="n">{fdate(a["pub"])}</td></tr>')
    return f'<div class="scroll"><table><thead><tr><th>Upphandling</th><th>Vinnare</th><th class="n">Anbud</th><th class="n">Publicerad</th></tr></thead><tbody>{trs}</tbody></table></div>'


def endings_table(rows, n=12):
    horizon = TODAY + timedelta(days=730)
    rows = sorted((a for a in rows if a["ends"] and TODAY <= a["ends"] <= horizon), key=lambda a: a["ends"])
    if not rows:
        return "", 0
    trs = ""
    for a in rows[:n]:
        named = [w for w in a["winners"] if COMPANY.search(w)]
        trs += (f'<tr><td><a href="{TED_NOTICE}{esc(a["ref"])}" rel="nofollow noopener" target="_blank">{esc(a["title"])}</a><div class="mut small">{esc(a["buyer"])}</div></td>'
                f'<td>{esc(", ".join(named[:2]) or "–")}</td><td class="n">{MONTHS[a["ends"].month - 1]} {a["ends"].year}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Avtal</th><th>Leverantör idag</th><th class="n">Beräknat slut</th></tr></thead><tbody>{trs}</tbody></table></div>'
            '<p class="mut small">Beräknat från avtalsdatum och angiven löptid. Förlängningsoptioner kan skjuta slutet framåt, och ingen vet om avtalet upphandlas på nytt.</p>'), len(rows)


def links(items):
    return '<ul class="links">' + "".join(f'<li><a href="{esc(u)}">{esc(n)}</a></li>' for n, u in items) + "</ul>"


def main():
    awards, leads = load()
    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / BASE.lstrip("/")).mkdir(parents=True)
    (DIST / BASE.lstrip("/") / "atlas.css").write_text(CSS)
    nat = stats(awards)

    by_lan, by_cat, by_buyer, by_combo = (collections.defaultdict(list) for _ in range(4))
    for a in awards:
        by_buyer[a["buyer"]].append(a)
        if a["lan"]:
            by_lan[a["lan"]].append(a)
        if a["cat"]:
            by_cat[a["cat"]].append(a)
        if a["lan"] and a["cat"]:
            by_combo[(a["lan"], a["cat"])].append(a)

    lan_url = lambda l: f"{BASE}/lan/{slug(l)}/"
    cat_url = lambda c: f"{BASE}/bransch/{slug(c)}/"
    combo_url = lambda l, c: f"{BASE}/lan/{slug(l)}/{slug(c)}/"
    buyer_url = lambda b: f"{BASE}/kopare/{slug(b)}/"

    buyers = {b: r for b, r in by_buyer.items() if sum(a["bids"] is not None for a in r) >= MIN_BUYER}
    seen = {}
    for b in sorted(buyers, key=lambda b: -len(buyers[b])):  # olika namn kan ge samma slug: störst vinner
        seen.setdefault(slug(b), b)
    buyers = {b: buyers[b] for b in seen.values()}
    combos = {k: r for k, r in by_combo.items() if sum(a["bids"] is not None for a in r) >= MIN_COMBO}
    cats = {c: r for c, r in by_cat.items() if sum(a["bids"] is not None for a in r) >= MIN_RANK}

    def ranked(groups, url, min_n):
        out = []
        for key, rows in groups.items():
            s = stats(rows)
            if s["median"] is not None and s["with_bids"] >= min_n:
                out.append((key, url(key) if url else None, s))
        return sorted(out, key=lambda x: (x[2]["median"], -(x[2]["single"] or 0), -x[2]["n"], str(x[0])))

    # Län
    for lan, rows in sorted(by_lan.items()):
        s = stats(rows)
        lr = [l for l in leads if lan in l["_lans"]]
        in_lan = {c: r for (l, c), r in combos.items() if l == lan}
        cat_rank = ranked(in_lan, lambda c, l=lan: combo_url(l, c), MIN_COMBO)
        buyer_rank = ranked({b: r for b, r in buyers.items() if sum(a["lan"] == lan for a in r) >= MIN_BUYER},
                            buyer_url, MIN_BUYER)[:12]
        body = (f'<h1>Upphandlingar i {esc(lan)}</h1><p class="lead">Hälften av upphandlingarna i {esc(lan)} fick {num(s["median"])} anbud eller färre, och {pct(s["single"])} fick bara ett. {compare(s, nat)} Just nu är {fnum(len(lr))} upphandlingar öppna.</p>'
                + tiles(s) + "<h2>Öppna upphandlingar just nu</h2>" + open_table(lr, f"Inga öppna upphandlingar i {lan} i dagens data."))
        if cat_rank:
            body += f"<h2>Branscher i {esc(lan)} med minst konkurrens</h2>" + rank_table("Bransch", cat_rank)
        if buyer_rank:
            body += f"<h2>Köpare i {esc(lan)}</h2>" + rank_table("Köpare", buyer_rank)
        body += winners_table(rows) + "<h2>Senaste tilldelningarna</h2>" + recent_table(rows)
        page(lan_url(lan), f"Upphandlingar i {lan}: öppna affärer och konkurrens",
             f"{fnum(len(lr))} öppna upphandlingar i {lan}. Se hur många anbud varje bransch och köpare får, vem som vinner och var konkurrensen är lägst.",
             [(lan, lan_url(lan))], body, dataset=True)

    # Bransch
    for cat, rows in sorted(cats.items()):
        s = stats(rows)
        lr = [l for l in leads if l["_cat"] == cat]
        lan_rank = ranked({l: r for (l, c), r in combos.items() if c == cat}, lambda l, c=cat: combo_url(l, c), MIN_COMBO)
        body = (f'<h1>Upphandlingar inom {esc(cat)}</h1><p class="lead">Inom {esc(cat)} fick hälften av upphandlingarna {num(s["median"])} anbud eller färre, och {fnum(s["suppliers"])} olika leverantörer har vunnit. {compare(s, nat)}</p>'
                + tiles(s) + "<h2>Öppna upphandlingar just nu</h2>" + open_table(lr, "Inga öppna upphandlingar i dagens data."))
        if lan_rank:
            body += "<h2>Län med minst konkurrens</h2>" + rank_table("Län", lan_rank)
        body += winners_table(rows) + "<h2>Senaste tilldelningarna</h2>" + recent_table(rows)
        page(cat_url(cat), f"Upphandlingar {cat}: öppna affärer och konkurrens",
             f"{fnum(len(lr))} öppna upphandlingar inom {cat}. Se antal anbud, vem som vinner och i vilka län konkurrensen är lägst.",
             [(cat, cat_url(cat))], body, dataset=True)

    # Län + bransch
    for (lan, cat), rows in sorted(combos.items()):
        s = stats(rows)
        lr = [l for l in leads if lan in l["_lans"] and l["_cat"] == cat]
        body = (f'<h1>{esc(cat)}: upphandlingar i {esc(lan)}</h1><p class="lead">Hälften av upphandlingarna inom {esc(cat)} i {esc(lan)} fick {num(s["median"])} anbud eller färre. {pct(s["single"])} fick bara ett anbud. {compare(s, nat)}</p>'
                + tiles(s) + "<h2>Öppna upphandlingar just nu</h2>"
                + open_table(lr, "Inga öppna upphandlingar i dagens data. Nya publiceras löpande.")
                + winners_table(rows) + "<h2>Senaste tilldelningarna</h2>" + recent_table(rows)
                + "<h2>Läs vidare</h2>" + links([(f"Alla upphandlingar i {lan}", lan_url(lan)), (f"{cat} i hela Sverige", cat_url(cat))]))
        page(combo_url(lan, cat), f"{cat} i {lan}: upphandlingar och anbud",
             f"{cat} i {lan}: median {num(s['median'])} anbud, {pct(s['single'])} med bara ett anbud. {fnum(len(lr))} öppna upphandlingar just nu och vilka som vinner.",
             [(lan, lan_url(lan)), (cat, combo_url(lan, cat))], body, dataset=True)

    # Köpare
    for buyer, rows in sorted(buyers.items()):
        s = stats(rows)
        lr = [l for l in leads if l["_buyer"] == buyer]
        cat_groups = collections.defaultdict(list)
        for a in rows:
            if a["cat"]:
                cat_groups[a["cat"]].append(a)
        cat_rank = ranked(cat_groups, None, 5)
        ends_html, ends_n = endings_table(rows, 8)
        body = (f'<h1>Upphandlingar hos {esc(buyer)}</h1><p class="lead">{esc(buyer)} har tilldelat {fnum(s["n"])} upphandlingar i TED sedan {MONTHS[s["first"].month - 1]} {s["first"].year}. Hälften fick {num(s["median"])} anbud eller färre, och {pct(s["single"])} fick bara ett. {compare(s, nat)}</p>'
                + tiles(s) + "<h2>Öppna upphandlingar just nu</h2>" + open_table(lr, f"{buyer} har ingen öppen upphandling i dagens data."))
        if cat_rank:
            body += f"<h2>Vad {esc(buyer)} köper</h2>" + rank_table("Bransch", cat_rank)
        if ends_html:
            body += "<h2>Avtal som kan löpa ut inom två år</h2>" + ends_html
        body += winners_table(rows) + "<h2>Senaste tilldelningarna</h2>" + recent_table(rows)
        page(buyer_url(buyer), f"{buyer}: upphandlingar och anbud",
             f"Vad {buyer} köper, hur många anbud upphandlingarna får, vilka som vinner och vad som är öppet just nu. Bygger på {fnum(s['n'])} tilldelningar i TED.",
             [(buyer, buyer_url(buyer))], body, dataset=True)

    # Avtal som kan löpa ut
    ends_html, ends_n = endings_table(awards, 60)
    all_with_duration = sum(1 for a in awards if a["ends"])
    page(f"{BASE}/avtal-som-loper-ut", "Offentliga avtal som kan löpa ut inom två år",
         f"{fnum(ends_n)} offentliga avtal med beräknat slutdatum inom två år, med köpare och nuvarande leverantör. Beräknat från TED.",
         [("Avtal som kan löpa ut", f"{BASE}/avtal-som-loper-ut/")],
         f'<h1>Offentliga avtal som kan löpa ut inom två år</h1><p class="lead">När ett avtal närmar sig slutet kan det upphandlas på nytt. Här är {fnum(ends_n)} avtal där TED anger löptid, sorterade efter beräknat slutdatum.</p>'
         f'<p class="note">Listan är ett urval, inte hela bilden: bara {fnum(all_with_duration)} av {fnum(len(awards))} tilldelningsbeslut anger en löptid vi kan räkna på. Förlängningsoptioner kan skjuta slutet framåt.</p>'
         + ends_html, dataset=True)

    # Metod
    page(f"{BASE}/metod", "Så räknar Anbudsatlasen: källor och begränsningar",
         "Hur Kommunradar räknar anbud, andel med ett anbud och små och medelstora företags andel från TED, och vad siffrorna inte säger.",
         [("Metod", f"{BASE}/metod/")],
         f"""<h1>Så räknar Anbudsatlasen</h1><p class="lead">Atlasen bygger på {fnum(len(awards))} tilldelningsbeslut för svenska köpare, publicerade i TED sedan {MONTHS[nat['first'].month - 1]} {nat['first'].year}.</p>
<h2>Måtten</h2><p><b>Anbud (median):</b> antalet mottagna anbud per upphandling. Har en upphandling flera delar används medianen av delarna, och delar utan anbud räknas inte. {pct(nat['with_bids'] / nat['n'])} av besluten har ett användbart antal, och bara de ingår i måttet.</p>
<p><b>Ett anbud:</b> andelen upphandlingar där medianen är ett anbud.</p>
<p><b>Olika vinnare:</b> antalet olika leverantörsnamn bland vinnarna. Samma bolag kan räknas flera gånger om namnet stavas olika.</p>
<p><b>Företagsstorlek visas inte.</b> TED har ett sådant fält, men det är ifyllt i under hälften av besluten och varierar så mycket mellan jämförbara köpare att vi inte litar på det.</p>
<p><b>Län och bransch:</b> länet är köparens län, inte alltid där uppdraget utförs. Branschen kommer från upphandlingens första CPV-kod. Köpare med olika stavning kan räknas separat.</p>
<h2>Vad siffrorna inte säger</h2><p>Få anbud betyder inte att en upphandling är lätt att vinna. Det kan bero på snäva krav, en smal nisch eller en stark befintlig leverantör. Direktupphandlingar och annat som inte publiceras i TED ingår inte. Sidor skapas bara när underlaget är minst {MIN_COMBO} upphandlingar för län och bransch och {MIN_BUYER} för en köpare.</p>
<p>Vi visar leverantörer bara när namnet har en tydlig bolagsform, eftersom enskilda firmor kan bära en privatpersons namn. Ser du ett fel? Mejla oss via kontaktuppgifterna på <a href="/">startsidan</a>.</p>""")

    # Nav
    lan_rank = ranked(by_lan, lan_url, MIN_RANK)
    cat_rank = ranked(cats, cat_url, MIN_RANK)
    buyer_rank = ranked(buyers, buyer_url, MIN_RANK)
    body = (f"""<h1>Anbudsatlasen: var konkurrensen om offentliga affärer är lägst</h1>
<p class="lead">Hälften av Sveriges upphandlingar i TED fick {num(nat['median'])} anbud eller färre, och {pct(nat['single'])} fick bara ett. Atlasen visar skillnaderna per län, bransch och köpare, tillsammans med det som är öppet just nu.</p>"""
            + tiles(nat) + '<p class="note">Få anbud är inte detsamma som en lätt affär. <a href="' + BASE + '/metod/">Läs hur vi räknar</a>.</p>'
            + "<h2>Län</h2>" + rank_table("Län", lan_rank)
            + "<h2>Branscher</h2>" + rank_table("Bransch", cat_rank)
            + "<h2>Köpare med lägst antal anbud</h2>" + rank_table("Köpare", buyer_rank[:25])
            + "<h2>Köpare med högst antal anbud</h2>" + rank_table("Köpare", list(reversed(buyer_rank[-15:])))
            + f'<h2>Nästa våg av upphandlingar</h2><p>{fnum(ends_n)} avtal kan löpa ut inom två år. <a href="{BASE}/avtal-som-loper-ut/">Se listan</a>.</p>'
            + "<h2>Alla köpare</h2>" + links([(b, buyer_url(b)) for b in sorted(buyers, key=str.casefold)]))
    page(f"{BASE}", "Anbudsatlasen: konkurrens om offentliga upphandlingar i Sverige",
         f"Hur många anbud får upphandlingar i ditt län och din bransch? Statistik från {fnum(len(awards))} tilldelningar i TED, med köpare, vinnare och öppna affärer.",
         [], body, dataset=True)

    # Tre vågor: skicka in en sitemap i taget i Search Console, så att sajten inte går från 3 till 761 sidor på en dag.
    waves = {1: [p for p in PAGES if "/kopare/" not in p and p.rstrip("/").count("/") <= 3],
             2: [p for p in PAGES if "/kopare/" in p]}
    waves[3] = [p for p in PAGES if p not in waves[1] and p not in waves[2]]
    for nr, paths in waves.items():
        urls = "".join(f"<url><loc>{SITE}{p.rstrip('/')}/</loc><lastmod>{TODAY.isoformat()}</lastmod></url>\n" for p in paths)
        (DIST / f"sitemap-atlas-{nr}.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    print("Vågor:", {k: len(v) for k, v in waves.items()})
    print(f"Sidor: {len(PAGES)} (län {len(by_lan)}, bransch {len(cats)}, län+bransch {len(combos)}, köpare {len(buyers)})")
    print(f"Riket: median {nat['median']}, ett anbud {pct(nat['single'])}, vinnare {fnum(nat['suppliers'])}, öppna {len(leads)}, avtal som löper ut {ends_n}")


if __name__ == "__main__":
    main()
