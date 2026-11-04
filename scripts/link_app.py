"""Lägger in en länk till appen (Blueberry Station) i den publicerade startsidan, utan att röra något annat.

Läser index.html som den ligger på servern (den kan ha ändrats direkt där), lägger till ett avsnitt före
slutrutan och en länk i sidfoten, och skriver resultatet. Körs igen utan att lägga in något två gånger.
Användning: python scripts/link_app.py <in.html> <ut.html>
"""
import sys

MARK = "<!--bb-app-->"
SECTION = MARK + """<section><div style="border-radius:28px;padding:2px;background:linear-gradient(135deg,#B8955A,#B9A8FF,#6C70FF)"><div style="background:#0e1530;border-radius:26px;padding:clamp(24px,4vw,44px);display:flex;flex-wrap:wrap;gap:24px;align-items:center;justify-content:space-between"><div style="max-width:640px"><div style="font-size:12px;letter-spacing:.18em;font-weight:800;color:#E2C68F">NY · ANDROID-APP</div><h2 style="margin-top:10px">Hittat en affär? Låt AI:n läsa underlaget.</h2><p class="sub" style="margin-top:12px">Blueberry Station listar alla ska-krav med sidhänvisning, ger go eller no-go och skriver utkast till anbudet. Gratis att börja.</p></div><a class="btn" href="/app/" style="background:linear-gradient(90deg,#B8955A,#E2C68F,#F6E7C4);color:#07080F">Ladda ned appen →</a></div></div></section>"""
FOOTER_LINK = ' · <a href="/app/">Appen för Android</a>'


def patch(html: str) -> str:
    if MARK in html:
        return html
    anchor = '<section><div class="final">'
    if anchor not in html or "</html>" not in html:
        raise SystemExit("Hittade inte förväntad struktur i index.html – publicerar inte.")
    html = html.replace(anchor, SECTION + anchor, 1)
    portal = '<a data-portal>Hantera prenumeration</a>'
    if portal in html:
        html = html.replace(portal, portal + FOOTER_LINK, 1)
    return html


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()
    out = patch(html)
    if len(out) < len(html) or len(out) < 10_000:
        raise SystemExit("Resultatet ser fel ut – publicerar inte.")
    open(dst, "w", encoding="utf-8").write(out)
    print("oförändrad" if out == html else "länk tillagd")
