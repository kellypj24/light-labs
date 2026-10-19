import base64
import hashlib
import io
import json
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

from light_labs.core import google

CLIENT = {"installed": {"client_id": "cid", "client_secret": "csec", "token_uri": "https://t"}}


class AuthUrlTest(unittest.TestCase):
    def test_pkce_challenge_matches_verifier(self):
        verifier, challenge = google.pkce()
        digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        self.assertEqual(challenge, digest.decode().rstrip("="))

    def test_each_robot_asks_only_for_its_own_scopes(self):
        url = google.auth_url(
            CLIENT["installed"], google.SCOPES["rush"], "http://127.0.0.1:5", "st", "ch", "me@x"
        )
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(q["scope"], ["https://www.googleapis.com/auth/gmail.readonly"])
        self.assertEqual(q["access_type"], ["offline"])
        self.assertEqual(q["code_challenge_method"], ["S256"])
        self.assertEqual(q["include_granted_scopes"], ["false"])
        self.assertEqual(q["login_hint"], ["me@x"])

    def test_no_robot_can_send_or_delete_mail(self):
        scopes = [s for group in google.SCOPES.values() for s in group]
        self.assertFalse([s for s in scopes if "send" in s or "compose" in s])
        for word in ("send", "delete", "trash"):
            self.assertFalse(any(word in name.lower() for name in dir(google.Gmail)), word)

    def test_only_roll_may_relabel(self):
        with self.assertRaises(PermissionError):
            google.Gmail("rush", "me@x", get=lambda s: "{}").relabel(["m1"], remove=["INBOX"])


class RedirectTest(unittest.TestCase):
    def redirect(self, query):
        server = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
        url = f"http://127.0.0.1:{server.server_port}/?{query}"

        def visit():
            try:
                urllib.request.urlopen(url).read()
            except urllib.error.HTTPError:
                pass  # the 400 page for a refused sign-in

        threading.Thread(target=visit, daemon=True).start()
        try:
            return google._wait_for_code(server, "st")
        finally:
            server.server_close()

    def test_returns_the_code_when_state_matches(self):
        self.assertEqual(self.redirect("state=st&code=abc"), "abc")

    def test_rejects_a_forged_state(self):
        with self.assertRaises(RuntimeError):
            self.redirect("state=other&code=abc")


class GmailTest(unittest.TestCase):
    def test_refreshes_once_and_calls_with_the_access_token(self):
        calls = []

        def opener(req, timeout=None):
            calls.append(req)
            body = (
                {"access_token": "AT"} if req.full_url == "https://t" else {"emailAddress": "me@x"}
            )
            return io.BytesIO(json.dumps(body).encode())

        def get(service):
            if service == google.CLIENT_KEYCHAIN:
                return json.dumps(CLIENT)
            self.assertEqual(service, "light-labs-google-rush-me@x")
            return json.dumps({"refresh_token": "RT"})

        g = google.Gmail("rush", "me@x", get=get, opener=opener)
        self.assertEqual(g.profile()["emailAddress"], "me@x")
        g.profile()
        self.assertEqual([c.full_url for c in calls].count("https://t"), 1)
        self.assertIn(b"refresh_token=RT", calls[0].data)
        self.assertEqual(calls[1].headers["Authorization"], "Bearer AT")


if __name__ == "__main__":
    unittest.main()
