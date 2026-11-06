# GP Noise Model — Contract and Pre-Launch Gate (LIVE 11BM-CMS)

Single source of truth for how the GP's noise is chosen, measured, and approved. Cog skills carry only
a pointer plus their §5 duty; every number lives in **`config.json → gpcam.noise`**, never hard-coded.

Kernel and acquisition change *how fast* a GP learns. **The noise model changes whether it learns at
all** — tell the GP a measurement is noisy and it is entitled to ignore it, permanently, silently, and
with a healthy-looking log. It is a physics claim about the instrument, not a tuning knob, and it is
the one setting whose failure mode looks like "the sample is boring."

*Derivations, precision tables, and references live in `../discussion/appendix/noise-model-math.md` — human
reference, not required reading for any cog.*

## The rule

**σ must never grow as the signal gets weaker.**

| form | verdict |
|---|---|
| `σ = const` | fine when repeats say so |
| `σ = max(floor, α·\|y\|)` — value-proportional | the 11BM learned default |
| `σ ∝ (1 − \|y\|)`, `σ ∝ 1/SNR`, anything inflating σ at low amplitude | **rejected** |

The inverted form is self-defeating for any weak field: small signal → declared noisy → down-weighted →
never learned. It cannot recover, because the mechanism that would reveal the signal is the one being
suppressed.

Two corollaries:

- **Anchor every constant in data** — repeat measurements (§1). σ has exactly one measured source;
  a constant with no empirical origin is not ready to launch.
- **A new objective is not a licence for a new noise model.** Start from the form already working in
  this pipeline and justify any departure. If a *derived* quantity is noisy at low amplitude, model
  that quantity's noise, not its components' — an angle's error diverges as amplitude → 0, its
  Cartesian components' does not.

---

## 1. Repeats → σ and its form

**What this is for:** measure the noise at one position, then at another, then a few more. If σ comes
out the same everywhere, a constant-σ model fits the experiment. If it grows with the signal, a
value-proportional one does. That comparison — not the precision of any single number — is the point.

op-cog measures `n_repeats` exposures at each of `n_positions` (§5): move to a position, expose
`n_repeats` times without moving, move to the next. AE exposure time throughout. gpcam-cog computes,
from `ana_log.csv`:

```
ȳ_p, s_p     per-position mean and unbiased sample SD
s_pool       pooled over positions, dof = P·(n−1)      ← the number the noise model uses
```

**Two outputs, and the second is the important one:**

| output | use |
|---|---|
| `s_pool` | magnitude — the `floor`, and the yardstick everything in §2 is measured against |
| trend of `s_p` vs `ȳ_p` | **form** — this is what the position count buys |

**The two variances never mix.** `s_pool` uses only *within-position* scatter — each position's own
mean is subtracted first — so it is pure counting + instrument noise: nothing moved between the
repeats, so sample inhomogeneity cannot enter it. The *between-position* spread **is** inhomogeneity,
and that is exactly what it is for: it supplies the several **signal levels** `ȳ_p` without which β is
undeterminable. Heterogeneity is the instrument for the form test, never an input to σ.

**Pooling assumes one σ at every position**, which holds only if the form comes back `constant`. If
the form is value-proportional, use `σ = α·|y|` with `α = mean(s_p/ȳ_p)` — a single pooled number is
then the wrong object. The card states which to use.

**Form decision** (fit `log s_p = log α + β·log\|ȳ_p\|`):

- `β ≈ 0` → constant σ; use `σ = s_pool`
- `β ≈ 1` → value-proportional; `α = mean(s_p / ȳ_p)`
- **`β < 0` → σ grows as signal shrinks. Reject the model and say so explicitly.**

**Treat β as a sign test, never a fitted exponent** — with 3 repeats per position each `s_p` carries
~50 % error. Eyeball equivalent: is `s_p/ȳ_p` roughly constant across positions (⇒ proportional), or is
`s_p` roughly constant (⇒ additive)?

**Precision, to state on the card:** the default 5 × 3 design pins σ to a 95 % CI of
**[0.70, 1.75] × s_pool** — enough to catch a campaign-killing error (run007 inflated σ up to 4.5×),
never enough to fine-tune. Full table: appendix §B.

