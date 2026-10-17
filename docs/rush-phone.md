# Rush on PJ's phone

Rush runs on the MacBook. The phone reaches it two ways:

| Piece | What it does | Needs |
|---|---|---|
| Remote page (`lab rush remote`) | Queue (edit and send, reject), board, inbox, comment as PJ | Tailscale on the phone; `tailscale serve` on the Mac |
| Texts (`RUSH_NOTIFY_TO`) | At most one iMessage per tick, starting `Rush:`: the waiting draft with a link to it, or a digest when several are new. None in quiet hours (`RUSH_QUIET_HOURS`, default `0-8`) | Messages signed in on the Mac; Automation access to Messages (one prompt) |
| Wake schedule (`RUSH_WAKE_MINUTES`) | Each tick schedules the next wake, so the Mac sleeps between ticks | One sudoers line for `pmset schedule wake` |

Rush only sends texts. It never reads Messages, so nothing needs Full Disk Access.

## Setup

1. `.env` (git-ignored):

   ```
   RUSH_NOTIFY_TO=+15555550123          # PJ's own number or Apple ID
   RUSH_REMOTE_URL=http://<mac>.<tailnet>.ts.net
   RUSH_WAKE_MINUTES=60
   ```

2. The sudoers line, so ticks can schedule wakes without a password. Only `pmset schedule
   wake` is allowed:

   ```
   echo "$(whoami) ALL=(root) NOPASSWD: /usr/bin/pmset schedule wake *" \
     | sudo tee /etc/sudoers.d/light-labs-rush-wake && sudo chmod 440 /etc/sudoers.d/light-labs-rush-wake
   sudo visudo -c
   ```

   Remove with `sudo rm /etc/sudoers.d/light-labs-rush-wake`.

3. `just rush-install` installs both launchd jobs (the hourly tick runs under
   `caffeinate -i`; the remote page stays up), then publish the page tailnet-only:

   ```
   tailscale serve --bg --http 80 http://127.0.0.1:8787
   ```

4. Send one test text from a terminal (`lab rush tick` with a draft waiting) and allow
   the Automation prompt. If the launchd job can't text, `var/rush/journal.md` says
   "could not text PJ".

## Checks

- `pmset -g sched` lists the next wake.
- `pmset -g log | grep -E " (Wake|Sleep) "` shows whether the Mac woke and slept again.
- A MacBook with the lid closed on battery may go back to sleep straight after a
  scheduled wake. Test that case before relying on it.
