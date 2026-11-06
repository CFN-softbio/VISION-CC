# Choosing an Acquisition Function (11BM)

Companion to `../SKILL.md` §2. Open this when picking *which* acquisition to run — the
SKILL section covers the contract and the recipes; this file covers the decision and the
gpCAM behaviors that silently differ from the textbook definitions.

**Code convention here is version-tolerant.** The posterior-mean key is `"m(x)"` on
gpCAM 8.2.4 → 8.4.x (source-verified) and *claimed* `"f(x)"` on the 8.1.13 pin, so every
snippet below goes through a helper rather than hardcoding either — see
`gpcam-cog/reference.md` → **VERSION MATRIX**:

```python
def _pm(gpo, x, **kw):
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d: return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")
```

`posterior_covariance(x, variance_only=True)["v(x)"]`, `ask(...)["x"]`, `gpo.y_data`, and
`tell(..., append=True)` are stable across every version.

---

## 0. Availability — read before recommending a string

**Fourteen** built-in strings exist in 8.4.x, verified by reading
`surrogate_model.py:218-283`. `reference.md` previously documented only five for the
claimed 8.1.13 pin:

| Tier | Strings | Use |
|---|---|---|
| **Documented for the claimed 8.1.13 pin** | `"variance"`, `"expected improvement"`, `"relative information entropy"`, `"relative information entropy set"`, `"total correlation"` | Safe to pass as a string on any version. |
| **Present 8.2.4 → 8.4.x (source-verified)** | `"ucb"`, `"lcb"`, `"maximum"`, `"minimum"`, `"gradient"`, `"probability of improvement"`, `"target probability"` | Available once the install is probed at ≥8.2.4. Until then, use the callable form. |
| **8.4-era additions** | `"knowledge gradient"`, `"noisy expected improvement"` | 8.4+ only. |

Passing an absent string raises `Exception("No valid acquisition function string
provided…")` — loud, not silent, but still a wasted beamtime iteration. **Multi-task
(`x_out is not None`) implements only nine** — see the `multi-task-advanced` skill.

**The resolution: custom callables work on every version.** `acquisition_function` is an
`ask()` argument, not a constructor argument, so unlike `kernel_function` /
`noise_function` / `prior_mean_function` it is unaffected by whatever the constructor
does or doesn't accept. §2 of `../SKILL.md` is therefore the one customization surface
that is safe regardless of the pin. **When you need UCB with a tuned β, LCB, PoI,
gradient, or a threshold finder, write the callable.** It is four lines and version-proof.

> ✅ **Resolved:** `args` *does* reach acquisition functions — but **through the `gpo`
> object**, not as a call parameter. gpCAM's own acquisitions read it via
> `getattr(gpo, "args", None)` (`surrogate_model.py:343`), and callables are invoked as
> exactly `acquisition_function(x, gpo)`. Set `GPOptimizer(..., args={...})` or
> `gpo.args = {...}` and read it off `gpo` inside the callable. Note `ask(args=…)`
> **overwrites** `self._args` permanently rather than overriding for one call.
> `functools.partial` still works, but only for **keyword** parameters.

---

## 1. The meta-rule

**The scientist's opening sentence almost never determines the acquisition function.
One follow-up question usually does.**

Never pick silently, and never default to `"expected improvement"`. State your
recommendation, state its one tradeoff, and confirm. Put the reasoning in a comment in
the generated daemon so the choice stays revisitable.

The single most useful disambiguation: **"find the best conditions"** covers two
different experiments.

- *the single best point* — they'll park the instrument there and run production; the
  rest of the space is disposable → exploitation-leaning
- *a trustworthy map that contains the best point* — they need to see the landscape,
  report it, or find secondary features → exploration-leaning

Also worth saying out loud: **the acquisition is an argument to `ask()`, not a property
of the GP.** Exploring first and switching to exploitation once the posterior is
informative is often the right design, and it costs one line.

### Decision table

