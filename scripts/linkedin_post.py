"""Postar text på LinkedIn via LinkedIn Posts API (v2).

    python scripts/linkedin_post.py --text "Hej LinkedIn!"          # postar på personlig profil
    python scripts/linkedin_post.py --file utkast.txt              # läser text från fil
    python scripts/linkedin_post.py --text "..." --org 12345       # postar på organisationsida
    python scripts/linkedin_post.py --text "..." --dry-run         # bygger payload, postar inget

Kräver miljövariabler:
    LINKEDIN_ACCESS_TOKEN  (från linkedin_auth.py)
    LINKEDIN_PERSON_URN    (urn:li:person:..., från linkedin_auth.py)
  eller
    LINKEDIN_ORG_URN       (urn:li:organization:..., för organisationsida)

Token går ut efter 60 dagar. Kör linkedin_auth.py igen för att förnya,
eller sätt LINKEDIN_REFRESH_TOKEN + LINKEDIN_CLIENT_ID/SECRET för automatisk förnyelse.
"""
import argparse, json, os, sys, urllib.request, urllib.error

API = "https://api.linkedin.com/rest/posts"
VERSION = "202405"


def refresh_token():
    rt = os.environ.get("LINKEDIN_REFRESH_TOKEN")
    cid = os.environ.get("LINKEDIN_CLIENT_ID")
    sec = os.environ.get("LINKEDIN_CLIENT_SECRET")
    if not (rt and cid and sec):
        return None
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": rt,
        "client_id": cid, "client_secret": sec,
    }).encode()
    req = urllib.request.Request("https://www.linkedin.com/oauth/v2/accessToken", data=data,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("access_token")
    except Exception as e:
        print("Token-förnyelse misslyckades:", e, file=sys.stderr)
        return None


def post(text, author_urn, token, dry=False):
    payload = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    if dry:
        print("DRY RUN — payload:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API, data=data, method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("LinkedIn-Version", VERSION)
    req.add_header("X-Restli-Protocol-Version", "2.0.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"Postat! Status {r.status}")
            loc = r.headers.get("x-restli-id") or r.headers.get("Location")
            if loc:
                print("Post-ID:", loc)
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"Fel {e.code}: {body}", file=sys.stderr)
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="Text att posta")
    ap.add_argument("--file", help="Läs text från fil")
    ap.add_argument("--org", help="Organisations-ID (postar på företagssida istället för personlig profil)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read().strip()
    elif args.text:
        text = args.text
    else:
        print("Ange --text eller --file", file=sys.stderr); sys.exit(1)

    token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    if not token:
        token = refresh_token()
        if not token:
            print("LINKEDIN_ACCESS_TOKEN saknas och kunde inte förnyas.", file=sys.stderr); sys.exit(1)

    if args.org:
        author = "urn:li:organization:" + args.org
    else:
        author = os.environ.get("LINKEDIN_PERSON_URN") or os.environ.get("LINKEDIN_ORG_URN")
        if not author:
            print("LINKEDIN_PERSON_URN eller LINKEDIN_ORG_URN saknas.", file=sys.stderr); sys.exit(1)

    ok = post(text, author, token, dry=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()