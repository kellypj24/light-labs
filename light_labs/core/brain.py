"""Local model via Ollama's chat API."""

import json
import urllib.request

from light_labs import config


class Brain:
    def __init__(self, model, base=config.OLLAMA, timeout=300):
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def think(self, system, user, temperature=0.7):
        body = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": temperature},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        req = urllib.request.Request(
            f"{self.base}/api/chat",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode(), strict=False)["message"]["content"].strip()
