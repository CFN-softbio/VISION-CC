---
name: gpcam-cog
description: Generate control code for gpCAM-driven experiments at 11BM beamline based on user requests.
---

## Purpose

This skill defines the optimization-side rules, APIs, file contracts, and code patterns for gpCAM-driven autonomous experiments at the 11BM beamline.

## Workspace convention (intermediate code)

Your canonical daemon (`gpcam_<name>.py`) goes in the **run root** (`$RUN_DIR`). Any **intermediate / ad-hoc / scratch / self-test** script you generate goes under **`$RUN_DIR/log/`**, never the run root. Create `log/` if missing.

**Output products go under `$RUN_DIR/gp_out/`** (create it if missing), mirroring ana-cog's `ana_out/`: write `gpcam_posterior.npz`, `gpcam_posterior_history.npz`, and `gpcam_hyperparameters.csv` there. Keep these at the **run root** (they are coordination + easy-check files, not products): `gpcam_log.txt`, `gpcam_metadata.json`, and the `GPCAM_NEXT.txt` / `GPCAM_STOP.txt` flag files. `gpcam_log.txt` is append-only; gpCAM never rewrites `ana_log.csv` (it only reads it), and any full rewrite of a log follows `docs/ownership.md`, Backups (`run_files.backup(path, "rewrite")`, then temp file + `os.replace()`). writer-cog reads `gpcam_metadata.json` from the run root and the posterior/hyperparameter products from `gp_out/`. Define the product paths once near the top of the daemon (e.g. `GP_OUT = os.path.join(RUN_DIR, "gp_out"); os.makedirs(GP_OUT, exist_ok=True)`) and build `POSTERIOR`, `POST_HISTORY`, `HYPER_CSV` under it. **Tag the posterior files per daemon start** (`<phase>_seq<startseq>_scan<scanid>`, built by this skill's `gp_out_paths.py`: `launch_tag` + `tagged_path`) so a restart or steer never overwrites or appends to a previous phase's history; save per-field mean and variance too (see gpcam-cog.md).

## Required reading (MANDATORY)

Before writing any code, read:

1. [reference.md](reference.md) — complete gpCAM API, including `GPOptimizer`, `ask`, `tell`, `train`, `posterior_mean`, `posterior_covariance`, and common mistakes

Do not generate code until the required file is read.

Every gpCAM method used must appear in `reference.md`. Pay special attention to the
**VERSION MATRIX** at the top and the "Common Mistakes" section at the bottom.

**Load these when the work calls for it** — do not rely on the agent frontmatter, which is
ignored for teammates:

| Skill | Load it when |
|---|---|
| `gpcam-customization` | Custom kernel, acquisition callable, prior mean, noise function, or cost function. |
| `gpcam-diagnostics` | A run crashed, stalled, or keeps re-picking the same point; or before adding any validation / variance-based stopping code. It also lists which validation metrics exist per version — `picp`, `mpiw`, `coverage_curve`, `msll`, `evaluate_posterior` raise `AttributeError` on older pins. |
| `gp2scale-advanced` / `multi-task-advanced` | >10k points; vector-valued measurements. |

### Import the pinned gpCAM, and only that one (MANDATORY)

**The gpCAM source is set once, in `config.json → paths.gpcam`** — never ask the user, never
restate a version number elsewhere. This host carries several gpcam installs and
`import gpcam` takes the first match on `sys.path`, so **no VISION process may import gpcam
by accident**:

- Prepend `paths.gpcam.path` to `PYTHONPATH`, and set `PYTHONNOUSERSITE=1` — `~/.local/lib`
  holds an old gpcam that Python searches before the pixi env. Both, every time: daemon,
  smoke test, preflight, one-off script.
- **Assert at startup, before any GP work:** `gpcam.__file__` must live under the configured
  path. If it does not, log the offending path and exit — never continue on whatever loaded.
  Then record `gpcam.__version__` / `fvgp.__version__` in `gpcam_metadata.json`.

Write against the pinned version; `reference.md` is the API. Use the two accessors below
anyway — they cost nothing and turn the one expensive failure (a posterior-key mismatch
mid-run) into a non-event:

