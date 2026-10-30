---
name: update-robot-memory
description: Keep a robot's local memory.md accurate after work is done or promised on its behalf. Use whenever Auto or PJ acts as a robot's actor, or a robot's draft is approved.
audience: [auto]
---

Small local models invent past work when their memory is stale, so memory upkeep is part
of finishing any task done as a robot's actor.

- File: `light_labs/agents/<robot>/memory.md`. It is git-ignored and never committed; it
  may name people and systems outside this repo.
- After posting, building or promising something as the robot's actor, add a dated line
  under "Work so far" or "Open threads": what was done, where (task or artifact id), and
  what is still owed.
- When a thread closes, move it out of "Open threads".
- Write facts, not intentions. "Sent a holding reply; a real answer is still owed" beats
  "will answer soon".
- Keep it short. It is in every prompt, and the model's context is small. Merge or prune
  old entries once they no longer affect what the robot should say.
- Notes go to Auto's cloud brain scrubbed (`sanitize.notes`: addresses, URLs, ids and
  numbers replaced; dates kept). What it must not see at all goes under `## Private`,
  which never leaves the laptop.
- If the structure changes, update `memory.example.md` to match.
