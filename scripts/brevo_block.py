"""Speglar stopplistan till Brevos egen blocklista.

    python scripts/brevo_block.py             # blockera allt som står i svarat.txt
    python scripts/brevo_block.py --dry-run   # visa bara vilka som skulle blockeras

Stopplistan i repot (`.github/outbound/svarat.txt`) styr våra egna utskick. Brevos
blocklista är ett andra lager: den stoppar även sådant som inte går via scripts — en
kampanj, ett testutskick, en manuell sändning.

Kräver `BREVO_API_KEY` med Contacts-behörighet. Nyckeln skapas i Brevo under
Settings → SMTP & API → API keys, Restricted → Contacts: All.

Endast standardbiblioteket.
"""
import json, os, sys, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVARAT = os.path.join(ROOT, ".github", "outbound", "svarat.txt")
API = "https://api.brevo.com/v3/contacts"


def adresser(path=SVARAT):
    """Adresserna i stopplistan, utan kommentarer och dubbletter."""
    if not os.path.exists(path):
        return []
    ut, sedda = [], set()
    with open(path, encoding="utf-8") as f:
        for rad in f:
            a = rad.split("#", 1)[0].strip().lower()
            if not a or "@" not in a or a in sedda:
                continue
            sedda.add(a)
            ut.append(a)
    return ut


def blockera(epost, nyckel, torrkorning=False):
    """Sätt emailBlacklisted på kontakten. Skapar den om den inte finns."""
    if torrkorning:
        return "skulle blockeras"
    kropp = json.dumps({"email": epost, "emailBlacklisted": True, "updateEnabled": True}).encode()
    req = urllib.request.Request(API, data=kropp, method="POST", headers={
        "api-key": nyckel, "Content-Type": "application/json", "Accept": "application/json"})
    for försök in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as svar:
                return f"blockerad ({svar.status})"
        except urllib.error.HTTPError as e:
            if e.code == 429 and försök < 2:      # Brevo: för många anrop, vänta och gör om
                time.sleep(1 + försök)
                continue
            detalj = e.read().decode("utf-8", "replace")[:160]
            return f"FEL {e.code}: {detalj}"
        except urllib.error.URLError as e:
            return f"FEL nät: {e.reason}"
    return "FEL: gav upp"


def main():
    torrkorning = "--dry-run" in sys.argv
    nyckel = os.environ.get("BREVO_API_KEY")
    if not nyckel and not torrkorning:
        sys.exit("BREVO_API_KEY saknas. Sätt den i miljön eller kör med --dry-run.")

    lista = adresser()
    if not lista:
        print("Stopplistan är tom — inget att göra.")
        return

    print(f"{len(lista)} adresser i {os.path.relpath(SVARAT, ROOT)}")
    fel = 0
    for epost in lista:
        resultat = blockera(epost, nyckel, torrkorning)
        print(f"  {epost:40} {resultat}")
        fel += resultat.startswith("FEL")
    if fel:
        sys.exit(f"{fel} av {len(lista)} gick inte att blockera.")


if __name__ == "__main__":
    main()
