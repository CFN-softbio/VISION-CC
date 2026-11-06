---
name: gpcam-diagnostics
description: Diagnose a gpCAM run that crashed, stalled, or produced untrustworthy error bars. Maps the actual exception text to the cause and fix (Cholesky/non-PD, bounds mismatch, NaNs, callable-signature, pickling, Dask hangs), covers the silent failures that cost the most beamtime (loop re-picking the same point, edge-piling, hyperparameters training to nonsense, cost function doing nothing), and validates posterior uncertainty with scoring rules and coverage curves. Open this skill when a gpCAM daemon errors, when the AE loop misbehaves without an exception, or before trusting a variance-based stopping criterion.
---

# Skill: gpCAM Diagnostics (troubleshooting · uncertainty calibration)

Two jobs that are really one job: **why did the GP do that, and can I believe it?**

- **Part 1 — Troubleshooting.** From the error you actually saw to the thing that is
  actually wrong. Plus the silent failures that raise nothing.
- **Part 2 — Uncertainty calibration.** Whether the error bars are honest, which is what
  every acquisition function and every variance-based stopping rule is trusting.

Companion to `gpcam-cog` (the loop + file contract) and `gpcam-customization` (kernel,
acquisition, prior mean, noise, cost). API facts and version deltas come from
`gpcam-cog/reference.md` → **VERSION MATRIX**; do not re-derive them here.

**First, read the exception text.** fvGP's common errors carry diagnostics inline. The
Cholesky failure prints `min(diag(M))` and `max|M - M.T|`, which usually identifies the
problem by itself.

**Version-tolerant accessor — use it in every diagnostic snippet:**

```python
def _pm(gpo, x, **kw):
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d: return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")
```

---

# PART 1 — Troubleshooting

## Fast triage

