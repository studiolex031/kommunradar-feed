import calendar, html, json, re, time, urllib.error, urllib.request
from datetime import date, datetime, timedelta, timezone

URL = "https://api.ted.europa.eu/v3/notices/search"
KALLA = "TED, © Europeiska unionen, CC BY 4.0, bearbetad av Kommunradar"
P1_KOLUMNER = ["publicerad", "upphandling", "köpare", "vinnande leverantör(er)", "org.nr i annonsen",
               "värde", "bransch", "län", "länk"]

P2_KOLUMNER = ["beräknat slutdatum", "köpare", "nuvarande leverantör", "upphandling",
               "värde", "län", "länk", "säkerhet"]
FIELDS = ["publication-number", "publication-date", "notice-title", "notice-type", "buyer-name",
          "buyer-country-sub", "place-of-performance", "classification-cpv", "winner-name",
          "winner-identifier", "organisation-identifier-tenderer", "contract-conclusion-date",
          "contract-duration-start-date-lot", "contract-duration-end-date-lot",
          "contract-duration-period-lot", "contract-duration-start-date-part",
          "contract-duration-end-date-part", "contract-duration-period-part",
          "estimated-value-lot", "estimated-value-cur-lot", "total-value", "total-value-cur"]
LAN = {"SE110": "Stockholm", "SE121": "Uppsala", "SE122": "Södermanland", "SE123": "Östergötland",
       "SE124": "Örebro", "SE125": "Västmanland", "SE211": "Jönköping", "SE212": "Kronoberg",
       "SE213": "Kalmar", "SE214": "Gotland", "SE221": "Blekinge", "SE224": "Skåne", "SE231": "Halland",
       "SE232": "Västra Götaland", "SE311": "Värmland", "SE312": "Dalarna", "SE313": "Gävleborg",
       "SE321": "Västernorrland", "SE322": "Jämtland", "SE331": "Västerbotten", "SE332": "Norrbotten"}
CPV = {"03": "Jordbruk & skog", "09": "Bränsle & energi", "14": "Gruvprodukter", "15": "Livsmedel",
       "16": "Jordbruksmaskiner", "18": "Kläder & skor", "19": "Textil & läder", "22": "Trycksaker & böcker",
       "24": "Kemikalier", "30": "Datorer & kontorsutrustning", "31": "El & belysning", "32": "Telekom & AV",
       "33": "Medicinteknik & läkemedel", "34": "Fordon & transportmedel", "35": "Säkerhet & räddning",
       "37": "Sport & fritidsutrustning", "38": "Labb & mätinstrument", "39": "Möbler & inredning",
       "41": "Vatten", "42": "Industrimaskiner", "43": "Bygg- & anläggningsmaskiner", "44": "Byggmaterial",
       "45": "Bygg & anläggning", "48": "Programvara & system", "50": "Service & underhåll",
       "51": "Installation", "55": "Hotell, restaurang & måltider", "60": "Transporter", "63": "Resor & logistik",
       "64": "Post & telekomtjänster", "65": "Energi- & vattentjänster", "66": "Finans & försäkring",
       "70": "Fastighetstjänster", "71": "Arkitekt- & teknikkonsult", "72": "IT-tjänster",
       "73": "Forskning & utveckling", "75": "Offentlig förvaltning", "76": "Olja & gas",
       "77": "Park, skog & grönyta", "79": "Företagstjänster", "80": "Utbildning", "85": "Vård & omsorg",
       "90": "Avfall, städ & miljö", "92": "Kultur & fritid", "98": "Övriga tjänster"}


def retry_after(value):
    if not value:
        return None
    if value.strip().isdigit():
        return int(value)
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(value)
        return max(0, int((when - datetime.now(tz=timezone.utc)).total_seconds()))
    except (TypeError, ValueError):
        return None


def fetch(query, page=1, limit=100):
    body = json.dumps({"query": query, "fields": FIELDS, "page": page, "limit": limit}).encode()
    req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 429 and error.code < 500 or attempt == 5:
                raise
            wait = retry_after(error.headers.get("Retry-After")) or 5 * 2 ** attempt
            time.sleep(min(wait, 120))


def fetch_notices(query, fields=None, max_pages=50, limit=100):
    all_notices, page = [], 1
    while page <= max_pages:
        body = json.dumps({"query": query, "fields": fields or FIELDS, "page": page, "limit": limit}).encode()
        req = urllib.request.Request(URL, data=body, headers={"Content-Type": "application/json"})
        for attempt in range(6):
            try:
                with urllib.request.urlopen(req, timeout=60) as response:
                    result = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code != 429 and error.code < 500 or attempt == 5:
                    raise
                wait = retry_after(error.headers.get("Retry-After")) or 5 * 2 ** attempt
                time.sleep(min(wait, 120))
        notices = result.get("notices", [])
        all_notices.extend(notices)
        if len(notices) < limit:
            break
        page += 1
        time.sleep(1)
    return all_notices