```python
def _pm(gpo, x, **kw):
    """Posterior mean, tolerant of the m(x)/f(x) key split."""
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d:
            return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")

def _acq_val(r):
    return r.get("f_a(x)", r.get("f(x)"))     # acquisition value from an ask() result
```

`posterior_covariance(..., variance_only=True)["v(x)"]`, `ask()["x"]`, `gpo.x_data`, and
`gpo.y_data` are stable — use them directly.

**gpCAM 8.3.9 — the vendored pin (`vendor/gpcam-8.3.9`), verified. These override anything below or in `reference.md`:**
- `evaluate_acquisition_function(x, acquisition_function=...)` returns the acquisition with its **sign unchanged** (higher = better), for built-in strings and callables. Do **not** negate it. Safest: call your own acquisition callable `acq(x, gpo)` directly. The built-in `'variance'` string returns σ (the standard deviation), not the variance.
- `posterior_mean(x)["m(x)"]` for a **single** point is a 0-d array: wrap it with `np.atleast_1d(...)`.
- `posterior_covariance(x, variance_only=True)` still builds V×V intermediates (peak memory grows with V²: about 1 GB at V = 6000), so evaluate a large candidate grid in chunks of about 500 points.
- `ask(input_set=...)` with the candidates as a (V, D) numpy array fails ("wrong number of columns in x_pred"). Pass a Python list of points, or skip `ask()` and take the argmax of your own acquisition over the masked grid (the pattern below).

> **Fallback (the only place this is mentioned).** If the pinned version misbehaves in a way
> that looks like an API mismatch, point `paths.gpcam` at an 8.1.x install and re-run — that
> is the older pin this rig ran on. Note that `calc_inv=True` is valid on ≤8.3.x and was
> replaced by `linalg_mode="CholInv"` on 8.4.x.

## Design Choices
Based on their answers, decide:

| Choice | Guidance |
|--------|----------|
| **Kernel** | Default Matérn-3/2 ARD is good for most cases. Use periodic kernel if periodicity is known. Use Matérn-1/2 for rough/discontinuous data, Matérn-5/2 or SE for very smooth. See `gpcam-customization` skill for custom kernels. |
| **Acquisition function** | **Choose it *with* the user — never silently, and never `'expected improvement'` by reflex.** `'variance'` for exploration/mapping; `'ucb'` for optimization; `'lcb'` / `'minimum'` for minimization (EI/PI/UCB/KG/NEI all maximize **silently**); `'gradient'` for transitions; `'noisy expected improvement'` when single-shot noise is large (8.4+). **The `'ucb'`/`'lcb'` strings hardcode `β = 3.0` — β is NOT tunable from the string;** use a callable if you need a different β. Custom callable for multi-objective, constraints, or any string not confirmed present on the install. See `gpcam-customization` §2 + its `references/choosing-an-acquisition-function.md`. |
| **Prior mean** | Default is the **data mean**, not zero. Override only with a physical model. Custom prior means are rejected by the constructor if the install really is 8.1.13 (Rule D). See `gpcam-customization` skill. |
| **Noise model** | **Highest-stakes choice in this table — read "⚑ The noise model decides whether anything can be learned" below before writing it.** Use `noise_variances` if noise is known and uniform; `noise_function` if it varies. **LEARNED DEFAULT for fit-metric objectives (e.g. a SciAnalysis peak-fit `prefactor`): per-point noise = 10% of the objective VALUE (`noise_std=0.10·\|y\|`, floored), NOT the peak-fit error/χ².** Using the fit-error makes blank/no-peak frames look high-uncertainty → EI over-samples the box edges. See `gpcam-customization` skill §4 (⭐ Learned default). |
| **Training strategy** | `method='global'` for first training, `method='local'` for re-training during the loop. Other options: `"mcmc"` (Bayesian — returns posterior samples over hyperparameters), `"adam"` (stochastic-gradient, fast, works well for high-dimensional hyperparameter vectors like deep kernels), `"hgdl"` (distributed local+global hybrid — needs a `dask_client`). |
| **Cached inverse** | Worth it below ~2000 points, harmful above. Use `calc_inv=True` (renamed to `linalg_mode="CholInv"` on 8.4.x). Omitting it is always safe — the default is correct, just slower. |
| **Number of initial points** | Rule of thumb: 5-10× the input dimensionality for initial random sampling. |
| **Validation** | `gpo.rmse(x_test, y_true)` and `gpo.crps(x_test, y_true)` give RMSE and continuous ranked probability score on a held-out grid — call these after training to sanity-check the fit. |