| They say… | Start from | Tradeoff to state out loud |
|---|---|---|
| "map the whole space" / "replace my raster scan" | `"variance"` | even confidence everywhere; won't refine the peak |
| "find where the signal *changes*" / "where's the edge" | `radical_gradient` callable | targets changing regions; ignores flat ones even if unmeasured |
| "find the single best point, I have limited time" | `ucb` callable, `beta≈2` | exploits toward the max; needs the min-step guard (§4) |
| "find the best point, my data is noisy" | `"noisy expected improvement"` if the install is ≥8.4; otherwise `ucb` callable with larger `beta` | NEI integrates over the posterior of the incumbent instead of trusting the largest noisy reading — the statistically correct answer, but 8.4+ only |
| "the loop has stalled, it keeps re-suggesting near the same point" | `"knowledge gradient"` (8.4+), else `"variance"` for a stretch | KG reasons about the *fantasized* posterior max, so it escapes; check the min-step guard (§6) first |
| "it keeps re-measuring the same spot" | see §6 — this is usually the min-step guard, not the acquisition | — |
| "find where the signal crosses X" | `threshold_finder` callable | concentrates on one level set; rest stays coarse |
| "find conditions where output ≈ X" | `target_band` callable | same — a band, not a global map |
| "**minimize** this" | `lcb` callable | **not** EI/PI/UCB — all hardcode maximization |
| "give me N points per round" | `"total correlation"` or `"relative information entropy set"` | any other string is silently overridden — caveat (e) |
| "I already know roughly where the peak is, refine it" | `"expected improvement"` | greedy; assumes the incumbent is known exactly — caveat (c) |
| "I don't know yet" | `"variance"` for the first ~20 points, then revisit | you can change it between `ask()` calls |

---

## 2. Archetypes

### 2.1 Peak finding — "maximize my prefactor / ring intensity"

**Ask back:** *"Do you want the single best point, or a map that contains it? And how
noisy is one frame?"*

The 11BM default is explore-then-exploit, because a fit-metric objective is noisy and
the early posterior is not worth exploiting against:

```python
# Explore first, then exploit. Acquisition is per-ask(), so this is free.
for it in range(MAX_ITERS):
    acq = "variance" if it < N_EXPLORE else ucb      # ucb = callable, see SKILL §2
    new_x = gpo.ask(BOUNDS, n=1, acquisition_function=acq)["x"]
    y_raw = measure(new_x)                            # via the flag-file loop
    t = (y_raw - Y_MU) / Y_SD                         # standardize (gpcam-cog Rule E)
    gpo.tell(new_x, np.array([t]),
             noise_variances=np.array([nv(t)]), append=True)
    gpo.train(hyperparameter_bounds=hp_bounds, method="local")
```

**Why not plain EI by default** — two gpCAM-specific reasons, both in §3: its EI anchors
to the largest *noisy* reading (c), and until the posterior mean somewhere exceeds that
incumbent, gpCAM's EI is algebraically `0.3989·σ(x)` — identical in ranking to
`"variance"` (a). Early in a run it is not exploiting at all.

### 2.2 Mapping — "replace my raster scan over smx/smy"

**Ask back:** *"Uniform quality everywhere, or is some region more important?"*

- Uniform → `"variance"`
- Sharper, slower → `"relative information entropy"`
- Some regions matter more → `"variance"` times a weight (see the constrained recipe in SKILL §2)

This is the archetype where an optimization acquisition does real damage: EI or UCB
concentrates shots near the maximum and leaves the rest of the map at raster quality or
worse — the opposite of what was asked for.

### 2.3 Change mapping — "find the phase boundary / the film edge"

The scientist wants *derivative* structure, not an extremum.

**Ask back:** *"One transition you need located precisely, or several features of
different sharpness you want all characterized?"*

- One dominant transition → the built-in `"gradient"` (`‖∇m‖·σ`), or the callable below
  without the square root
- Several features, differing steepness → `radical_gradient`, `√‖∇m‖·σ`

