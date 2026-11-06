# Auditable Human–Agent Teams for Autonomous X-ray Experiments

**VISION-CC** (Virtual Scientific Companion with Claude Code) uses a team of Claude Code agents to run autonomous experiments (AE). The scientist steers the experiment with evolving goals; a team-lead agent relays their direction to four *cogs* (specialized agents): **op-cog** drives the beamline, **ana-cog** analyses the data, **gpcam-cog** decides where to measure next with gpCAM Bayesian optimization, and **writer-cog** provides the visualization. An **audit-cog** reconstructs offline, who proposed, decided, and corrected what during a campaign.

VISION-CC succeeds [VISION](https://github.com/CFN-softbio/VISION), our earlier LLM-based assistant, moving from a single LLM to a team of Claude Code agents.

## Contents

| Path | What |
|---|---|
| `CLAUDE.md`, `.claude/`, `docs/` | the agent team: team-lead procedure, cog definitions, skills, and shared protocols |
| `src/audit/codebook.md` | the audit's definitions and the exact prompt of every model step |
| `data/exp2_p07_s44/` | 44 SAXS frames from Exp. 2, losslessly compressed, with index, mask and decoder (`frames.py`) |
| `results/ledgers/exp2/` | an example audit ledger: 25 minutes of Exp. 2 in which the scientist proposed and steered the peak-07 mapping that produced these frames (sanitized) |

Read a frame: `frames.load("data/exp2_p07_s44/" + row["frame"], (1679, 1475))` for a row of `index.csv`.

More code will follow in this repository.