## ⚑ The noise model decides whether anything can be learned (MANDATORY)

Kernel and acquisition change *how fast* a GP learns. **The noise model changes whether it learns at
all.** Tell the GP a measurement is noisy and it is entitled to ignore it — permanently, silently, and
with a healthy-looking log. Treat it as a physics claim to justify, not a knob.

- **σ must never grow as the signal gets weaker.** Value-proportional (`σ ∝ |y|`) is correct.
  Anything inflating σ for low-amplitude points (`σ ∝ (1 − |y|)`, `σ ∝ 1/SNR`) is **self-defeating**:
  weak signal → declared noise → down-weighted → never learned, with no way back.
- **Anchor σ in data, not in the objective's value:** the seed **repeat measurements** (`s_pool`),
  else the value-proportional default. No empirical anchor → do not launch.
- **A new objective rarely needs a new noise model.** Start from the one already working in this
  pipeline and justify any departure.
- **If a *derived* quantity is noisy at low amplitude, model that quantity's noise — not its
  components'.** (An angle's error diverges as amplitude → 0; its Cartesian components' does not.)
- **`signal_variance` pinned at its lower bound ⇒ STOP.** It means the model concluded there is no
  signal — flat acquisition, edge-hopping, railed `ℓ`, posterior ≈ a constant. Log `signal_variance`
  every fit and warn when it sits within ~2× of its floor for several fits in a row. **Capping `ℓ` is
  not the fix** — ℓ is the symptom, σ² is the disease. Unrelated faults (a gated objective that zeroes
  most points; an inverted noise model) all land on this one signature, which is what makes it worth
  asserting on.
- **"Noise model present" ≠ "noise model sound."** Any new or changed noise key gets fresh
  justification, never inherited trust. Record the formula in `gpcam_metadata.json → noise_model` +
  the `config_history/` snapshot.

### HARD GATE — approved in words before the AE starts

The existing "never execute without explicit user confirmation" step **is** the gate; the material you
hand up for it MUST include a noise card — **no card, no launch**:

1. **The formula**, verbatim, and its **direction** ("σ grows with the signal").
2. **The empirical source of every constant.** All of it comes from `ana_log.csv` and **you compute
   it** via `noise_helpers.py` — ana-cog just analyzes the frames: pooled repeat scatter `s_pool` +
   its CI, and the nearest-neighbour statistics (`SNR`, `ratio`). No anchor ⇒ not ready.
3. **Seed-fit diagnostics:** β and its verdict (INVERTED ⇒ stop) · `signal_variance` vs its lower
   bound · declared σ vs `s_pool` · fitted `ℓ` vs the NN spacing when under-resolved · posterior CV
   vs a constant predictor.

In flight the check is **advisory** — report and keep running; a blocking pause collides with
`gpcam.stopping.analysis_wait_timeout_s`. The **one** automatic exception is `signal_variance` at its
floor. Re-run the card on any steer changing the objective or a noise key.

**All settings, thresholds, and the repeat design come from `config.json → gpcam.noise` — never
hard-code them, and compute the statistics with `noise_helpers.py` rather than re-deriving them
(`pixi run check-noise` verifies it; `--csv/--value` runs it on real data).** Full spec and failure
signatures: **`docs/noise-model.md`** (single source of truth).

## Source of truth (CRITICAL)

- The skill files are the ONLY source of truth.
- The runtime code path is available for execution, but it is NOT a source of truth for discovering APIs or behavior.
- Do NOT inspect, read, or traverse implementation folders to discover methods or logic.
- Do NOT explore directories to infer hidden functionality.
- Do NOT import modules just to inspect their contents.
- If something is not defined in `reference.md`, do not use it.
- **Run settings come from `config.json` in exactly ONE shape** — the nested
  `gpcam.sampling` / `gpcam.stopping` blocks of `config.template.json`. Do not read legacy
  flat keys (`gpcam.min_sample_distance`, `gpcam.max_iters`, …), do not accept both, and do
  not silently fall back to built-in defaults when the block is missing: log the error and
  stop, so a run never proceeds on values nobody confirmed.

