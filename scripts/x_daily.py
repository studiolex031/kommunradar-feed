"""Dagligt X-inlägg för Kommunradar: gårdagens nya upphandlingar i ett län eller en bransch, med en bild i sajtens stil.

    python scripts/x_daily.py --dry-run     # bygger text + bilder i x-out/, postar och mejlar inget
    python scripts/x_daily.py               # postar på X (om X_*-nycklarna finns) och mejlar annonsmaterial till REPORT_TO

Allt innehåll kommer ur leads.json (TED-data), inget hittas på. Text och bild renderas från mallar.
Postning: X API v2 med OAuth 1.0a (kontots egna nycklar). Endast egna inlägg, aldrig svar till andra,
eftersom X sedan feb 2026 bara tillåter automatiska svar till den som själv nämnt kontot.
Bildrendering kräver Playwright (installeras i workflowen); resten är standardbiblioteket.
"""
import base64, hashlib, hmac, html, json, os, secrets, smtplib, ssl, sys, time, urllib.parse, urllib.request
from collections import Counter
from datetime import date
from email.message import EmailMessage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MONTHS = ["jan", "feb", "mars", "april", "maj", "juni", "juli", "aug", "sep", "okt", "nov", "dec"]
LIMIT, URL_LEN = 280, 23  # X räknar varje länk som 23 tecken
CTA = "Få nya upphandlingar i inkorgen varje morgon. 7 dagar gratis, ingen bindningstid."


def kort_datum(iso):
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return ""
    return f"{d.day} {MONTHS[d.month - 1]}"