The square root softens the gradient weighting so the uncertainty term carries relatively
more weight; sampling spreads across every changing region instead of piling onto the
single steepest ridge.

```python
def radical_gradient(x, gpo):
    """sqrt(||grad m(x)||) * sigma(x) — spreads across all changing regions."""
    g = gpo.posterior_mean_grad(x)["dm/dx"]              # (V, D) FULL gradient
    std = np.sqrt(np.maximum(
        gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-10))
    return np.sqrt(np.linalg.norm(g, axis=1)) * std
```

> ✅ **Resolved — call it with `x` only.** The real signature is
> `posterior_mean_grad(x_pred, hyperparameters=None, x_out=None, direction=None)`, so
> `direction` is the **fourth** parameter: the old `posterior_mean_grad(x, direction)`
> form passed `direction` as *hyperparameters* and silently returned the wrong thing
> rather than raising. Omitting it returns the full `(V, D)` gradient, which is what
> `np.linalg.norm(g, axis=1)` needs. The return key `"dm/dx"` is confirmed
> (`fvgp/gp_posterior.py:93`), and this is exactly how the built-in `"gradient"`
> acquisition calls it (`surrogate_model.py:241`).

Swapping between the two forms is a one-line change — say so, and let the scientist try
both on the same data.

### 2.4 Boundary / threshold — "find where the signal crosses X"

**Ask back:** *"Is X a hard number, or a band?"* A band means 2.5 instead.

```python
def threshold_finder(x, gpo):
    threshold = 0.5     # EDIT — in the GP's modeling space (standardized, if Rule E applies)
    mean = _pm(gpo, x)
    std = np.sqrt(np.maximum(
        gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-10))
    eps = 0.01 * np.std(gpo.y_data) + 1e-12    # scale-aware, NOT a hardcoded 0.01
    return std / (np.abs(mean - threshold) + eps)
```

The scale-aware epsilon matters: a fixed `0.01` is meaningful only when `y` is O(1). On
raw detector counts it's negligible and the acquisition becomes a near-singular spike; on
data of order `1e-3` it dominates and the acquisition goes flat. Both degrade silently.
(If Rule E standardization is on, `y` is already O(1) — but the daemon shouldn't depend
on that staying true.)

Warn them that everything away from the level set stays coarsely sampled. If they also
want a usable map, alternate with `"variance"`.

### 2.5 Target value — "give me conditions where output ≈ X"

Common in synthesis and alignment: not a maximum, a specification. A built-in
`"target probability"` exists on 8.2.4+ but reads its band from `gpo.args["a"]` /
`gpo.args["b"]` and raises if `args` is unset — so unless you have probed the install and
set `args`, write the callable:

```python
from scipy.stats import norm

def make_target_band(lo, hi):
    """P(lo < f(x) < hi). Bounds are in the GP's modeling space — standardize them
    the same way the objective is standardized (Rule E)."""
    def target_band(x, gpo):
        mean = _pm(gpo, x)
        std = np.sqrt(np.maximum(
            gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-10))
        return norm.cdf((hi - mean) / std) - norm.cdf((lo - mean) / std)
    return target_band
```

### 2.6 Minimization — "minimize my background"

**This is where a reflexive EI recommendation is outright wrong.** gpCAM's
`"expected improvement"`, `"probability of improvement"`, `"ucb"`, and `"maximum"` all
hardcode a maximum (`np.max(gpo.y_data)` or the raw posterior mean), so they hunt maxima
with no error raised.

```python
def lcb(x, gpo):
    beta = 2.0     # TUNE
    mean = _pm(gpo, x)
    std = np.sqrt(np.maximum(
        gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-10))
    return -(mean - beta * std)     # negated: gpCAM MAXIMIZES the acquisition
```

An alternative some scientists prefer: negate the objective in the analysis step and keep
maximizing. Cleaner, but remember to flip the sign back in the report — and tell
writer-cog.

### 2.7 Batch — "N points per round"