## Code rules

- Use `from gpcam import GPOptimizer`
- `ask()` results: the suggested point is `result["x"]`. For the acquisition value use `_acq_val(result)`, not a hardcoded key.
- `posterior_mean()` results must always go through `_pm(gpo, x)` — **never a hardcoded `["m(x)"]` or `["f(x)"]`** (see "Write version-tolerant daemons" above).
- `posterior_covariance(x, variance_only=True)` results must always be accessed as `result["v(x)"]`. The **full** covariance matrix key is `["S"]`, **not** `["S(x)"]`.
- `posterior_mean_grad(x)["dm/dx"]` returns the **full `(V, D)` gradient**. `direction` is the 4th parameter and keyword-only in practice — `posterior_mean_grad(x, 0)` passes `0` as `hyperparameters` and silently returns the wrong thing.
- Read the cumulative training data via the `gpo.x_data` / `gpo.y_data` **attributes**, not `get_data()` keys (see notes below).
- `tell(x, y, ..., append=True)` — **ALWAYS pass `append=True` explicitly** (see notes below).
- `x_data` shape must be `(N, D)` — use `.reshape(-1, 1)` for 1D inputs
- `y_data` shape must be `(N,)` — use `.reshape(-1)` if needed
- `init_hyperparameters` length must equal `D + 1` for the default ARD kernel
- Custom acquisition functions must return a 1-D array

## gpCAM API notes (MANDATORY)

Written against the pinned version (`config.json → paths.gpcam`). A–D are the four ways a
daemon breaks; E–F are 11BM defaults independent of version.

**A. Posterior-mean key is `'m(x)'`.** Getting it wrong raises `KeyError` — the classic
seeds→BO crash, after the seeds are already spent. Go through the accessor anyway:
```python
mean = _pm(gpo, X)                                               # see above
var  = gpo.posterior_covariance(X, variance_only=True)["v(x)"]   # stable
```
(`'f(x)'` is real elsewhere — `gpMCMC` traces, `optimize()`'s `'trace f(x)'` — which is why
the accessor accepts both.)

**B. Read the cumulative dataset via attributes, not `get_data()` keys.**
`get_data()` keys are space-separated (`'x data'`, `'y data'`, `'noise variances'` /
`'measurement variances'`) — the underscore names raise `KeyError`. Use the attributes,
which are the reliable cumulative dataset:
```python
x_all = gpo.x_data        # (N, D)
y_all = gpo.y_data        # (N,)   -- grows after each tell(append=True)
hp    = gpo.get_data()["hyperparameters"]   # this key IS present
```

**C. `tell(...)` MUST pass `append=True` explicitly.** Highest priority: the failure mode is
silent data loss — the GP ends up trained on only the last point. It is the signature
default, but pass it anyway; it costs nothing and documents intent:
```python
gpo.tell(new_x, new_y, noise_variances=new_nv, append=True)   # append=True REQUIRED
```
`noise_variances` here covers **only the new points** (length `M`), not the whole dataset.
The rank-n-update kwarg is `gp_rank_n_update` (it is `rank_n_update` on 8.4.x) — omit it
unless you have a reason.

**D. The `GPOptimizer` constructor accepts `kernel_function`, `prior_mean_function`, and
`noise_function` — but prefer the defaults.** Not for compatibility; because the defaults
are the right 11BM choice:
- Kernel → the default anisotropic ARD Matérn-3/2.
- Prior mean → the default is the **data mean** (not zero), which is usually what you want.
- Noise → a fixed `noise_variances` array (see E), preferred over `noise_function`.

Reach for the callables only when `gpcam-customization` calls for one.