**Positions beat repeats at equal cost.** 5 × 3 and 3 × 5 cost the same and give near-identical σ
precision, but 5 × 3 samples five signal levels instead of three, and the form test is what matters.
`n_repeats ≥ 3` is the floor for a variance at all, not a target. (Appendix §C.)

---

## 2. Is there signal, and is it resolved?

Two questions the noise model needs answered, both by comparing **neighbouring measurements against
σ**. Computed by gpcam-cog from `ana_log.csv`; no spatial model, no fitting.

```
SNR   = Var(y) / σ²                        is there any signal above the noise at all?
ratio = rms(Δy_NN) / (√2 · σ)              is the structure resolved at my sampling step?
```

where `Δy_NN` is the difference between each point and its nearest neighbour.

**Which pairs count — the beam sets the floor.** Two exposures closer together than one beam
footprint share illuminated sample area, so they are correlated *by construction*: their difference
is suppressed by the overlap, not by the field being smooth. Including them drags `ratio` toward 1
and makes any map look resolved. **Pairs closer than one beam are excluded** (as are the repeats at
zero separation, which measure σ). The beam is a low-pass filter — nothing below it is observable by
stepping below it.

Two separations are therefore worth having, and they answer different questions:

| separation | where it comes from | question |
|---|---|---|
| **1 beam** | `seed_repeats.offset_frames` — one extra exposure per position, displaced by one beam | is there structure at the **instrument's resolution limit**? If yes, no grid refinement helps — only a smaller beam. |
| **the grid step** | free, from the seed map itself | is my **sampling step** fine enough? If not, refine the grid. |

**Reading `ratio`.** For two points separated by `d`, `E[(yᵢ−yⱼ)²] = 2σ² + 2[k(0) − k(d)]`, so:

| ratio | meaning |
|---|---|
| **≈ 1** | neighbours differ by noise *only* ⇒ `d ≪ ℓ` — **resolved**, the field varies slowly across your step |
| **≫ 1** | neighbours are already decorrelated ⇒ `d ≳ ℓ` — **under-resolved**, structure is finer than your step, and **ℓ ≤ the sampling step** |

Combined with `SNR ≈ 1` (no structure above noise at all), those three states are the whole
diagnosis. `ratio` also yields the only length scale the gate needs: an **upper bound on ℓ**, which
is what catches a GP fitting a length scale far larger than the data supports.

**Why not a variogram.** A variogram assumes second-order stationarity — one mean and one covariance
depending only on separation. **An autonomous experiment violates that by design**: the whole point
is to map an *inhomogeneous* sample. On real run007 data the empirical semivariogram was
non-monotonic (γ peaked at 2.4× its far-field value), so no standard model applied and every derived
quantity was either meaningless or actively wrong. The comparison above is purely local — it holds
wherever the pairs happen to be and needs no assumption that one covariance describes the whole map.

---

## 3. Using σ, and what it does not cover

Feed gpCAM `noise_variances = σ(yᵢ)²` from the approved form, floored at `s_pool²`. If the objective
is standardized by `Y_SD`, divide by `Y_SD²` (`noise_var_std` in the gpcam-cog skill).

**`s_pool` is a lower bound on σ.** Repeats at a fixed spot capture counting and instrument noise
only; sub-beam sample heterogeneity is absent from them. If the field turns out **under-resolved**
(§2), that heterogeneity is real structure sitting below your sampling step — **do not raise σ to
absorb it**, which would tell the GP to ignore signal that exists. Take a finer step or a smaller
beam instead.

**Cross-checks the card runs** against the trained GP:

| check | what it catches |
|---|---|
| declared σ vs `s_pool` | a noise model inflated or deflated relative to the one measured number |
| `signal_variance` vs its lower bound | the model concluding there is no signal (§4) |
| fitted `ℓ` vs the NN spacing, when under-resolved | the run007 failure: `ℓ` tens of times the scale the data resolves |
| posterior CV vs a constant predictor | a posterior that is a single number painted over the map |

---

## 4. HARD GATE — approved in words before the AE starts

The existing "never execute without explicit user confirmation" step **is** the gate; this adds
required content to it. **No card, no launch.** Team-lead assembles:

