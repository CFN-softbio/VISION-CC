# Completion Protocol (11BM-CMS) — full detail

Full version of the **Completion Protocol** summary in `CLAUDE.md`. Team-lead enforces the
handshake below; the per-cog liveness self-checks live in each agent file's
**"Liveness Self-Check"** section (`op-cog.md` / `ana-cog.md` / `gpcam-cog.md`).

## Why this exists (past failure)

Team-lead saw `state=complete` on the op kernel and killed all teammates — but the op terminal
had actually stalled (not finished) and the loop hadn't started. **Never declare an experiment
complete from a single signal.** Completion requires the 3-way handshake AND each teammate
self-verifying its own terminal/process is alive before reporting status.

## Per-cog liveness self-check (MANDATORY before a cog reports completion)

Each cog verifies its own terminal/process is genuinely alive AND its work is genuinely done —
`state=complete` alone is not enough (the kernel could have stalled, the daemon crashed, or a
flag been written prematurely). The exact per-cog checks (kernel responsiveness, terminal state
stability, log/row-count parity, no stale flags, no tracebacks) live in each agent file's
"Liveness Self-Check" section. Team-lead trusts the cog's reported result and enforces the
handshake below.

## Team-lead 3-way handshake (MANDATORY before spawning writer-cog or shutting down)

Team-lead does NOT declare the experiment done — and does NOT spawn writer-cog or request
shutdowns — until **all three** are confirmed:

1. **operator** has sent a completion `SendMessage` AND its self-check passes
2. **analysis** has sent a completion `SendMessage` AND its self-check passes
3. **gpcam** has sent a completion `SendMessage` AND its self-check passes

If any one is missing or stale, explicitly ping that teammate (single status-check
`SendMessage`) before assuming completion. Never infer completion from a flag file alone.
Read the stop kind, the first field of `AE_COMPLETE.txt` (`docs/flag-file-contract.md`):
`CLEAN` → run this handshake as a normal finish; `STALLED` or `UNVERIFIED` → report it to the user
first, and request no writer report and no shutdown on your own. Runs before this format wrote
`complete,…` on every exit path: there, check the cog logs for a terminal `reason=error`.

## Stuck-terminal detection

If a teammate has produced no `SendMessage` for `> 2 × expected_iter_time` AND its log file's
last-modified time hasn't advanced:

1. Send ONE status-check `SendMessage` to that teammate.
2. The teammate must run its liveness self-check and report results — including any error
   tracebacks, kernel state, daemon process status, last-written log line.
3. If the teammate confirms stuck (kernel hang, daemon crash, motor not moving), team-lead asks
   the user before taking any action — **never auto-kill or auto-abort.**
4. Stuck ≠ done. A stalled op kernel is not a completed experiment.

## NEVER auto-shutdown teammates from team-lead unless:

- All three completion conditions above are satisfied, OR
- The user explicitly says "stop" / "abort" / "kill the team"