**E. Standardize the objective (default guard against pinned signal variance).**
For tiny- or arbitrary-magnitude objectives (e.g. integrated ring intensity
~1e-4–1e-2), training pins `signal_variance` at its bound and the GP is
mis-scaled. Z-score the objective with a **fixed affine from the seed set**
(`y_std = (y - μ)/σ`, μ/σ fixed for the whole run), train the GP in standardized
space, and un-standardize posterior mean/variance for dumps. Then
`signal_variance` bounds of `[1e-3, 10]` are well-conditioned regardless of raw
scale. (Equivalent alternative: set `signal_variance` bounds from the data, e.g.
`[1e-3·var(y), 10·var(y)]`.) For the noise on the **standardized** objective, use the
**value-proportional LEARNED DEFAULT** for fit-metric objectives — `noise_var_std = max((0.10·|y|)/σ, floor)²`
(floor ≈ 0.05·σ_seed → ~1e-6 hard floor), applied at init AND every `tell()`; do **NOT** use the peak-fit
error/χ² as noise (it inflates blank frames → EI clusters on edges). The old flat `max((0.01·mean|y_std|)², 1e-6)`
is only a fallback for non-fit objectives with no meaningful value scale. See `gpcam-customization` §4.

**F. Tie length-scale bounds to sampling & range (guard against sub-spacing).**
On sparse data, length scales collapse below the point spacing (near-interpolation
of noise) or escape to "irrelevant". Set, per input dimension:
- length-scale **lower** bound ≈ median nearest-neighbour point spacing (not 0.01),
- length-scale **upper** bound ≈ the parameter **range** (≈ `1×range`, **not**
  `10×range`),
