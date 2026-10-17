"""Rush on Telegram: PJ's two-way channel to the approval queue.

Rush is a bot PJ created with @BotFather; the token lives in Keychain
(`light-labs-rush-telegram`) and the bot talks to one chat only, RUSH_TELEGRAM_CHAT
(`lab rush telegram-link` finds it after PJ sends the bot /start). Drafts arrive with
Send and Reject buttons; replying to a draft with text sends PJ's version, or rejects it
when the reply starts with "no". /queue lists what waits, /tick checks the board now.

Outgoing texts come from the tick (phone.py decides when). Incoming updates are read by
a long-poll thread in the remote's process, so they are handled while the Mac is awake;
Telegram keeps them for a day otherwise. Message contents pass through Telegram's servers.
"""

import json
import re
import time
import urllib.error
import urllib.request

from light_labs.core.agentnet import keychain_token

KEYCHAIN = "light-labs-rush-telegram"
API = "https://api.telegram.org/bot{token}/{method}"
POLL_SECONDS = 50
KEEP_MESSAGES = 200
# A reply that rejects: "no", "No.", "no: wrong thread", "no - not ours". Not "nope, send it".
_NO = re.compile(r"^no\b[\s.:,!-]*(.*)$", re.IGNORECASE | re.DOTALL)
HELP = (
    "I'm Rush. I text you when a draft waits on you.\n"
    "Tap Send or Reject under a draft, or reply to it: your text goes out instead, "
    'and "no <reason>" rejects it.\n'
    "/queue lists what's waiting. /tick checks the board now."
)


class Telegram:
    def __init__(self, token, chat_id, state_path, opener=urllib.request.urlopen):
        self.token, self.chat_id = token, str(chat_id)
        self.state_path, self.opener = state_path, opener

    @classmethod
    def from_keychain(cls, chat_id, state_path):
        return cls(keychain_token(KEYCHAIN), chat_id, state_path)

    # --- wire
    def call(self, method, wait=30, **params):
        req = urllib.request.Request(
            API.format(token=self.token, method=method),
            data=json.dumps(params).encode(),
            headers={"Content-Type": "application/json"},
        )
        with self.opener(req, timeout=wait) as r:
            body = json.loads(r.read().decode())
        if not body.get("ok"):
            raise OSError(f"telegram {method}: {body.get('description')}")
        return body["result"]

    def _state(self):
        if self.state_path.exists():
            return json.loads(self.state_path.read_text())
        return {"offset": 0, "messages": {}}

    def _save(self, state):
        msgs = state["messages"]
        state["messages"] = dict(list(msgs.items())[-KEEP_MESSAGES:])
        self.state_path.write_text(json.dumps(state, indent=2) + "\n")

    # --- outgoing
    def text(self, to, text):
        """Plain message; `to` is ignored (one chat), kept to match phone.imessage."""
        return self.call("sendMessage", chat_id=self.chat_id, text=text)

    def draft(self, item, text):
        """A waiting draft with its buttons; remembers which message is which draft."""
        msg = self.call(
            "sendMessage",
            chat_id=self.chat_id,
            text=text,
            reply_markup={
                "inline_keyboard": [
                    [
                        {"text": "Send", "callback_data": f"send:{item['id']}"},
                        {"text": "Reject", "callback_data": f"reject:{item['id']}"},
                    ]
                ]
            },
        )
        state = self._state()
        state["messages"][str(msg["message_id"])] = item["id"]
        self._save(state)
        return msg

    # --- incoming
    def poll_once(self, remote, timeout=POLL_SECONDS):
        state = self._state()
        updates = self.call(
            "getUpdates", wait=timeout + 10, offset=state["offset"], timeout=timeout
        )
        for u in updates:
            state["offset"] = u["update_id"] + 1
            self._save(state)  # an update that crashes the handler is not retried forever
            self.handle(u, remote)
        return len(updates)

    def poll_forever(self, remote, sleep=time.sleep):
        while True:
            try:
                self.poll_once(remote)
            except (OSError, urllib.error.URLError) as e:  # asleep, offline, Telegram down
                print(f"telegram poll: {e}")
                sleep(15)

    def _from_pj(self, chat):
        return str(chat.get("id")) == self.chat_id

    def handle(self, update, remote):
        if "callback_query" in update:
            return self._button(update["callback_query"], remote)
        msg = update.get("message") or {}
        if not self._from_pj(msg.get("chat", {})):
            return None
        text = (msg.get("text") or "").strip()
        replied = msg.get("reply_to_message")
        if replied:
            item_id = self._state()["messages"].get(str(replied["message_id"]))
            if item_id:
                return self._answer(item_id, text, remote)
        if text in ("/queue", "queue"):
            return self.queue(remote)
        if text in ("/tick", "tick"):
            started = remote.start_tick()
            return self.text(None, "Checking the board." if started else "Already checking.")
        return self.text(None, HELP)

    def _answer(self, item_id, text, remote):
        try:
            no = _NO.match(text)
            if no:
                remote.reject(item_id, no.group(1).strip() or "rejected on Telegram")
                return self.text(None, f"Rejected {item_id}.")
            remote.approve(item_id, text)
            return self.text(None, f"Sent your version of {item_id}.")
        except FileNotFoundError:
            return self.text(None, f"{item_id} was already handled.")

    def _button(self, query, remote):
        if not self._from_pj(query.get("message", {}).get("chat", {})):
            return None
        action, _, item_id = (query.get("data") or "").partition(":")
        try:
            if action == "send":
                remote.approve(item_id, None)
                note = "Sent"
            elif action == "reject":
                remote.reject(item_id, "rejected on Telegram")
                note = "Rejected"
            else:
                note = "?"
        except FileNotFoundError:
            note = "Already handled"
        self.call("answerCallbackQuery", callback_query_id=query["id"], text=note)
        msg = query.get("message", {})
        if msg.get("message_id"):
            self.call(
                "editMessageText",
                chat_id=self.chat_id,
                message_id=msg["message_id"],
                text=f"{msg.get('text', '')}\n\n{note}.",
            )
        return note

    def queue(self, remote):
        items = remote.store.pending()
        if not items:
            return self.text(None, "Nothing waiting.")
        from light_labs.agents.rush.phone import text_for

        for item in items[:5]:
            self.draft(item, text_for(item))
        if len(items) > 5:
            self.text(None, f"And {len(items) - 5} more on the remote page.")
        return len(items)


def link(token):
    """Chats that have messaged the bot: [(chat id, name)]. For setting RUSH_TELEGRAM_CHAT."""
    tg = Telegram(token, "", None)
    seen = {}
    for u in tg.call("getUpdates", timeout=0):
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("id"):
            seen[chat["id"]] = chat.get("username") or chat.get("first_name") or ""
    return sorted(seen.items())