def values(value, decode=False):
    if isinstance(value, dict):
        value = value.get("swe") or value.get("eng") or next(iter(value.values()), [])
    if not isinstance(value, list):
        value = [value] if value else []
    return [(html.unescape(str(item)) if decode else str(item)).strip() for item in value if str(item or "").strip()]


def txt(value):
    items = values(value)
    return items[0] if items else ""


def clean_title(title):
    parts = title.split(" – ", 2)
    return parts[-1].strip() if title.startswith("Sverige – ") and len(parts) == 3 else title.strip()


def date_only(value):
    match = re.match(r"\d{4}-\d{2}-\d{2}", str(value or ""))
    return match.group(0) if match else ""


def orgnr(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith(("16", "19", "20")):
        digits = digits[2:]
    return f"{digits[:6]}-{digits[6:]}" if len(digits) == 10 else digits


def luhn(digits):
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def ar_personnummer(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) == 12 and digits.startswith(("18", "19", "20")):
        digits = digits[2:]
    if len(digits) != 10:
        return False
    month, day = int(digits[2:4]), int(digits[4:6])
    return 1 <= month <= 12 and 1 <= day <= 31 and luhn(digits)


def add_months(value, months):
    total = value.month - 1 + months
    year, month = value.year + total // 12, total % 12 + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def parse_duration(value):
    if isinstance(value, dict):
        amount = value.get("value", value.get("number", value.get("amount")))
        unit = str(value.get("unit", "")).upper()
        try:
            amount = int(float(amount))
        except (TypeError, ValueError):
            return None
        if unit in ("YEAR", "YEARS", "Y"):
            return {"years": amount, "months": 0, "days": 0}
        if unit in ("MONTH", "MONTHS", "M"):
            return {"years": 0, "months": amount, "days": 0}
        if unit in ("WEEK", "WEEKS", "W"):
            return {"years": 0, "months": 0, "days": amount * 7}
        if unit in ("DAY", "DAYS", "D"):
            return {"years": 0, "months": 0, "days": amount}
        return None
    text = str(value or "").strip().upper()
    match = re.fullmatch(r"P(?:(\d+)Y)?(?:(\d+)M)?(?:(\d+)W)?(?:(\d+)D)?", text)
    if not match or not any(match.groups()):
        return None
    years, months, weeks, days = (int(part or 0) for part in match.groups())
    return {"years": years, "months": months, "days": weeks * 7 + days}


def add_duration(start, duration):
    parsed = parse_duration(duration)
    if not parsed or not start:
        return None
    result = add_months(start, parsed["years"] * 12 + parsed["months"])
    return result + timedelta(days=parsed["days"])


def koder(value):
    return values(value.get("place-of-performance")) or values(value.get("buyer-country-sub"))


def laner(value):
    return list(dict.fromkeys(LAN[code] for code in koder(value) if code in LAN))


def belopp(value):
    total = value.get("total-value")
    currency = values(value.get("total-value-cur"))
    if total and (not currency or currency[0].upper() == "SEK"):
        try:
            amount = int(float(total))
            if 0 < amount <= 5e9:
                return amount
        except (TypeError, ValueError):
            pass
    amounts = values(value.get("estimated-value-lot"))
    currencies = values(value.get("estimated-value-cur-lot"))
    for index, amount in enumerate(amounts):
        currency = currencies[index] if index < len(currencies) else (currencies[0] if len(currencies) == 1 else "SEK")
        try:
            number = int(float(amount))
        except (TypeError, ValueError):
            continue
        if currency.upper() == "SEK" and 0 < number <= 5e9:
            return number
    return ""


def vinnare(value):
    names = values(value.get("winner-name"), True)
    identifiers = values(value.get("winner-identifier")) or values(value.get("organisation-identifier-tenderer"))
    result, seen = [], set()
    for index, name in enumerate(names):
        identifier = identifiers[index] if index < len(identifiers) else ""
        if ar_personnummer(identifier):
            continue
        key = re.sub(r"[^a-z0-9åäö]", "", name.casefold())
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((name, orgnr(identifier)))
    return result


def ar_award(value, today=None):
    notice_type = txt(value.get("notice-type"))
    return not notice_type or notice_type.startswith("can")


def p1_query(days=7):
    since = (date.today() - timedelta(days=days)).strftime("%Y%m%d")
    return f"organisation-country-buyer=SWE AND notice-type IN (can-standard, can-social) AND publication-date>={since}"


def p2_query(today=None):
    day = date.fromisoformat(date_only(today)) if today else date.today()
    start, end = day.strftime("%Y%m%d"), (day + timedelta(days=365)).strftime("%Y%m%d")
    return (f"organisation-country-buyer=SWE AND notice-type IN (can-standard, can-social) "
            f"AND (contract-duration-end-date-lot>={start} AND contract-duration-end-date-lot<={end} "
            f"OR contract-duration-start-date-lot>={start} AND contract-duration-start-date-lot<={end})")


def url_for(value):
    return f"https://ted.europa.eu/sv/notice/-/detail/{value.get('publication-number', '')}"


def p1_rows(notices, bransch=None, lan=None, today=None):
    cutoff = (date.fromisoformat(today) - timedelta(days=7)).isoformat() if today else None
    rows, seen = [], set()
    for notice in notices:
        if not ar_award(notice, today):
            continue
        published = date_only(notice.get("publication-date"))
        if cutoff and (not published or published < cutoff):
            continue
        cpvs = values(notice.get("classification-cpv"))
        if bransch and not any(code[:2] == bransch for code in cpvs):
            continue
        if lan and lan not in koder(notice):
            continue
        pid = txt(notice.get("publication-number")) or published
        if pid in seen:
            continue
        winners = vinnare(notice)
        if not winners:
            continue
        seen.add(pid)
        names = "; ".join(name for name, _ in winners)
        numbers = "; ".join(number for _, number in winners if number)
        rows.append({"publicerad": published,
                     "upphandling": clean_title(txt(notice.get("notice-title"))),
                     "köpare": txt(notice.get("buyer-name")),
                     "vinnande leverantör(er)": names,
                     "org.nr i annonsen": numbers,
                     "värde": belopp(notice),
                     "bransch": CPV.get(cpvs[0][:2], "") if cpvs else "",
                     "län": laner(notice)[0] if laner(notice) else "",
                     "länk": url_for(notice)})
    return rows


def raw_first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value if value else None


def slutdatum(value):
    explicit = (values(value.get("contract-duration-end-date-lot"))
                or values(value.get("contract-duration-end-date-part")))
    if explicit:
        return date_only(explicit[0]), "Angivet slutdatum"
    start = (values(value.get("contract-duration-start-date-lot"))
             or values(value.get("contract-duration-start-date-part"))
             or values(value.get("contract-conclusion-date")))
    duration = (raw_first(value.get("contract-duration-period-lot"))
                or raw_first(value.get("contract-duration-period-part")))
    if not start or not duration:
        return "", ""
    parsed_start = date_only(start[0])
    if not parsed_start:
        return "", ""
    end = add_duration(date.fromisoformat(parsed_start), duration)
    return (end.isoformat(), "Beräknat från löptid") if end else ("", "")


def p2_rows(notices, bransch=None, lan=None, today=None):
    day = date.fromisoformat(today) if today else date.today()
    limit = day + timedelta(days=365)
    rows, seen = [], set()
    for notice in notices:
        if not ar_award(notice, today):
            continue
        cpvs = values(notice.get("classification-cpv"))
        if bransch and not any(code[:2] == bransch for code in cpvs):
            continue
        if lan and lan not in koder(notice):
            continue
        end, certainty = slutdatum(notice)
        if not end or not certainty:
            continue
        end_date = date.fromisoformat(end)
        if not day <= end_date <= limit:
            continue
        pid = txt(notice.get("publication-number")) or end
        if pid in seen:
            continue
        winners = vinnare(notice)
        if not winners:
            continue
        seen.add(pid)
        names = "; ".join(name for name, _ in winners)
        rows.append({"beräknat slutdatum": end,
                     "köpare": txt(notice.get("buyer-name")),
                     "nuvarande leverantör": names,
                     "upphandling": clean_title(txt(notice.get("notice-title"))),
                     "värde": belopp(notice),
                     "län": laner(notice)[0] if laner(notice) else "",
                     "länk": url_for(notice),
                     "säkerhet": certainty})
    return rows


def coverage(notices):
    total = len(notices)
    explicit = sum(1 for notice in notices if values(notice.get("contract-duration-end-date-lot"))
                   or values(notice.get("contract-duration-end-date-part")))
    duration = sum(1 for notice in notices if values(notice.get("contract-duration-period-lot"))
                   or values(notice.get("contract-duration-period-part")))
    return {"notiser": total,
            "angivet_slutdatum": explicit,
            "beraknat_slutdatum": duration,
            "tackning_slutdatum": round(min(1.0, (explicit + duration) / total), 3) if total else 0.0,
            "vinnare": sum(1 for notice in notices if values(notice.get("winner-name"))),
            "lan": sum(1 for notice in notices if laner(notice)),
            "varde": sum(1 for notice in notices if belopp(notice) != "")}
