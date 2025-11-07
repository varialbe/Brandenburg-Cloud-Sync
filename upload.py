#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import sys
import time
import json
import re
from urllib.parse import urlparse, parse_qsl
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import mimetypes


BASE = "https://brandenburg.cloud"

def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)

def get_csrf_from_html(html_bytes):
    try:
        soup = BeautifulSoup(html_bytes, "html.parser")
        m = soup.find("meta", attrs={"name": "csrfToken"})
        if m and m.get("content"):
            return m["content"]
    except Exception:
        pass
    return None

def must_get_csrf(session, url="/"):
    r = session.get(BASE + url, allow_redirects=True)
    r.raise_for_status()
    token = get_csrf_from_html(r.content)
    if not token:
        die("Konnte CSRF-Token nicht aus HTML extrahieren.")
    return token

def login(session, username, password):
    # 1) CSRF von der Start- oder Login-Seite holen
    csrf = must_get_csrf(session, "/")
    # 2) Form-POST nach /login (wie in deinem DevTools-Dump)
    data = {
        "redirect": "",
        "username": username,
        "password": password,
        "schoolId": "",
        "_csrf": csrf,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": BASE + "/",
    }
    r = session.post(BASE + "/login", data=data, headers=headers, allow_redirects=True)
    r.raise_for_status()

    # 3) Check: sind wir drin? Dashboard laden
    dash = session.get(BASE + "/dashboard", allow_redirects=True)
    if dash.status_code != 200:
        die(f"Login fehlgeschlagen (HTTP {dash.status_code}).")
    # Extra: prüfen, ob weiterhin Login-HTML kommt
    if b"Login - Schul-Cloud" in dash.content:
        die("Login fehlgeschlagen: Dashboard zeigt Login-Seite.")
    print("✓ Login erfolgreich.")

def extract_allowed_s3_headers_from_url(presigned_url):
    """
    Für S3-PUT dürfen wir nur exakt die Header setzen,
    die in der Signatur vorgesehen sind (z. B. Content-Type und x-amz-meta-*).
    Wir lesen die x-amz-meta-* aus der Query und geben sie als Header zurück.
    """
    q = dict(parse_qsl(urlparse(presigned_url).query))
    headers = {}
    # Content-Type ist häufig signiert:
    if "Content-Type" in q:
        headers["Content-Type"] = q["Content-Type"]
    # x-amz-meta-*
    for k, v in q.items():
        if k.lower().startswith("x-amz-meta-"):
            headers[k] = v
    return headers

def init_file(session, filename, mime):
    csrf = must_get_csrf(session, "/files/my/")
    data = {"type": mime, "filename": filename}
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "csrf-token": csrf,
        "Referer": BASE + "/files/my/",
    }
    r = session.post(BASE + "/files/file", data=data, headers=headers)
    r.raise_for_status()

    if "application/json" not in (r.headers.get("Content-Type","")):
        print("INIT lieferte kein JSON. Server-Antwort (gekürzt):")
        print(r.text[:500]); die("Nicht eingeloggt oder falscher Flow.")

    j = r.json()

    # Neuer Branch: Struktur mit 'signedUrl'
    su = j.get("signedUrl")
    if su and isinstance(su, dict):
        url = su.get("url")
        hdr = su.get("header", {}) or {}
        storage = hdr.get("x-amz-meta-flat-name")
        if not storage and url:
            # Fallback: aus URL-Query ziehen
            storage = dict(parse_qsl(urlparse(url).query)).get("x-amz-meta-flat-name")

        if not url or not storage:
            print("Server-JSON:", json.dumps(j, indent=2, ensure_ascii=False))
            die("Init-JSON unvollständig (erwarte 'signedUrl.url' und 'x-amz-meta-flat-name').")

        # Damit wir exakt die erlaubten Header verwenden, geben wir sie zurück
        return url, storage, {"headers": hdr}

    # Alter Branch (falls Backend-Variante ohne 'signedUrl')
    url = j.get("url") or j.get("uploadUrl")
    storage = j.get("storageFileName") or j.get("storage") or j.get("key")
    if not url or not storage:
        print("Server-JSON:", json.dumps(j, indent=2, ensure_ascii=False))
        die("Init-JSON unvollständig.")
    return url, storage, j


def s3_put(presigned_url, file_path, allowed_headers=None):
    # allowed_headers: direkt vom Backend (signedUrl.header)
    if allowed_headers:
        headers = dict(allowed_headers)  # genau so senden
    else:
        headers = extract_allowed_s3_headers_from_url(presigned_url)

    with open(file_path, "rb") as f:
        data = f.read()

    r = requests.put(presigned_url, data=data, headers=headers)
    if r.status_code not in (200, 201, 204):
        print("S3 PUT fehlgeschlagen:", r.status_code)
        print(r.text[:500])
        die("S3 PUT nicht erfolgreich (Signatur abgelaufen? falsche Header?)")
    print("✓ S3 Upload ok.")
    return len(data)


def finalize(session, orig_name, mime, size_bytes, storageFileName):
    csrf = must_get_csrf(session, "/files/my/")
    data = {
        "name": orig_name,
        "type": mime,
        "size": str(size_bytes),
        "storageFileName": storageFileName,
    }
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "csrf-token": csrf,
        "Referer": BASE + "/files/my/",
    }
    r = session.post(BASE + "/files/fileModel", data=data, headers=headers)
    r.raise_for_status()
    # Manche Endpunkte geben JSON zurück, manche 200/204 ohne Body.
    ok = (r.status_code in (200, 201, 204))
    if not ok:
        print("Finalize Antwort:", r.status_code, r.text[:400])
        die("Finalize fehlgeschlagen.")
    print("✓ Finalisierung ok.")

