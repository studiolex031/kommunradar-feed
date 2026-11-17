"""Publiceringspaket för teaser-videon: mejlar färdig text till YouTube, LinkedIn och X.

    python scripts/video_kit.py --dry-run    # skriver paketet i video-out/, mejlar inget
    python scripts/video_kit.py              # mejlar paketet till REPORT_TO med videon bifogad

Inget publiceras automatiskt: YouTube och LinkedIn kräver inloggning som bara kontots ägare
kan göra, och X API är pay-per-use utan krediter. Mejlet är paketet — kopiera, klistra in, klart.
"""
import os, smtplib, ssl, sys
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "media", "blueberry-teaser.mp4")
POSTER = os.path.join(ROOT, "media", "blueberry-teaser-poster.jpg")
SIDA = "https://kommunradar.online/video.html"
LANK = "https://kommunradar.online/?utm_source={kalla}&utm_medium=video&utm_campaign=teaser"
GRATIS = "https://kommunradar.online/veckobrev.html"

YT_TITEL = "Blueberry Station — så läser appen upphandlingen åt dig (15 sek)"
YT_TEXT = f"""Kommunradar hittar affären. Blueberry Station hjälper dig vinna den.

Varje morgon: nya offentliga upphandlingar för din bransch och ditt län.
Öppna en — appen har redan läst underlaget och pekar ut krav, bilagor och sista anbudsdag.

Prova 7 dagar gratis: {LANK.format(kalla='youtube')}
Gratis veckobrev, inget kort: {GRATIS}

0:00 Upphandlingar för din bransch och ditt län
0:05 Underlaget läst — krav, bilagor, deadline
0:10 Beslut på minuter i stället för en eftermiddag

#upphandling #offentligsektor #småföretag"""
YT_TAGGAR = ("upphandling, offentlig upphandling, kommunal upphandling, anbud, "
             "anbudsunderlag, småföretag, entreprenör, kommunradar, blueberry station")

LI_TEXT = """Hälften av Sveriges upphandlingar får tre anbud eller färre.

Det är sällan för att affärerna är dåliga. Det är för att underlaget tar en eftermiddag att läsa igenom — och deadline är på fredag.

Vi byggde Blueberry Station för den eftermiddagen.

Kommunradar hittar upphandlingarna som matchar din bransch och ditt län. Blueberry Station läser underlaget och pekar ut kraven, bilagorna och det som brukar fälla anbud.

15 sekunder inifrån appen. Länk i första kommentaren.

7 dagar gratis, ingen bindningstid.

#upphandling #offentligsektor #småföretag"""

X_TEXT = """15 sekunder inifrån Blueberry Station.

Kommunradar hittar upphandlingen. Appen läser underlaget och pekar ut kraven, bilagorna och sista anbudsdagen.

Beslut på minuter i stället för en eftermiddag."""


def paket():
    """Hela publiceringspaketet som text."""
    return f"""PUBLICERINGSPAKET — Blueberry Station, 15 sekunder
Video: media/blueberry-teaser.mp4 (1920x1080, 15 s, 3,6 MB, h264 + aac)
Affisch: media/blueberry-teaser-poster.jpg
Sida: {SIDA}

============================================================
1. YOUTUBE — ladda upp manuellt (2 min)
============================================================
Titel:
{YT_TITEL}

Beskrivning:
{YT_TEXT}

Taggar:
{YT_TAGGAR}

Inställningar:
  Kategori: Science & Technology
  Synlighet: Public
  Miniatyr: media/blueberry-teaser-poster.jpg
  Inte Short (liggande 16:9)

============================================================
2. LINKEDIN — ladda upp videon direkt, inte som YouTube-länk
============================================================
Inläggstext:
{LI_TEXT}

Första kommentar (klistra in direkt efter publicering):
{LANK.format(kalla='linkedin')}

Varför direkt uppladdning: LinkedIn visar native video för fler än en länk till YouTube.

============================================================
3. X — text + video, länk i svar
============================================================
Inlägg:
{X_TEXT}

Svar direkt efter (länken i svaret, inte i inlägget):
{LANK.format(kalla='x')}

Kostnad om du köper krediter: inlägg utan länk $0,015, med länk $0,20. Länken i svaret
håller nere kostnaden för själva inlägget, men svaret med länk debiteras som länk-inlägg.

============================================================
4. EFTERÅT
============================================================
- Svara på kommentarer första timmen — det avgör räckvidden.
- Klistra in YouTube-länken i beskrivningen på video.html när den finns.
- 48 h senare: nytt inlägg på LinkedIn med en av annonstexterna i x-dagligt-mejlet.

Filer bifogade: videon och affischen, redo att ladda upp.
"""


def main():
    dry = "--dry-run" in sys.argv
    text = paket()
    if dry:
        print(text)
        return
    msg = EmailMessage()
    msg["Subject"] = "Publiceringspaket: Blueberry Station 15 sek — YouTube, LinkedIn, X"
    msg["To"] = os.environ["REPORT_TO"]
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"])
    msg.set_content(text)
    for path, sub in ((VIDEO, "mp4"), (POSTER, "jpeg")):
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype="video" if sub == "mp4" else "image",
                               subtype=sub, filename=os.path.basename(path))
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=90)
    s.starttls(context=ssl.create_default_context())
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
    s.quit()
    print("Publiceringspaketet mejlat till REPORT_TO")


if __name__ == "__main__":
    main()
