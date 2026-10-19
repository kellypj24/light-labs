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
lab google auth rush --account kellypj24@gmail.com   # browser opens; PJ signs in and approves
lab google check rush                                # prints the mailbox address and size
```

No robot can send mail: no scope includes sending, and `light_labs/core/google.py` has no
send call (`tests/test_google.py` checks both). Drafts, when they come, need
`gmail.compose`, which Google also lets send, so the no-send rule stays in code.

Revoke any robot at https://myaccount.google.com/permissions and delete its Keychain item.
The app's privacy policy is https://pjksystems.com/privacy.
