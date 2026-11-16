"""LinkedIn-nätverk: bolag som nyss vann svenska upphandlingar, med LinkedIn-sökning och färdig kontaktbegäran.

    python scripts/linkedin_network.py --days 3            # skriver linkedin-network.csv
    python scripts/linkedin_network.py --days 3 --mail     # mejlar listan till REPORT_TO

Användning: kopiera sök-URL:en i webbläsaren, hitta bolagets sida, skicka kontaktbegäran med meddelandet.
LinkedIn tillåter max 300 tecken i en kontaktbegäran — mallen är anpassad för det.
"""
import csv, io, os, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import winner_leads as wl

NOTE = ("Hej! Såg att ni vann {upphandling} — grattis. Jag driver Kommunradar, vi bevakar svenska "
        "upphandlingar och mejlar dem varje morgon. Hör gärna av er om ni vill se nästa matchande affär.")


def fetch_rows(days):
    return wl.collect(days)


def to_text(rows):
    out = []
    for r in rows:
        search = "https://www.linkedin.com/search/results/companies/?keywords=" + urllib.parse.quote(r["bolag"])
        note = NOTE.format(upphandling=r["upphandling"][:60])
        out.append(f"{r['bolag']} | {r['epost']} ({r['adresstyp']}) | {r['upphandling'][:60]}")
        out.append(f"   LinkedIn-sök: {search}")
        out.append(f"   Kontaktbegäran (max 300 tecken, {len(note)}): {note}")
        out.append("")
    return "\n".join(out or ["Inga nya i dag."])


def to_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["bolag", "epost", "adresstyp", "upphandling", "kopare", "lan", "linkedin_search_url", "kontaktbegäran"])
    for r in rows:
        search = "https://www.linkedin.com/search/results/companies/?keywords=" + urllib.parse.quote(r["bolag"])
        note = NOTE.format(upphandling=r["upphandling"][:60])
        w.writerow([r["bolag"], r["epost"], r["adresstyp"], r["upphandling"], r["kopare"], r["lan"], search, note])
    return buf.getvalue()


def mail(rows, days):
    import smtplib, ssl
    from email.message import EmailMessage
    to = os.environ["REPORT_TO"]
    msg = EmailMessage()
    msg["Subject"] = f"Kommunradar: {len(rows)} LinkedIn-kontakter (senaste {days} dagarna)"
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"]); msg["To"] = to
    msg.set_content("Bolag som nyss vunnit svenska upphandlingar — kontakta dem på LinkedIn.\n"
                    "Öppna sök-URL:en, hitta bolagets sida, skicka kontaktbegäran med meddelandet.\n\n"
                    + to_text(rows))
    msg.add_attachment(to_csv(rows).encode("utf-8-sig"), maintype="text", subtype="csv",
                       filename=f"linkedin-network-{__import__('datetime').date.today().isoformat()}.csv")
    smtp = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    smtp.starttls(context=ssl.create_default_context()); smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    smtp.send_message(msg); smtp.quit()


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 3
    rows = fetch_rows(days)
    print(f"{len(rows)} bolag med LinkedIn-mål")
    if "--mail" in sys.argv:
        mail(rows, days); print("Mejlad till REPORT_TO")
    else:
        open("linkedin-network.csv", "w", encoding="utf-8-sig").write(to_csv(rows)); print("Skrev linkedin-network.csv")


if __name__ == "__main__":
    main()