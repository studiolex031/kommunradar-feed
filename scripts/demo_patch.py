"""Fixar 404 efter "Visa mina missade upphandlingar" på den publicerade startsidan.

Demoformuläret (#kr-demo-form) postar till /api/demo-signup.php, som sparar anmälan och svarar
med redirect till https://login.kommunradar.online/search. Den adressen finns inte (Simply svarar
404 och certifikatet täcker inte subdomänen), så besökaren hamnade på en felsida.

Patchen ändrar bara raden som följer redirecten: anmälan sparas som förut, men i stället för att
lämna sidan fylls sökorden och länet i hero-sökningen, träffarna visas direkt och sidan scrollar
dit. Kör mot live-filen (som site_patch.py), är idempotent och rör inget annat.

Användning: python scripts/demo_patch.py <in.html> <ut.html>
"""
import sys

OLD = "if (d.ok && d.redirect) { window.location.href = d.redirect; return; }"
NEW = (
    "if (d.ok) { /*dp:v1*/ var q=document.getElementById('q'),ls=document.getElementById('lan'),"
    "fd=new FormData(f),ln=String(fd.get('lan')||'');"
    "if(q)q.value=String(fd.get('nyckelord')||'');"
    "if(ls){ls.value=(ln==='Hela Sverige'?'':ln);}"
    "if(typeof search==='function')search();"
    "msg.textContent='Klart! Här är upphandlingarna som matchar dina sökord just nu.';"
    "btn.disabled=false;var r=document.getElementById('res');if(r)r.scrollIntoView({behavior:'smooth',block:'start'});"
    "if(window.gtag)gtag('event','demo_signup');return; }"
)


def patch(html: str) -> str:
    if "/*dp:v1*/" in html:
        return html
    if html.count(OLD) != 1:
        sys.exit("Hittade inte demoformulärets redirect-rad exakt en gång – sidan ser annorlunda ut. Inget ändrat.")
    return html.replace(OLD, NEW, 1)


def main() -> None:
    src, dst = sys.argv[1], sys.argv[2]
    html = open(src, encoding="utf-8").read()
    out = patch(html)
    assert out.count("/*dp:v1*/") == 1
    assert OLD not in out
    assert out.count("<!--pp:s-->") == html.count("<!--pp:s-->"), "Prismarkörer rörda!"
    assert len(out) - len(html) < 2000
    open(dst, "w", encoding="utf-8").write(out)
    print("Startsidan uppdaterad:", dst)


if __name__ == "__main__":
    main()