def pick(leads, today):
    """Senaste publiceringsdagens upphandlingar, fokuserat på ett län (jämna dagar) eller en bransch (udda).
    Rotera bland de fem största så att samma län inte kommer varje dag."""
    open_ = [l for l in leads if l.get("type", "").startswith("cn")]
    if not open_:
        return None
    day = max(l["published"] for l in open_)
    new = [l for l in open_ if l["published"] == day]
    by_region = today.toordinal() % 2 == 0
    keys = lambda l: (l.get("regions") or [l.get("region")]) if by_region else l.get("categories", [])
    counts = Counter(k for l in new for k in keys(l) if k)
    top = [k for k, n in counts.most_common(5) if n >= 2] or [k for k, _ in counts.most_common(1)]
    if not top:
        return None
    focus = top[(today.toordinal() // 2) % len(top)]
    items = [l for l in new if focus in keys(l)]
    items.sort(key=lambda l: (l.get("deadline") or "9999", l["title"]))
    return {"kind": "lan" if by_region else "bransch", "focus": focus, "day": day, "total": len(new),
            "n": len(items), "items": items}


def tweet_length(text):
    words = text.split()
    return len(text) - sum(len(w) - URL_LEN for w in words if w.startswith("http"))


def compose(p, url):
    plats = f"i {p['focus']}" if p["kind"] == "lan" else f"inom {p['focus'].lower()}"
    head = f"{p['n']} nya offentliga upphandlingar {plats} publicerades {kort_datum(p['day'])}. Bland dem:"
    for n_items, cut in ((3, 60), (3, 42), (2, 42), (2, 30), (1, 40)):
        bullets = []
        for l in p["items"][:n_items]:
            t = l["title"] if len(l["title"]) <= cut else l["title"][:cut - 1].rstrip() + "…"
            dl = f", sista dag {kort_datum(l['deadline'])}" if l.get("deadline") else ""
            bullets.append(f"• {t}{dl}")
        text = f"{head}\n\n" + "\n".join(bullets) + f"\n\n{CTA}\n{url}"
        if tweet_length(text) <= LIMIT:
            return text
    return f"{head.split('. Bland')[0]}.\n\n{CTA}\n{url}"


def ad_copy(p):
    plats = p["focus"] if p["kind"] == "lan" else p["focus"].lower()
    return [f"{p['total']} nya offentliga upphandlingar på en dag. Missar du dem i {plats}? Kommunradar mejlar dig varje morgon. 7 dagar gratis.",
            f"Sluta leta i upphandlingsportaler. Välj bevakningsord och län, få nya upphandlingar i inkorgen. 990 kr/mån, ingen bindningstid.",
            f"Färre anbud per upphandling betyder bättre chans för den som hittar dem i tid. Testa Kommunradar 7 dagar gratis."]


def card_html(p, w, h):
    rows = "".join(f"<li><b>{html.escape(l['title'][:70])}</b><span>{html.escape(l.get('buyer', '')[:48])}"
                   f"{' · sista dag ' + kort_datum(l['deadline']) if l.get('deadline') else ''}</span></li>"
                   for l in p["items"][:3 if h < w else 5])
    label = p["focus"] if p["kind"] == "lan" else p["focus"]
    sq = h >= w
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;700;800;900&display=swap" rel="stylesheet">
<style>
:root{{--ink:#070b18;--txt:#f4f6fb;--mut:#9aa6c4;--c:#22d3ee;--y:#fbbf24;--line:#ffffff1a}}
*{{box-sizing:border-box}}html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden}}
body{{background:radial-gradient(circle at 85% 15%,#22d3ee22,transparent 45%),var(--ink);color:var(--txt);
font-family:"Inter Tight",system-ui,sans-serif;padding:{64 if sq else 56}px;display:flex;flex-direction:column}}
.logo{{display:flex;gap:12px;align-items:center;font-weight:900;letter-spacing:-.02em;font-size:24px}}
.logo svg{{width:40px;height:40px}}
.tag{{margin-left:auto;font-weight:700;font-size:20px;color:var(--ink);background:var(--c);padding:6px 14px;border-radius:999px}}
h1{{font-size:{104 if sq else 72}px;line-height:.95;letter-spacing:-.045em;font-weight:900;margin:{56 if sq else 36}px 0 8px}}
h1 .num{{color:var(--y)}}
.sub{{color:var(--mut);font-size:26px;font-weight:500}}
ul{{list-style:none;padding:0;margin:{40 if sq else 28}px 0 0;display:grid;gap:14px}}
li{{border:1px solid var(--line);border-radius:16px;padding:14px 18px;background:#ffffff08}}
li b{{display:block;font-size:{27 if sq else 24}px;font-weight:700;letter-spacing:-.01em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
li span{{color:var(--mut);font-size:{21 if sq else 19}px}}
.foot{{margin-top:auto;display:flex;justify-content:space-between;align-items:center;font-size:22px;font-weight:700}}
.foot .y{{color:var(--ink);background:var(--y);padding:10px 18px;border-radius:12px;font-weight:800}}
</style></head><body>
<div class="logo"><svg viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="#0d1428"/><circle cx="32" cy="32" r="20" fill="none" stroke="#22d3ee" stroke-width="4" opacity=".5"/><circle cx="32" cy="32" r="9" fill="none" stroke="#22d3ee" stroke-width="4"/><path d="M32 32L48 16" stroke="#fbbf24" stroke-width="5" stroke-linecap="round"/></svg>KOMMUNRADAR
<span class="tag">{html.escape(label)}</span></div>
<h1><span class="num">{p['n']}</span> nya upphandlingar</h1>
<div class="sub">{'i ' + html.escape(p['focus']) if p['kind'] == 'lan' else 'inom ' + html.escape(p['focus'].lower())} · publicerade {kort_datum(p['day'])}</div>
<ul>{rows}</ul>
<div class="foot"><span>kommunradar.online</span><span class="y">7 dagar gratis</span></div>
</body></html>"""


def render(p, out):
    from playwright.sync_api import sync_playwright
    paths = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        for name, w, h in (("post", 1200, 675), ("annons-kvadrat", 1080, 1080)):
            page = b.new_page(viewport={"width": w, "height": h})
            page.set_content(card_html(p, w, h), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            path = os.path.join(out, f"{name}.png")
            page.screenshot(path=path)
            paths.append(path)
        b.close()
    return paths


# --- X API (OAuth 1.0a) ---------------------------------------------------------------------------
def q(s):
    return urllib.parse.quote(str(s), safe="~-._")


def oauth_header(method, url, params, keys, nonce=None, ts=None):
    """keys = (consumer_key, consumer_secret, token, token_secret). params = query/form params that are signed."""
    ck, cs, tk, ts_secret = keys
    oauth = {"oauth_consumer_key": ck, "oauth_nonce": nonce or secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(ts or int(time.time())),
             "oauth_token": tk, "oauth_version": "1.0"}
    allp = sorted((q(k), q(v)) for k, v in {**params, **oauth}.items())
    base = "&".join([method.upper(), q(url), q("&".join(f"{k}={v}" for k, v in allp))])
    sig = base64.b64encode(hmac.new(f"{q(cs)}&{q(ts_secret)}".encode(), base.encode(), hashlib.sha1).digest()).decode()
    oauth["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{q(k)}="{q(v)}"' for k, v in sorted(oauth.items()))


def x_keys():
    k = [os.environ.get(n, "") for n in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")]
    return tuple(k) if all(k) else None


def x_request(method, url, keys, body=None, content_type=None, params=None):
    full = url + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(full, data=body, method=method,
                                 headers={"Authorization": oauth_header(method, url, params or {}, keys)})
    if content_type:
        req.add_header("Content-Type", content_type)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def upload_image(path, keys):
    boundary = secrets.token_hex(12)
    data = open(path, "rb").read()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"media_category\"\r\n\r\ntweet_image\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"post.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    r = x_request("POST", "https://api.x.com/2/media/upload", keys, body, f"multipart/form-data; boundary={boundary}")
    return r["data"]["id"]


def post(text, image, keys):
    payload = {"text": text}
    try:
        payload["media"] = {"media_ids": [upload_image(image, keys)]}
    except Exception as e:  # hellre ett inlägg utan bild än inget inlägg
        print(f"::warning::Bilduppladdning misslyckades ({e}); postar utan bild")
    r = x_request("POST", "https://api.x.com/2/tweets", keys, json.dumps(payload).encode(), "application/json")
    return r["data"]["id"]


def mail(subject, text, attachments):
    msg = EmailMessage()
    msg["Subject"], msg["To"] = subject, os.environ["REPORT_TO"]
    msg["From"] = os.environ.get("MAIL_FROM", os.environ["SMTP_USER"])
    msg.set_content(text)
    for path in attachments:
        msg.add_attachment(open(path, "rb").read(), maintype="image", subtype="png", filename=os.path.basename(path))
    s = smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587")), timeout=60)
    s.starttls(context=ssl.create_default_context()); s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
    s.send_message(msg); s.quit()


def main():
    dry = "--dry-run" in sys.argv
    leads = json.load(open(os.path.join(ROOT, "leads.json"), encoding="utf-8"))["leads"]
    p = pick(leads, date.today())
    if not p:
        print("Inga nya upphandlingar att posta om"); return
    site = os.environ.get("SITE_URL") or "https://kommunradar.online"
    text = compose(p, f"{site.rstrip('/')}/?utm_source=x&utm_medium=social&utm_campaign=dagligt")
    out = os.path.join(ROOT, "x-out"); os.makedirs(out, exist_ok=True)
    images = render(p, out)
    print(text, f"\n({tweet_length(text)} tecken)")
    if dry:
        print("Torrkörning: bilder i", out); return
    keys, status = x_keys(), "inte postat (X-nycklar saknas)"
    if keys:
        tid = post(text, images[0], keys)
        status = f"postat: https://x.com/i/web/status/{tid}"
    print(status)
    if os.environ.get("REPORT_TO") and os.environ.get("SMTP_HOST"):
        ads = "\n".join(f"{i}. {a}" for i, a in enumerate(ad_copy(p), 1))
        mail(f"Kommunradar på X: {p['n']} nya {'i ' + p['focus'] if p['kind'] == 'lan' else 'inom ' + p['focus'].lower()}",
             f"Dagens inlägg, {status}\n\n{text}\n\n--- Annonstexter (för att marknadsföra inlägget eller köra som annons) ---\n{ads}\n\n"
             "Bilder bifogade: post.png (1200x675) och annons-kvadrat.png (1080x1080).", images)


if __name__ == "__main__":
    main()