**Ask back:** *"Do the N points need to be jointly informative, or are N independent
suggestions fine?"* Jointly informative is the entire reason batch acquisition exists —
N copies of the same greedy suggestion is worthless.

```python
result = gpo.ask(BOUNDS, n=5, acquisition_function="total correlation")
next_x = result["x"]        # shape (5, D)
```

See caveat (e) — with `n > 1` and a *string* acquisition, gpCAM silently substitutes
`"total correlation"` for whatever you asked for.

### 2.8 Multi-task — "each measurement returns a spectrum"

`fvGPOptimizer` with `x_out`. Mapping/exploring → `"relative information entropy set"` or
`"variance"`. **Do not use plain EI** — see caveat (d). The proper alternatives
(`"knowledge gradient"`, `"noisy expected improvement"`) exist only on 8.4+; on an older
install, multi-task *optimization* means extracting a derived scalar in ana-cog and
running single-task. Only nine strings are implemented on the `x_out` branch at all — see
the `multi-task-advanced` skill.

### 2.9 Cost-constrained — "moving smy takes 4 minutes"

The acquisition stays whatever the science calls for; cost is a separate argument.
gpCAM divides the acquisition by the cost function — so an expensive move must earn its
score.

```python
next_x = gpo.ask(BOUNDS, acquisition_function="variance",
                 position=current_motor_position)["x"]   # position= is REQUIRED
```

**Omitting `position=` silently disables cost-awareness** — gpCAM applies the cost only
when `origin is not None`. See SKILL §5 for the full contract. Note this does not survive
the §6 grid+mask pattern: if you're doing your own argmax, you must divide by cost
yourself.

---

## 3. gpCAM behaviors that silently differ

Properties of gpCAM's implementation, not of the textbook definitions. Tell the scientist
about any that apply to their choice.

**(a) EI degenerates to pure exploration early in a run.** gpCAM clips the improvement
*before* forming the ratio, rather than after:

```python
a = (m - last_best); a[a < 0.] = 0.       # clipped BEFORE gamma, unlike textbook EI
gamma = a / (std + 1e-9)
return std * (gamma * cdf + pdf)
```

At every candidate whose posterior mean sits **below** the incumbent, `gamma == 0` and
the score collapses to `σ·φ(0) = 0.3989·σ` — the `"variance"` acquisition up to a
positive constant. Until the posterior mean somewhere exceeds the best observed value,
gpCAM's EI *is* pure exploration. Never tell a scientist "EI will exploit toward the
maximum" without this caveat. (Upstream: [lbl-camera/gpCAM#55](https://github.com/lbl-camera/gpCAM/issues/55);
source line numbers cited upstream are 8.4.x — the behavior, not the line, is the claim
here.)

> **This is a second, independent cause of the edge-piling we already fixed at 11BM.**
> SKILL §4's ⭐ noise default attributes points piling on the box edges to using the
> peak-fit error as the noise (blank frames look high-uncertainty). Caveat (a) says that
> *whenever EI hasn't yet found a mean above the incumbent, EI is variance* — which also
> sends shots to the least-sampled regions, i.e. the corners. Both are real, they
> compound, and the value-proportional noise fix only addresses the first. If edge-piling
> persists after the noise fix, this is why.

**(b) EI, PI, UCB, and `"maximum"` are maximization-only.** If the scientist is
minimizing, every one of them misbehaves with no error. Use the `lcb` callable (2.6).

**(c) Plain EI/PI anchor to a noisy observation.** The incumbent is `np.max(y_data)` —
the largest *measured* value, not the posterior mean at that location — so on noisy data
EI over-exploits around a noise spike. `"noisy expected improvement"` exists precisely to
fix this — it integrates over the posterior of the incumbent rather than trusting the
largest reading — but it is **8.4+ only**. On an older install, prefer a UCB callable, or
swap the incumbent for the model's own estimate inside a custom EI:
`y_best = np.max(_pm(gpo, gpo.x_data))`.

