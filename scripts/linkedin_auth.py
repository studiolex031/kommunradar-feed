"""LinkedIn OAuth 2.0: hämtar access token för att posta på LinkedIn.

    python scripts/linkedin_auth.py

Kräver att du först skapat en app på https://developer.linkedin.com/ med:
  - Client ID och Client Secret (sätts som miljövariabler eller anges vid körning)
  - Redirect URL: http://localhost:8080/callback
  - Produkter: "Sign In with LinkedIn using OpenID Connect" och "Share on LinkedIn"

Scope som begärs: w_member_social (posta på personlig profil) + r_basicprofile (hämta person-id).

Token sparas i linkedin-token.json (lägg till i .gitignore!). Kopiera sedan värdet till
GitHub Secrets: LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN.

För organisationssida: begär w_organization_social och ange LINKEDIN_ORG_URN istället.
"""
import http.server, json, os, sys, urllib.parse, urllib.request, webbrowser, threading

CLIENT_ID = os.environ.get("LINKEDIN_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
REDIRECT = "http://localhost:8080/callback"
SCOPES = "w_member_social r_liteprofile r_emailaddress"
TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "linkedin-token.json")


def get_code():
    global CLIENT_ID, CLIENT_SECRET
    if not CLIENT_ID:
        CLIENT_ID = input("LinkedIn Client ID: ").strip()
    if not CLIENT_SECRET:
        CLIENT_SECRET = input("LinkedIn Client Secret: ").strip()

    auth_url = ("https://www.linkedin.com/oauth/v2/authorization?"
                "response_type=code&client_id=" + urllib.parse.quote(CLIENT_ID) +
                "&redirect_uri=" + urllib.parse.quote(REDIRECT) +
                "&scope=" + urllib.parse.quote(SCOPES))

    code_holder = {"code": None, "error": None}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/callback":
                qs = urllib.parse.parse_qs(parsed.query)
                if "code" in qs:
                    code_holder["code"] = qs["code"][0]
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>OK!</h1><p>Du kan stanga detta fonster.</p>")
                else:
                    code_holder["error"] = qs.get("error", ["unknown"])[0]
                    self.send_response(400)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(b"<h1>Fel</h1>")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("localhost", 8080), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("Oppnar webblasaren for LinkedIn-inloggning...")
    print("Om den inte oppnas, ga till:", auth_url)
    webbrowser.open(auth_url)

    # Vanta pa callback
    import time
    for _ in range(120):
        if code_holder["code"] or code_holder["error"]:
            break
        time.sleep(1)
    server.shutdown()

    if code_holder["error"]:
        print("Fel:", code_holder["error"]); sys.exit(1)
    if not code_holder["code"]:
        print("Timeout — ingen callback mottogs."); sys.exit(1)
    return code_holder["code"]


def exchange_code(code):
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }).encode()
    req = urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=data,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get_person_urn(token):
    req = urllib.request.Request("https://api.linkedin.com/v2/userinfo",
                                headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    return "urn:li:person:" + data["sub"], data.get("name", ""), data.get("email", "")


def main():
    code = get_code()
    print("Byter kod mot token...")
    tok = exchange_code(code)
    access = tok["access_token"]
    urn, name, email = get_person_urn(access)
    print(f"\nInloggad som: {name} ({email})")
    print(f"Person URN: {urn}")
    out = {"access_token": access, "expires_in": tok.get("expires_in"),
           "refresh_token": tok.get("refresh_token"), "person_urn": urn, "name": name, "email": email}
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\nToken sparad i {TOKEN_FILE}")
    print("\nNasta steg:")
    print("  1. Lagg till i GitHub Secrets:")
    print("     LINKEDIN_ACCESS_TOKEN =", access)
    print("     LINKEDIN_PERSON_URN  =", urn)
    if tok.get("refresh_token"):
        print("     LINKEDIN_REFRESH_TOKEN =", tok["refresh_token"])
    print("  2. Kör: python scripts/linkedin_post.py --text \"Hej LinkedIn!\"")


if __name__ == "__main__":
    main()