- a **non-zero** noise floor (don't let fitted/fixed noise → 0).
This keeps fitted scales physical and interior. On genuinely sparse/low-signal
data, also warn that no length scale is well-determined — denser sampling is the
real fix, not bound tuning.

**Persisting dynamic bounds (record honestly).** Because the ℓ bounds above are
recomputed at every `train()` (the lower bound shrinks as data densifies), a single
startup snapshot is misleading — the trained ℓ at later iters will sit *below* the
iter-0 lower bound **by design**, and a static reader misreads it as an
"unenforced-bound" bug. Persist the bounds as they actually move:
- write the **effective** `hp_bounds` used at each `train()` into
  `gp_out/gpcam_hyperparameters.csv` (add `ls_<dim>_lower` / `ls_<dim>_upper` columns), and
- in `gpcam_metadata.json`, store the startup box as **`hyperparameter_bounds_initial`**
  (NOT a bare `hyperparameter_bounds`) and add a **`hyperparameter_bounds_policy`**
  string, e.g. "ℓ lower = median NN spacing of current data; upper = param range".

This is recording-only — it never changes how `train()` behaves or any AE result; it
makes the trace self-consistent and lets writer-cog plot the bound envelope against
the trained ℓ.

### Canonical loop pattern (version-tolerant; incorporates A–C, E)

```python
def _pm(gpo, x, **kw):                    # A: tolerant of the m(x)/f(x) split
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d: return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")

# seeds collected as raw (x_seed, y_seed_raw); fix the standardization once (E):
Y_MU = float(np.mean(y_seed_raw)); Y_SD = float(np.std(y_seed_raw)) or 1.0
y_std = (y_seed_raw - Y_MU) / Y_SD

# ⭐ value-proportional noise on the STANDARDIZED objective (E) — NOT the fit error
FLOOR = 0.05
nv = np.maximum(0.10 * np.abs(y_std), FLOOR) ** 2

gpo = GPOptimizer(x_seed, y_std, init_hyperparameters=hp_init,
                  noise_variances=nv)      # NO kernel/mean/noise fn (D);
                                           # no calc_inv/linalg_mode unless version-probed
gpo.train(hyperparameter_bounds=hp_bounds, method='global')

for it in range(MAX_ITERS):
    # acquisition chosen WITH the user; 'ucb'/'lcb' hardcode beta=3.0 (see Design Choices)
    new_x = gpo.ask(input_set=BOUNDS, n=1, acquisition_function=ACQ)["x"]
    y_obj = measure(new_x)                        # via flag-file loop
    t = (y_obj - Y_MU) / Y_SD                     # standardize (E)
    gpo.tell(new_x, np.array([t]),
             noise_variances=np.array([max(0.10 * abs(t), FLOOR) ** 2]),   # new points only
             append=True)                          # append=True REQUIRED (C)
    gpo.train(hyperparameter_bounds=hp_bounds, method='local')
    mean = _pm(gpo, grid)                          # A — never a hardcoded key
# report best in raw units: best_raw = Y_MU + Y_SD * best_t
```

**Min-step guard (⭐ learned default).** Replace the bare `ask()` above with a candidate
grid + exclusion mask + argmax whenever a min-sample-distance applies — a continuous
`ask()` will otherwise re-propose a point it has already measured:

All numbers come from `config.json → gpcam.sampling` (**the single source of truth** — never
hardcode them here or in the daemon):

**One knob: `min_dist_frac`.** The grid is spaced at exactly the min distance it derives, so
there is nothing else to tune. This is the **coupling INVARIANT** — the candidate grid spacing
= `min_sample_distance` **always**; `min_sample_distance` alone is only an anti-cluster filter,
so a grid coarser than it silently snaps every pick to the grid and the min-step knob no-ops
(run009 bug: min-step 0.01 mm but a 0.05 mm grid → all picks on 0.05). If you build a
**two-stage** coarse→fine grid (region-finder + fine window, as in the orientation daemon),
`coarse_grid_mm` may stay coarser but `fine` spacing MUST derive from `min_sample_distance`,
and auto-size the fine window to tile the coarse spacing (no gaps). Full rule + guard/clamp +
startup-log requirement: **`gpcam-customization` §6** (canonical: `config.template.json` sampling comment).

```python
from scipy.spatial.distance import cdist
s = cfg["gpcam"]["sampling"]
MIN_SAMPLE_DISTANCE = s["min_dist_frac"] * BEAM_SIZE   # beam_size_mm, user-confirmed
spacing = MIN_SAMPLE_DISTANCE                          # grid resolves exactly the mask
if s.get("max_grid_cells"):                            # optional cost cap; usually null
    spacing = max(spacing, span.max() / (s["max_grid_cells"] ** (1 / n_dim)))
acq  = np.concatenate([np.asarray(gpo.evaluate_acquisition_function(c, acquisition_function=ACQ)).ravel()
                       for c in np.array_split(grid, max(1, len(grid) // 500))])   # 8.3.9: sign unchanged; chunked
mask = np.min(cdist(grid, gpo.x_data), axis=1) >= MIN_SAMPLE_DISTANCE
if not mask.any():
    return _stop("grid_exhausted")   # all -inf → argmax silently returns cell 0 forever
new_x = grid[np.where(mask, acq, -np.inf).argmax()][None, :]
```

Log the resulting cell count at start. `max_grid_cells` only bounds the **per-iteration**
acquisition evaluation (a fine 2D grid can reach millions of cells) — it never limits how long
the AE runs, and when set it raises the effective min step to `spacing`, so log that instead.

On the 8.3.9 pin `evaluate_acquisition_function` returns the acquisition with its sign unchanged
(higher = better): take the argmax as is. Negating it, as earlier notes said, turns UCB into an
argmin; in a simulator run that sampled the zero-signal corner.

**Optional capability — resume from seeds.** A daemon may, on startup, ingest
already-measured rows from the result log (objective + position keyed by seq) and
skip re-measuring the seed phase, continuing BO at the next seq. Useful after a
mid-run crash. Self-falls-back to fresh seeding if the log is empty/reset.

## Canonical coordination contract

The flag-file + log contract is defined ONCE in **`docs/flag-file-contract.md`** (the LIVE
11BM-CMS contract, verified in production). op-cog, ana-cog, and gpcam-cog all follow it — do not
redefine names/formats here; coordinate any change across all three cogs in that file. All flag
files + `ana_log.csv` live in `$RUN_DIR` (`os.environ["RUN_DIR"]`), not a fixed `EXCHANGE_DIR`.

## Handshake (gpcam side) — gpCAM drives EVERY point, including seeds

```
init: read ana_log.csv (by seq) for any already-measured rows → init GP → train
loop:
  ask GP → write GPCAM_NEXT.txt (seq,x,y)
  wait for that seq's row to appear in ana_log.csv (keyed by seq) → tell GP
  check convergence → if met OR iterations >= MAX: write GPCAM_STOP.txt, exit
```

**⭐ Sampling + stopping live in `config.json → gpcam.sampling` / `gpcam.stopping`.** That block is
the single source of truth; read it, never restate or hardcode the numbers. Rationale for each
default is in `gpcam-customization` §6. Your two obligations:

1. **CONFIRM BEFORE STARTING.** Ask the user for every `must_confirm` field — currently
   `beam_size_mm` and `no_improvement_patience`. Never assume either.
2. **ANNOUNCE THE RESOLVED VALUES.** In the Step-2 presentation and the first `gpcam_log.txt`
   line, state what will actually run — effective min step (in µm, with the fraction and beam it
   came from) and the stopping values — flagged as defaults the user can change.

Behaviour follows the config values directly, with no extra logic here:
`no_improvement_patience: null` means never self-stop, i.e. run until someone runs
`touch $RUN_DIR/GPCAM_STOP.txt` (gpcam checks it before every BO iteration and inside every wait;
op/ana already exit on it, so no extra flag is needed). `analysis_wait_timeout_s` is a
per-iteration hang detector, not a run budget.

There is **no** `SEEDS_DONE.txt` wait and **no** `OP_DONE.txt` — those were simulator-era. gpCAM
reads `ana_log.csv` keyed by `seq` (not `op_log.csv`, not a single "last row"), and every `_wait_*`
must break on its own stop condition so it cannot hang after a stop.
A NaN/empty objective row (failed fit or missing frame) is never told to the GP, but its position is masked (never proposed again) and it counts toward `max_iters`.


## Self-review checklist
Before finishing, verify:
Noise model: fit-metric objective → value-proportional LEARNED DEFAULT max((0.10*|y|)/Y_SD, floor)^2 (NOT fit-error/chi2); flat max((0.01*mean|y_std|)^2, 1e-6) only as fallback for non-fit objectives
every custom acquisition returns a 1-D array of length len(x), higher = better, no NaN/inf
the acquisition was chosen WITH the user and the reasoning is a comment in the daemon
if minimizing: 'lcb'/'minimum'/a negating callable is used — NOT EI/PI/UCB/KG/NEI (they maximize silently)
if a tuned beta is needed: a callable is used, not the 'ucb'/'lcb' string (beta is hardcoded to 3.0)
ask()["x"] is used, not the raw result; the acquisition value goes through _acq_val()
posterior_mean goes through the tolerant _pm() helper — NO hardcoded ["m(x)"] or ["f(x)"] (A)
posterior_covariance(x, variance_only=True)["v(x)"] is used; full matrix key is ["S"] not ["S(x)"]
posterior_mean_grad(x)["dm/dx"] is called WITHOUT a positional 2nd arg (direction is the 4th param)
evaluate_acquisition_function results are used as returned (sign unchanged on 8.3.9, no negation) and evaluated in chunks on a large grid
tell(..., append=True) passes append=True explicitly; its noise_variances covers only the M new points
cumulative data is read via gpo.x_data / gpo.y_data attributes (not get_data() keys)
no kernel_function / prior_mean_function / noise_function kwargs are emitted (D)
no calc_inv / linalg_mode / gp2Scale_* / rank_n_update kwarg unless the version was probed (names differ across 8.3/8.4)
gpcam_metadata.json records the probed gpcam.__version__ and fvgp.__version__
objective is standardized (or signal_variance bounds are scaled to the data) so signal_var is not pinned at its bound
length-scale bounds are tied to point spacing (lower) and range (upper, ~1x not 10x); noise floor is non-zero
if ℓ bounds are dynamic (Rule F), the hyperparameter trace records per-iter effective bounds and metadata labels the startup box hyperparameter_bounds_initial + records hyperparameter_bounds_policy
x_data shape is (N, 1) for 1D temperature inputs
y_data shape is (N,)
init_hyperparameters length is 2 for 1D
Flag names match the contract exactly
the new result is read from ana_log.csv keyed by seq (no OP_DONE.txt / SEEDS_DONE.txt — simulator-era)
ana_log.csv header is skipped when parsing
gpcam_log.csv has the correct columns
GPCAM_STOP.txt is written on every terminal state as `STOP` + a second line with the reason: converged, max_iters_reached, grid_exhausted, wait_timeout (no result within analysis_wait_timeout_s), error (docs/flag-file-contract.md); it is honoured, not written, when a user creates it
save_intermediate_csv is called after every iteration, if required by the active workflow
No subprocess calls are used for operator or analysis scripts

## Additional Resources
1. [reference.md](reference.md) - detailed gpCAM docs