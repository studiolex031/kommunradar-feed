"""Presenterar appen Blueberry Station på den publicerade startsidan, utan att röra något annat.

Läser index.html som den ligger på servern (den kan ha ändrats direkt där). Allt som läggs in omges av
markörerna <!--bb:s--> och <!--bb:e-->, så skriptet först tar bort en tidigare version och sedan lägger in
den aktuella. Det kan alltså köras hur många gånger som helst.

Det som läggs in:
  1. Knapp "✦ AI-appen" i sidhuvudet.
  2. "Nytt"-etikett ovanför rubriken som leder till presentationen.
  3. Ett presentationsavsnitt (#blueberry) direkt efter "Så funkar det", med bild, tre steg och nedladdning.
  4. Länken "✦ Analysera underlaget med AI" på varje upphandling i sökresultatet.
  5. En första fråga under Frågor: "Vad är Blueberry Station?"
  6. Länk i sidfoten.

Användning: python scripts/link_app.py <in.html> <ut.html>
"""
import re
import sys

S, E = "<!--bb:s-->", "<!--bb:e-->"
OLD_V1 = re.compile(r"<!--bb-app-->.*?</section>", re.S)
OLD_V1_FOOTER = ' · <a href="/app/">Appen för Android</a>'


def block(html: str) -> str:
    return S + html + E


CSS = block("""<style>
.bbnav{display:flex;gap:8px;align-items:center}
.bbbtn{display:inline-flex;align-items:center;gap:8px;border-radius:99px;text-decoration:none;font-weight:800;transition:transform .15s,box-shadow .2s}
.bbbtn:hover{transform:translateY(-2px)}
.bbgold{background:linear-gradient(90deg,#B8955A,#E2C68F,#F6E7C4);color:#07080F;box-shadow:0 12px 40px #E2C68F33}
.bbsm{padding:10px 16px;font-size:14px}
.bblg{padding:17px 26px;font-size:17px}
.bbghost{border:1px solid #ffffff26;color:#f4f6fb;background:#ffffff08}
.bbtag{display:inline-flex;align-items:center;gap:8px;margin:14px auto 0;padding:7px 8px 7px 14px;border-radius:99px;border:1px solid #E2C68F55;background:#E2C68F12;color:#F6E7C4;font-size:13.5px;font-weight:700;text-decoration:none}
.bbtag b{background:linear-gradient(90deg,#B8955A,#E2C68F);color:#07080F;border-radius:99px;padding:3px 9px;font-size:11px;letter-spacing:.08em}
.bbsec{border-radius:32px;padding:2px;background:linear-gradient(135deg,#B8955A,#B9A8FF,#6C70FF)}
.bbin{border-radius:30px;background:radial-gradient(40rem 26rem at 100% 0,#6C70FF33,transparent),#0D0F1A;padding:clamp(24px,5vw,56px);display:grid;grid-template-columns:1.05fr .95fr;gap:clamp(24px,4vw,48px);align-items:center}
.bbeb{font-size:12px;letter-spacing:.18em;font-weight:800;color:#E2C68F;text-transform:uppercase}
.bbh{font-family:Georgia,"Noto Serif",serif;font-weight:400;letter-spacing:-.02em;font-size:clamp(32px,4.6vw,56px);line-height:1.04;margin:12px 0 0}
.bbh em{font-style:italic;color:#E2C68F}
.bbsteps{display:grid;gap:12px;margin:26px 0}
.bbstep{display:grid;grid-template-columns:42px 1fr;gap:14px;align-items:start;border:1px solid #2A2F48;border-radius:18px;padding:14px 16px;background:#151827}
.bbstep i{font-style:normal;width:42px;height:42px;border-radius:12px;display:grid;place-items:center;font-weight:900;background:#6C70FF26;color:#B9A8FF}
.bbstep b{display:block;font-size:16px}.bbstep span{color:#9EA3C0;font-size:14.5px}
.bbstep.k i{background:#22d3ee22;color:#a5f3fc}
.bbshot{border-radius:24px;overflow:hidden;border:1px solid #2A2F48;box-shadow:0 40px 100px #000a}
.bbshot img{display:block;width:100%;height:auto}
.bbmeta{color:#9EA3C0;font-size:13.5px;margin-top:12px}
.bbcta{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.card a.bbai{display:table;margin-top:6px;font-size:13px;font-weight:700;color:#E2C68F;text-decoration:none}
.card a.bbai:hover{color:#F6E7C4;text-decoration:underline}
@media(max-width:820px){.bbin{grid-template-columns:1fr}.bbnav .bbapp{padding:9px 13px}}
</style>""")