| Error text (first line) | Go to |
|---|---|
| `Cholesky factorization failed: … not positive definite` | [Non-PD covariance](#non-positive-definite-covariance) |
| `index N is out of bounds for axis 0 with size M` (during `train`) | [Bounds mismatch](#hyperparameter-bounds-mismatch) |
| `NaNs encountered in dataset.` | [NaNs](#nans-in-the-data) |
| `No valid kernel function signature` (or mean / noise) | [Callable signature](#wrong-callable-signature) |
| `prior covariance K must be 2-d` | [Kernel shape](#kernel-returns-the-wrong-shape) |
| `'GPOptimizer' object has no attribute 'posterior'` | [Uninitialized GP](#gp-not-initialized-yet) |
| `Reading the arguments for acq func 'target probability' failed.` | [Acquisition args](#acquisition-function-arguments) |
| `No valid acquisition function string provided…` | [Acquisition args](#acquisition-function-arguments) |
| `TypeError: __init__() got an unexpected keyword argument 'gp2Scale_dask_client'` (or `calc_inv`, `linalg_mode`) | version mismatch — `gpcam-cog/reference.md` VERSION MATRIX |
| `LogGPOptimizer requires strictly positive observations` | [Constrained data](#constrained-observations) |
| Script hangs / spawns endless processes | [Dask & multiprocessing](#dask-hangs-and-process-storms) |
| `PicklingError` / `Can't pickle local object` | [Pickling](#pickling-and-checkpointing) |
| **No error, but the loop misbehaves** | [Silent problems](#silent-problems--no-exception) ← most 11BM incidents |

> **Before blaming the GP, check whether it is even the stalled component.** In an 11BM AE
> a "stuck" loop is more often the flag-file handshake than the optimizer. `gpcam_log.txt`
> stops growing but `GPCAM_NEXT.txt` still exists → the operator never picked the
> suggestion up; `TRIGGER.txt` exists with no `ANA_DONE.txt` → analysis is the blocked one.
> See `docs/flag-file-contract.md` and the Liveness Self-Check in `agents/gpcam-cog.md`.

---

## Non-positive-definite covariance

```
NonPositiveDefiniteError: Cholesky factorization failed: the 12x12 prior covariance
matrix is not positive definite.
Diagnostics: min(diag(M)) = ..., max|M - M.T| = ... (should be ~0).
```

The single most common gpCAM crash. Use the printed diagnostics to pick the branch.

**`max|M - M.T|` not ~0 → the kernel is not symmetric.** A kernel must satisfy
`k(x1, x2) == k(x2, x1).T`; look for indexing `x1` where you meant `x2`.

```python
assert np.allclose(my_kernel(x1, x2, hps), my_kernel(x2, x1, hps).T), "kernel not symmetric"
```

**`min(diag(M))` very small or negative → the kernel is not PSD.** Sums and products of
valid kernels are valid; **differences are not**. If you wrote `k1 - k2`, that is almost
certainly it.

```python
K = my_kernel(x_data, x_data, hps)
print("min eigenvalue:", np.linalg.eigvalsh((K + K.T) / 2).min())   # must be >= 0
```

A non-stationary kernel with an input-dependent length scale needs its normalizing
prefactor — see the Gibbs recipe in `gpcam-customization` §1.

**Diagnostics look fine → conditioning.** In order of likelihood:

1. **Duplicate / near-duplicate `x` with tiny noise.** Two identical rows make `K`
   rank-deficient. ⭐ **The classic 11BM failure** — motor positions are reported rounded, so
   without the guard `ask()` returns a point already measured. Diagnose and fix it as under
   *The loop keeps picking the same point* below; dedupe, never jitter.
2. **Noise driven to zero.** A learnable noise hyperparameter pinned at a lower bound of
   `0` removes the diagonal jitter holding the matrix together. Set the noise lower bound
   small but positive (`1e-3`, or `1e-6·var(y)`), never `0`. The ⭐ 11BM
   value-proportional noise already carries a `FLOOR` for exactly this reason.
3. **Length scale collapsed** to its lower bound → every off-diagonal ~0. Raise the bound.
4. **Genuinely ill-conditioned large problem** → `linalg_mode="Chol"` (8.4.x) or the
   `gp2scale-advanced` skill.

---

## Hyperparameter bounds mismatch

```
IndexError: index 2 is out of bounds for axis 0 with size 2
```

Raised during `train()` when a kernel / mean / noise callable reads an index the bounds
array does not cover. **The bounds array length defines the hyperparameter vector length
during training.**

```python
assert len(gpo.hyperparameters) == len(hp_bounds), (
    f"{len(hp_bounds)} bounds rows but {len(gpo.hyperparameters)} hyperparameters")
```

| Component | Hyperparameters (default ARD kernel, D input dims) |
|---|---|
| Kernel | `1 + D` — `hps[0]` signal variance, `hps[1:D+1]` length scales |
| Prior mean | however many it reads, starting at `K = 1 + D` |
| Noise | however many it reads, starting after the mean's |

**The usual root cause is a hardcoded `K = 3`**, correct only for `D = 2`. Derive it:
`K = 1 + x.shape[1]`.

If the indices *overlap* rather than run past the end there is **no error at all** — see
[Silent problems](#silent-problems--no-exception).

---

## NaNs in the data

```
Exception: NaNs encountered in dataset.
```

⭐ **In an 11BM AE this is nearly always a failed measurement reaching `tell()`** — a
dropped frame, a fit that did not converge, an `ana_log.csv` row with an empty metric
column. Filter before telling, and log the skip:

```python
ok = np.isfinite(y_new)
if ok.any():
    gpo.tell(x_new[ok], y_new[ok], noise_variances=nv[ok], append=True)
else:
    log("iter %d: all measurements non-finite, skipping tell" % it)
```

Do **not** impute a value — a fabricated point pulls the posterior toward a number nobody
measured, and the GP has no way to know.

**Exception — multi-task.** For `fvGPOptimizer`, `NaN` in `y_data` legitimately means
"this task was not measured here"; the matching `noise_variances` entry **must also** be
`NaN`. A `NaN` in `y` with a finite noise entry is an error.

---

## Wrong callable signature

```
Exception: No valid kernel function signature
```

gpCAM dispatches on **parameter count**, via `inspect.signature`:

| Callable | Without `args` | With `args` |
|---|---|---|
| Kernel | `f(x1, x2, hps)` | `f(x1, x2, hps, args)` |
| Prior mean | `f(x, hps)` | `f(x, hps, args)` |
| Noise | `f(x, hps)` | `f(x, hps, args)` |
| Cost | `f(origin, x)` | **not supported** |
| Acquisition | `f(x, gpo)` | **not supported as a parameter** — read `gpo.args` |

A default value still counts as a parameter, so `def my_kernel(x1, x2, hps, args=None)` is
a **4**-parameter kernel and will be handed the `args` dict.

Cost and acquisition callables never receive `args` positionally. Acquisitions can still
reach it: gpCAM's own read it via `getattr(gpo, "args", None)`, so set
`GPOptimizer(..., args={...})` or `gpo.args = {...}`. For cost functions use a closure or
`functools.partial` — but see [Pickling](#pickling-and-checkpointing) first.

---

## Kernel returns the wrong shape

```
AssertionError: prior covariance K must be 2-d
```

The kernel must return `(len(x1), len(x2))`. Common causes: a `np.sum` without `axis=`, a
distance matrix reduced along an axis, or forgetting that `x1`/`x2` are always 2-D even
for 1-D inputs (`x[:, 0]`, not `x`).

```python
K = my_kernel(x1, x2, hps)
assert K.shape == (len(x1), len(x2)), f"got {K.shape}, expected {(len(x1), len(x2))}"
```

---

## GP not initialized yet

```
AttributeError: 'GPOptimizer' object has no attribute 'posterior'
```

`GPOptimizer()` constructed without `x_data`/`y_data` defers building the underlying
`fvgp.GP` until the first `tell()`; until then `posterior_mean`, `train`, `ask`, and most
properties are unavailable. `gpo.gp` is the boolean that tracks this.

11BM daemons should not hit this — the canonical pattern constructs the optimizer **from
the seed rows** of `ana_log.csv`, so data is present from line one. If you see it, the
daemon started before the seed phase finished: wait on the seed count, don't construct empty.

---

## Acquisition function arguments

```
Exception: Reading the arguments for acq func `target probability` failed.
```

`"target probability"` needs an interval in `args`:

```python
gpo.args = {"a": 1.0, "b": 2.0}      # or GPOptimizer(..., args={...})
gpo.ask(bounds, acquisition_function="target probability")
```

⚠️ Bounds are in the **GP's modeling space** — if the objective is z-scored (Rule E),
standardize `a`/`b` the same way. With a transformed optimizer pass them already
transformed (`np.log(a)` for `LogGPOptimizer`). Note `ask(args=…)` **overwrites**
`gpo._args` permanently rather than overriding for one call.

```
Exception: No valid acquisition function string provided…
```

The string does not exist **on this version**. Fourteen exist single-task on 8.4.x, nine
on the multi-task (`x_out`) branch, and fewer on older pins — see
`gpcam-customization/references/choosing-an-acquisition-function.md` §0 for the tiers.
`"maximum"`, `"minimum"`, `"gradient"`, `"probability of improvement"`, and
`"target probability"` are **single-task only**. The version-proof fix is a callable.

A custom callable must return a **1-D array of length `len(x)`**. A scalar or a `(V, 1)`
column raises further down, far from the callable.

---

## Constrained observations

```
ValueError: LogGPOptimizer requires strictly positive observations (y > 0).
```

A zero or negative value reached a `LogGPOptimizer`. If zeros are physically meaningful (a
genuinely empty detector bin), add a floor appropriate to the instrument, or use a plain
`GPOptimizer` and accept that the posterior can go negative.

`LogitGPOptimizer` clips boundary values to `[eps, 1-eps]` with a warning rather than
raising. Frequent clipping at `1e-6` produces enormous latent values and an
ill-conditioned GP — raise `eps` (e.g. `1e-4`).

---

## Dask hangs and process storms

Endless processes or a hang at startup is almost always a missing entrypoint guard.
Dask/`multiprocessing` re-imports the module in each worker; without the guard,
module-level code creates another cluster, recursively.

```python
if __name__ == "__main__":       # REQUIRED whenever a Dask client is involved
    main()
```

- **Workers not ready** → `client.wait_for_workers(n)` before constructing a gp2Scale GP.
- **Two live GPs on one client** → scatter race conditions; use a separate client.
- **`method="hgdl"` without a client** → HGDL needs `dask_client=`.
- **Async training left running** → `train(asynchronous=True)` returns immediately; call
  `gpo.stop_training(opt_obj)` and `kill_client()` or the process never exits.

⭐ **11BM note:** a gpCAM daemon that will not die on `GPCAM_STOP.txt` is usually this last
one. Prefer synchronous `train(method="local")` in the loop; a beamline AE retrains on a
few hundred points and does not need async.

---

## Pickling and checkpointing

```
PicklingError: Can't pickle local object 'make_cost.<locals>.cost'
```

`GPOptimizer` instances pickle, but **attached callables must pickle by reference**, i.e.
be defined at **module level**. A closure or a lambda defined inside a function cannot.

```python
# Breaks pickling:
def make_cost(speed):
    def cost(origin, x): return 1.0 + speed * np.linalg.norm(x - origin, axis=1)
    return cost

# Pickles fine:
from functools import partial
def cost(origin, x, speed): return 1.0 + speed * np.linalg.norm(x - origin, axis=1)
gpo.cost_function = partial(cost, speed=2.5)
```

This is the one reason to prefer `partial` over the closure factories in
`gpcam-customization` §5. If the daemon never pickles the optimizer, closures are fine.
Reloading arrays containing Python objects needs `np.load(path, allow_pickle=True)`.

---

## Silent problems — no exception

The failures that cost the most beamtime.

### The loop keeps picking the same point (or a corner)

Check in this order — the first two are 11BM-specific and by far the most common:

1. ⭐ **The min-sample-distance guard is missing or wrong.** Without the candidate grid + mask,
   nothing stops `ask()` from re-proposing a point it already measured. Confirm before
   touching the acquisition:
   ```python
   from scipy.spatial.distance import pdist
   print("closest pair:", pdist(gpo.x_data).min(),
         "vs MIN_SAMPLE_DISTANCE", MIN_SAMPLE_DISTANCE,   # config.json gpcam.sampling
         "vs beam", BEAM_SIZE)
   ```
   Below `MIN_SAMPLE_DISTANCE` → the guard is broken. Above it but well below `BEAM_SIZE` →
   the guard works and the complaint is about the setting: raise `min_dist_frac` toward 1.0.
   Swapping acquisition will not fix sub-beam resampling.
2. ⭐ **Edge-piling from the wrong noise model.** Using peak-fit error as the noise makes
   blank frames look high-uncertainty, so the loop walks to the corners. The ⭐ 11BM
   default is **value-proportional** noise (`0.10·|y|`, floored), not fit error. A second,
   independent cause compounds it: until the posterior mean exceeds the incumbent,
   gpCAM's EI is algebraically `0.3989·σ(x)` — *identical in ranking to `"variance"`*, so
   early EI also runs to the least-sampled corners. Both are real; fixing the noise only
   addresses the first.
3. **Hyperparameters are stale.** A wildly wrong length scale produces a nearly flat
   acquisition, and the optimizer returns an arbitrary point — often a bound. Retrain
   more often.
4. **Length scale collapsed** → every unmeasured point looks equally uncertain. Check for
   a hyperparameter pinned at its lower bound (recipe below) and raise it.
5. **Cost function dominating.** The acquisition is *divided* by the cost, so a large cost
   pins the optimizer next to `origin`. Compare magnitudes with
   `gpo.evaluate_acquisition_function(x_grid)`.
6. **`n > len(candidates)`** on a discrete set — you get the whole set back.

### The cost function seems to do nothing

`cost_function` applies **only when `origin is not None`** — you must pass
`ask(..., position=current_position)`. Without it gpCAM silently ignores the cost.

⚠️ And it does **not** apply at all under the ⭐ 11BM grid+mask+argmax pattern, which
bypasses `ask()`'s internal optimizer. Doing your own argmax means dividing by cost
yourself.

### Hyperparameters train to nonsense / the likelihood is flat

Two components are reading the same index. fvGP requires the index ranges used by kernel,
mean, and noise to be **disjoint**, and assumes a mean's hyperparameter has zero kernel
derivative — an overlap corrupts the gradients too. Standard ordering is **kernel, then
mean, then noise**; never read `hps[-1]` in a prior mean.

Test that a hyperparameter actually matters:
```python
h1 = gpo.hyperparameters.copy(); h2 = h1.copy(); h2[i] *= 1.5
assert not np.isclose(gpo.log_likelihood(hyperparameters=h1),
                      gpo.log_likelihood(hyperparameters=h2)), f"hps[{i}] does nothing"
```

A related silent case: a deep kernel whose recipe never calls `set_weights` /
`set_biases`. The network keeps its random initialization, the NN hyperparameters have no
effect, and training wanders over an exactly flat likelihood.

### Results change between runs

`method="global"` uses `differential_evolution`, which is stochastic. Seed
`np.random.seed(...)`, raise `max_iter`, or use `method="mcmc"`. Large run-to-run swings
usually mean the likelihood surface is flat or multi-modal — often too little data for the
number of hyperparameters.

### Error bars look wrong

Do not diagnose this by eye — go to Part 2. **An overconfident model can have excellent
RMSE.**

---

## General debugging recipe

```python
# 1. Does the kernel behave on its own, before any GP is involved?
K = my_kernel(x_data, x_data, init_hps)
assert K.shape == (len(x_data), len(x_data))
assert np.allclose(K, K.T), "not symmetric"
print("min eigenvalue:", np.linalg.eigvalsh((K + K.T) / 2).min(), "(want >= 0)")

# 2. Do the counts line up?
print(f"bounds rows {len(hp_bounds)}, hyperparameters {len(gpo.hyperparameters)}")

# 3. Is the data clean?
print("x NaN:", np.isnan(x_data).any(), " y NaN:", np.isnan(y_data).any())
from scipy.spatial.distance import pdist
print("closest pair:", pdist(x_data).min(), "(near 0 -> duplicates)")

# 4. Turn on gpCAM's logging for the training loop
from loguru import logger; logger.enable("gpcam")
gpo.train(hyperparameter_bounds=hp_bounds, info=True)

# 5. Are any hyperparameters pinned at their bounds after training?
for i, (h, (lo, hi)) in enumerate(zip(gpo.hyperparameters, hp_bounds)):
    if np.isclose(h, lo) or np.isclose(h, hi):
        print(f"  hps[{i}] = {h:.4g} pinned at bound [{lo}, {hi}] -- widen it")
```

**Step 5 is worth running routinely** — a pinned hyperparameter is the fingerprint of a
bound that is too tight, and it precedes most of the failures above. ⭐ At 11BM the
per-iteration `gpcam_hyperparameters.csv` already logs the trace; plot each column against
`iter` and look for a flat line sitting exactly on a bound.

---

# PART 2 — Uncertainty calibration

A GP's headline product is not the prediction — it is the *uncertainty on* the prediction.
An autonomous loop acts on that uncertainty at every step: `"variance"` goes where the
model claims ignorance, `ucb`/EI weigh mean against spread, and any convergence rule that
stops when variance falls below a threshold is trusting the error bar completely. **An
overconfident GP stops early, under-samples the interesting region, and reports a wrong
error bar with conviction.**

## ⚠️ Which metrics exist on your install

Source-verified across local installs. **`picp`, `mpiw`, `coverage_curve`,
`interval_score`, `msll`, and `evaluate_posterior` are NOT on older pins** — calling them
raises `AttributeError`, which is a wasted beamtime iteration if it happens inside a live
daemon.

| Method | fvgp 4.6.x (gpcam 8.2.x) | fvgp 4.7.9 (8.3.7) | fvgp 4.8.x (8.4.x) |
|---|---|---|---|
| `rmse`, `nlpd`, `crps`, `r2`, `log_likelihood` | ✅ | ✅ | ✅ |
| `nrmse`, `picp` | ❌ | ✅ | ✅ |
| `msll`, `mpiw`, `interval_score`, `coverage_curve` | ❌ | ❌ | ✅ |
| `mae`, `mape`, `evaluate_posterior`, `plot_observed_vs_predicted` | ❌ | ❌ | ✅ |

**Guard every optional metric** rather than assuming:

```python
def _metric(gpo, name, *a, **kw):
    """Call an fvgp metric if this version has it; return None otherwise."""
    fn = getattr(gpo, name, None)
    return fn(*a, **kw) if callable(fn) else None
```

The z-score check below uses only `posterior_mean` + `posterior_covariance`, so **it works
on every version** — prefer it when the install is unprobed.

## The one-minute check

```python
# Hold out data the GP has never seen. A RANDOM split — not the tail of the loop.
print(f"RMSE  {gpo.rmse(x_test, y_test):.4f}")     # accuracy only
print(f"NLPD  {gpo.nlpd(x_test, y_test):.4f}")     # accuracy + calibration (lower better)
picp = _metric(gpo, "picp", x_test, y_test, interval=0.95)
print(f"PICP  {picp:.3f}  (target 0.95)" if picp is not None else "PICP  n/a on this version")
```

If `PICP ≈ 0.95` and `NLPD` is small, the posterior is roughly trustworthy. If `PICP` is
far from `0.95`, nothing downstream is reliable.

**Shapes must match exactly.** `rmse`/`nlpd`/`crps` assert
`posterior_mean(x_test).shape == y_test.shape` — for a single-task GP `y_test` must be
`(V,)`, not `(V, 1)`.

⚠️ **`crps` returns a tuple `(mean, std)`**, on every version — unpack it:
```python
crps_mean, crps_std = gpo.crps(x_test, y_test)     # NOT a single float
```

## The metrics

| Method | What it measures | Reading it |
|---|---|---|
| `rmse` | Accuracy of the mean only | Lower better. **Blind to uncertainty** — absurd error bars can still give excellent RMSE. |
| `nrmse` | RMSE / range(y) | Dimensionless; compare across datasets. 8.3.7+. |
| `r2` | Fraction of variance explained | 1 perfect, 0 no better than the mean. |
| **`nlpd`** | **Negative log predictive density** | **The primary scoring rule.** Penalizes wrong means *and* wrong spreads. Lower better, can be negative. Use it to choose between models. |
| `crps` | Continuous ranked probability score | Returns `(mean, std)`. In the units of `y`, less brutal than NLPD toward underestimated variance. |
| `msll` | Mean standardized log loss | NLPD relative to a trivial Gaussian baseline. **Negative = you beat the baseline**; ≈0 = the GP learned nothing. 8.4+. |
| `picp(…, interval=q)` | Fraction of test points inside the `q` credible interval | Compare against `q`. The calibration workhorse. 8.3.7+. |
| `mpiw(…, interval=q)` | Mean prediction interval width | Only meaningful **alongside** `picp` — coverage is trivially achievable with absurdly wide intervals. 8.4+. |
| `interval_score` | Coverage and width in one number | Lower better. The right single metric when tuning interval quality. 8.4+. |
| `coverage_curve` | `picp` across many levels | The full calibration picture. 8.4+. |

## The version-proof check — standardized residuals

This needs only `posterior_mean` + `posterior_covariance`, so it runs anywhere, and it
localizes problems that a single scalar hides:

```python
mean = _pm(gpo, x_test)
std  = np.sqrt(np.maximum(
    gpo.posterior_covariance(x_test, variance_only=True)["v(x)"], 1e-12))
z = (y_test - mean) / std          # ~ N(0, 1) if well calibrated

print(f"z mean {z.mean():+.3f} (want 0)   z std {z.std():.3f} (want 1)")
```

- `z.std() > 1` → **over-confident** (intervals too narrow)
- `z.std() < 1` → **under-confident** (intervals too wide)
- `z.mean()` far from 0 → the prior mean is biased

You can also build the coverage curve by hand on any version:

```python
from scipy.stats import norm
for q in np.arange(0.05, 1.0, 0.05):
    k = norm.ppf(0.5 + q / 2)
    measured = (np.abs(z) <= k).mean()
    print(f"  target {q:.2f} -> measured {measured:.3f} "
          f"{'over-confident' if measured < q else 'under-confident'}")
```

| Curve shape | Meaning | Consequence in an AE |
|---|---|---|
| On the diagonal | Well calibrated | Error bars mean what they say |
| **Below** the diagonal | **Over-confident** | Loop stops early, under-explores, publishes error bars that are too small. **The dangerous failure.** |
| **Above** the diagonal | **Under-confident** | Over-explores, wastes measurements; conclusions safe but inefficient |
| S-shaped / crossing | Mis-specified *shape*, not just scale | Usually a wrong noise model or a non-Gaussian likelihood |

Understating the noise variance by 100× on an otherwise identical model moves `PICP@95`
from 0.95 to 0.88 and `NLPD` from 0.23 to 4.21 while RMSE barely moves. **That is why RMSE
cannot be the only check.**

## Diagnosing and fixing

### Over-confident (measured coverage below target)

Most common, most dangerous. In order of likelihood:

1. **Understated observation noise** — `noise_variances` too small, or a noise
   hyperparameter pinned at its lower bound.
   ```python
   print(gpo.get_data()["measurement variances"][:5])
   print(gpo.hyperparameters)     # any noise hp pinned at a bound?
   ```
   ⭐ At 11BM this is the ⭐ value-proportional coefficient being too small for the
   metric — raise it (`0.10·|y|` is the learned default, not a law), or switch to a
   learnable `noise_function` so the data can speak.
2. **Length scale too short** — the GP fits every wiggle, calls the residual signal, and
   leaves no uncertainty between points. Raise the length-scale lower bound.
3. **Wrong noise structure** — heteroscedastic data fitted with constant noise is
   over-confident in the noisy region and under-confident in the quiet one; this is what
   produces the S-shaped curve. Fix with a position-dependent `noise_function`.
4. **Test set is not independent** — see the holdout note below.

### Under-confident (measured coverage above target)

Wasteful rather than dangerous: **overstated noise** (lower the coefficient), **length
scale too long** (check `r2` — poor `r2` *and* under-confident = underfitting), or a
**signal-variance upper bound too high** (an inflated `hps[0]` inflates every interval).

## ⭐ Holdout inside an 11BM AE

**You cannot score against points chosen by `ask()`** — they cluster exactly where the
model was uncertain, so they are not i.i.d. and will flatter or slander the model
arbitrarily. But an AE also cannot afford a large dedicated holdout.

The workable compromise: **reserve ~20% of the *seed* points**, which are random or
gridded and therefore i.i.d., before the first `tell()`. Never tell them to the GP.

```python
rng = np.random.default_rng(0)
idx = rng.permutation(len(x_seed))
n_hold = max(3, len(idx) // 5)
hold, train = idx[:n_hold], idx[n_hold:]
holdout_x, holdout_y = x_seed[hold], y_std[hold]
gpo = GPOptimizer(x_seed[train], y_std[train], ...)
```

Then track calibration as data accumulates — it *will* drift, especially early:

```python
if (it + 1) % RETRAIN_EVERY == 0:
    m = _pm(gpo, holdout_x)
    s = np.sqrt(np.maximum(
        gpo.posterior_covariance(holdout_x, variance_only=True)["v(x)"], 1e-12))
    z = (holdout_y - m) / s
    log(f"iter {it}: n={len(gpo.y_data)} rmse={np.sqrt(np.mean((m-holdout_y)**2)):.4f} "
        f"z_std={z.std():.3f} (want ~1)")
```

Expect RMSE to fall and `z.std()` to settle near 1. If it drifts steadily **up** as points
accumulate, the hyperparameters are overfitting the growing dataset — retrain globally
rather than locally, or tighten the length-scale lower bound.

⚠️ If the holdout would leave fewer than ~10 training seeds, **skip it and say so in the
log** rather than crippling the initial fit. Record the decision in `gpcam_metadata.json`.

## Constrained observations

If `y` is strictly positive or bounded, a plain GP is often *structurally* mis-calibrated
near the boundary: it puts probability mass on impossible values, so lower credible bounds
go negative exactly where the data is most interesting. On 8.4+, check calibration on the
**original** scale with `evaluate_posterior`, not the latent-space metrics:

```python
post = gpo.evaluate_posterior(x_test, level=0.95)          # 8.4+ only
covered = (y_test >= post["lower"]) & (y_test <= post["upper"])
print(f"original-scale PICP@95: {covered.mean():.3f}")
```

`picp`/`nlpd`/`coverage_curve` operate in the GP's latent space — the correct check for the
*latent* model, but not the number you report to a collaborator. Good latent calibration
with poor original-scale coverage means the transform is the problem.

## Common pitfalls

1. **Reporting RMSE alone.** It says nothing about the error bars.
2. **Unpacking `crps` as a scalar.** It returns `(mean, std)`.
3. **`picp` without `mpiw`.** Coverage is trivially achievable with absurdly wide intervals.
4. **Testing on adaptively-acquired points.** Not i.i.d.; hold out random seeds instead.
5. **Shape mismatch.** `y_test` must be `(V,)` for a single-task GP.
6. **Judging a transformed optimizer by latent-space metrics.**
7. **Calibrating once and never again.** Calibration drifts as the loop adds data.
8. ⭐ **Calling `picp`/`coverage_curve` in a daemon without a version guard** — an
   `AttributeError` mid-loop costs a live iteration. Use `_metric()` or the z-score check.

---

## Reference

- `gpcam-cog` SKILL.md — the AE loop, flag-file contract, ⭐ 11BM learned defaults
- `gpcam-cog/reference.md` → **VERSION MATRIX** — the authority on every version delta
- `gpcam-customization` — kernel PSD rules, the deep-kernel `set_weights` pitfall,
  hyperparameter index convention, noise and cost recipes
- `gpcam-customization/references/choosing-an-acquisition-function.md` — acquisition
  availability tiers and the behaviors that silently differ
- `gp2scale-advanced` / `multi-task-advanced` — large-N and vector-valued cases
- [gpCAM documentation](https://gpcam.readthedocs.io)
