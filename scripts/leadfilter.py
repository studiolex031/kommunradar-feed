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
