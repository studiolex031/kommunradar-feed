import io, re, zipfile
from xml.sax.saxutils import escape

TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>"""
RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>"""
WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets></workbook>"""
WORKBOOK_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>"""
INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def column_letter(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def safe(text):
    return escape(INVALID.sub("", str(text if text is not None else "")))


def sheet_name(name):
    clean = re.sub(r"[\[\]:*?/\\]", "_", str(name or "Leverans")).strip() or "Leverans"
    return clean[:31]


def cell(reference, value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{reference}"><v>{value}</v></c>'
    return f'<c r="{reference}" t="inlineStr"><is><t>{safe(value)}</t></is></c>'


def write_xlsx(rows, headers=None, sheet="Leverans"):
    lines = [list(headers)] if headers else []
    for row in rows:
        lines.append([row.get(key, "") for key in headers] if isinstance(row, dict) and headers else list(row))
    body = []
    for row_index, row in enumerate(lines, 1):
        cells = "".join(cell(f"{column_letter(column_index)}{row_index}", value)
                        for column_index, value in enumerate(row, 1))
        body.append(f'<row r="{row_index}">{cells}</row>')
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetData>' + "".join(body) + '</sheetData></worksheet>')
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("xl/workbook.xml", WORKBOOK.format(sheet=safe(sheet_name(sheet))))
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", xml)
    return output.getvalue()