def main():
    ap = argparse.ArgumentParser(description="Brandenburg Cloud: Login + Upload")
    ap.add_argument("--user", required=True, help="Login (E-Mail)")
    ap.add_argument("--pass", dest="passwd", required=True, help="Passwort")
    ap.add_argument("--file", required=True, help="Pfad zur Datei")
    ap.add_argument("--type", default=None, help="MIME-Type (z. B. image/png)")
    ap.add_argument("--name", default=None, help="Anzeigename (optional; default=Dateiname)")
    args = ap.parse_args()

    p = Path(args.file)
    if not p.is_file():
        die(f"Datei nicht gefunden: {p}")

    # MIME fallback
    mime = args.type
    if not mime:
        # minimaler Fallback – im Zweifel image/png
        ext = p.suffix.lower()
        if ext in (".png",):
            mime = "image/png"
        elif ext in (".jpg", ".jpeg"):
            mime = "image/jpeg"
        elif ext == ".pdf":
            mime = "application/pdf"
        else:
            mime = "application/octet-stream"

    display_name = args.name or p.name

    with requests.Session() as s:
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        })

        print("→ Login…")
        login(s, args.user, args.passwd)

        print("→ Presigned URL holen (INIT)…")
        presigned_url, storage_key, raw_json = init_file(s, display_name, mime)
        print("  storageFileName:", storage_key)

        print("→ S3 PUT…")
        size = s3_put(presigned_url, str(p), allowed_headers=raw_json.get("headers") if isinstance(raw_json, dict) else None)


        print("→ Finalisieren…")
        finalize(s, display_name, mime, size, storage_key)

        print("✅ Fertig. Datei registriert.")

def create_session(username: str, password: str) -> requests.Session:
    """Einmal einloggen und Session zurückgeben."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    })

    # 1) CSRF von /login (oder /) holen
    r = s.get(f"{BASE}/login", allow_redirects=True)
    r.raise_for_status()
    csrf = get_csrf_from_html(r.text)  # <-- hier statt _extract_csrf_from_html
    if not csrf:
        # Fallback über Startseite probieren
        r2 = s.get(f"{BASE}/", allow_redirects=True)
        r2.raise_for_status()
        csrf = get_csrf_from_html(r2.text)
    if not csrf:
        die("CSRF-Token beim Login nicht gefunden.")

    # 2) Login-POST
    data = {
        "redirect": "",
        "username": username,
        "password": password,
        "schoolId": "",
        "_csrf": csrf,
    }
    r = s.post(f"{BASE}/login", data=data, allow_redirects=True)
    r.raise_for_status()

    # 3) Verifizieren, dass wir eingeloggt sind (Dashboard darf keine Login-Seite sein)
    dash = s.get(f"{BASE}/dashboard", allow_redirects=True)
    dash.raise_for_status()
    if b"Login - Schul-Cloud" in dash.content or "Login - Schul-Cloud" in dash.text:
        die("Login fehlgeschlagen: Dashboard zeigt Login-Seite.")

    return s


def upload_with_session(session: requests.Session, file_path: str) -> dict:
    """Nutzt die bestehende Session, macht INIT → S3 PUT → fileModel POST."""
    p = Path(file_path)
    if not p.is_file():
        raise FileNotFoundError(p)

    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "application/octet-stream"

    # CSRF von /files/my/ holen
    csrf = must_get_csrf(session, "/files/my/")
    # INIT
    init_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "csrf-token": csrf,
        "Referer": f"{BASE}/files/my/",
    }
    init_data = {"type": mime, "filename": p.name}
    r = session.post(f"{BASE}/files/file", data=init_data, headers=init_headers)
    r.raise_for_status()
    j = r.json()
    su = j.get("signedUrl") or {}
    presigned_url = su.get("url")
    signed_headers = su.get("header") or {}
    storage = signed_headers.get("x-amz-meta-flat-name")
    if not storage and presigned_url:
        from urllib.parse import urlparse, parse_qsl
        storage = dict(parse_qsl(urlparse(presigned_url).query)).get("x-amz-meta-flat-name")
    if not presigned_url or not storage:
        raise RuntimeError(f"Unerwartetes INIT-JSON: {j}")

    # S3 PUT mit GENAU den signierten Headern
    with open(p, "rb") as f:
        put = requests.put(presigned_url, data=f.read(), headers=signed_headers)
    if put.status_code not in (200, 201, 204):
        raise RuntimeError(f"S3 PUT failed {put.status_code}: {put.text[:200]}")

    # fileModel POST
    fm_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "csrf-token": csrf,
        "Referer": f"{BASE}/files/my/",
    }
    fm_data = {
        "name": p.name,
        "type": mime,
        "size": p.stat().st_size,
        "storageFileName": storage,
    }
    r = session.post(f"{BASE}/files/fileModel", data=fm_data, headers=fm_headers)
    r.raise_for_status()
    return {"ok": True, "name": p.name, "size": p.stat().st_size, "mime": mime}

if __name__ == "__main__":
    main()
