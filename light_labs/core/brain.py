"""Model backends. Every brain has `think(system, user) -> str` and records stats in `last`.

Specs, as used in dln.json and evals/contestants.yaml:
    ollama:<tag>     local model via Ollama's chat API
    claude:<model>   cloud model via the Claude Code CLI (`claude -p`)
    mock             deterministic, no model: for CI and wiring tests
"""

import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request

from light_labs import config


class Brain:
    """Local model via Ollama."""

    def __init__(self, model, base=config.OLLAMA, timeout=300):
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.last = {}

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
        start = time.monotonic()
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode(), strict=False)
        self.last = {
            "latency_s": round(time.monotonic() - start, 3),
            "input_tokens": data.get("prompt_eval_count"),
            "output_tokens": data.get("eval_count"),
            "cost_usd": 0.0,
        }
        return data["message"]["content"].strip()


class ClaudeCLI:
    """Cloud model through `claude -p`: one turn, no tools, run from an empty directory.

    Isolated either way, so the baseline is the model, not the user's setup: with
    ANTHROPIC_API_KEY set it runs `--bare` (billed to the key); without one it uses the
    logged-in subscription with `--setting-sources project` from an empty directory, which
    skips the user's settings, hooks (no Stop chime per call) and ~/.claude/CLAUDE.md.
    """

    def __init__(self, model, timeout=300):
        self.model = model
        self.timeout = timeout
        self.last = {}

    def think(self, system, user, temperature=None):
        isolated = bool(os.environ.get("ANTHROPIC_API_KEY"))  # else: subscription
        cmd = [
            "claude",
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--system-prompt",
            system,
            "--tools",
            "",
            "--no-session-persistence",
            "--strict-mcp-config",
        ]
        cmd += ["--bare"] if isolated else ["--setting-sources", "project"]
        start = time.monotonic()
        with tempfile.TemporaryDirectory() as empty:
            proc = subprocess.run(
                cmd + [user],
                cwd=empty,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p failed: {proc.stderr.strip()[:300]}")
        data = json.loads(proc.stdout, strict=False)
        usage = data.get("usage") or {}
        self.last = {
            "latency_s": round(time.monotonic() - start, 3),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "cost_usd": data.get("total_cost_usd"),
            "isolated": True,
        }
        if data.get("is_error"):
            raise RuntimeError(f"claude -p error: {data.get('result')}")
        return (data.get("result") or "").strip()


class Mock:
    """No model. Escalates when the message asks for work, otherwise a short reply."""

    WORK = re.compile(
        r"\b(write|review|benchmark|build|script|analy[sz]e|fix|code)\b", re.IGNORECASE
    )

    def __init__(self, model="mock"):
        self.model = model
        self.last = {}

    def think(self, system, user, temperature=None):
        message = user.split("<message>")[-1].split("</message>")[0]
        self.last = {"latency_s": 0.0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        if self.WORK.search(message):
            return "ESCALATE: mock work request\nPassed to Auto; PJ will follow up."
        return "Thanks, good to hear from you."


def brain_for(spec, **kwargs):
    kind, _, model = spec.partition(":")
    if kind == "ollama" and model:
        return Brain(model, **kwargs)
    if kind == "claude" and model:
        return ClaudeCLI(model, **kwargs)
    if spec == "mock":
        return Mock()
    raise ValueError(f"unknown brain spec {spec!r} (want ollama:<tag>, claude:<model>, mock)")