**(d) Multi-task plain EI is dimensionally incoherent.** The `x_out` branch sums the
posterior mean across tasks and *sums* the standard deviations across tasks, then
compares that against `np.max(gpo.y_data)` of a scalar. Summed std is not the std of the
sum — that needs the cross-task covariance. No error is raised.

**(e) `ask(n>1)` silently rewrites string acquisitions.** With an array `input_set`,
`n > 1`, `method != "hgdl"`, and a *string* acquisition, gpCAM replaces whatever was
requested with `"total correlation"` and emits a warning. Batch EI is not EI. Either ask
for a batch-aware acquisition deliberately, or pass a callable with `method="hgdl"` and a
Dask client.

**(f) `"ucb"` / `"lcb"` hardcode `beta = 3.0`.** The strings expose no tuning. To change
the exploration/exploitation balance you must pass the callable form.

> `gpcam-cog`'s Design Choices table used to say UCB "exposes a tunable
> exploration/exploitation tradeoff via `beta`" — true of the callable, false of the
> string. That table has been corrected; keep the distinction when you write either one.

**(g) The acquisition is maximized, and public evaluation helpers return higher-is-better.**
Any custom callable must return a 1-D array where higher = more desirable. If you
evaluate an acquisition yourself for the §6 grid pattern, don't negate it — and don't
double-negate a helper's output.

---

## 4. Interaction with the 11BM min-step guard

`gpcam-cog`'s ⭐ learned default does **not** take a raw continuous `ask()`. It evaluates
the acquisition on a candidate grid, masks any cell within `min_sample_distance` of an
existing measurement, and takes the argmax. Consequences for everything above:

- **The acquisition must be evaluable on an arbitrary grid**, which every callable in
  this file already is: `score = acq(X_grid, gpo)`, then `score[masked] = -np.inf`,
  then `argmax`. Callables are strictly more convenient here than strings.
- **"It keeps re-measuring the same spot" is usually the missing mask, not the
  acquisition.** Check the guard before changing acquisition — swapping EI for something
  else will not fix sub-beam resampling.
- **Cost functions don't apply automatically** (2.9): `position=` only works through
  `ask()`. Doing your own argmax means dividing by cost yourself.
- **Batch caveat (e) doesn't bite**, because you aren't going through `ask(n>1)`.

---

## Quick reference

Version-proof column first: a callable works on every install. The string column is what
to prefer **once you have probed `gpcam.__version__`** on the beamline host.

| Goal | Version-proof choice | If probed ≥8.4 | Never use |
|---|---|---|---|
| Map the space | `"variance"` (all versions) | `"relative information entropy"` for sharper | EI, UCB |
| Map changes / transitions | `radical_gradient` callable | `"gradient"` (8.2.4+) | `"maximum"` |
| Find the max | `ucb` callable (tunable β) | `"ucb"` if β = 3.0 is acceptable | plain EI early — it *is* variance (a) |
| Refine a known max, low noise | `"expected improvement"` | same | — |
| Find the max, noisy data | `ucb` callable, larger β | `"noisy expected improvement"` | plain EI (c) |
| Loop stalled / re-suggesting | check the §6 mask first | `"knowledge gradient"` | — |
| Find the min | `lcb` callable | `"lcb"` (β = 3.0) / `"minimum"` | EI, PI, UCB, `"maximum"` |
| Hit a target value | `target_band` callable | `"target probability"` + `gpo.args` | EI |
| Find a level set | `threshold_finder` callable | — (no built-in) | EI |
| Batch | `"total correlation"`, `"relative information entropy set"` | same | any other string (silently overridden) |
| Multi-task, exploring | `"relative information entropy set"`, `"variance"` | same | plain EI (d) |
| Multi-task, optimizing | extract a scalar in ana-cog, go single-task | `"knowledge gradient"` / `"noisy expected improvement"` with `x_out` | plain EI (d) |

All fourteen single-task strings and the nine multi-task strings, with their exact source
formulas, are tabulated in `gpcam-cog/reference.md` → **Acquisition Functions**.