1. **The formula**, verbatim, and its **direction** ("σ grows with the signal").
2. **The empirical source of every constant** — `s_pool`, its 95 % CI, and the per-position
   `(ȳ_p, s_p)` table; plus `SNR` and `ratio` from §2.
3. **Seed-fit diagnostics:**
   - β and its verdict — INVERTED ⇒ **stop**; any "possible inversion" ⇒ warn
   - `signal_variance` vs its lower bound — within `signal_variance_floor_ratio` ⇒ **stop** (§5 below)
   - declared σ vs `s_pool` — more than 2× either way ⇒ warn
   - fitted `ℓ` vs the NN spacing when the field is under-resolved — beyond `ell_vs_nn_max_ratio`
     ⇒ **stop**
   - posterior CV vs a constant predictor — if it does not beat a single number, it is a single number
4. **The precision caveat** for the repeat design used (§1).

**In flight the check is advisory** — recompute every `advisory_every_n_points`, report to team-lead,
loop keeps running. A synchronous pause would collide with `gpcam.stopping.analysis_wait_timeout_s`:
the daemon declares an error stop if no `ana_log` row arrives in time, so blocking for a human read can
end the campaign. The one automatic exception is the `signal_variance` floor.

**Re-run the card on any steer that changes the objective definition or a noise key** — the previous
approval does not cover a new model.

### Failure signatures

**`signal_variance` pinned at its lower bound** is the master detector: cheap, and it catches an entire
class of unrelated faults, which is what makes it worth asserting on. Observed causes:

- the **noise model** declared the variance to be noise (inverted σ, or σ far above `√c₀`);
- the **objective definition** destroyed the variance (e.g. a gate zeroing almost every point) — here
  the GP is *right* about the data it was given; fix the objective or the sampling, not the GP.

Everything else follows from it: flat acquisition surface, edge-hopping into empty corners, `ℓ` railing
to its upper bound, posterior ≈ a constant painted over the map. **Capping `ℓ` is not the fix** — ℓ
re-rails while σ² stays pinned (appendix §H). ℓ is the symptom, σ² is the disease.

---

## 5. Config keys and cog duties

`config.json → gpcam.noise` — everything tunable, so the cogs stay in sync and each run records what it used.

| Key | Meaning |
|---|---|
| `model` | `value_proportional` (default) · `constant` · `from_repeats` |
| `frac` | α in `σ = α·\|y\|` (default 0.10) |
| `floor` | absolute σ floor in objective units; `null` ⇒ take it from `s_pool` |
| `seed_repeats.n_positions` | distinct positions (default 5) |
| `seed_repeats.n_repeats` | exposures per position (default 3; ≥ 3 required for a variance) |
| `seed_repeats.placement` | `current+random` (default) — current position + the rest random inside the search bounds, since nobody knows in advance where the signal is strong |
| `gate.signal_variance_floor_ratio` | stop if `signal_variance` < ratio × its lower bound (default 2.0) |
| `gate.form_k_sigma` | flag INVERTED when β is negative by this many of its own standard errors (default 1.5, leaning toward sensitivity). Decides BLOCK vs warn only — the same σ table reaches the same human either way; not worth revisiting (appendix §D) |
| `gate.ell_vs_nn_max_ratio` | stop if the fitted `ℓ` exceeds this × the NN spacing *while the field is under-resolved* (default 10) |
| `gate.advisory_every_n_points` | in-flight recompute cadence (default 20) |

- **op-cog** — measure the repeats per config; flag the rows so they can be grouped (`repeat_group` /
  `repeat_idx` in `op_log.csv`, or an agreed savename tag).
- **ana-cog** — nothing special: repeat frames are ordinary frames. Analyze and log **every** one, and
  never dedup/collapse rows by position — repeats at an identical `(x,y)` are deliberate.
- **gpcam-cog** — owns every statistic, computed from `ana_log.csv` (§1, §2) via
  `noise_helpers.py` (do not re-derive them). Applies the approved formula, records it verbatim in
  `gpcam_metadata.json → noise_model`, runs the §4 diagnostics at the seed fit and each
  `advisory_every_n_points` after.
- **team-lead** — assemble the card, hold the gate, snapshot the resolved block into `config_history/`.
