# Google sign-ins for the robots

Google Cloud project `light-labs` (owner kellypj24@gmail.com) has the Gmail API and one
OAuth client (Desktop app). The client JSON lives in Keychain as
`light-labs-google-oauth-client`; it never goes in the repo.

Each robot signs in on its own, with only its scopes, and keeps its own refresh token in
Keychain (`light-labs-google-<robot>`):

| Robot | Scope | For |
|---|---|---|
| Rush | `gmail.readonly` | triage, summaries |
| Roll | `gmail.modify` | archive and label (inbox cleanup) |

```
lab google auth rush --account kellypj24@gmail.com    # browser opens; PJ signs in and approves
lab google check rush --account kellypj24@gmail.com   # prints the mailbox address and size
```

Tokens are per mailbox (`light-labs-google-rush-<account>`); sign in once per account.

## Mail triage (Rush)

With `RUSH_MAIL_ACCOUNTS` set, each tick labels new inbox mail (needs_reply, fyi, receipt,
newsletter, spam) with Rush's local model and texts PJ once about anything that needs a
reply: sender and a one-line summary, never the message. Mail needing a reply that lands
in quiet hours is texted after. The phone page's Mail view lists everything triaged, with
Gmail links. Only sender, subject, label and summary are kept (`var/rush/mail/`).
The eval stage is `evals/stages/mail-triage.yaml`.

No robot can send mail: no scope includes sending, and `light_labs/core/google.py` has no
send call (`tests/test_google.py` checks both). Drafts, when they come, need
`gmail.compose`, which Google also lets send, so the no-send rule stays in code.

Revoke any robot at https://myaccount.google.com/permissions and delete its Keychain item.
The app's privacy policy is https://pjksystems.com/privacy.

### Teacher (temporary)

With `RUSH_MAIL_TEACHER=claude:sonnet`, each email is also labelled by Claude and Claude's
label is the one acted on; the local label is kept beside it, and the journal reports
agreement each tick. This sends the sender, subject and first 600 characters of new mail
to Anthropic, which PJ allowed until a local model earns the mail-triage weapon. The
teacher turns off by itself once Rush's `dln.json` entry holds that weapon.
Disagreements stay local in `var/rush/mail/disagreements.jsonl`;
`lab rush mail-fixtures` rewrites them into synthetic fixture candidates for review.
