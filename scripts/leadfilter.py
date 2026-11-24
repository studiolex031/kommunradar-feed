"""Vilka vinnar-leads som är för stora för att vara kunder.

TED har ingen uppgift om antal anställda. Det här är därför en **lista**, inte en
mätning: kända stora koncerner på e-postdomän, plus en regel om adresser som är en
anbudsavdelning i stället för en människa. Fyll på listan när nya dyker upp —
domänen är stabilare än namnet, eftersom TED stavar bolagsnamn olika i olika notices.

Används av både `winner_leads.py` (när listan byggs) och `followup_send.py`
(så att uppföljningen inte går till dem som redan fått mejl 1 men är fel segment).

Endast standardbiblioteket.
"""
import re

# Bolag som redan har egna anbudsavdelningar och inte är målgruppen (5–150 anställda).
BIG = re.compile(r"\b(peab|ncc|skanska|veidekke|jm|svevia|ramboll|sweco|wsp|afry|tyréns|iss|sodexo|compass|coor|"
                 r"samhall|forenede|stena|ragn-sells|prezero|ab volvo|scania|siemens|atea|tietoevry|cgi|telia|"
                 r"tele2|vattenfall|eon|e\.on|fortum|attendo|azets|omexom|ge healthcare|securitas|g4s|avarn|bravida|caverion|instalco|assemblin)\b", re.I)

STORA_DOMANER = {
    # internationella grupper
    "abbott.com", "bbraun.com", "cochlear.com", "oticonmedical.com", "invacare.com",
    "permobil.com", "etac.com", "sunrisemedical.se", "stryker.com", "zimmerbiomet.com",
    "medtronic.com", "its.jnj.com", "linde.com", "xylem.com", "schindler.com",
    "eurofins.com", "allente.tv", "trygghansa.se", "swissre.com", "scor.com",
    "specsavers.com", "elis.com", "sortera.se", "lyreco.com", "ahlsell.se",
    # nordiska koncerner, konsult- och bemanningsjättar
    "teliacompany.com", "falck.com", "falcksverige.se", "soprasteria.com",
    "eworkgroup.com", "b3.se", "consid.se", "norconsult.com", "rejlers.se",
    "combitech.com", "semcon.com", "cegal.com", "tengbom.se", "manpowergroup.se",
    "randstad.se", "poolia.se", "academicwork.se", "studentconsulting.com",
    "attendo.se",
    # dagligvaror och grossister (koncerner), funna i torrkörningen 2026-11-24
    "olympus.com", "coop.se", "ica.se", "axfood.se", "dagab.se", "menigo.se", "martinservera.se",
    "svenskcater.se", "bergendahls.se",
    # anbudsbyråer: adressen går via en konsult, inte till bolaget självt
    "tenders.se", "stromsholmadvokat.se",
}

# Adresser som är en anbudsavdelning i stället för en människa. De bolagen har
# redan en funktion för det här. "upphandling@" och "info@" räknas inte hit —
# små bolag använder dem också.
ANBUDSAVDELNING = re.compile(r"^(bid|bidteam|avrop|avropa|ramavtal|tender|tenders|tenderhelp)\b", re.I)


def for_stor(bolag, epost):
    """Är bolaget för stort för att köpa ett mejl för 490 kr i månaden?"""
    epost = (epost or "").strip().lower()
    if "@" not in epost:
        return True
    doman = epost.rsplit("@", 1)[-1]
    return (doman in STORA_DOMANER
            or bool(BIG.search(bolag or ""))
            or bool(ANBUDSAVDELNING.match(epost.split("@")[0])))


# --- ICP-filtret för den automatiska kampanjen (scripts/outbound_campaign.py) ---
# Kommunradar säljer till små och medelstora leverantörer som bjuder regelbundet.
# Myndigheter, kommunala bolag och anbudsbyråer är aldrig kunder; börsbolag (publ)
# har nästan alltid en egen anbudsfunktion.
MYNDIGHET = re.compile(r"(\bkommun$|\bkommun\b(?!.*\b(ab|aktiebolag)\b)|^region(en)?\b(?!.*\b(ab|aktiebolag)\b)|"
                       r"\blandsting|myndighet\b|\buniversitet\b|\bhögskola\b|länsstyrelsen|kommunalförbund|"
                       r"^statens\b|försvarsmakten|(trafik|skatte|naturvårds|bo|livsmedels|läkemedels|migrations|"
                       r"fortifikations)verket\b|försäkringskassan|arbetsförmedlingen)", re.I)
BORSBOLAG = re.compile(r"\(\s*publ\s*\)", re.I)
ANBUDSBYRA = re.compile(r"(anbudsbyr[åa]|upphandlingskonsult|tender\s*(service|consult)|anbudshjälp|anbudsservice)", re.I)
GRATISMEJL = {"gmail.com", "hotmail.com", "hotmail.se", "outlook.com", "outlook.se", "live.se",
              "yahoo.com", "yahoo.se", "icloud.com", "telia.com", "bredband.net", "spray.se"}


# "X Sverige AB" med en .com-adress är nästan alltid ett dotterbolag till en internationell koncern.
DOTTERBOLAG = re.compile(r"\b(sverige|sweden|scandinavia|nordic|nordics)\s+(ab|aktiebolag)\b", re.I)


def utanfor_icp(bolag, epost):
    """Varför leadet INTE är målgrupp, eller "" om det är det."""
    bolag = bolag or ""
    epost = (epost or "").strip().lower()
    if for_stor(bolag, epost):
        return "stor koncern eller anbudsavdelning"
    if MYNDIGHET.search(bolag):
        return "myndighet eller offentlig aktör"
    if BORSBOLAG.search(bolag):
        return "börsnoterat bolag (publ)"
    if ANBUDSBYRA.search(bolag):
        return "anbudsbyrå"
    if DOTTERBOLAG.search(bolag) and epost.endswith(".com"):
        return "svenskt dotterbolag till internationell koncern"
    return ""
