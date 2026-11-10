"""Lägger till årspris och grundarpris i prissektionen (#pris) på den publicerade startsidan, utan att röra något annat.

Läser index.html som den ligger på servern (den kan ha ändrats direkt där). Det befintliga 990 kr-kortet
lämnas orört. Varje inlagd del omges av markörerna <!--pp:s--> och <!--pp:e-->, så skriptet först tar bort en
tidigare version och sedan lägger in den aktuella. Det kan alltså köras hur många gånger som helst.

Rubriken "Ett pris. Alla affärer." byts till "Välj ditt pris. Samma affärer.".

Ordningen i <section id="pris">, uppifrån:
  1. Grundarpris: 490 kr/mån, låst så länge man är kund, för de 20 första kunderna (ovanför 990 kr-kortet).
     Stripe-länken stänger sig själv efter 20 köp och visar då ett meddelande.
  2. Det befintliga 990 kr-kortet (orört).
  3. Årspris: 7 900 kr/år, motsvarar 658 kr/mån (under 990 kr-kortet).

Båda länkarna har samma 7 dagars provperiod, bevakningsord, län och tack-sida som 990 kr-länken.

Användning: python scripts/pricing_plans.py <in.html> <ut.html>
"""
import re
import sys

S, E = "<!--pp:s-->", "<!--pp:e-->"

YEARLY_LINK = "https://buy.stripe.com/bJe4gy43K2wranb5agg7e04"
FOUNDER_LINK = "https://buy.stripe.com/7sYeVcbwc5ID9j7fOUg7e03"
FOUNDER_SEATS = 20

STYLE = """<style>
.ppcard{max-width:560px;margin:40px auto 0;border:1px solid var(--line);border-radius:24px;padding:28px;background:#ffffff06;text-align:center}
.ppcard.f{border-color:#fbbf2466;background:linear-gradient(180deg,#fbbf2412,#ffffff04)}
.ppeb{font-size:12px;letter-spacing:.16em;font-weight:800;text-transform:uppercase;color:var(--mut)}
.ppcard.f .ppeb{color:var(--y)}
.ppamt{font-size:44px;font-weight:900;letter-spacing:-.04em;line-height:1;margin-top:10px}
.ppamt small{font-size:16px;color:var(--mut);font-weight:700;letter-spacing:0;margin-left:4px}
.ppnote{color:#a5f3fc;font-weight:700;font-size:14px;margin-top:8px}
.ppcard p{color:var(--mut);font-size:15px;margin:12px auto 20px;max-width:440px}
.ppcard .btn{justify-content:center;width:100%;font-size:17px;padding:16px 18px}
.ppsmall{color:var(--mut);font-size:12.5px;margin-top:10px}
#pris .price{margin-top:24px}
</style>"""

FOUNDER = S + STYLE + """
<div class="ppcard f">
  <div class="ppeb">Grundarpris · bara """ + str(FOUNDER_SEATS) + """ platser</div>
  <div class="ppamt">490 kr<small>/mån</small></div>
  <div class="ppnote">Låst så länge du är kund</div>
  <p>För de """ + str(FOUNDER_SEATS) + """ första företagen. Du får hela Kommunradar Pro för halva priset – för alltid – och hjälper oss forma tjänsten.</p>
  <a class="btn y" href=\"""" + FOUNDER_LINK + """\">Säkra grundarpriset →</a>
  <div class="ppsmall">7 dagar gratis · ingen moms · ingen bindningstid</div>
</div>""" + E

YEARLY = S + """
<div class="ppcard" style="margin-top:24px">
  <div class="ppeb">Årspris</div>
  <div class="ppamt">7 900 kr<small>/år</small></div>
  <div class="ppnote">Motsvarar 658 kr/mån – du sparar 3 980 kr</div>
  <p>Samma Kommunradar Pro, betalt en gång om året. Även här är de första 7 dagarna gratis.</p>
  <a class="btn g" href=\"""" + YEARLY_LINK + """\">Välj årspris →</a>
  <div class="ppsmall">Ingen moms · förnyas årsvis · säg upp när du vill</div>
</div>""" + E

OLD = re.compile(re.escape(S) + r".*?" + re.escape(E), re.S)
PRIS = re.compile(r'(<section id="pris">.*?)(</section>)', re.S)


OLD_TITLE = ">Ett pris. Alla affärer.<"
NEW_TITLE = ">Välj ditt pris. Samma affärer.<"


def price_card(section: str):
    """Start och slut för 990 kr-kortet (<div class="price">…</div>) i prissektionen."""
    i = section.find('<div class="price"')
    if i < 0:
        return None
    depth = 0
    for t in re.finditer(r"<div\b|</div>", section[i:]):
        depth += 1 if t.group(0) != "</div>" else -1
        if depth == 0:
            return i, i + t.end()
    return None


def patch(html: str) -> str:
    html = OLD.sub("", html)
    m = PRIS.search(html)
    if not m:
        sys.exit('Hittade ingen <section id="pris"> på sidan – inget ändrat.')
    section = m.group(1).replace(OLD_TITLE, NEW_TITLE, 1)
    card = price_card(section)
    if card:  # grundarpris ovanför 990 kr-kortet, årspris under
        a, b = card
        section = section[:a] + FOUNDER + section[a:b] + YEARLY + section[b:]
    else:  # hittar inte kortet: lägg båda sist i sektionen
        section = section + FOUNDER + YEARLY
    return html[: m.start()] + section + html[m.start(2):]


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()
    out = patch(html)
    assert out.count(S) == 2 and out.count(E) == 2
    assert out.count('<section id="pris">') == html.count('<section id="pris">')
    open(dst, "w", encoding="utf-8").write(out)
    print("Prissektionen uppdaterad:", dst)


if __name__ == "__main__":
    main()
