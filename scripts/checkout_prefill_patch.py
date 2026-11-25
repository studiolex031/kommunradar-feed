"""Kopplar in checkout-prefill.js på den publicerade startsidan.

Läser index.html som den ligger LIVE (repots index.html får aldrig publiceras, se deploy.yml) och
lägger en script-rad före </body> inom markörerna <!--cp:s--> / <!--cp:e-->. Byter också texten
"Ange dina bevakningsord och välj län i Stripe-kassan." om den finns. Idempotent: en tidigare
version av blocket tas bort först, och inget annat på sidan rörs.

Användning: python scripts/checkout_prefill_patch.py <in.html> <ut.html> [version]
"""
import re
import sys

S, E = "<!--cp:s-->", "<!--cp:e-->"
OLD_NOTE = "Ange dina bevakningsord och välj län i Stripe-kassan."
NEW_NOTE = "Dina bevakningsord och ditt län följer med till kassan."


def patch(html: str, version: str = "1") -> str:
    html = re.sub(re.escape(S) + r".*?" + re.escape(E) + r"\n?", "", html, flags=re.S)
    if html.count("</body>") != 1:
        sys.exit("Hittade inte </body> exakt en gång – sidan ser annorlunda ut. Inget ändrat.")
    block = f'{S}<script src="/checkout-prefill.js?v={version}" defer></script>{E}\n'
    html = html.replace("</body>", block + "</body>", 1)
    return html.replace(OLD_NOTE, NEW_NOTE)


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    version = re.sub(r"[^A-Za-z0-9]", "", sys.argv[3] if len(sys.argv) > 3 else "1")[:12] or "1"
    html = open(src, encoding="utf-8").read()
    out = patch(html, version)
    assert out.count(S) == 1 and out.count(E) == 1
    for marker in ("<!--pp:s-->", "/*dp:v1*/", "<!--sp:s-->", 'id="kr-demo-form"'):
        assert out.count(marker) == html.count(marker), f"{marker} rördes!"
    assert abs(len(out) - len(html)) < 400
    open(dst, "w", encoding="utf-8").write(out)
    print("Startsidan uppdaterad:", dst)


if __name__ == "__main__":
    main()
