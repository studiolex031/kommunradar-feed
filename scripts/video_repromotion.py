"""Återpublicering av teaser-videon: mejlar en färdig text med ny vinkel.

    python scripts/video_repromotion.py --dry-run    # skriv ut, mejla inget
    python scripts/video_repromotion.py              # mejla dagens vinkel

Körs av .github/workflows/video-aterpublicering.yml den 1:a och 15:e varje månad.
Vinkeln roterar, så att samma 15 sekunder inte beskrivs likadant två gånger i rad.
Inget publiceras automatiskt: YouTube och LinkedIn kräver kontots inloggning, och
X API saknar krediter. Antingen publicerar du själv från mejlet, eller ber
assistenten göra det i din inloggade webbläsare.
"""
import os, smtplib, ssl, sys
from datetime import date
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "media", "blueberry-teaser.mp4")
POSTER = os.path.join(ROOT, "media", "blueberry-teaser-poster.jpg")
SIDA = "https://kommunradar.online/video.html"
YOUTUBE = "https://youtu.be/X7FXJC06hb8"

LANK = ("https://kommunradar.online/"
        "?utm_source={kalla}&utm_medium=video&utm_campaign=aterpublicering")

VINKLAR = [
    {
        "namn": "Tiden",
        "linkedin": """Underlaget tar en eftermiddag att läsa. Deadline är på fredag.

Det är sällan affärerna är dåliga. Det är tiden som inte räcker.

Vi byggde Blueberry Station för den eftermiddagen.

Kommunradar hittar upphandlingarna som matchar din bransch och ditt län. Blueberry Station läser underlaget och pekar ut kraven, bilagorna och det som brukar fälla anbud.

15 sekunder inifrån appen.

7 dagar gratis, ingen bindningstid.""",
        "x": """Underlaget tar en eftermiddag. Deadline är på fredag.

Blueberry Station läser underlaget och pekar ut kraven, bilagorna och sista anbudsdagen.

15 sekunder inifrån appen.""",
    },
    {
        "namn": "Fällorna",
        "linkedin": """Det som fäller ett anbud är sällan priset.

Det är bilagan ingen läste, kravet som stod på sidan 34, eller att sista anbudsdagen passerade medan underlaget låg oläst.

Blueberry Station går igenom underlaget och pekar ut just det: kraven, bilagorna, fällorna.

15 sekunder inifrån appen.

7 dagar gratis, ingen bindningstid.""",
        "x": """Det som fäller ett anbud är sällan priset.

Det är bilagan ingen läste och kravet på sidan 34.

Blueberry Station pekar ut kraven, bilagorna och fällorna. 15 sekunder inifrån appen.""",
    },
    {
        "namn": "Deadline",
        "linkedin": """Fler dagar att skriva anbudet får du inte av att jobba snabbare.

Du får dem av att se affären tidigt.

Kommunradar mejlar de nya upphandlingarna varje morgon, filtrerade på din bransch och ditt län. Blueberry Station läser underlaget samma dag.

15 sekunder inifrån appen.

7 dagar gratis, ingen bindningstid.""",
        "x": """Fler dagar att skriva anbudet får du inte av att jobba snabbare — utan av att se affären tidigt.

Nya upphandlingar i mejlen varje morgon, underlaget läst samma dag.

15 sekunder inifrån appen.""",
    },
    {
        "namn": "Fokus",
        "linkedin": """80 sidor för att komma fram till att du inte kan lämna anbud.

Det är den dyraste läsningen som finns.

Blueberry Station läser först och säger vad som gäller: kraven, bilagorna, deadlinen. Du läser bara det som avgör.

15 sekunder inifrån appen.

7 dagar gratis, ingen bindningstid.""",
        "x": """80 sidor för att komma fram till att du inte kan lämna anbud.

Blueberry Station läser först och säger vad som gäller. Du läser bara det som avgör.

15 sekunder inifrån appen.""",
    },
]

HASHTAGS = "#upphandling #offentligsektor #småföretag"


def valj_vinkel(dagens_datum=None):
    """Roterar vinkeln med två veckors mellanrum, så den inte upprepas i rad."""
    d = dagens_datum or date.today()
    return VINKLAR[(d.timetuple().tm_yday // 14) % len(VINKLAR)]


def paket(vinkel):
    """Hela mejltexten för en vinkel."""
    li = f"{vinkel['linkedin']}\n\n{HASHTAGS}"
    return f"""ÅTERPUBLICERING — Blueberry Station, 15 sekunder
Vinkel: {vinkel['namn']}
Video: media/blueberry-teaser.mp4 (1920x1080, 15 s, h264 + aac)
Sida: {SIDA}
YouTube (befintlig): {YOUTUBE}

============================================================
1. LINKEDIN — native uppladdning, inte YouTube-länk
============================================================
{li}

Första kommentar (klistra in direkt efter publicering):
{LANK.format(kalla='linkedin')}

============================================================
2. X — video i inlägget, länk i svaret
============================================================
{vinkel['x']}

Svar direkt efter:
{LANK.format(kalla='x')}

============================================================
3. OM DU VILL SLIPPA GÖRA DET SJÄLV
============================================================
Säg till assistenten: "publicera videon igen". Den publicerar i din inloggade
webbläsare — YouTube, LinkedIn och X — och verifierar att inläggen ligger ute.
Kostar 0 kr, eftersom det går via webbläsaren och inte via X API.

============================================================
4. EFTERÅT
============================================================
- Svara på kommentarer första timmen.
- Kolla GA4: händelsen video_play och video_complete på /video.html.
- Ger videon inga visningar alls? Byt vinkel i stället för att posta oftare.

Videon och affischen är bifogade.
"""


def main():
    vinkel = valj_vinkel()
    text = paket(vinkel)
    if "--dry-run" in sys.argv:
        print(text)
        return
    msg = EmailMessage()
    msg["Subject"] = f"Återpublicering: videon med vinkeln {vinkel['namn']}"
    msg["To"] = os.environ["REPORT_TO"]
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"])
    msg.set_content(text)
    for path, maintype, subtype in ((VIDEO, "video", "mp4"), (POSTER, "image", "jpeg")):
        with open(path, "rb") as f:
            msg.add_attachment(f.read(), maintype=maintype, subtype=subtype,
                               filename=os.path.basename(path))
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=90)
    s.starttls(context=ssl.create_default_context())
    s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg)
    s.quit()
    print(f"Återpubliceringen mejlad till REPORT_TO (vinkel: {vinkel['namn']})")


if __name__ == "__main__":
    main()
