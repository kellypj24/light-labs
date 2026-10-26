"""Google OAuth for the lab's robots, and a minimal Gmail client. Stdlib only.

The OAuth client (a Desktop app in Google Cloud project light-labs) lives in Keychain as
`light-labs-google-oauth-client`. Each robot signs in separately with only the scopes its
job needs, and keeps one refresh token per mailbox in Keychain
(`light-labs-google-<robot>-<account>`), so a bug in one robot can never use another's
permissions:

    rush  gmail.readonly             triage, summaries
    roll  gmail.modify               archive and label (inbox cleanup)

`lab google auth <robot>` runs the installed-app flow: a loopback listener on 127.0.0.1,
PKCE, the browser for PJ's sign-in and consent. PJ types his password into Google only.

Gmail here has no send method on purpose: nothing in the lab sends email.
"""

import base64
import hashlib
import json
import secrets
import subprocess
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

CLIENT_KEYCHAIN = "light-labs-google-oauth-client"
AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"

SCOPES = {
    "rush": ["https://www.googleapis.com/auth/gmail.readonly"],
    "roll": ["https://www.googleapis.com/auth/gmail.modify"],
}


def keychain_service(robot, account):
    """One Keychain item per robot per mailbox: a robot signed in to two accounts holds two
    tokens, and never one that another robot could use."""
    return f"light-labs-google-{robot}-{account}"


def _keychain_get(service):
    return subprocess.run(
        ["security", "find-generic-password", "-s", service, "-w"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _keychain_put(service, secret):
    # -U updates an existing item; the secret goes through argv only for `security`.
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", service, "-a", "light-labs", "-w", secret],
        capture_output=True,
        check=True,
    )


def client_config(get=_keychain_get):
    data = json.loads(get(CLIENT_KEYCHAIN))
    return data.get("installed") or data["web"]


def _post(url, fields, opener=urllib.request.urlopen):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
    with opener(req, timeout=30) as r:
        return json.loads(r.read().decode())


def pkce():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.decode().rstrip("=")


def auth_url(client, scopes, redirect_uri, state, challenge, login_hint=None):
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",  # a refresh token
        "prompt": "consent",  # always issue one, even on a repeat sign-in
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "include_granted_scopes": "false",  # this robot's scopes only
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URI}?{urllib.parse.urlencode(params)}"


def _wait_for_code(server, state):
    """Serve one redirect on the loopback listener; return the code."""
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            ok = q.get("state", [""])[0] == state and "code" in q
            got.update(code=q.get("code", [None])[0] if ok else None, error=q.get("error"))
            body = (
                "Signed in. You can close this tab."
                if ok
                else f"Sign-in failed: {q.get('error', ['state mismatch'])[0]}"
            )
            self.send_response(200 if ok else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

    server.RequestHandlerClass = Handler
    while "code" not in got:
        server.handle_request()
    if not got["code"]:
        raise RuntimeError(f"Google sign-in failed: {got.get('error') or 'state mismatch'}")
    return got["code"]


def authorize(robot, login_hint=None, open_browser=webbrowser.open, put=_keychain_put):
    """Sign `robot` in with its scopes and store its refresh token under the mailbox that
    actually signed in (not the hint). Returns (account, scopes)."""
    client = client_config()
    server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    state = secrets.token_urlsafe(16)
    verifier, challenge = pkce()
    url = auth_url(client, SCOPES[robot], redirect_uri, state, challenge, login_hint)
    print(f"Opening Google sign-in for {robot}. If no browser opens, visit:\n{url}", flush=True)
    open_browser(url)
    try:
        code = _wait_for_code(server, state)
    finally:
        server.server_close()
    token = _post(
        client.get("token_uri", TOKEN_URI),
        {
            "code": code,
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        },
    )
    if "refresh_token" not in token:
        raise RuntimeError("Google returned no refresh token; run the sign-in again")
    granted = token.get("scope", "").split()
    account = _profile(token["access_token"])["emailAddress"]
    put(
        keychain_service(robot, account),
        json.dumps({"refresh_token": token["refresh_token"], "scopes": granted}),
    )
    return account, granted


def _profile(access_token, opener=urllib.request.urlopen):
    req = urllib.request.Request(
        f"{GMAIL}/profile", headers={"Authorization": f"Bearer {access_token}"}
    )
    with opener(req, timeout=30) as r:
        return json.loads(r.read().decode())


# Robots allowed to change a mailbox, and only by moving labels (archive = remove INBOX).
# Nothing here deletes, trashes or sends.
MODIFIERS = {"roll"}


class Gmail:
    """Gmail calls for one robot in one mailbox. Reads for all; label changes for MODIFIERS;
    no delete, trash or send, by design. Taking mail out of Trash is allowed (a restore)."""

    def __init__(self, robot, account, get=_keychain_get, opener=urllib.request.urlopen):
        self.robot, self.account, self.get, self.opener = robot, account, get, opener
        self._access = None

    def _access_token(self):
        if self._access is None:
            client = client_config(self.get)
            saved = json.loads(self.get(keychain_service(self.robot, self.account)))
            token = _post(
                client.get("token_uri", TOKEN_URI),
                {
                    "client_id": client["client_id"],
                    "client_secret": client["client_secret"],
                    "refresh_token": saved["refresh_token"],
                    "grant_type": "refresh_token",
                },
                self.opener,
            )
            self._access = token["access_token"]
        return self._access

    def call(self, path, body=None, **params):
        query = f"?{urllib.parse.urlencode(params, doseq=True)}" if params else ""
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        req = urllib.request.Request(f"{GMAIL}/{path}{query}", data=data, headers=headers)
        with self.opener(req, timeout=60) as r:
            raw = r.read().decode()
        return json.loads(raw) if raw.strip() else {}  # batchModify answers with no body

    def label_id(self, name):
        """The id of the user label `name`, created if missing (Roll/... labels)."""
        if self.robot not in MODIFIERS:
            raise PermissionError(f"{self.robot} may not change mail")
        for label in self.call("labels").get("labels", []):
            if label["name"] == name:
                return label["id"]
        made = self.call(
            "labels",
            body={
                "name": name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        return made["id"]

    def profile(self):
        return self.call("profile")

    def messages(self, query="", max_results=50):
        return self.call("messages", q=query, maxResults=max_results).get("messages", [])

    def message(self, message_id, fmt="metadata", headers=("From", "Subject", "Date")):
        return self.call(f"messages/{message_id}", format=fmt, metadataHeaders=list(headers))

    def ids(self, query, cap=20000):
        """Every message id matching `query`, up to `cap`: 500 per page, ids only."""
        out, token = [], None
        while len(out) < cap:
            params = {"q": query, "maxResults": 500}
            if token:
                params["pageToken"] = token
            page = self.call("messages", **params)
            out += [m["id"] for m in page.get("messages", [])]
            token = page.get("nextPageToken")
            if not token:
                break
        return out[:cap]

    def relabel(self, ids, add=(), remove=()):
        """Move labels on many messages, 1000 per call. Archive is remove=["INBOX"]; restore
        from Trash is remove=["TRASH"]. Adding TRASH or SPAM is refused."""
        if self.robot not in MODIFIERS:
            raise PermissionError(f"{self.robot} may not change mail")
        if {"TRASH", "SPAM"} & set(add):
            raise PermissionError("robots never trash or spam mail")
        for i in range(0, len(ids), 1000):
            self.call(
                "messages/batchModify",
                body={"ids": ids[i : i + 1000], "addLabelIds": list(add),
                      "removeLabelIds": list(remove)},
            )  # fmt: skip