HEADER_OPEN = block('<div class="bbnav"><a class="bbbtn bbghost bbsm bbapp" href="#blueberry">✦ AI-appen</a>')
HEADER_CLOSE = block("</div>")

TAG = block('<div><a class="bbtag" href="#blueberry"><b>NYTT</b>Blueberry Station – AI som läser förfrågningsunderlaget åt dig →</a></div>')

SECTION = block("""<section id="blueberry"><div class="bbsec"><div class="bbin">
<div>
  <div class="bbeb">Ny · Android-app från Kommunradar</div>
  <h2 class="bbh">Kommunradar hittar affären.<br><em>Blueberry Station</em> hjälper dig vinna den.</h2>
  <p class="sub" style="margin-top:16px">Ett förfrågningsunderlag är ofta 50–200 sidor. Appen läser det åt dig, plockar ut varje ska-krav med sidhänvisning och säger om det är värt att lägga anbud – innan du lagt en hel dag på det.</p>
  <div class="bbsteps">
    <div class="bbstep k"><i>◎</i><div><b>1 · Hitta – Kommunradar</b><span>Nya upphandlingar i din bransch och ditt län, varje morgon.</span></div></div>
    <div class="bbstep"><i>✦</i><div><b>2 · Analysera – Blueberry Station</b><span>AI:n listar alla krav, jämför med dina intyg och ger go eller no-go.</span></div></div>
    <div class="bbstep"><i>✎</i><div><b>3 · Skriv anbudet – Blueberry Station</b><span>Utkast till varje svar, skrivna från dina egna texter och referenser.</span></div></div>
  </div>
  <div class="bbcta">
    <a class="bbbtn bbgold bblg" href="/app/">⬇ Ladda ned appen – gratis</a>
    <a class="bbbtn bbghost bblg" href="/app/#installera">Så funkar det</a>
  </div>
  <div class="bbmeta">Android 9 eller senare · gratis för 3 analyser i månaden · Pro 299 kr/mån · data i EU</div>
</div>
<a class="bbshot" href="/app/"><img src="/app/screens.jpg" alt="Illustration av Blueberry Station: introduktion, bevakningslista och AI-agenten" loading="lazy" width="1400" height="957"></a>
</div></div></section>""")

CARD_LINK = block('<a class="bbai" href="/app/">✦ Analysera underlaget med AI</a>')

FAQ = block('<details><summary>Vad är Blueberry Station?</summary><p>Vår app för Android som tar vid när du hittat en intressant upphandling. Den läser förfrågningsunderlaget med AI, listar alla ska-krav med sidhänvisning, ger go eller no-go och skriver utkast till anbudet. Gratis att börja – <a href="/app/">läs mer och ladda ned</a>.</p></details>')

FOOTER = block(' · <a href="/app/">Blueberry Station – appen</a>')


def strip(html: str) -> str:
    html = re.sub(re.escape(S) + ".*?" + re.escape(E), "", html, flags=re.S)
    html = OLD_V1.sub("", html)
    return html.replace(OLD_V1_FOOTER, "")


def insert(html: str, anchor: str, text: str, before: bool = True, required: bool = True) -> str:
    if anchor not in html:
        if required:
            raise SystemExit(f"Hittade inte {anchor!r} i index.html – publicerar inte.")
        return html
    return html.replace(anchor, text + anchor if before else anchor + text, 1)


def patch(html: str) -> str:
    if "</html>" not in html:
        raise SystemExit("index.html ser trasig ut – publicerar inte.")
    html = strip(html)
    html = insert(html, "</head>", CSS)
    # Sidhuvud: lägg knappen bredvid köpknappen (sista länken i headern).
    head_end = html.index("</header>")
    last_a = html.rfind("<a ", 0, head_end)
    html = html[:last_a] + HEADER_OPEN + html[last_a:head_end] + HEADER_CLOSE + html[head_end:]
    html = insert(html, '<h1><span class="num"', TAG)
    html = insert(html, '<section id="pris">', SECTION)
    html = insert(html, 'rel="noopener">${E(l.title)}</a>', CARD_LINK, before=False, required=False)
    html = insert(html, "<details><summary>Vilka upphandlingar ingår?", FAQ, required=False)
    html = insert(html, "<a data-portal>Hantera prenumeration</a>", FOOTER, before=False, required=False)
    return html


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()
    out = patch(html)
    if len(out) < 10_000 or out.count("</html>") != 1:
        raise SystemExit("Resultatet ser fel ut – publicerar inte.")
    open(dst, "w", encoding="utf-8").write(out)
    print("startsidan uppdaterad med presentationen av appen")
