# Annotation Codebook — VISION Multi-Agent Audit Pipeline

The specification of the audit pipeline in `src/audit/audit_src/pipeline/`, the version that produced the published
ledgers (tag `audit-v7-frozen` in the authors' repository). Every prompt below is extracted from the code, never
retyped; `tests/check_v6_wordings.py` checks them. Model and settings for every call: `claude-opus-5-5`, effort high,
adaptive thinking, 32000 max tokens (pinned in `llm.py`, which refuses others).

## Reading the transcripts and running the raters

- **The human's AskUserQuestion answers are read in full.** An answer is read only if its content starts with an
  answer mark ("Your questions have been answered:" / "The user answered:") and its `tool_use_id` is an
  AskUserQuestion call of the run; the harness's closing instruction is removed; several answers in one record, or an
  answer with other text, fail closed. Turns the harness inserts itself (`isMeta`) are not human messages.
- **Team-lead replies are split where they end.** A new reply starts when the previous API message is complete
  (`end_turn` on any of its records) and the API message changes. One body rule for every stage (`plib.message_body`).
- **A different wording per rater.** Each rater, verifier or pass of a multi-rater stage reads its own WORDING of the
  task: w1 is the prompt quoted in PART A–D; w2 / w3 recast ONLY the opening sentence (every qualifier kept:
  INDEPENDENT, blind, the participants, what is rated) and the sentences that describe the input (what each item
  shows, "Timestamps are UTC", the INPUT line). Category definitions, examples, rubrics, vocabularies, decision rules
  (blinding, evidence limits, neutrality, eligibility, cardinality), answer fields and OUTPUT blocks are the same
  string in every wording (`wording.check`). The variants are same-model calls with slightly different phrasing, not
  independent instruments. Single adjudicators (p11b, p12b) read w3. p04 intent keeps its two prompt styles (A / B).
  See PART E.
- **Every "nothing found" search is verified.**
- **The settlement layer (PART D)** runs on the first-pass ledger: C3 target resolution, C4 settlement search
  (forward / backward / lifecycle, two passes + a replay), referral of settling messages without an extracted
  decision, C5 code evidence (edits -> `implements` / `results_from`), C6 verification per relation family with
  adjudication of conflicts. The decider of an idea is the sender of the message that settles it.

## Deterministic rules (no model calls)

- **p05:** a message the API refuses for one intent rater takes the other rater's label.
- **p10a (C5):** every finding within 20 minutes after a file edit is also proposed as a `results_from` candidate.
- **p10c:** a fix link stands in for the ledger's fix only when the verifiers counted it.
- **p10t:** a decision cannot take up an idea that did not exist yet. A counted `settles` claim from a decision to an
  idea is invalidated when the idea's first occurrence comes after the decision's first occurrence (by time across
  messages, by position within one message).
- **Final ledger:** `final_ledger.py` writes the ledger from the views as copies of the files, never links.

## The human's instruction and the wordings

The rule: *the human's instruction IS the LLM's prompt, verbatim.* With several wordings, a human annotator
is given **wording w1** (the prompt quoted in PART A / B / D) and the same item fields. The
other wordings differ only in their opening sentence and their descriptions of the input (PART E), so the
definitions and rules a human applies are exactly those every model rater applied.

## Provenance (where each scheme is defined in the code)

All paths under `audit_src/pipeline/`; rendered prompts under `<AUDIT_OUT>/` (`<stem>_w<k>.md`, with
`prompts_manifest.json`: the md5 of every wording, its verbatim blocks and the job -> wording map).

| § | Task | Raters / wordings | Source (code -> rendered prompt) |
|---|---|---|---|
| A1 | Message intent | raters 3, 4: prompt styles A / B; adjudicator | `p03_label_prep.py` -> `03_prompt_{A,B}_blind.md`; `p05_label_ingest.py` |
| A2 | Ledger extraction | 2 passes: w1, w2 | `p07_extract_prep.py` -> `extract/p07_extract_prompt_w{1,2}.md`; union `p08_extract_ingest.py` |
| A3, A4, A4b | Event types | 2 raters: w1, w2; adjudicator w3 | `p11_type_prep.py` -> `types/p11_<kind>_prompt_w{1,2,3}.md`; `p11b`, `p11c` |
| A5 | Coordination type | 2 raters: w1, w2; adjudicator w3 | `p12_coord_prep.py` -> `coord/p12_prompt_w{1,2,3}.md`; `p12b`, `p12c` |
| B1, B2 | Contribution / link verification | 3 verifiers: w1, w2, w3 | `p09_verify_prep.py` -> `verify/p09_{contrib,link}_prompt_w{1,2,3}.md`; accept `p10_ledger_v5.py` |
| D1 | C3 target resolution | 3 verifiers: w1, w2, w3 | `p09c_target.py` -> `verify_c3/prompt_w{1,2,3}.md` |
| D2 | C4 settlement search | 2 passes: w1, w2 | `p10s_settle.py` -> `settle/prompt_w{1,2}.md` (+ `settle/replay/`) |
| D3 | Referral | 3 verifiers: w1, w2, w3 | `p10x_referral.py` -> `referral/prompt_w{1,2,3}.md` |
| D4 | C6 verification, per relation family | 3 verifiers: w1, w2, w3 | `v5verify.py` (`PROMPTS`) -> `verify_v5/prompt_<family>_w{1,2,3}.md`; rule `v5verify.decide` |
| D5 | C6 adjudication of conflicts | 3 adjudicators: w1, w2, w3 | `v5verify.py` (`ADJ_PROMPT`) -> `verify_v5/adj/adj_prompt_w{1,2,3}.md` |
| — | C5 code evidence | no model (edits read from the transcripts) | `p10a_artifacts.py` |

---

> The prompts in PART A–C are wording **w1** of their stages, byte for byte (checked by `tests/check_v6_wordings.py`); the prompt files are `<stem>_w1.md`.

> Where PART A–C say that passes, raters, third raters or verifiers get "the same prompt", the pipeline gives rater / verifier / pass k wording w<k> instead (PART E; single adjudicators: w3; p04 intent: prompts A / B as before). The prompts quoted here are w1 (for A3–A5 the runtime prompt is the JSON form shown with each). Typing (A3–A4b) covers the events that exist when p11 runs, not referral-created ones. The final counts are PART D's (counted claims), not the first pass's; "precision comes from verifiers" names the control, not a measured precision.

# PART A — Annotation schemes (prompt quoted verbatim)

## A1. Message intent (per-message labeling)

Every message in the corpus (`02_corpus.csv`) gets two orthogonal axes: **Axis 1 = message intent**
(one primary; optional secondary; on long messages an optional tertiary) and **Axis 2 = sentence type**
(exactly one).

**What the rater sees** (`03_batches_blind.jsonl`, one JSON object per message, chunks of 100):
`message_id`; `target` — the full message body reconstructed from the transcripts, capped at 4000
characters; `antecedent` — the previous message between the same two participants (either direction),
capped at 600 characters, reference only; `long` — true if the full body is at least 1000 characters
(only long rows may carry a tertiary). **No sender, recipient or channel.** Never `timeline.md`, a ledger,
`report_notes`, or the other rater's labels.

**Two blind raters** with diverse prompt styles: **rater 3 = Style A (definitional)** and **rater 4 =
Style B (speech-act)**. The two prompts are identical except for the style paragraph. (The numbers 3 and
4 are kept so the `r3_*`/`r4_*` columns stay stable.) The intent and sentence-type definitions are
filled in from `audit_src/lib/instrument.py`, which is fixed in code and identical for every run (a run
config may not carry them).

Rater 3, `03_prompt_A_blind.md` (verbatim):

```
You are labeling messages exchanged between participants coordinating a scientific experiment.

The messages arrive one JSON object per line: message_id, target (the message to label), antecedent (the previous message between the same two participants, usually the one it replies to; reference only) and long (true if the full message is at least 1000 characters). You are NOT told who sent it or to whom -- judge purely from the words. If that makes a label uncertain, set confidence low; that is expected.

AXIS 1 -- MESSAGE INTENT (assign one PRIMARY; add a SECONDARY only if a second
intent is clearly, independently present). Label by what the message CONTRIBUTES to
the shared work, NOT by its sentence type:

  idea (propose)         Originates a course of action, option, approach or change NOT YET DECIDED -- whether phrased as a statement, a question, or a directive. Labelled by role, so a proposal wearing directive or interrogative mood is still an idea.
  decision (decide)      Commits to, authorises, or declines a course of action ALREADY ON THE TABLE -- enacts or gates it ('go', 'do it', 'yes', 'don't'). A directive that FIRST raises the action is idea(+decision), not decision alone.
  question (ask)         Seeks information or a judgment from the recipient WITHOUT itself proposing a course of action. A leading/rhetorical question that proposes is an idea, not a question.
  correction (correct)   Flags something as wrong, reverses course, or retracts a prior claim (including one's own).
  finding (report_result) Establishes a concrete result: a measured value, verdict, diagnosis or observation about the data or the run, including an unexpected failure and its cause. If it shows that an earlier claim or action was wrong, it is also a correction.
  status (report_state)  Reports where things stand: progress, readiness, completion, or acknowledgement. Delivers no new result: something being ready or not yet ready, running, or working as expected (a check passed) is status. If it shows that an earlier claim or action was wrong, it is also a correction.
  other (none)           Greeting, interrupt marker, machine bookkeeping, noise.

AXIS 2 -- SENTENCE TYPE (assign exactly ONE on EVERY message):
  directive        Imperative/commanding form: tells the recipient to do something ('add p02', 'go', 'don't run more calibration').
  interrogative    Question form: asks something ('why not p02?', 'is the backfill ready?').
  declarative      Statement form: asserts or reports ('prefactor_p04 is 0 there', 'phase 2d is running').
  expressive_other Greeting, exclamation, acknowledgement token, or non-propositional marker ('thanks', 'ok', 'sorry').
  Sentence type is how the sentence is BUILT, INDEPENDENT of what it contributes. "add p02 as a cross-check" is DIRECTIVE type but an IDEA intent (it proposes p02). "why not p02?" is INTERROGATIVE type, also an IDEA intent. "is the backfill ready?" is INTERROGATIVE type, an ASK (question) intent.

RULES:
  - Label INTENT by CONTRIBUTION, not sentence type. An idea phrased as a
    directive ('add p02') or a question ('why not p02?') is still an IDEA intent.
    This is the whole point of separating intent (axis 1) from sentence type (axis 2).
  - A message that BOTH proposes a new action AND directs it carries both idea and
    decision -- capture both. Primary = the intent that carries the most of what the
    sender is doing; there is NO fixed ranking of the intents.
  - A message that passes on someone else's proposal, result or decision also carries
    that intent -- capture it alongside what the message itself does (often status).
    Primary = the intent that carries the most of what the sender is doing.
  - TERTIARY (LONG messages only): rows marked "long": true may carry THREE or more
    distinct intents that two slots cannot hold. For a long row, if a THIRD intent is
    clearly and independently present beyond primary+secondary, add a TERTIARY label
    (same seven intents). In particular, a long finding/status message often ALSO
    overturns/retracts/corrects a prior claim -- check explicitly for correction.
    Leave tertiary EMPTY for short rows ("long": false), or when no clear third intent
    exists. A tertiary on a short row is discarded.
  - Primary, secondary and tertiary must be DIFFERENT intents; leave a slot empty
    rather than repeat a label.
  - Judge intent by CONTENT, NOT by who usually plays what role.
  - Label the TARGET message only. The antecedent is context to resolve references
    (what does 'go' approve?), never the thing being labeled.
  - Sentence type is INDEPENDENT of intent: assign it from the sentence's form.
  - If genuinely unlabelable from what you are given, pick your best primary and
    set confidence low. Do NOT ask for more context.
  - Label EVERY message you are given, each exactly once.

STYLE A -- DEFINITIONAL
For each message, compare it against the seven definitions above and assign the PRIMARY intent whose definition it best matches. Work definition-first.

OUTPUT: a JSON array, one object per input message, and nothing else:
  {"message_id": "<as given>", "primary": "<intent>", "secondary": "<intent or empty>",
   "tertiary": "<intent or empty; long rows only>", "sentence_type": "<sentence type>",
   "confidence": <a number 0.0-1.0>, "rationale": "<=15 words quoting the deciding words"}
Use the intent and sentence-type ids exactly as written above (lower case); empty string for an unused slot.
```

Rater 4, `03_prompt_B_blind.md` (verbatim):

```
You are labeling messages exchanged between participants coordinating a scientific experiment.

The messages arrive one JSON object per line: message_id, target (the message to label), antecedent (the previous message between the same two participants, usually the one it replies to; reference only) and long (true if the full message is at least 1000 characters). You are NOT told who sent it or to whom -- judge purely from the words. If that makes a label uncertain, set confidence low; that is expected.

AXIS 1 -- MESSAGE INTENT (assign one PRIMARY; add a SECONDARY only if a second
intent is clearly, independently present). Label by what the message CONTRIBUTES to
the shared work, NOT by its sentence type:

  idea (propose)         Originates a course of action, option, approach or change NOT YET DECIDED -- whether phrased as a statement, a question, or a directive. Labelled by role, so a proposal wearing directive or interrogative mood is still an idea.
  decision (decide)      Commits to, authorises, or declines a course of action ALREADY ON THE TABLE -- enacts or gates it ('go', 'do it', 'yes', 'don't'). A directive that FIRST raises the action is idea(+decision), not decision alone.
  question (ask)         Seeks information or a judgment from the recipient WITHOUT itself proposing a course of action. A leading/rhetorical question that proposes is an idea, not a question.
  correction (correct)   Flags something as wrong, reverses course, or retracts a prior claim (including one's own).
  finding (report_result) Establishes a concrete result: a measured value, verdict, diagnosis or observation about the data or the run, including an unexpected failure and its cause. If it shows that an earlier claim or action was wrong, it is also a correction.
  status (report_state)  Reports where things stand: progress, readiness, completion, or acknowledgement. Delivers no new result: something being ready or not yet ready, running, or working as expected (a check passed) is status. If it shows that an earlier claim or action was wrong, it is also a correction.
  other (none)           Greeting, interrupt marker, machine bookkeeping, noise.

AXIS 2 -- SENTENCE TYPE (assign exactly ONE on EVERY message):
  directive        Imperative/commanding form: tells the recipient to do something ('add p02', 'go', 'don't run more calibration').
  interrogative    Question form: asks something ('why not p02?', 'is the backfill ready?').
  declarative      Statement form: asserts or reports ('prefactor_p04 is 0 there', 'phase 2d is running').
  expressive_other Greeting, exclamation, acknowledgement token, or non-propositional marker ('thanks', 'ok', 'sorry').
  Sentence type is how the sentence is BUILT, INDEPENDENT of what it contributes. "add p02 as a cross-check" is DIRECTIVE type but an IDEA intent (it proposes p02). "why not p02?" is INTERROGATIVE type, also an IDEA intent. "is the backfill ready?" is INTERROGATIVE type, an ASK (question) intent.

RULES:
  - Label INTENT by CONTRIBUTION, not sentence type. An idea phrased as a
    directive ('add p02') or a question ('why not p02?') is still an IDEA intent.
    This is the whole point of separating intent (axis 1) from sentence type (axis 2).
  - A message that BOTH proposes a new action AND directs it carries both idea and
    decision -- capture both. Primary = the intent that carries the most of what the
    sender is doing; there is NO fixed ranking of the intents.
  - A message that passes on someone else's proposal, result or decision also carries
    that intent -- capture it alongside what the message itself does (often status).
    Primary = the intent that carries the most of what the sender is doing.
  - TERTIARY (LONG messages only): rows marked "long": true may carry THREE or more
    distinct intents that two slots cannot hold. For a long row, if a THIRD intent is
    clearly and independently present beyond primary+secondary, add a TERTIARY label
    (same seven intents). In particular, a long finding/status message often ALSO
    overturns/retracts/corrects a prior claim -- check explicitly for correction.
    Leave tertiary EMPTY for short rows ("long": false), or when no clear third intent
    exists. A tertiary on a short row is discarded.
  - Primary, secondary and tertiary must be DIFFERENT intents; leave a slot empty
    rather than repeat a label.
  - Judge intent by CONTENT, NOT by who usually plays what role.
  - Label the TARGET message only. The antecedent is context to resolve references
    (what does 'go' approve?), never the thing being labeled.
  - Sentence type is INDEPENDENT of intent: assign it from the sentence's form.
  - If genuinely unlabelable from what you are given, pick your best primary and
    set confidence low. Do NOT ask for more context.
  - Label EVERY message you are given, each exactly once.

STYLE B -- SPEECH-ACT
For each message, first ask: what is the sender trying to DO to the recipient -- instruct, ask, report a result, flag an error, propose an option, acknowledge, or none of these? Then pick the intent naming that act. Work function-first.

OUTPUT: a JSON array, one object per input message, and nothing else:
  {"message_id": "<as given>", "primary": "<intent>", "secondary": "<intent or empty>",
   "tertiary": "<intent or empty; long rows only>", "sentence_type": "<sentence type>",
   "confidence": <a number 0.0-1.0>, "rationale": "<=15 words quoting the deciding words"}
Use the intent and sentence-type ids exactly as written above (lower case); empty string for an unused slot.
```

**Output schema (per message):** `message_id, primary, secondary, tertiary, sentence_type,
confidence ∈ [0,1], rationale (≤15 words)`.

**Validation at ingest (`p05`).** Fatal, never dropped silently: a missing or stale output (prompt/input
md5 differs from its `.prov.json`), an id outside its chunk, a duplicate id, a message with no label, an
off-vocabulary intent or sentence type, a confidence outside [0,1]. Logged in `05_ingest_checks.csv` and
blanked: a tertiary on a short row; a slot that repeats an earlier slot's label.

**Adjudicator.** Every message whose two primaries differ goes to one blind adjudicator. Each item shows
`message_id`, `target`, `antecedent`, `long`, and the two raters' labels as `"Rater 1"` and `"Rater 2"`
(primary and, where given, secondary/tertiary), in a per-item random order (seed `20261009`, recorded in
`adjudication/05_adjudication_key.csv`); the adjudicator is never told which style a rater used, nor the
sender. `adjudication/05_adjudication_prompt.md` (verbatim):

```
You are adjudicating MESSAGE INTENT for messages exchanged between participants coordinating a
scientific experiment. Two independent raters labeled each message and disagreed on its PRIMARY intent.

Each item gives: the TARGET message, the ANTECEDENT (the previous message between the same two participants;
context only), whether it is long,
and the labels each rater assigned (primary, and secondary/tertiary where given). You are NOT told who
sent the message; judge from the words.

Intent = what the message CONTRIBUTES, not its grammar:
  idea             proposes a course of action not yet decided (even as a question or directive)
  decision         commits to, authorises, defers or declines an action already on the table (an instruction
                   that first raises an action and commits to it is idea + decision)
  question         seeks information without proposing an action
  correction       flags something as wrong, reverses course, or retracts a prior claim
  finding          establishes a concrete result: a value, verdict, diagnosis or observation, including an
                   unexpected failure and its cause (also a correction if it shows an earlier claim or action
                   wrong)
  status           reports where things stand: progress, readiness, completion, or acknowledgement; no new
                   result (ready or not yet ready, running, or a check that passed; also a correction if it
                   shows an earlier claim or action wrong)
  other            greeting, interrupt marker, bookkeeping, noise

A message that passes on someone else's proposal, result or decision carries that intent too; choose the
primary by what the message mainly does.

Choose the FINAL PRIMARY: the intent that carries most of what the sender is doing in the TARGET.
Choose ONLY from the labels the raters gave for that item (any of their primary/secondary/tertiary).
Do not split the difference by default; pick the label the target's words support best.

Output a JSON array, one object per item, and nothing else:
  {"message_id": "...", "final_primary": "<one of the given labels>", "confidence": <a number 0.0-1.0>,
   "reason": "<=20 words quoting the deciding words"}
```

**Combine rule** (`p05` → `p05b`, written to `05_labels.csv`):

| case | `final_primary` | `label_source` |
|---|---|---|
| rater 3 primary = rater 4 primary | that label | `agreed` |
| primaries differ; adjudicator picks a label one of the raters gave (any slot) | the pick | `adjudicated` |
| primaries differ; the pick is not among the raters' labels | empty (flagged in `05b_adjudication_flags.csv`) | `adjudication_rejected` |

`final_sentence_type` = the raters' sentence type when they agree, else blank. **Intent results use only
`final_primary`**; secondary and tertiary labels feed only the ledger candidate pool (§A2). The
reproducibility number is **Cohen's κ between rater 3 and rater 4 on primary** (`p05` meta, also printed).

**Notes on intent boundaries** (not part of any prompt; neither the model nor the human annotator is shown
them — they record the reasoning the definitions encode, for readers of the results):
- *Proposal vs commitment.* An idea introduces an option and commits to nothing; a decision commits with
  authority. A useful test: if the run would proceed unchanged when the utterance is ignored, it did not
  commit (idea, or status). The human's "go" / "do it" is a decision even when it approves someone else's
  idea; a cog's "ack, noted" commits nothing and is status.
- *Declining is a decision, not a correction.* Rejecting a sound alternative involves no error; at the
  event level its direction is recorded as `disposition = decline` (§A2). The message-level instrument has
  no stance field.
- *Correction vs finding vs decision.* A new result about the sample, data or run (a value, a diagnosis, an
  unexpected failure) is a finding -- a report that something is ready, running or works as expected is status;
  one that shows something wrong is a correction (as an intent broadly: flags something as wrong; as a
  contribution only when a claim or action asserted earlier is shown wrong, with the exclusions of §A2); one
  that commits to, authorises, defers or declines what to do next is a decision (proposing it is an idea). They co-occur — one episode can yield a finding, a correction and the
  decision it triggers — and are captured as primary/secondary/tertiary rather than forced into one label.
- *The intent `correction` is broader than the category* (`glossary.md`): a message that flags something as
  wrong is a correction intent even when it is a lesson from an earlier run; extraction records a correction
  only for a claim or action asserted and now shown wrong, excluding errors from an earlier run already known when
  this run started.
- *question and status have no ledger by design*: the ledgers record contributions, not information
  transfer.

## A2. Ledger extraction — contributions and links (message-first ledger)

The ledgers are built from **messages and directed links between messages**; roles and times are then
read off the linked messages' senders and timestamps (§C), never from the model's interpretation.

**Targets.** Every message in the candidate pool (`p06`): the union of every label either blind rater
gave a message — primary, secondary or tertiary of rater 3 and rater 4 — mapped
`idea → ideas`, `decision → decisions`, `correction → corrections`, `finding → findings`. The
adjudicator does not change the pool. Recall here, precision later. Non-candidate messages can still be
link targets.

**What the model sees** (`extract/windows/pP_wNNN.jsonl` for pass P, one JSON object per line, in time
order). Targets are processed in time order in windows of 20 (`EXTRACT_WINDOW`); pass 2's windows are
shifted by half a window (its first window has 10 targets), so no message is at a window edge in both passes.
Each window's input, every row with `role`, `message_id`, `ts` (UTC), `sender`, `recipient`, `text`:
- `context` rows: the 100 corpus messages (about an hour of the run) immediately before the window's first
  target (any message, not only candidates — a claim being corrected often sits in a status message),
  preceded by long-range messages from before those 100: for each target, the 5 earlier messages most
  similar to it by TF-IDF (each target is its own query), so that a reference hours back is reachable;
- the window itself: its targets (`role: target`, shown in full) interleaved with the non-candidate
  messages between them (`role: context`). Every context row's text is cut at 4,000 characters.

Text is the full message body rebuilt from the transcripts. A window is estimated at 0.5 input tokens per
character; p07 stops if any window exceeds 170k (measured maxima: 146k / 144k / 115k for Exp. 3 / 2 / 1).

**Senders are shown** (unlike intent labeling): who did what is the point of this step.

`extract/p07_extract_prompt.md` (verbatim):

```
You are extracting the CONTRIBUTIONS of messages exchanged between a human scientist and
AI agents (a team-lead orchestrator and specialist agents) running a scientific experiment, and the LINKS
from each contribution to the EARLIER message it acts on.

INPUT: one JSON object per line, in time order. Rows with "role": "context" are earlier messages given for
reference only. Rows with "role": "target" are the messages you label. Every row has message_id, ts (UTC),
sender, recipient and text.

For EACH target message, list its contributions (zero or more). A contribution is one of:
  idea        proposes a course of action, approach or change that is NOT yet decided (even phrased as a
              question, or as a suggestion in imperative form).
  decision    commits to, authorises, defers or declines a course of action already on the table. An
              instruction that FIRST raises an action and commits to it (tells someone to do it, rather than
              suggesting it) both proposes and decides it: list it as an idea AND a decision of this message
              (the decision then needs no takes_up link). An action is FIRST raised only if no earlier
              message you can see already proposed, suggested or offered it -- by anyone, including the
              sender. Check the messages above, especially the recipient's latest ones and whatever the
              instruction answers: an order or approval that takes up such a proposal (e.g. "yes, make that
              the default") is a decision with a takes_up link to it, not a new idea. Passing on or
              re-issuing a decision already made (e.g. tasking another agent with it) is not an original
              decision; it restates that one: record it as a decision with a "restates" link to the message
              where it was decided. Reporting that a decided action has been done ("Config written") is
              status, not a decision; committing to an action for the first time ("I will write config.json
              now" in answer to "should we?") is a decision.
  finding     establishes a concrete result: a measured value, verdict, diagnosis or observation about the
              data or the run, established HERE. Forwarding a result someone else established is not a new
              finding: record it with a "restates" link to where it was established.
  correction  overturns, retracts or fixes something earlier: a claim or action that was ASSERTED (stated
              as true, or acted on) and is now shown wrong. Code or configuration written with a defect
              counts as an asserted action (a bug found and fixed IS a correction). An expectation or
              prediction stated as the expected outcome, or used to plan or justify an action, counts as
              an assertion, unless it was explicitly raised as a hypothesis to be checked and was not acted
              on, and so does a claim stated as true inside a question or request ("we have no data yet,
              so ..."). NOT a correction: a
              hypothesis explicitly raised to be checked, not acted on, and then ruled out; an error from an
              EARLIER run that was already known at the start of this run (a handoff/brief lesson).
One message may carry several contributions (e.g. a finding and an idea); list each separately. A message
that only reports status (what is being done, is ready or is complete, or already agreed work that will be
done), asks a question without
proposing a course of action, acknowledges or greets has NO contribution (return an empty list). Something
being ready or not yet ready, running, or working as expected (a check passed) is status; a measured value, a
diagnosis, or an unexpected failure and its cause is a finding. Either one is also a correction if it shows that
an earlier claim or action was wrong and meets the correction definition, including its exclusions.

For each contribution give LINKS to EARLIER messages -- a target_message_id must be a row listed ABOVE this
target in the input (a context row, or an earlier target). Never link to a later message or to the
message itself. Link types (each only from the contribution category before its arrow):
  takes_up     (decision -> the message that RAISED the idea it takes up; the earliest one you can see)
  relies_on    (decision -> a message with a finding or correction the decision relies on)
  claim        (correction -> the EARLIEST message that asserted the claim, or performed/announced the
               action, being corrected)
  catch        (correction -> the EARLIEST message that first flagged the problem, which may be a question
               or a doubt from someone else; omit if the target message is itself the first flag)
  builds_on    (finding -> the message whose data, request or earlier result it builds on)
  restates     (any category -> an earlier message that already made the SAME contribution -- the same
               proposal, the same commitment, the same result, or the same correction of the same claim --
               whether relayed, repeated, summarised, or restated with added supporting detail or evidence.
               NOT restates if the content changes: a different value, action or conclusion. The
               contribution then belongs to that earlier message.)
Give only links the text supports. If the earlier message is not in the input, give no link.

For each CORRECTION also give "change", what correcting it requires:
  belief_only   only a statement or assumption was wrong; nothing needs to be changed.
  needs_change  something must be changed: the defective thing itself (code, configuration, a mask, a
                parameter, an analysis, a plan, data written) or something built on the wrong claim, and THIS
                message does not report that change as done.
  changed_here  as needs_change, and this message itself reports the change as done.

For EACH target message, also list its FIX links -- whatever its contributions, including none:
  fix          (message -> the EARLIEST message you can see that stated a correction) this message reports,
               as DONE, the change that correction requires: code, configuration, a mask, a parameter, an
               analysis or a plan is changed, or a run is redone. A promise or a plan is not a fix; a
               different change on the same topic is not a fix. A correction whose change is reported in
               its own message gets "change": "changed_here" instead (a link cannot point to the message
               itself). A correction that needed no change (belief_only) has no fix.

OUTPUT: a JSON array with one object per TARGET message, in input order, and nothing else:
  {"message_id": "<target id>",
   "contributions": [
     {"category": "idea|decision|finding|correction",
      "statement": "<=20 words: what is proposed / decided / found / corrected",
      "disposition": "adopt|decline|defer  (decisions only, e.g. 'not yet' / 'hold' = defer; omit otherwise)",
      "change": "belief_only|needs_change|changed_here  (corrections only; omit otherwise)",
      "links": [{"link_type": "<type>", "target_message_id": "<earlier id>", "why": "<=15 words"}]}
   ],
   "fix_links": [{"target_message_id": "<earlier id>", "why": "<=15 words"}]}
Use "contributions": [] for a target with no contribution, and "fix_links": [] for one that reports no
fix. Judge only from the text; be neutral -- do not judge whether an idea, decision or fix was good.
```

**Contribution** — one thing a message does that a ledger records: proposes an idea, commits a decision,
establishes a finding, or overturns a prior claim or action (a correction). **One event per contribution**:
a message can carry several (e.g. a finding and an idea), and a message proposing two separate things
yields two ideas. Decisions carry a `disposition` (`adopt` / `decline` / `defer`); corrections a `change`
(`belief_only` / `needs_change` / `changed_here`, defined in the prompt).

**Link** — a directed edge from a later message to an **earlier** one, read as a sentence ("[later message]
takes up [earlier message]"); the sender of the later message does the action. Allowed types, and the
contribution category each may start from (enforced at ingest). A correction's links are named after the stage
of the message they point to.

| link type | from | to | meaning |
|---|---|---|---|
| `takes_up` | decision | the message that raised the idea | the decision takes up that proposal (adopt / decline / defer) |
| `relies_on` | decision | a message with a finding or correction | evidence the decision relies on |
| `claim` | correction | the earliest message that asserted the claim, or performed the action | the error being corrected (introduce) |
| `catch` | correction | the earliest message that first flagged the problem (may be a question or doubt) | who caught it (catch) |
| `builds_on` | finding | the message whose data, request or result it builds on | finding provenance |
| `restates` | any | an earlier message that already made the same contribution (relay, repeat, summary) | duplicate; collapses into the earlier one |
| `fix` | a message (no contribution needed) | the earliest message that stated a correction | the message reports, as done, the change that correction requires (fix) |

The correction message itself is the **state** stage: the `claim` and `catch` links start from it, `fix`
links end at it, and its sender is `stated_by` (no link of its own).

**Ingest rules (`p08`)**, each violation logged in `extract/p08_rejected.csv` and dropped (a bad or missing
`disposition` / `change` is blanked and logged): every target of every window must have an output object (else the
stage stops), except targets the API refused (listed in `extract/p08_refused.csv`); contribution category must be one of the
four; link type must be one of the seven and fit its contribution category (table above; `fix` is message-level); a link target must
be a row listed **before** the contribution's message in that window's input — no forward links, no
self-links, no link to a message the model was not shown. A bad `disposition` or `change` is blanked. `fix`
links follow the same target rules; whether their target holds a correction is settled after verification.

**Two passes, agreement, union.** Two independent extraction passes (same prompt, same model, staggered
windows). Per message, contributions of the same category are paired across passes greedily by word overlap
(Jaccard) of their statements, and only if the two statements share at least one content word (stop words and
words under 3 characters ignored; otherwise both stay single-pass and are verified); a paired contribution has `extracted_by = both`, an unpaired one `pass1`
or `pass2`. Each union contribution keeps the union of both passes' links, deduplicated by
(link type, target), each tagged with the pass(es) that produced it. Reproducibility
(`extract/p08_agreement.json`; `messages` = answered in at least one pass, agreement only over messages both
passes answered, with the counts `messages_answered_by_both_passes` and `messages_with_fix_links_answered_by_both`):
per message and category, presence agreement and Cohen's κ between the
passes; for paired contributions with links, the share whose link sets agree exactly and the share that
overlap; for paired corrections, agreement on `change`; per message, agreement on `fix` links (unioned per
message). Outputs: `extract/contributions.csv`, `extract/links_extracted.csv` (fix links: `link_type = fix`,
empty `contrib_key`).

> **Human-labeling note.** For human parity give the annotator the same window input and prompt. The
> per-item measure is the one `p08` uses between the two passes: per message and contribution category,
> present or absent; links are compared as (link type, target message) pairs. Event-level agreement
> additionally depends on the restates merge (§C) and needs alignment by anchor message.

## A3. Correction type

> **Scope.** The type rubrics A3 and A4
> assign a DOMAIN TYPE to events that p07–p10 have already categorised; their own wording about what a correction or
> an idea is ("a correction is a claim that was later overturned"; an idea example that reads like a finding) does
> not decide categories -- the category definitions are those of §A2 and `glossary.md`.

Verbatim from `discussion/cross_run/correction_domain/rater_prompt.md`:

```
You are a blind rater assigning a DOMAIN to each *correction* from an autonomous
X-ray-scattering campaign. A correction is a claim that was later overturned. You are given ONLY the
short claim text — you do NOT know who made the claim or who caught it, and you must not guess.
Judge the DOMAIN of the claim's content, nothing else.

Assign exactly one label per item:

- **operational** — about the SYSTEM, not the science: infrastructure, running processes, files,
  directories, configuration/permissions, tooling, bookkeeping, what is or isn't running.
  e.g. "the bridge watcher is still running"; "raw data lives in folder 0_btd"; "writer-cog already
  has a snapshot cron".

- **methodological** — about HOW to measure, analyze, or configure the experiment or the optimizer:
  procedure, analysis parameters, algorithm behavior, acquisition/scan settings, experimental design.
  e.g. "the no_improve patience counter is still meaningful under radical_gradient"; "the p08 window
  must be a hard <=0.0015 half-width gate"; "min step 0.01 mm gives 0.01 mm placement"; "the variogram
  is the right tool for this".

- **scientific** — about the PHYSICS or interpretation of the sample/data itself: peak assignment,
  lattice/morphology interpretation, geometry/calibration values, what the scattering means.
  e.g. "p04 and p08 are the 2nd/4th harmonics of one 29.5 nm lamellar lattice"; "the 2-fold/6-fold
  m-index may be mis-assigned"; "MAXS SDD ~ 0.159 m".

- **other** — genuinely does not fit the three above, or too vague to tell.

Boundary guidance:
- "How to run/tune the analysis or optimizer" = methodological. "What the physics IS" = scientific.
- A specific numeric value that is a CALIBRATION/geometry/physics quantity = scientific; a value that
  is a config/path/system setting = operational.
- When a claim mixes layers, pick the one the correction is really ABOUT.

Read every item in items.jsonl (one JSON object per line: {id, run, claim}). Output a CSV
with a header row `id,domain,confidence` — one row per item, domain in
{operational, methodological, scientific, other}, confidence in [0,1]. Write it to the output path
you are given. Do not output anything else.
```

**Pipeline (`p11` → `p11b` → `p11c`).** The rubric above is used VERBATIM up to and
including its boundary guidance; its final paragraph (write a CSV to a path) is replaced by this input/output
paragraph for `llm.py`:

```
INPUT: one JSON object per line, {id, claim}. The claim text is a one-line statement of the
correction: what had been asserted and how it was overturned. Judge the DOMAIN of the claim it is about.

OUTPUT: a JSON array with one object per input line, in input order, and nothing else:
  {"id": "<id>", "type": "operational|methodological|scientific|other", "confidence": 0.0-1.0}
```

For corrections the item text is the correction's one-line statement (the message-first ledger keeps no
separate claim summary); it states what had been asserted and how it was overturned.
Two independent blind raters (same prompt, separate calls; statement text only, keyed by `event_key`) label
every correction. Where they differ, a THIRD blind rater gets the same prompt and input and is not shown their
labels; its label is final. Output:
`ledger/types.csv` (`type`, `label_source` = agreed | adjudicated, all three raters' labels, model/settings).

## A4. Idea type

Verbatim from `discussion/cross_run/idea_type/rater_prompt.md` (same four types as A3, for
cross-ledger comparability; blind to originator):

```
You are a blind rater assigning a TYPE to each IDEA (a proposal) from an autonomous
X-ray-scattering campaign. You are given ONLY the short idea text — you do NOT know who proposed it,
and you must not guess. Judge the TYPE of the idea's content, nothing else. Use the SAME four types
used for corrections, so ideas and corrections are comparable.

Assign exactly one label per item:

- **operational** — about the SYSTEM, not the science: infrastructure, running processes, files,
  directories, configuration/permissions, tooling, logging, orchestration, bookkeeping.
  e.g. "spawn a second analysis daemon"; "log each step to an isolated file"; "add a manual
  injection-points hook"; "put session-log date headers in".

- **methodological** — about HOW to measure, analyze, or configure the experiment or the optimizer:
  procedure, analysis parameters, algorithm behavior, acquisition/scan settings, experimental design,
  or an investigation/plot/quantification to run.
  e.g. "use standardized-joint intensity weighting"; "add a ring-presence gate"; "min step 0.01 mm";
  "rebalance the acquisition exponent"; "quantify the 2-fold/6-fold wall co-location".

- **scientific** — about the PHYSICS or interpretation of the sample/data itself: what to measure
  scientifically, peak/lattice/morphology interpretation, geometry/calibration values.
  e.g. "measure the hex-vs-lamellar fraction across the ROI"; "the sharp WAXS peak is CeO2(111)";
  "check the seq138 director value".

- **other** — genuinely does not fit the three above, or too vague to tell.

Boundary guidance:
- "How to run/tune the analysis or optimizer, or an analysis/plot to produce" = methodological.
  "What the physics IS / what to conclude about the sample" = scientific.
- A numeric value that is a CALIBRATION/geometry/physics quantity = scientific; a value that is a
  config/path/system setting = operational.
- When an idea mixes layers, pick the one the idea is really ABOUT.

Read every item in items.jsonl (one JSON object per line: {id, run, idea}). Output a CSV with a
header row `id,type,confidence` — one row per item, type in
{operational, methodological, scientific, other}, confidence in [0,1]. Write it to the output path
you are given. Do not output anything else.
```

**Pipeline (`p11` → `p11b` → `p11c`).** The rubric above is used VERBATIM up to and
including its boundary guidance; its final paragraph (write a CSV to a path) is replaced by this input/output
paragraph for `llm.py`:

```
INPUT: one JSON object per line, {id, idea}.

OUTPUT: a JSON array with one object per input line, in input order, and nothing else:
  {"id": "<id>", "type": "operational|methodological|scientific|other", "confidence": 0.0-1.0}
```

Implicit ideas (created from a decision's `takes_up` link) are typed too.
Two independent blind raters (same prompt, separate calls; statement text only, keyed by `event_key`) label
every idea. Where they differ, a THIRD blind rater gets the same prompt and input and is not shown their
labels; its label is final. Output:
`ledger/types.csv` (`type`, `label_source` = agreed | adjudicated, all three raters' labels, model/settings).

## A4b. Decision and finding type

`p11` also types every decision and every finding, with the SAME four
types and the same raters / third-rater rule as A3/A4. The rubric is the A4 idea rubric with only its subject
sentence and examples adapted. Decision rubric:

```
You are a blind rater assigning a TYPE to each DECISION (a commitment to, or a decision to defer
or decline, a course of action) from an autonomous X-ray-scattering campaign. You are given ONLY the short
decision text — you do NOT know who decided it, and you must not guess. Judge the TYPE of the action
decided on, nothing else. Use the SAME four types used for corrections and ideas, so all events are
comparable.

Assign exactly one label per item:

- **operational** — about the SYSTEM, not the science: infrastructure, running processes, files,
  directories, configuration/permissions, tooling, logging, orchestration, bookkeeping.
  e.g. "relaunch the analysis daemon as a background task"; "keep one authoritative transcript archive";
  "drop the separate backfill CSV task".

- **methodological** — about HOW to measure, analyze, or configure the experiment or the optimizer:
  procedure, analysis parameters, algorithm behavior, acquisition/scan settings, experimental design,
  or an investigation/plot/quantification to run.
  e.g. "adopt standardized-joint fairness"; "switch the lamellar driver from p04 to p02"; "run a
  0.067 mm grid with 0.01 mm local placement"; "no noise-model change tonight".

- **scientific** — about the PHYSICS or interpretation of the sample/data itself: what to measure
  scientifically, peak/lattice/morphology interpretation, geometry/calibration values.
  e.g. "accept q~1.876 as the WAXS peak of interest"; "treat the WAXS arc as a lamellar cross-check";
  "use 0.242 m as the WAXS SDD".

- **other** — genuinely does not fit the three above, or too vague to tell.

Boundary guidance:
- "How to run/tune the analysis or optimizer, or an analysis/plot to produce" = methodological.
  "What the physics IS / what to conclude about the sample" = scientific.
- A numeric value that is a CALIBRATION/geometry/physics quantity = scientific; a value that is a
  config/path/system setting = operational.
- When a decision mixes layers, pick the one the decision is really ABOUT.

INPUT: one JSON object per line, {id, decision}.

OUTPUT: a JSON array with one object per input line, in input order, and nothing else:
  {"id": "<id>", "type": "operational|methodological|scientific|other", "confidence": 0.0-1.0}
```

Finding rubric:

```
You are a blind rater assigning a TYPE to each FINDING (a result: a measured value, verdict,
diagnosis or observation) from an autonomous X-ray-scattering campaign. You are given ONLY the short
finding text — you do NOT know who established it, and you must not guess. Judge the TYPE of the
finding's content, nothing else. Use the SAME four types used for corrections and ideas, so all events
are comparable.

Assign exactly one label per item:

- **operational** — about the SYSTEM, not the science: infrastructure, running processes, files,
  directories, configuration/permissions, tooling, logging, orchestration, bookkeeping.
  e.g. "all four daemons exited unexpectedly mid-run"; "the op_log has 88 ok rows"; "the daemon crashed:
  out of memory".

- **methodological** — about HOW to measure, analyze, or configure the experiment or the optimizer:
  procedure, analysis parameters, algorithm behavior, acquisition/scan settings, experimental design,
  or the outcome of an investigation/plot/quantification of the method.
  e.g. "the variance term, not the gradient, decides the picks"; "the fit-sigma noise model passes the
  gate with b >= 0"; "a 0.01 mm min step only widens a filter".

- **scientific** — about the PHYSICS or interpretation of the sample/data itself: peak/lattice/morphology
  interpretation, geometry/calibration values, what the scattering means.
  e.g. "p04 and p08 are harmonics of one 29.5 nm lamellar lattice"; "seq 597 contains lamellar";
  "WAXS SDD 0.3334 m".

- **other** — genuinely does not fit the three above, or too vague to tell.

Boundary guidance:
- A result about how the analysis or optimizer BEHAVES = methodological. "What the physics IS / what to
  conclude about the sample" = scientific.
- A numeric value that is a CALIBRATION/geometry/physics quantity = scientific; a value that is a
  config/path/system setting = operational.
- When a finding mixes layers, pick the one the finding is really ABOUT.

INPUT: one JSON object per line, {id, finding}.

OUTPUT: a JSON array with one object per input line, in input order, and nothing else:
  {"id": "<id>", "type": "operational|methodological|scientific|other", "confidence": 0.0-1.0}
```

## A5. Coordination type

Verbatim from `discussion/cross_run/status_type/rater_prompt.md`. Applied to the coordination messages
(final intent = `status` or `other`). Blind to sender.

```
You are a blind rater assigning a COORDINATION TYPE to each MESSAGE from an autonomous
X-ray-scattering campaign run by a team of AI agents (an orchestrator called team-lead, plus operator,
analysis, gp, writer cogs) and a human. These are the run's COORDINATION messages (status updates and
miscellaneous traffic), NOT the substantive science. You are given ONLY the message text — you do NOT
know who sent it, and you must not guess. Judge what the message IS DOING, nothing else.

The goal is to separate coordination that a PROGRAM could have produced from coordination that needed a
mind. Assign exactly one label per item:

- **mechanical** — a relay / bookkeeping statement of a SYSTEM FACT that could be emitted
  deterministically from flag files and logs, with NO interpretation: a daemon started/stopped/relaunched,
  a file or flag was written/read/seen, an iteration/step completed, a count/path/parameter is echoed,
  "cog X finished", "wrote Y", "log at Z", "TRIGGER written", "seq 123 done".
  The message only REPORTS state a machine already knows.

- **synthesis** — interpretation, judgment, or summarization that required READING and REASONING about
  content: digesting a result into what it MEANS, assessing whether something is normal / anomalous / a
  stall, diagnosing a problem, deciding or recommending a next step, weighing options, or summarizing
  "where are we / what happened so far". This is the value-add a program could not produce from logs.
  e.g. "the variance is flat so the noise cap won't help"; "iter 11 looks converged, hold"; "this log
  froze but mtime is recent, likely still running"; "recommend recentering the box".

- **procedural** — conversational / acknowledgement glue with NO system fact and NO judgment: "ok",
  "will do", "starting now", "on it", "thanks", "got it", greetings, or a bare confirmation that carries
  no state and no reasoning. Trimmable over-narration.

- **other** — genuinely does not fit the three above, or too vague to tell.

Boundary guidance:
- Only STATES a system fact a program could log -> mechanical. INTERPRETS / EVALUATES / DECIDES /
  SUMMARIZES content -> synthesis. Pure acknowledgement / social with no fact and no judgment -> procedural.
- A message that relays a fact AND interprets it -> synthesis (the interpretation is the point).
- A short confirmation that also carries a real state fact ("done, ana_log has 42 rows") -> mechanical,
  not procedural.
- When mixed, pick what the message is really FOR.

Read every item in items.jsonl (one JSON object per line: {n, id, run, text}). Output a CSV with a
header row `n,type,confidence` — EXACTLY one row per item, keyed by the item's integer `n` (copy it
verbatim), type in {mechanical, synthesis, procedural, other}, confidence in [0,1]. You must rate ALL
items (check the final n matches the line count). Write it to the output path you are given. Do not
output anything else.
```

> **A3–A5** are stages p11 (A3, A4, A4b: every event of the four ledgers, item
> text = the event's statement) and p12 (A5: every message whose final intent is `status` or `other`).

**Pipeline (`p12` → `p12b` → `p12c`).** Applied to every message whose final intent
(`05_labels.csv`) is `status` or `other`. The rubric above is used VERBATIM up to and including its boundary
guidance; its final paragraph (CSV keyed by `n`) is replaced by this input/output paragraph for `llm.py`:

```
INPUT: one JSON object per line, {id, text}: the full message text.

OUTPUT: a JSON array with one object per input line, in input order, and nothing else:
  {"id": "<id>", "type": "mechanical|synthesis|procedural|other", "confidence": 0.0-1.0}
```

The rater sees the FULL message text (cap 8000 characters). Two independent blind raters (same prompt, separate calls), a third blind rater on their
disagreements (raters' labels not shown) whose label is final; the sender is attached after rating. Output:
`12_coordination.csv` (`type`, `label_source`, all three raters' labels, model/settings).

## A6. Threads (replaces causal-chain linking)

**Deterministic; no LLM.** `ledger/threads.csv` holds the connected components of events over the links
that count (§C): verified (or, for `builds_on`, found by both passes), from an accepted contribution,
and landing on an event at the target message — of the type the link expects (`takes_up` → idea,
`relies_on` → finding or correction, `builds_on` → finding), or any event for `claim` and `catch`.
`fix` links (message-level, no source event) and `restates` links are not used here — the latter
they have already merged their ends into one event. Every event belongs to exactly one thread; an event
with no counted link is a thread of one. Columns: `thread_id` (`T001`, … by first event time),
`n_events`, `event_ids`, `categories`, `first_ts`, `last_ts`. There is no granularity bias and nothing to
verify beyond the links themselves.

---

# PART B — Verification schemes

Both verifiers judge **from the evidence alone**, are **blind to extraction support** (how many passes
produced the item), and see **UTC timestamps and senders**. Items come in chunks of 16 (`VERIFY_CHUNK`);
messages are shown in full (the antecedent, context only, is cut at 4,000 characters). **Three independent verifiers** (same prompt, same model,
separate calls) judge every item. **Accept rule: at least 2 of the 3 verifiers vote `real`** — a majority of
the verifiers there should be, so an item with a missing or refused vote needs both remaining votes. Confidence is
"confidence in the verdict" — a confident rejection is high-confidence — so it is reported (`mean_conf`)
and never used as the accept rule. An item with fewer verdicts than verifiers is listed in
`ledger/p10_checks.csv`. Output per item: `{item_id, real, confidence, reason}`, plus `change` on correction items.

## B1. Contribution verification

- **Which contributions** (`p09`): every contribution only one extraction pass found
  (`extracted_by ≠ both`), and every correction, whichever pass found it (its check decides acceptance when
  no `claim` link is verified, e.g. a defect written in code; it also gives the correction's `change`).
- **What the model is shown:** `{item_id, category, statement, message, antecedent}` — `message` with
  `message_id, ts, sender, recipient, text`; `antecedent` = the previous message between the same two
  participants, for context; for a correction with a `claim` link also `claimed_message` (the earliest
  claim target), to judge `change`.
- **Prompt** (`verify/p09_contrib_prompt.md`, verbatim):

```
You are an INDEPENDENT verifier of contributions in messages exchanged between a human scientist
and AI agents running a scientific experiment. Each item names a MESSAGE (with the previous message between the
same two participants, for context) and a proposed contribution of that message: a category and a one-line statement.

Contribution categories:
  idea        proposes a course of action, approach or change that is not yet decided.
  decision    commits to, authorises, defers or declines a course of action already on the table. An
              instruction that FIRST raises an action (no earlier message proposed, suggested or offered it)
              and commits to it is both an idea and a decision; one that takes up an earlier proposal is a
              decision only.
              Passing on or re-issuing a decision already made restates that decision; reporting that a
              decided action has been done is status, not a decision; committing to an action for the first
              time is a decision.
  finding     establishes a concrete result (a value, verdict, diagnosis or observation) in this message;
              forwarding a result someone else established restates that finding. Something being ready or
              not yet ready, running, or working as expected (a check passed) is status, not a finding; a
              measured value, a diagnosis, or an unexpected failure and its cause is a finding. Either one is
              also a correction if it shows that an earlier claim or action was wrong and meets the
              correction definition, including its exclusions.
  correction  overturns, retracts or fixes something earlier: a claim or action that was ASSERTED (stated as
              true, or acted on) and is now shown wrong. Code or configuration written with a defect counts
              as an asserted action. An expectation or prediction stated as the expected outcome, or used to
              plan or justify an action, counts as an assertion, unless it was explicitly raised as a
              hypothesis to be checked and was not acted on, and so does a claim stated as true inside a
              question or request. NOT a correction: a hypothesis explicitly
              raised to be checked, not acted on, and then ruled out; an error from an EARLIER run already known at the
              start of this run (a handoff or brief lesson).

A contribution that restates an earlier one (relayed, repeated, summarised, or passed on to another agent) is
still made by this message: judge it real if the message makes it. Whether it was made first here is decided
separately (restates links), not by you.

For each item decide:
  real (1/0): does the MESSAGE itself make this contribution, as defined above?
  confidence (0.0-1.0): your confidence in that verdict.
  reason: <=25 words citing the deciding words.
For a CORRECTION item (it may also show the claimed message, the earlier message it corrects) also give
  change: what correcting it requires --
    belief_only   only a statement or assumption was wrong; nothing needs to be changed.
    needs_change  something must be changed: the defective thing itself (code, configuration, a mask, a
                  parameter, an analysis, a plan, data written) or something built on the wrong claim, and
                  the MESSAGE does not report that change as done.
    changed_here  as needs_change, and the MESSAGE itself reports the change as done.
  Omit change when real is 0.
Judge only from the text. Be neutral: do not judge whether an idea, decision or fix was good.

OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "confidence": <a number 0.0-1.0>, "reason": "<=25 words",
   "change": "belief_only|needs_change|changed_here  (correction items only; omit otherwise)"}
```

## B2. Link verification

- **Which links** (`p09`): every extracted link of type `takes_up`, `relies_on`, `claim`, `catch`, `fix`
  or `restates`, one item per (source contribution, link type, target message) -- two contributions of one
  message with the same link are checked separately, each with its own statement. `builds_on` is
  provenance only and is not verified; it counts when both passes found it. A `fix` link whose target
  message carries no extracted correction is not packaged (nothing to fix there).
- **What the model is shown:** `{item_id, link_type, source_contribution {category, statement}, source,
  target}` — `source` and `target` each with `message_id, ts, sender, recipient, text`. A `fix` link gives one
  item per correction extracted at its target message (`F|…`, with `target_correction` instead of
  `source_contribution`), so a fix is credited only to the correction it was verified for (about 20% of
  corrections share their message with another).
- **Target candidates.** A `takes_up`, `relies_on` or `restates` item lists `target_candidates` when the target
  message has extracted contributions of the needed category (numbered); the verifiers also name the one the
  source takes up, relies on or restates (`target`, 0 = none of them). p10 resolves the link to the candidate at
  least 2 of the 3 verifiers name (`verify/p09_target_candidates.json` maps the numbers). If they name none: a
  `takes_up` / `restates` link goes to a separate implicit contribution (never reused by word overlap), a
  `relies_on` link stays message-level (counted, no event, no thread). Only if they disagree, by word overlap
  (listed in `ledger/p10_checks.csv`). A verifier answer that judges such a link real but gives no valid `target`
  (missing, null, not a number 0..N) is not an answer: `llm.py` asks for it again (job field `required`), and p10
  stops if one reaches it, so a missing choice is never read as a disagreement. p10 also checks that every
  verifier was shown exactly the map's numbered candidates (number, category, statement).
  Without this, a verified link would say only that the target MESSAGE raised the proposal.
- **Same-message items** (`S|…`, link type `takes_up`, `same_message: true`): every (decision, idea) pair
  extracted in one message, with `target_idea`; source and target are that message. They verify the
  same-message idea + decision pairing (§C rule 3).
- **Prompt** (`verify/p09_link_prompt.md`, verbatim):

```
You are an INDEPENDENT verifier of links between messages exchanged between a human scientist
and AI agents running a scientific experiment. Each item proposes that a contribution in a SOURCE message is
linked to an EARLIER TARGET message (or, for a same-message item, to an idea in the same message). You see
both messages in full, with UTC timestamps and senders.

Contribution categories:
  idea        proposes a course of action, approach or change that is not yet decided.
  decision    commits to, authorises, defers or declines a course of action already on the table. An
              instruction that FIRST raises an action (no earlier message proposed, suggested or offered it)
              and commits to it is both an idea and a decision; one that takes up an earlier proposal is a
              decision only.
              Passing on or re-issuing a decision already made restates that decision; reporting that a
              decided action has been done is status, not a decision; committing to an action for the first
              time is a decision.
  finding     establishes a concrete result (a value, verdict, diagnosis or observation) in this message;
              forwarding a result someone else established restates that finding. Something being ready or
              not yet ready, running, or working as expected (a check passed) is status, not a finding; a
              measured value, a diagnosis, or an unexpected failure and its cause is a finding. Either one is
              also a correction if it shows that an earlier claim or action was wrong and meets the
              correction definition, including its exclusions.
  correction  overturns, retracts or fixes something earlier: a claim or action that was ASSERTED (stated as
              true, or acted on) and is now shown wrong. Code or configuration written with a defect counts
              as an asserted action. An expectation or prediction stated as the expected outcome, or used to
              plan or justify an action, counts as an assertion, unless it was explicitly raised as a
              hypothesis to be checked and was not acted on, and so does a claim stated as true inside a
              question or request. NOT a correction: a hypothesis explicitly
              raised to be checked, not acted on, and then ruled out; an error from an EARLIER run already known at the
              start of this run (a handoff or brief lesson).

Link types -- the claim to verify:
  takes_up     the source DECISION takes up (adopts, declines or defers) the SAME concrete proposal that the
               target message raised. Not just the same topic; not a follow-up that implements or details a
               decision taken earlier.
  relies_on    the source DECISION relies on a finding or correction stated in the target message.
  claim        the source CORRECTION overturns a claim or action that the target message ASSERTED (stated as
               true, or acted on), per the correction definition above.
  catch        the target message is where the problem that the source CORRECTION resolves was FIRST
               flagged -- possibly as a question or doubt -- before the source message.
  restates     the source message makes the SAME contribution the target message already made -- the same
               proposal, commitment, result, or correction of the same claim -- whether relayed, repeated,
               summarised, or restated with added supporting detail or evidence. NOT restates if the content
               changes: a different value, action or conclusion.
  fix          the source message reports, as DONE, the change that the correction stated in the target
               message requires: code, configuration, a mask, a parameter, an analysis or a plan is changed,
               or a run is redone. Not a promise or a plan; not a different change on the same topic; a
               correction that needed no change (only a belief was wrong) has no fix. A fix
               item has no source contribution; it names ONE correction stated in the target message
               (target_correction): judge the fix against that correction only.

A takes_up item can have the SAME message as source and target (same_message: true; extraction never links a
message to itself, these items check the idea + decision of one message). It then names one idea of that
message (target_idea): judge whether the source decision commits to that idea -- an instruction that first
raises an action and commits to it -- rather than to something else in the message.

Several link types ask for the EARLIEST or FIRST message. You see only these two messages, so you cannot tell
whether an even earlier one exists: judge whether the target is a valid target as defined (it raised the
proposal, asserted the claim, first flagged the problem as far as these two messages show, stated the
correction); finding the earliest is the extractor's task.

A takes_up, relies_on or restates item may list target_candidates: the contributions of the needed category
extracted from the target message, numbered. Then also give "target": the number of the candidate the source
takes up, relies on or restates, or 0 if it is none of them (the target message raised it, but it is not among
the candidates). Omit target when real is 0.

For each item decide:
  real (1/0): does the evidence support the link exactly as defined?
  confidence (0.0-1.0): your confidence in that verdict.
  reason: <=25 words citing the deciding words.
Judge only from the two messages. Be neutral: do not judge whether a decision, idea or fix was good.

OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "confidence": <a number 0.0-1.0>, "reason": "<=25 words",
   "target": <number; only for items with target_candidates>}
```

## Accept rules (`p10`)

| what | accepted when | `accepted_via` |
|---|---|---|
| a link (`takes_up`, `relies_on`, `claim`, `catch`, `fix`, `restates`) | majority `real` | — (`links.csv → verified`) |
| a `builds_on` link | found by both passes | — |
| a correction | at least one of its `claim` links is verified; otherwise (no `claim` link, or all rejected — the claim is not in the corpus, or the extractor pointed at the wrong message) its contribution check passes. Every correction gets a contribution check. | `claim_verified` / `{no_claim,claim_rejected}_contribution_check_{passed,failed,missing}` |
| a correction's `change` | both passes found the correction and agree; else the value given by at least 2 of the verifiers who judged the correction `real`; else the extraction's value | `change_via` = `both_passes` / `verifiers` / `extraction` |
| any other contribution | found by both passes, or its contribution check passes | `both_passes` / `contribution_check_*` |

A link **counts** (`links.csv → counted = 1`) when it is accepted and its source contribution is accepted;
a `fix` item counts when it is accepted, its correction is accepted, and the correction's final `change` is not
`belief_only` (credited to that correction only). Only counted links set roles, merge events or join threads.

**Attribution.** `introduced_verified = 1` on a correction when its claim is grounded by a verified
`claim` link; only then are `introduced_message_id`, `introduced_by` and `self_or_other` filled. **Per-role
correction results (who erred, self vs cross-agent) use only `introduced_verified = 1` rows.** `caught_by` is
filled on every correction: the sender of the earliest verified `catch` target, else the correction's own
sender. `stated_by` is always the correction's own sender; `fixed_by` is filled when a fix is recorded: the
sender of the message reporting the fix as done (a relayed report of someone else's fix credits the relayer
unless the original report is the earliest one linked).

---

# PART C — How labels combine, and how human agreement is measured

**Message intent (A1).** Final label = the two blind raters' primary when equal (`agreed`), else the
adjudicator's pick among the labels the raters gave (`adjudicated`); an out-of-set pick is rejected
(`adjudication_rejected`, no final label). The **headline reproducibility number is κ(3,4)** on primary
(blind, diverse prompts). Sentence type = the two raters' agreement, else blank. Intent results use the
final primary only.

**Ledger candidates (input to A2).** The union of every rater label (primary, secondary, tertiary) of
both raters, so a message carrying two or three distinct intents seeds every matching ledger.

**Extraction (A2).** Two passes → union; per-message presence κ and link agreement measure
reproducibility; the union goes to verification.

**Verification (B1–B2).** Three verifiers → majority `real`; accept rules in the table above. Precision
comes from the verifiers, recall from the candidate union and the extraction union; this is distinct from
rater agreement.

**Events (`p10`).**
1. *Merge.* A counted `restates` link merges a contribution into the earlier contribution of the same category
   at the target message that the verifiers named (§B2, target candidates); the earliest message of the merged group is the event's **anchor**, and the
   other senders in the group are recorded as `relayed_by`. A relay of the human's idea stays the human's
   idea.
2. *Implicit events.* A counted `takes_up` or `restates` link whose target contribution is not in the ledger --
   the verifiers named none of the extracted candidates, or named one that was not accepted, or nothing of that
   category was extracted there -- creates an implicit contribution at the target message (the proposal was made
   but not extracted or not accepted as one; §B2). An event whose first message is such a created contribution has `origin = implicit`.
3. *Same-message idea + decision.* An instruction that first raises an action is an idea and a decision of
   the same message. A decision with no counted `takes_up` link is paired with an accepted idea in its own
   message whose same-message item is verified (§B2; the best-matching one if several); `links.csv` records the
   pair as `takes_up` with `extracted_by = same_message`, `dt_min = 0`. A decision with no verified
   same-message idea is not paired. A decision that `restates` an earlier one is not paired: it
   relays a commitment made before, so an idea in the relaying message (e.g. team-lead's own plan next to the
   human's go-ahead) was not taken up by it.
4. *Roles and times, read off the messages:*

| ledger | role column(s) | read from |
|---|---|---|
| ideas | `proposed_by`, `proposed_ts` | sender and ts of the anchor; `taken_up_by` = decisions with a counted `takes_up` link to it; `outcome` = `taken_up` / `not_taken_up` |
| decisions | `decided_by`, `decided_ts`, `disposition` | sender and ts of the anchor; most common disposition in the group; `takes_up_ideas`, `relies_on_{events,messages,senders}` from counted links |
| findings | `established_by`, `established_ts` | sender and ts of the anchor; `builds_on_messages` from counted links |
| corrections | `introduced_message_id`, `introduced_ts`, `introduced_by` | the earliest verified `claim` target (introduce) |
| | `caught_message_id`, `caught_ts`, `caught_by` | the earliest verified `catch` target, else the correction's anchor — whoever first raised the problem, even as a question or doubt (catch) |
| | `stated_message_id`, `stated_ts`, `stated_by` | the anchor: the correction message itself (state) |
| | `fixed_message_id`, `fixed_ts`, `fixed_by` | the earliest of: a counted `fix` item for this correction (its source message), or a member message whose `change` is `changed_here` (fix) |
| | `change` | `belief_only` / `needs_change` (`changed_here` counts as `needs_change`): the anchor's value (else the first member's); `change_via` as in §B |
| | `fix_status` | `fixed` (a fix recorded) / `not needed` (`belief_only`) / `not seen` (`needs_change`, no fix recorded). A fix recorded for a `belief_only` correction is not credited and is listed in `ledger/p10_checks.csv` |
| | `self_or_other` | `self` if `introduced_by = caught_by`, else `other`; blank without a verified `claim` link |

   All times are message timestamps (UTC). Links only point to earlier messages, so no decision can
   precede the idea it takes up.
5. *Ids.* Chronological per type (`ide_001` = earliest idea; `dec_`, `fin_`, `cor_`), plus a stable
   `event_key` (`category:anchor_message_id:n`) for joins across re-runs of p10 on the same extraction. `evidence_uuid` lists the member
   messages and the targets of counted links.

**Threads (A6).** Connected components over counted non-`restates` links between events.

**Type schemes (A3–A5).** Two blind raters label every item; a third blind adjudicator resolves only the
disagreements; agreement reported as Cohen's κ. Coordination labels are combined by majority over the three raters
(3-way splits excluded).

**Recall.** Missed events are guarded against by **candidate recall** — the primary ∪ secondary ∪ tertiary
union above — distinct from the precision gates above. No separate correction-recall estimate is made for the
published ledgers.

**Human validation protocol (this codebook's purpose).** Two domain experts each independently label a
**small stratified subset per task** (sized so every label — and known edge cases — appears; not a full
census). Each expert receives the **same prompt** shown above. We then report **human↔LLM Cohen's κ**
(agreement of each expert with the pipeline's final label) and **human↔human Cohen's κ**. A **two-phase**
capture (app: `audit_src/app/label_app.py`): (1) **blind label** the sample, then (2) **adjudicate** only
the human≠LLM items with both answers revealed, giving a conclusive per-item gold — so
`score.py` reports LLM **accuracy** on the representative stratum with a Wilson 95% CI, not just κ.

**Context provided to the human (deliberate deviation from strict parity).** For the `intent` step the
human is shown **±3 surrounding messages** (a context expander) in *both* phases — more than the LLM saw
(the LLM had only target + antecedent, §A1). This is an intentional choice: it makes the human a
**fuller-context reference**, so the reported number measures *whether the LLM's label is CORRECT* rather
than *same-input reproducibility*. Consequence to state in the paper: human↔LLM agreement/accuracy here is
"human-with-context vs LLM-with-antecedent," a correctness check, not a matched-input κ; it may also
partially reveal the target's sender via the surrounding turns (the LLM was sender-blind). The **coverage**
(sampled / total, e.g. `coverage.csv`) is surfaced in the app and should be quoted alongside each result.

**Message-level idea+decision collapse (intent scoring only).** At the MESSAGE level `idea` and `decision`
are treated as one act for human-vs-LLM agreement/adjudication — a single message frequently proposes AND
commits, and the two are the dominant, low-agreement boundary. `question` stays
separate. This is a **reporting collapse only**: the 7-intent instrument (§A1) and the ledgers are
unchanged, so the event-level "who proposes vs who decides" result (read off the senders of the idea's
anchor and of the decision that takes it up via a verified `takes_up` link, §C) is unaffected. `score.py`
reports the collapsed κ/overlap as the headline for `intent` and prints the raw 7-cat alongside for
reference.

---


---

# PART D — The settlement layer (wordings in PART E)

Each prompt below is **wording w1**, rendered from the code. The decision rules are hand-written summaries of the
code (function named in each), checked against it by reading, not generated from it:
- **D1 C3** (`p09c_target.py`, `decide_T`): three stored states per multi-target item. `rejected`: fewer than
  `need` (2) of 3 `real` votes -- the link is not counted. `accepted`: each candidate named by at least 2 real voters is
  its own accepted pair; if instead at least 2 real voters name NONE of the candidates, the item is `accepted` with no
  pair (the target message raised it, but it is none of the candidates) -- nothing is linked. `no_target_majority`:
  real, but neither a candidate nor "none" reaches 2 -- not counted, listed. A restates pair also needs a majority
  subtype (identity / part), else it is unresolved. Same-message pairs and implicit fixes: accepted on 2 of 3 `real`.
- **D2 C4** (`p10s_settle.py ingest`): the two passes only PROPOSE claims (union); nothing is counted until C6.
- **D3 Referral** (`p10x_referral.py`, `resolve`): a settling message with no extracted decision, or an idea a
  backward search found in a shown message but not among the events: rejected with
  fewer than 2 of 3 `exists`; else identity `same:<n>` named by 2 reuses nearby event n, `new` named by 2 makes a new
  event, anything else is `unclear` (its claims rejected). For a DECISION candidate (the prompt asks for `targets` for
  decision items only), each pending claim also needs its own target named by 2; an idea candidate has no target
  question.
  Then one replay of C4 for the new events.
- **D4 C6** (`v5verify.decide`): settles -- at least 2 of 3 verifiers `real` AND naming the claim's outcome and
  scope exactly (if 2 agree on another outcome / scope, that claim is accepted instead); reverses / other /
  assessment -- 2 of 3 `real`; implements / results -- 2 of 3 `real` with kind `direct`. Incompatible accepted
  claims become a conflict, adjudicated (D5: a claim named by 2 of 3 adjudicators is kept and the others rejected; otherwise all are
  `unresolved` and reported).
- **Counting** (`p10g_materialize.py`): a claim counts when its state is accepted / counted, it passes the relation
  table and time rules (`v5lib.check_claim`), both endpoints exist, and it is not superseded, invalidated, in conflict
  or unresolved. An idea is decided by a counted `settles` claim whose outcome is an UPTAKE (adopted, deferred,
  declined, declined_by_alternative, unspecified; any scope); `authorized_to_investigate` is its own column, never
  uptake. A correction is repaired by a counted claim with a REPAIR outcome (repaired, partially_repaired, workaround,
  unspecified). The first decider / repairer is the sender of the source message of the EARLIEST such claim (by source
  time). PART D's counted claims supersede the first-pass attribution of PART C wherever both exist.

## D1. C3 target resolution (3 verifiers)
```
You are an INDEPENDENT verifier of links between messages exchanged between a human scientist and AI
agents running a scientific experiment. You see the messages in full, with UTC timestamps and senders.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Items:
  kind=multi_target  The SOURCE contribution is linked (link_type) to the TARGET message, which holds several
      numbered candidate contributions. Name EVERY candidate the source acts on as that link type defines:
        takes_up   the source decision adopts, declines or defers that same concrete proposal.
        relies_on  the source decision relies on that finding or correction.
        restates   the source makes that same contribution again.
      Give "targets": a list of candidate numbers (empty list if none). For restates also give "parts": an object
      with one entry per named candidate number, "identity" (the source makes the same contribution) or "part"
      (the source restates only part of it, or bundles it with other contributions).
  kind=same_message  One message holds a decision and an idea. Does the decision commit to the named idea --
      an instruction that first raises an action and commits to it -- rather than to something else in the message?
      The antecedent is the message where that idea was first raised (it may be this message).
  kind=fix_implicit  Does the SOURCE report, as DONE, the change that the named correction (target_correction, at
      the TARGET message) requires? Judge this correction only. Not a promise or a plan; not a different change on
      the same topic.

For each item decide real (1/0), confidence (0.0-1.0), reason (<=25 words quoting the deciding words); for
multi_target items also "targets" (and "parts" for restates). Be neutral.
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "targets": [1, 2], "parts": {"1": "identity"}, "confidence": 0.0, "reason": "..."}
```

## D2. C4 settlement search (2 passes)
```
You search a conversation between a human scientist and AI agents running a scientific experiment for
what happened to an earlier proposal or correction. Timestamps are UTC.
File changes (`file_changes`) state their `quality`: exact = the whole new file content; hunk = only the changed text
(old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key diff /
paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Items:
  kind=settle_forward   TARGET is an idea or correction with no settlement found so far. List every shown message
      (or file change) that SETTLES it, with the outcome and scope. The target's own messages and, for a correction,
      the messages between its catch and its statement are shown too: a repair can be reported there. Also list
      messages that only RELAY someone else's settlement (relays), carry out an already-decided action (implements),
      or do a similar thing independently (independent_action) -- recorded, not counted as settlements. If the cited
      message holds more than one decision (see `decisions_at_messages`), name which one in "decision".
  kind=lifecycle        TARGET already has the settlements listed under `known_settlements` (each with a claim id).
      List every LATER shown message (or file change) that changes one of them: reverses it (relation reverses, and
      name the reversed settlement in "reverses"), declines or defers it after adoption, re-adopts it, or repairs it
      again (relation settles).
  kind=settle_backward  SOURCE is a decision. List every idea in `ideas_before` (by its id) that this decision
      settles, with the outcome and scope. If the decision settles an idea that is NOT in the list but is raised in
      one of the shown messages, add it under "new_ideas" with that message id, a one-line statement, and the
      outcome and scope of this decision on it.
Every claim gets a local "id" (n1, n2, ...). A reversal of a settlement you list in the same answer names its local
id in "reverses". When the target lists `inventory` components, give the scope as component:<id> using those ids.
Cite only message ids, artifact ids, idea ids and claim ids that are shown in the item. Quote the deciding words
(<=30 words). Set "searched_all" to true only if you read every shown message for this question.

OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "searched_all": true,
   "claims": [{"id": "n1", "source": "<message id or artifact id>", "idea": "<idea id, backward items only>",
               "relation": "settles|reverses|implements|relays|independent_action", "decision": "<event id, optional>",
               "reverses": "<claim id or local id, reversals only>",
               "outcome": "...", "scope": "full|partial|component:<id>", "quote": "..."}],
   "new_ideas": [{"source": "<message id>", "statement": "...", "outcome": "...", "scope": "..."}]}
```

## D3. Referral (3 verifiers)
```
You are an INDEPENDENT verifier of contributions in messages exchanged between a human scientist and AI
agents running a scientific experiment.

Contribution categories (as defined in the audit):
  idea      proposes a course of action, approach or change that is not yet decided.
  decision  commits to, authorises, defers or declines a course of action already on the table. An instruction that
            FIRST raises an action and commits to it is both an idea and a decision. Passing on or re-issuing a
            decision already made restates that decision; reporting that a decided action has been done is status,
            not a decision.

Each item proposes that a MESSAGE (shown with the message before it) makes a contribution of the given category,
described by `candidate_statement`. Answer three separate questions:
  exists (1/0): does the MESSAGE itself make this contribution, as defined?
  identity: "new" if it is a contribution of its own; "same:<n>" if it only repeats, relays or re-issues the listed
            nearby contribution n of the same category; "unclear" if you cannot tell.
  targets (decision items only): the numbers of the listed TARGETS (earlier ideas) this decision decides on (adopts,
            declines, defers); an empty list if none.
Give confidence (0.0-1.0) and reason (<=25 words quoting the deciding words). Be neutral.
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "exists": 1, "identity": "new", "targets": [1], "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `settles` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item claims that the SOURCE SETTLES the TARGET, with an outcome and a scope.
  real (1/0): does the source settle the target (as defined above)?
  outcome: the outcome the evidence supports (from the lists above), even if it differs from the claimed one.
  scope: "full", or "component:<id>" naming one of the target's inventory components when it lists them, or
         "partial" when only part is settled and no inventory is listed.
  confidence (0.0-1.0), reason (<=25 words quoting the deciding words).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "outcome": "...", "scope": "...", "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `reverses` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item claims that the SOURCE REVERSES the earlier settlement shown under
`reversed_settlement` (its message and outcome): it undoes that settlement (a repair reverted, an adoption
withdrawn). Re-stating, refining or completing it is not a reversal.
  real (1/0), confidence (0.0-1.0), reason (<=25 words quoting the deciding words).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `implements` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item claims that a code or configuration EDIT (shown under `artifacts`: path, the
text before and after, who made it and when) IMPLEMENTS the TARGET DECISION: the edit is the carrying out of that
decision. Classify the edit:
  kind: "direct" (it does what the decision decided), "related" (same topic, but not what was decided),
        "preparation" (a step toward it that does not yet carry it out), "reversal" (it undoes it), or
        "failed" (an attempt that the shown messages report as failed or reverted).
  real (1/0): 1 only for kind direct.
  confidence (0.0-1.0), reason (<=25 words quoting the deciding words or code).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "kind": "direct", "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `results` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item claims that a reported RESULT (the finding shown under `finding`, with its message)
was produced WITH the code or configuration as changed by an EDIT (shown under `artifacts`: path, text before and
after, who made it and when). Classify:
  kind: "direct" (the result comes from running or using the changed code / configuration), "related" (same topic,
        but the result does not depend on this change), "before_change" (the result was obtained without it), or
        "unclear".
  real (1/0): 1 only for kind direct.
  confidence (0.0-1.0), reason (<=25 words quoting the deciding words).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "kind": "direct", "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `other` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item claims one of these relations between the SOURCE and the TARGET:
  relays              the source passes on someone else's settlement of the target (it does not settle it itself);
  independent_action  the source does something similar to the target independently (not because of it).
  real (1/0): does the evidence support exactly the named relation? confidence (0.0-1.0), reason (<=25 words).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "confidence": 0.0, "reason": "..."}
```

## D4. C6 verification — family `assessment` (3 verifiers)
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. Each item proposes a RELATION between a SOURCE (a message, or a file
version) and a TARGET. You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
Judge only from what is shown. Be neutral: do not judge whether a decision or fix was good.
File evidence (`artifacts`, `file_changes`) states its `quality`: exact = the whole new file content; hunk = only the
changed text (old -> new); cell = one notebook cell; pattern = a sed substitution pattern (NOT the written text); key
diff / paragraph diff / text diff = a comparison of two captured versions. Never read a hunk, cell or pattern as the
complete file.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

Each item is one page of a search that found nothing, over the messages listed as
searched. Answer the item's question for THESE messages only:
  question=settles                   real=1 if none of them settles the target, 0 if one does;
  question=changes_known_settlement  real=1 if none of them reverses, reopens or otherwise changes the listed
                                     known settlements (re-stating them is not a change), 0 if one does.
A page may list `searched_file_changes` (file versions or code edits) instead of messages: answer the same question
for those changes.
  confidence (0.0-1.0), reason (if 0, name the message id or file change id).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "real": 1, "confidence": 0.0, "reason": "..."}
```

## D5. C6 adjudication of conflicts (3 adjudicators)
```
You are an INDEPENDENT adjudicator. Each item lists two or more CONFLICTING claims about the same
source and target: each was supported by a majority of verifiers, but their outcomes cannot all be true of one
source at one time. You see the source in full and the target event as it stood at the source's time.

Outcomes of a SETTLES claim on an IDEA (a proposed course of action):
  adopted                    the source commits to doing the proposal (or the named part of it).
  deferred                   the source explicitly postpones the choice ("not now", "later", "I'll think").
  declined                   the source explicitly rejects the proposal.
  declined_by_alternative    the source chooses a different option that is demonstrably mutually exclusive with this
                             proposal, in the same choice (an either/or menu); not merely a different idea.
  authorized_to_investigate  the source authorises a check or investigation of the proposal, not the proposal itself.
NOT a settlement of an idea: carrying out or reporting an action already decided (status, "Config written");
relaying someone else's decision (that is a relay); doing something similar independently.

Outcomes of a SETTLES claim on a CORRECTION (something shown wrong that needed a change):
  repaired              the change the correction requires is reported (or shown in an artifact) as DONE.
  partially_repaired    part of the required change is done; the named scope says which part.
  workaround            the problem is avoided by a different change, not the one the correction requires.
  withdrawn_diagnosis   the correction itself is retracted: the original claim was right after all.
  already_satisfied     the required state already held (nothing had to change).
  abandoned_requirement the requirement the correction served is dropped.
  unclear               the evidence is real but does not say which of the above.
A promise or a plan is not a repair; a different change on the same topic is not a repair.

A REVERSES claim: the source undoes an earlier settlement (a repair reverted, an adoption withdrawn).

SCOPE: full = the whole event (every part of the proposal / correction); partial = part of it, and the
component named; a scope of component:<text> names the component.

For each item give "choice": the number of the claim the evidence supports, or 0 if the evidence does not decide
between them; confidence (0.0-1.0); reason (<=25 words, quoting the deciding words).
OUTPUT: a JSON array, one object per item, in input order, and nothing else:
  {"item_id": "...", "choice": 1, "confidence": 0.0, "reason": "..."}
```

---

# PART E — The wordings
For each multi-rater prompt: how many verbatim blocks it has (identical in every wording; their md5s are in the stage's `prompts_manifest.json`), then the reworded parts of each wording, in order (the opening sentence, then any sentence describing the input) -- the only text that differs. Rater / verifier / pass k reads w<k>; the single adjudicators of p11 / p12 read w3; p04 intent keeps its prompts A / B.

**Wording report (to be produced from the full runs; no model calls).** Per experiment, from the stored jobs, outputs and production reducers: (1) coverage by stage / family / wording -- expected jobs and items; answered, refused, missing, invalid, repaired answers; empty branches; (2) matched-item agreement w1-w2, w1-w3, w2-w3 (raw agreement, confusion tables, kappa where defined, with denominators); never w3 adjudicator prevalence against all items; (3) every count-relevant field -- p09 real / change / target, C3 real / targets / subtype, referral exists / identity / targets, C6 real / outcome / scope / kind, adjudication choice incl. 0 -- each with its conditional denominator (e.g. outcome / scope over real votes); duplicate and repaired answers counted; calls and chunks per wording; (4) extraction and search: p07 contributions found by both passes / w1 only / w2 only after p08's pairing, with their multiplicity per message, their links and fix links; C4 claims and new ideas by both / one pass, per search mode and replay, and their final acceptance; (5) strata: category, link type, C3 kind, referral category, C6 family and assessment question; sparse or empty strata shown, not dropped.

## p07 extract

2 verbatim block(s), 7221 characters.
**w1**
```
You are extracting the CONTRIBUTIONS of messages exchanged between a human scientist and
AI agents (a team-lead orchestrator and specialist agents) running a scientific experiment, and the LINKS
from each contribution to the EARLIER message it acts on.
----
Every row has message_id, ts (UTC),
sender, recipient and text.
```
**w2**
```
Your task is to extract the CONTRIBUTIONS of messages exchanged between a human scientist and
AI agents (a team-lead orchestrator and specialist agents) running a scientific experiment, and the LINKS
from each contribution to the EARLIER message it acts on.
----
Each row carries message_id, ts (UTC),
sender, recipient and text.
```

## p09 link

2 verbatim block(s), 5673 characters.
**w1**
```
You are an INDEPENDENT verifier of links between messages exchanged between a human scientist
and AI agents running a scientific experiment. 
----
You see
both messages in full, with UTC timestamps and senders.
```
**w2**
```
Act as an INDEPENDENT verifier of the links between messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Both
messages are shown in full, with their senders and UTC timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking links between messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
Each of
the two messages is shown in full, with its sender and UTC timestamp.
```

## p09 contrib

1 verbatim block(s), 3725 characters.
**w1**
```
You are an INDEPENDENT verifier of contributions in messages exchanged between a human scientist
and AI agents running a scientific experiment. 
```
**w2**
```
Act as an INDEPENDENT verifier of the contributions in messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking contributions in messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
```

## C3 p09c

1 verbatim block(s), 3710 characters.
**w1**
```
You are an INDEPENDENT verifier of links between messages exchanged between a human scientist and AI
agents running a scientific experiment. You see the messages in full, with UTC timestamps and senders.
```
**w2**
```
Act as an INDEPENDENT verifier of the links between messages that a human scientist and AI agents
exchanged while running a scientific experiment. The messages are shown in full, with their senders and UTC timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking links between messages exchanged by a human
scientist and AI agents who were running a scientific experiment. Each shown message appears in full, with its sender and UTC timestamp.
```

## C4 p10s

1 verbatim block(s), 4853 characters.
**w1**
```
You search a conversation between a human scientist and AI agents running a scientific experiment for
what happened to an earlier proposal or correction. Timestamps are UTC.
```
**w2**
```
Your task is to search a conversation between a human scientist and AI agents running a scientific experiment for
what happened to an earlier proposal or correction. UTC is used for timestamps.
```

## referral p10x

2 verbatim block(s), 1264 characters.
**w1**
```
You are an INDEPENDENT verifier of contributions in messages exchanged between a human scientist and AI
agents running a scientific experiment.
----
Each item proposes that a MESSAGE (shown with the message before it) makes a contribution of the given category,
described by `candidate_statement`.
```
**w2**
```
Act as an INDEPENDENT verifier of the contributions in messages that a human scientist and AI agents
exchanged while running a scientific experiment.
----
Each item shows a MESSAGE together with the message before it, and proposes that the MESSAGE makes a contribution
of the given category, described by `candidate_statement`.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking contributions in messages exchanged by a human
scientist and AI agents who were running a scientific experiment.
----
Each item presents a proposed contribution of a MESSAGE shown with the message before it: the contribution has
the given category and is described by `candidate_statement`.
```

## C6 settles

2 verbatim block(s), 3237 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 reverses

2 verbatim block(s), 3027 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 implements

2 verbatim block(s), 3347 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 results

2 verbatim block(s), 3313 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 other

2 verbatim block(s), 3096 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 assessment

2 verbatim block(s), 3357 characters.
**w1**
```
You are an INDEPENDENT verifier of claims about messages exchanged between a human scientist and AI
agents running a scientific experiment. 
----
You see the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are UTC.
```
**w2**
```
Act as an INDEPENDENT verifier of claims about the messages that a human scientist and AI agents
exchanged while running a scientific experiment. 
----
Shown for each item: the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). UTC is used for timestamps.
```
**w3**
```
Your role is that of an INDEPENDENT verifier, checking claims about messages exchanged by a human
scientist and AI agents who were running a scientific experiment. 
----
For each item you get the source in full, the target as it stood at the source's time (its statement and
member messages), messages just before the source, the message where the target was first raised, and later
messages that mention the target (they may show a reversal or contradict the claim). Timestamps are expressed in UTC.
```

## C6 adjudication

2 verbatim block(s), 2531 characters.
**w1**
```
You are an INDEPENDENT adjudicator. 
----
You see the source in full and the target event as it stood at the source's time.
```
**w2**
```
Act as an INDEPENDENT adjudicator. 
----
The source is shown in full, with the target event as it stood at the source's time.
```
**w3**
```
Your role is that of an INDEPENDENT adjudicator. 
----
Shown for each item: the full source and the target event as it stood at the source's time.
```

## p11 correction

2 verbatim block(s), 2174 characters.
**w1**
```
You are a blind rater assigning a DOMAIN to each 
----
INPUT: one JSON object per line, {id, claim}.
```
**w2**
```
Act as a blind rater and assign a DOMAIN to each 
----
INPUT: each line is one JSON object, {id, claim}.
```
**w3**
```
Your role is that of a blind rater, giving a DOMAIN to each 
----
INPUT: one JSON object per line, with fields {id, claim}.
```

## p11 idea

2 verbatim block(s), 2100 characters.
**w1**
```
You are a blind rater assigning a TYPE to each 
----
INPUT: one JSON object per line, {id, idea}.
```
**w2**
```
Act as a blind rater and assign a TYPE to each 
----
INPUT: each line is one JSON object, {id, idea}.
```
**w3**
```
Your role is that of a blind rater, giving a TYPE to each 
----
INPUT: one JSON object per line, with fields {id, idea}.
```

## p11 decision

2 verbatim block(s), 2158 characters.
**w1**
```
You are a blind rater assigning a TYPE to each 
----
INPUT: one JSON object per line, {id, decision}.
```
**w2**
```
Act as a blind rater and assign a TYPE to each 
----
INPUT: each line is one JSON object, {id, decision}.
```
**w3**
```
Your role is that of a blind rater, giving a TYPE to each 
----
INPUT: one JSON object per line, with fields {id, decision}.
```

## p11 finding

2 verbatim block(s), 2095 characters.
**w1**
```
You are a blind rater assigning a TYPE to each 
----
INPUT: one JSON object per line, {id, finding}.
```
**w2**
```
Act as a blind rater and assign a TYPE to each 
----
INPUT: each line is one JSON object, {id, finding}.
```
**w3**
```
Your role is that of a blind rater, giving a TYPE to each 
----
INPUT: one JSON object per line, with fields {id, finding}.
```

## p12 coord

2 verbatim block(s), 2619 characters.
**w1**
```
You are a blind rater assigning a COORDINATION TYPE to each 
----
INPUT: one JSON object per line, {id, text}: the full message text.
```
**w2**
```
Act as a blind rater and assign a COORDINATION TYPE to each 
----
INPUT: each line is one JSON object, {id, text}: the full message text.
```
**w3**
```
Your role is that of a blind rater, giving a COORDINATION TYPE to each 
----
INPUT: one JSON object per line, with fields {id, text}: the full message text.
```
