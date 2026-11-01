#!/usr/bin/env python3
"""Hämtar startsidan och robots.txt live och skriver uppdaterade versioner till atlas/dist/.

    python atlas/scripts/patch_home.py 2      # 1 = sitemap-våg 1, 2 = våg 1–2, 3 = alla

Länkar startsidan redan till atlasen skrivs bara robots.txt.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
SITE = "https://kommunradar.online"
LAN = ["Blekinge", "Dalarna", "Gotland", "Gävleborg", "Halland", "Jämtland", "Jönköping", "Kalmar", "Kronoberg",
       "Norrbotten", "Skåne", "Stockholm", "Södermanland", "Uppsala", "Värmland", "Västerbotten", "Västernorrland",
       "Västmanland", "Västra Götaland", "Örebro", "Östergötland"]
LD = [{"@context": "https://schema.org", "@type": "WebSite", "name": "Kommunradar", "url": f"{SITE}/", "inLanguage": "sv"},
      {"@context": "https://schema.org", "@type": "Service", "name": "Kommunradar",
       "serviceType": "Bevakning av offentliga upphandlingar", "areaServed": "SE", "url": f"{SITE}/",
       "provider": {"@type": "Organization", "name": "Kommunradar", "url": f"{SITE}/"},
       "offers": {"@type": "Offer", "price": "990", "priceCurrency": "SEK", "url": f"{SITE}/"}}]


def get(path):
    with urllib.request.urlopen(f"{SITE}{path}", timeout=30) as r:
        return r.read().decode()


def slug(s):
    s = s.lower().replace("å", "a").replace("ä", "a").replace("ö", "o")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def robots_for(current, wave):
    """Byter ut atlasens sitemap-rader, så att en ny våg inte ger dubbletter."""
    kept = [l for l in current.splitlines() if not re.match(r"(?i)sitemap:.*/sitemap-atlas-\d+\.xml\s*$", l)]
    return "\n".join(kept).rstrip() + "\n" + "".join(f"Sitemap: {SITE}/sitemap-atlas-{n}.xml\n" for n in range(1, wave + 1))


def patch_index(html):
    links = "".join(f'<a class="btn g sm" href="/upphandlingar/lan/{slug(l)}/">{l}</a>' for l in LAN)
    section = ('<section><div class="w" style="text-align:center"><h2>Hur hård är konkurrensen i ditt län?</h2>'
               '<p class="sub" style="margin-left:auto;margin-right:auto">Anbudsatlasen visar hur många anbud upphandlingarna får, vilka som vinner och vad som är öppet just nu.</p>'
               f'<div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin-top:18px">{links}</div>'
               '<p style="margin-top:18px"><a href="/upphandlingar/">Öppna hela Anbudsatlasen →</a></p></div></section>')
    marker = '<section><div class="final">'
    if html.count(marker) != 1:
        sys.exit("Hittar inte platsen för länkblocket – startsidan har ändrats.")
    html = html.replace(marker, section + marker)
    ld = json.dumps(LD, ensure_ascii=False).replace("</", "<\\/")
    return html.replace("</head>", f'<script type="application/ld+json">{ld}</script></head>', 1)


def main():
    wave = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    if wave not in (1, 2, 3):
        sys.exit("Vågen måste vara 1, 2 eller 3.")
    DIST.mkdir(exist_ok=True)
    html = get("/")
    if "/upphandlingar/" in html:
        print("Startsidan länkar redan till atlasen, så index.html ändras inte.")
    else:
        (DIST / "index.html").write_text(patch_index(html))
        print("dist/index.html klar")
    (DIST / "robots.txt").write_text(robots_for(get("/robots.txt"), wave))
    print(f"dist/robots.txt klar (våg {wave})")


if __name__ == "__main__":
    main()
