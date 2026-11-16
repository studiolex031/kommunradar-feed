"""Fixar två konverteringsfel på den publicerade startsidan: hero-knappen scrollar resultatet i vy,
och gaten erbjuder ett gratis e-postflöde före kortkravet.

Läser index.html som den ligger LIVE på servern (repots version är bara en basmall och får aldrig
publiceras – den saknar prisplaner och Blueberry). Varje ändring läggs inom markörerna
<!--sp:s--> och <!--sp:e-->, och skriptet tar först bort en tidigare version av dem. Kan köras
hur mång gånger som helst utan att röra prissektionen (<!--pp:s-->) eller något annat.

Användning: python scripts/site_patch.py <in.html> <ut.html>
"""
import sys

S, E = "<!--sp:s-->", "<!--sp:e-->"

# 1. Hero-knappen renderar resultatet under vikningen utan att visa något. Scrolla dit istället.
GO_OLD = "$('go').onclick=search;"
GO_NEW = "$('go').onclick=()=>{search();$('res').scrollIntoView({behavior:'smooth',block:'start'})};"

# 2. Gaten ledde rakt till Stripe. Nu: gratis e-postfångst först, Pro som alternativ.
GATE_OLD = '''<a class="btn y" href="${E(CFG.paymentLink||'#pris')}">Starta bevakning →</a>'''
GATE_NEW = (
    '<div class="gfree">'
    '<input id="gatemail" type="email" inputmode="email" autocomplete="email" '
    'placeholder="din@f&#246;retag.se" aria-label="E-postadress">'
    '<button class="btn y" id="gatego" type="button">F&#229; alla ${fmt(hits.length)} i mejlen – gratis</button>'
    '</div>'
    '<p class="meta" style="margin-top:10px">Gratis veckobrev &middot; inget kort &middot; avsluta n&#228;r du vill. '
    'Eller <a href="${E(CFG.paymentLink||\'#pris\')}" style="text-decoration:underline">prova Pro ${TD} dagar gratis</a>.</p>'
)

STYLE = (
    "<style>\n"
    ".gfree{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}\n"
    ".gfree input{flex:1;min-width:0;background:#0e1530;color:#fff;border:1px solid var(--line);"
    "border-radius:12px;padding:12px 14px;font:600 16px \"Inter Tight\",system-ui,sans-serif;outline:0}\n"
    ".gfree input:focus{border-color:#fbbf24}\n"
    ".gfree .btn{white-space:nowrap}\n"
    "@media(max-width:560px){.gfree{flex-direction:column}.gfree .btn{width:100%}}\n"
    "</style>"
)

SCRIPT = r"""
<script>
(function(){
  var cfg=window.KOMMUNRADAR||{};
  function go(){
    var m=document.getElementById('gatemail');if(!m)return;
    var em=m.value.trim();
    if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(em)){m.focus();m.style.borderColor='#fb7185';return}
    var base=cfg.freeLink||'/veckobrev.html';
    var sep=base.indexOf('?')>-1?'&':'?';
    location.href=base+sep+(cfg.freeLink?'prefilled_email=':'email=')+encodeURIComponent(em);
  }
  document.addEventListener('click',function(e){if(e.target.closest('#gatego'))go()});
  document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target&&e.target.id==='gatemail'){e.preventDefault();go()}});
})();
</script>
"""

BLOCK = S + STYLE + SCRIPT + E


def patch(html: str) -> str:
    # Ta bort tidigare version av våra ändringar.
    start = 0
    while True:
        a = html.find(S, start)
        if a < 0:
            break
        b = html.find(E, a)
        if b < 0:
            sys.exit("Markör %s utan %s – inget ändrat." % (S, E))
        html = html[:a] + html[b + len(E):]
        start = a
    html = html.replace("\n\n</body>", "\n</body>")

    if GO_OLD in html:
        html = html.replace(GO_OLD, GO_NEW, 1)
    elif GO_NEW not in html:
        sys.exit("Hittade varken hero-knappens gamla eller nya onclick – sidan ser annorlunda ut. Inget ändrat.")

    if GATE_OLD in html:
        html = html.replace(GATE_OLD, GATE_NEW, 1)
    elif '<div class="gfree">' not in html:
        sys.exit("Hittade varken gatens gamla eller nya formulär – sidan ser annorlunda ut. Inget ändrat.")

    i = html.rfind("</body>")
    if i < 0:
        sys.exit("Hittade inget </body> – inget ändrat.")
    html = html[:i] + BLOCK + html[i:]
    return html


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()
    out = patch(html)
    assert out.count(GO_NEW) >= 1
    assert out.count("<div class=\"gfree\">") == 1
    assert out.count("id=\"gatemail\"") == 1
    assert out.count(BLOCK) == 1
    assert out.count('<section id="pris">') == html.count('<section id="pris">'), "Prissektionen rörd!"
    assert out.count("<!--pp:s-->") == html.count("<!--pp:s-->"), "Prismarkörer rörda!"
    open(dst, "w", encoding="utf-8").write(out)
    print("Startsidan uppdaterad:", dst)


if __name__ == "__main__":
    main()
