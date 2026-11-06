---
name: gpcam-customization
description: One-stop skill for customizing gpCAM beyond defaults — kernel (covariance), acquisition, prior mean, noise, and cost functions. Open this skill whenever the user's experiment needs anything beyond a plain Matérn-3/2 + built-in acquisition setup.
---

# Skill: gpCAM Customization (kernel · acquisition · prior mean · noise · cost)

This skill consolidates five customization surfaces of gpCAM. The kernel, prior mean, and noise functions **share a single hyperparameter vector** that the GP trains jointly. Acquisition functions read the posterior but do not add hyperparameters. Cost functions have fixed parameters passed via `args=`.

---

## When to open each section

| Need | Section |
|------|---------|
| Default Matérn-3/2 ARD won't capture the structure (periodicity, symmetry, multi-scale, non-Euclidean inputs) | **Kernel** |
| Deciding which acquisition to use at all, or the built-ins aren't enough (multi-objective, constrained regions, tuned UCB, threshold finder) | **Acquisition** + [references/choosing-an-acquisition-function.md](references/choosing-an-acquisition-function.md) |
| User has a physical model / known baseline / expected peak | **Prior Mean** |
| Noise is non-uniform, position-dependent, or should be learned | **Noise** |
| Motor travel time, sample damage, or zone penalties matter | **Cost** |

If none of the above apply: use defaults from `gpcam-cog`'s `reference.md`.

---

## 1. Kernel functions

### Contract
```python
def my_kernel(x1, x2, hps):
    """
    x1: (N1, D), x2: (N2, D), hps: 1D
    returns K: (N1, N2), symmetric, positive semi-definite
    """
```

### Building blocks
```python
from gpcam.kernels import (
    matern_kernel_diff1,            # ν=3/2, once differentiable (default)
    matern_kernel_diff2,            # ν=5/2, twice differentiable
    squared_exponential_kernel,     # RBF, infinitely smooth
    wendland_kernel,                # compact support (gp2Scale)
    get_distance_matrix,
    get_anisotropic_distance_matrix,
)
```

Pattern: compute a distance matrix from points, then apply a base kernel to it.

### Smoothness guide
| Kernel | Smoothness | Use when |
|--------|-----------|----------|
| Matérn-1/2 | Rough, not differentiable | Sharp peaks, discontinuities |
| Matérn-3/2 | Once differentiable | **Default — most physical data** |
| Matérn-5/2 | Twice differentiable | Smooth physical signals |
| Squared exp (RBF) | Infinitely smooth | Very smooth data (tends to oversmooth) |

### Recipes

**Anisotropic Matérn (ARD)**
```python
def anisotropic_matern(x1, x2, hps):
    d = get_anisotropic_distance_matrix(x1, x2, hps[1:])
    return hps[0] * matern_kernel_diff1(d, 1.0)
```

**Periodic** (angular data, lattice)
```python
def periodic_kernel(x1, x2, hps):
    d = np.abs(np.subtract.outer(x1[:, 0], x2[:, 0]))
    return hps[0] * np.exp(-2.0 * np.sin(np.pi * d / hps[2])**2 / hps[1]**2)
```

**Periodic × smooth** (product)
```python
def periodic_plus_smooth(x1, x2, hps):
    d_p = np.abs(np.subtract.outer(x1[:, 0], x2[:, 0]))
    k_p = np.exp(-2.0 * np.sin(np.pi * d_p / hps[2])**2 / hps[1]**2)
    d_o = get_anisotropic_distance_matrix(x1[:, 1:], x2[:, 1:], hps[3:])
    k_o = matern_kernel_diff1(d_o, 1.0)
    return hps[0] * k_p * k_o
```

**Sum kernel** (multi-scale)
```python
def multi_scale_kernel(x1, x2, hps):
    d = get_distance_matrix(x1, x2)
    return hps[0]*matern_kernel_diff2(d, hps[1]) + hps[2]*matern_kernel_diff1(d, hps[3])
```

**Mirror symmetry**
```python
def symmetric_kernel_x(x1, x2, hps):
    x1f = x1.copy(); x1f[:, 0] = -x1f[:, 0]
    x2f = x2.copy(); x2f[:, 0] = -x2f[:, 0]
    d = get_anisotropic_distance_matrix
    k = lambda a, b: hps[0] * matern_kernel_diff1(d(a, b, hps[1:]), 1.0)
    return 0.25 * (k(x1, x2) + k(x1f, x2) + k(x1, x2f) + k(x1f, x2f))
```

**L1 (Manhattan) separable**
```python
def l1_kernel(x1, x2, hps):
    k = hps[0] * np.ones((len(x1), len(x2)))
    for i in range(x1.shape[1]):
        d_i = np.abs(np.subtract.outer(x1[:, i], x2[:, i]))
        k *= np.exp(-d_i / hps[1 + i])
    return k
```

**Non-Euclidean inputs** (strings, graphs, molecules) — `x_data` may be a Python list:
```python
def string_distance(s1, s2):
    diff = abs(len(s1) - len(s2))
    common = min(len(s1), len(s2))
    return diff + sum(a != b for a, b in zip(s1[:common], s2[:common]))

def string_kernel(x1, x2, hps):
    d = np.array([[string_distance(a, b) for b in x2] for a in x1])
    return hps[0] * matern_kernel_diff1(d, hps[1])

gp = GPOptimizer(x_data, y_data, init_hyperparameters=np.ones(2),
                 kernel_function=string_kernel)
```
A Python loop over objects is acceptable here (bottleneck is the distance function, not numpy). The base kernel still has to be PSD.

**Deep kernel** (NN-warped input)
```python
from gpcam.deep_kernel_network import Network
n = Network(iset_dim=3, layer_width=5)

def deep_kernel(x1, x2, hps):
    signal_var, length_scale = hps[0], hps[1]
    # unpack hps[2:] into n.set_weights / n.set_biases (see manual for layout)
    d = get_distance_matrix(n.forward(x1), n.forward(x2))
    return signal_var * matern_kernel_diff1(d, length_scale)
```
Use `method="mcmc"` or `"adam"` for training — `"global"`/`"local"` don't scale to NN-sized hyperparameter vectors.

### Kernel pitfalls
- Sums/products of valid kernels are valid; **differences are not guaranteed PSD**.
- Always include a leading amplitude hyperparameter (`hps[0] * ...`).
- Avoid Python loops over data points; use `np.subtract.outer` and vectorized ops.
- Length scale floor: lower bound must be > 0 (e.g. 0.001) to avoid singular matrices.

---

## 2. Acquisition functions

**This is the one customization surface that works on every gpCAM version, including the
claimed 8.1.13 pin.** `acquisition_function` is an `ask()` argument, not a constructor
argument — so unlike `kernel_function` / `prior_mean_function` / `noise_function` (which
8.1.13 was recorded as rejecting; 8.2.4+ accept them — Rule D) it is available no matter
what the install turns out to be. **Prefer callables over strings** whenever the choice is
close: they also sidestep the β = 3.0 hardcoding, the maximization-only convention, and
the batch override described below.

### Choose the acquisition *with* the user (MANDATORY)

**Never pick silently, and never default to `"expected improvement"`.** It is the choice
that most determines where the instrument actually goes.

1. Name your recommendation and the one tradeoff it makes.
2. Resolve "find the best conditions" — it covers two different experiments: *the single
   best point* (exploitation-leaning) vs. *a trustworthy map containing it*
   (exploration-leaning). Ask which.
3. Confirm before writing the loop, and put the reasoning in a comment in the daemon.

**→ Decision table, nine worked archetypes, and the gpCAM behaviors that silently differ:
[references/choosing-an-acquisition-function.md](references/choosing-an-acquisition-function.md).
Read it before recommending any acquisition.** The three things most likely to bite:

- **gpCAM's EI is pure exploration early in a run** — it collapses to `0.3989·σ`, i.e.
  `"variance"` up to a constant, until the posterior mean exceeds the incumbent. This is
  a second, independent cause of the edge-piling that §4's noise default addresses.
- **EI / PI / UCB / `"maximum"` are maximization-only** — they misbehave silently if the
  user is minimizing.
- **`"ucb"` / `"lcb"` hardcode `beta = 3.0`** — the *strings* expose no tuning; only the
  callable form below does.

### Contract
```python
def my_acquisition(x, gpo):
    """
    x: (V, D) candidate points.
    Returns: (V,) — HIGHER = more desirable. The function is MAXIMIZED.
    """
```

Acquisition callables are called as exactly `acquisition_function(x, gpo)` — two
positional arguments (`surrogate_model.py:200`).

**How to pass extra parameters — resolved.** `args` *does* reach the callable, but
**through the `gpo` object, not as a call argument**: gpCAM's own acquisitions read it via
`getattr(gpo, "args", None)`. Set it on the constructor or via `ask(args=…)`:

```python
def _acq_arg(gpo, key, default):
    a = getattr(gpo, "args", None)
    return a[key] if isinstance(a, dict) and a.get(key) is not None else default
```

⚠️ **`ask(args=…)` overwrites `self._args` permanently** — it is not a per-call override
that reverts afterwards. `functools.partial` remains a fine alternative, but only for
**keyword** parameters, since gpCAM passes `x` and `gpo` positionally.

### The tolerant posterior-mean accessor (used by every recipe below)

The posterior-mean key differs across versions (`"m(x)"` on 8.2.4 → 8.4.x, claimed
`"f(x)"` on 8.1.13 — see `gpcam-cog/reference.md` → VERSION MATRIX). Define this once per
daemon and never hardcode either key:

```python
def _pm(gpo, x, **kw):
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d: return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")
```

`posterior_covariance(..., variance_only=True)["v(x)"]` is stable everywhere. The
**full** covariance matrix key is `["S"]`, not `["S(x)"]`.

### Built-in strings — check availability first

**Fourteen** built-in strings exist in 8.4.x, source-verified against
`surrogate_model.py:218-283`. `reference.md` previously documented only five for the
claimed 8.1.13 pin. Passing a string that is absent raises
`Exception("No valid acquisition function string provided…")` — loud, not silent, but
still a dead beamtime iteration.

| Tier | Strings |
|---|---|
| **Documented for the claimed 8.1.13 pin** | `"variance"`, `"expected improvement"`, `"relative information entropy"`, `"relative information entropy set"`, `"total correlation"` |
| **Present 8.2.4 → 8.4.x (verified in source)** | `"ucb"`, `"lcb"`, `"maximum"`, `"minimum"`, `"gradient"`, `"probability of improvement"`, `"target probability"` |
| **8.4-era additions** | `"knowledge gradient"`, `"noisy expected improvement"` |

**Multi-task (`x_out is not None`) implements only nine:** `"variance"`,
`"relative information entropy"`, `"relative information entropy set"`,
`"total correlation"`, `"ucb"`, `"lcb"`, `"expected improvement"`,
`"knowledge gradient"`, `"noisy expected improvement"`.

Anything in the lower two tiers has a callable equivalent below. Until the install's
version is probed (see `gpcam-cog/SKILL.md`), prefer the callable — it is the only
acquisition surface guaranteed to work on every version, because `acquisition_function`
is an `ask()` argument rather than a constructor argument.

**What the strings actually compute** (surprises worth knowing):

| String | Actually computes | Surprise |
|---|---|---|
| `"variance"` | `√v(x)` | It's the **standard deviation**, despite the name. Same argmax, different `f_a(x)`. |
| `"ucb"` / `"lcb"` | `m ± 3.0·√v` | **β hardcoded to 3.0.** |
| `"gradient"` | `‖∇m‖·√v` | Uses the full gradient. |
| `"probability of improvement"` / `"expected improvement"` | anchored to `np.max(gpo.y_data)` | The largest **noisy observation**, not the posterior mean. |
| `"relative information entropy"` | one number for the whole set | Returns a **length-1 array** regardless of `len(x)`; forces `vectorized=False`. |
| `"target probability"` | `P(a ≤ f(x) ≤ b)` | **Requires** `args={"a": …, "b": …}` or it raises. |

### Recipes (custom callables)

**UCB with tunable β**
```python
def ucb(x, gpo):
    beta = 2.0      # 0=exploit, 1=mild explore, 3=strong explore
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    return m + beta * np.sqrt(v)
```

**LCB (minimization)** — gpCAM maximizes, so flip the sign:
```python
def lcb(x, gpo):
    beta = 2.0
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    return -(m - beta * np.sqrt(v))
```

**Expected improvement (minimization)**
```python
from scipy.stats import norm
def ei_min(x, gpo):
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    s = np.sqrt(np.maximum(v, 1e-10))
    y_best = np.min(gpo.y_data)
    z = (y_best - m) / s
    return s * (z * norm.cdf(z) + norm.pdf(z))
```

**Probability of improvement**
```python
from scipy.stats import norm
def poi(x, gpo):
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    s = np.sqrt(np.maximum(v, 1e-10))
    return norm.cdf((m - np.max(gpo.y_data)) / s)
```

**Constrained acquisition** (penalize forbidden zone)
```python
def constrained_variance(x, gpo):
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    dist = np.linalg.norm(x - np.array([5.0, 5.0]), axis=1)
    return v + np.where(dist < 1.0, -1e6, 0.0)
```

**Weighted multi-objective** — normalize against a *fixed* scale from the data, never
against the current candidate batch. Min-max scaling over `x` makes a point's score
depend on which other candidates happened to be evaluated alongside it, so the argmax
shifts between calls and the inner optimizer chases a moving target.
```python
def multi_objective(x, gpo):
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    scale = np.std(gpo.y_data) + 1e-10           # fixed reference scale
    m_n = (m - np.mean(gpo.y_data)) / scale      # dimensionless z-score
    v_n = np.sqrt(v) / scale                     # dimensionless
    return 0.7 * m_n + 0.3 * v_n
```
Both terms are now in units of "standard deviations of the observed signal", which makes
the weights mean what they say. Note this *is* UCB with `beta = w_explore / w_exploit` up
to a positive rescaling — if that's all you need, use the `ucb` callable above.

**Threshold finder** (boundary where the signal crosses T)
```python
def threshold_finder(x, gpo):
    T = 0.5     # EDIT — in the GP's modeling space (standardized, if Rule E applies)
    m = _pm(gpo, x)
    v = gpo.posterior_covariance(x, variance_only=True)["v(x)"]
    s = np.sqrt(np.maximum(v, 1e-10))
    eps = 0.01 * np.std(gpo.y_data) + 1e-12      # scale-aware, NOT a hardcoded 0.01
    return s / (np.abs(m - T) + eps)
```
The softening epsilon must scale with the signal. A fixed `0.01` is meaningful only when
`y` is O(1): on raw detector counts it is negligible and the acquisition becomes a
near-singular spike; on data of order `1e-3` it dominates and the acquisition goes flat.
Both degrade silently.

**Radical gradient** (map where the signal *changes* — phase boundaries, film edges)
```python
def radical_gradient(x, gpo):
    """sqrt(||grad m(x)||) * sigma(x) — spreads across all changing regions."""
    g = gpo.posterior_mean_grad(x)["dm/dx"]              # (V, D) FULL gradient
    s = np.sqrt(np.maximum(
        gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-10))
    return np.sqrt(np.linalg.norm(g, axis=1)) * s
```
The square root softens the gradient weighting relative to plain `‖∇m‖·σ`, so sampling
spreads across every changing region instead of piling onto the single steepest ridge.
Use plain `‖∇m‖·σ` (or the built-in `"gradient"`) when there is one dominant transition
to locate precisely — swapping between them is a one-line change, so offer both.

⚠️ **Call it with `x` only.** The real signature is
`posterior_mean_grad(x_pred, hyperparameters=None, x_out=None, direction=None)` —
`direction` is the **fourth** parameter, so `posterior_mean_grad(x, 0)` passes `0` as
*hyperparameters* and silently returns the wrong thing rather than raising. Omitting
`direction` returns the full `(V, D)` gradient, which is what `np.linalg.norm(g, axis=1)`
needs; passing `direction=k` returns a `(V, D)` array with only column `k` filled. This
is exactly how the built-in `"gradient"` acquisition calls it
(`surrogate_model.py:241`).

### Useful `ask()` options
| Argument | Meaning |
|----------|---------|
| `n=N` | Batch of N points; for single-task batches use `"relative information entropy set"` or `"total correlation"`. Any other *string* is silently replaced by `"total correlation"` — batch EI is not EI. |
| `vectorized=True` (default) | Acquisition called once with shape `(V, D)` — required for the contract above. |
| `vectorized=False` | One candidate at a time; use for non-vectorizable acquisition / non-Euclidean inputs. |
| `method="global"\|"local"\|"hgdl"\|"hgdlAsync"` | Inner optimizer for argmax over `input_set`. `hgdl*` needs `dask_client=`. |
| `dask_client=client`, `batch_size=B` | Distributed inner optimization. |

`input_set`: continuous bounds, a list of discrete candidates, or arbitrary Python objects (if the kernel handles them).

### Acquisition pitfalls
- **Reaching for `"expected improvement"` by reflex.** Best-known ≠ best-suited. Work the
  choice out with the scientist using the reference file's decision table.
- **Recommending a maximization acquisition to someone minimizing.** EI, PI, UCB, and
  `"maximum"` all assume bigger-is-better and fail silently. Scientists say "optimize"
  for both directions — confirm which.
- **Passing an undocumented string.** Check the availability table above first.
- **`ask(n>1)` with a string acquisition** is silently rewritten to `"total correlation"`.
- Acquisition is **maximized** — never return negative scores for points you want.
- Guard against division by zero: `np.sqrt(np.maximum(var, 1e-10))`.
- Normalize against fixed scales from the data, not against the candidate batch.
- Custom functions get called many times — keep them fast.
- Train the GP before calling acquisition; if you read `gpo.y_data` directly, make sure `tell()` ran.

---

## 3. Prior mean functions

### Contract
```python
def my_mean(x, hps):
    """
    x: (N, D), hps: 1D (shared with kernel + noise).
    Returns m: (N,)  — prior mean at each input.
    """
```

Without a prior mean, gpCAM uses `mean(y_data)` — fine for most cases. Add a prior mean only when you have a real physical expectation. **A bad prior mean biases the GP harder than no prior at all.**

### Recipes

**Explicit constant**
```python
def constant_mean(x, hps):
    return np.full(len(x), hps[-1])
```

**Linear trend** — `m(x) = a + b·x`
```python
def linear_mean(x, hps):
    K = 3  # index where mean hps start (adjust!)
    D = x.shape[1]
    return hps[K] + x @ hps[K+1:K+1+D]
```

**Gaussian peak at known location**
```python
def gaussian_peak_mean(x, hps):
    K = 3
    amp, cx, cy, w = hps[K], hps[K+1], hps[K+2], hps[K+3]
    r2 = (x[:, 0] - cx)**2 + (x[:, 1] - cy)**2
    return amp * np.exp(-r2 / (2 * w**2))
```

**Quadratic background (1D)**
```python
def quadratic_mean(x, hps):
    K = 2
    return hps[K] + hps[K+1]*x[:, 0] + hps[K+2]*x[:, 0]**2
```

**Physics-informed (Bragg's law)**
```python
def bragg_mean(x, hps):
    K = 3
    wavelength = 1.54  # Cu Kα
    two_theta = np.radians(x[:, 0])
    d = hps[K+1]
    return hps[K] * np.exp(-(np.sin(two_theta/2) - wavelength/(2*d))**2 / 0.001)
```

### Choosing bounds
- Intercept / amplitude: `[2·min(y), 2·max(y)]`
- Slopes: `[-range(y)/range(x), +range(y)/range(x)]`
- Peak position: `[known ± tolerance]`
- Width: `[min_expected, max_expected]`

### Prior mean pitfalls
- Wrong hyperparameter indices — must not overlap with kernel/noise.
- Overconfident priors fight the data — keep them loose.
- Every hp the mean reads must have a row in `hyperparameter_bounds`.
- Return shape must be `(N,)`, not a scalar.

---

## 4. Noise functions

### Contract
```python
def my_noise(x, hps):
    """
    x: (N, D), hps: 1D (shared with kernel + mean).
    Returns: (N,) diagonal variances, OR (N, N) full noise covariance.
    """
```

### Decision matrix
| Scenario | Approach |
|----------|----------|
| Known uniform σ | `noise_variances=np.full(N, sigma**2)` — no function |
| Known per-point σ | `noise_variances=my_array` — no function |
| Unknown uniform σ (learn it) | Noise function with one hp |
| Position-dependent | Noise function depending on `x` |
| Nothing known | Omit both — gpCAM defaults to `(0.01·mean|y|)²` |

**Never pass both `noise_variances` and `noise_function`.**

### ⭐ Learned default (beamline experience): value-proportional noise, NOT the fit-error

**When the objective is extracted by a fit (e.g. a SciAnalysis peak-fit `prefactor`/intensity), set the per-point uncertainty to a flat/proportional estimate ≈ 10% of the objective value — `noise_std = 0.10·|y|` (floored) — and do NOT use the peak-fit error / χ² as the GP noise.** This is a "Known per-point σ" case → a `noise_variances` array (no `noise_function`), recomputed each `tell()`.

- **Why (pseudo-bug this fixes):** using the fit-error as the noise makes **blank / no-signal frames look HIGH-uncertainty** — a frame with no peak fits badly → large fit-error → the GP thinks it is "uncertain" there → **EI keeps re-measuring those empty regions and points pile up on the edges/corners** of the search box. But in reality we are *confident* the value there is ≈ 0. Value-proportional noise makes blank/low points **low-uncertainty**, so the GP trusts them and EI **spreads points out** across the domain. (Observed and fixed at 11BM-CMS; human-scientist rule.)
- **Implementation (standardized objective):** if `y` is z-scored by `Y_SD`, use `noise_var_std = max((0.10·|y|)/Y_SD, floor)²` with a small absolute floor (e.g. `floor = 0.05`, i.e. ~5% of the seed spread) so blank frames (`y≈0`) get low-but-nonzero variance (never singular). Apply at **init** (seeds) **and every `tell()`**. Tunables: noise fraction (0.10) and floor.
- This is the **default for fit-metric autonomous experiments** — only deviate if the fit genuinely provides a trustworthy, calibrated per-point σ that is *not* inflated on blank frames.

### Recipes

**Learnable constant**
```python
def learnable_noise(x, hps):
    K = 3
    return np.full(len(x), hps[K]**2)   # return VARIANCE, not std
```

**Edge-amplified**
```python
def edge_noise(x, hps):
    K = 3
    center = np.mean(parameter_bounds, axis=1)
    half_range = (parameter_bounds[:, 1] - parameter_bounds[:, 0]) / 2
    edge = np.max(np.abs(x - center) / half_range, axis=1)
    return hps[K]**2 * (1.0 + 5.0 * edge**2)
```

**Two-detector / mode-dependent**
```python
def two_detector_noise(x, hps):
    K = 3
    n = np.empty(len(x))
    m0 = x[:, -1] < 0.5
    n[m0]  = hps[K]**2
    n[~m0] = hps[K+1]**2
    return n
```

### Choosing noise bounds
- Lower bound: never 0; use ≥ 0.001 (prevents singular matrices).
- Upper bound: `10 * std(y_data)` — noise shouldn't exceed signal.
- Initial value: `0.01 * mean(|y_data|)`.

### Noise pitfalls
- Return **variance** (σ²), not standard deviation.
- Zero noise → singular matrix. Always positive.
- Shape `(N,)` for independent noise, `(N, N)` for correlated.

---

## 5. Cost functions

Cost functions modify acquisition via `effective_score = acquisition / cost(origin, x)`. They have **fixed parameters** — not optimized during training.

### Contract

```python
def my_cost(origin, x):
    """
    origin: (D,) the CURRENT position — a single point, passed as ask(position=...).
    x:      (V, D) candidate points.
    Returns: (V,) costs — strictly > 0.
    """
```

⚠️ **Two positional arguments, not three.** gpCAM calls
`cost_function(origin, x)` (`surrogate_model.py:196`). The old
`def my_cost(origin, x, arguments=None)` form only survived because the third parameter
had a default — **`arguments` is never populated**, so any recipe doing
`arguments.get(...)` raised `AttributeError: 'NoneType'` the moment cost-awareness was
actually switched on. Bind parameters with a closure or `functools.partial` instead.

⚠️ **`position=` must be passed to `ask()`.** The cost divisor is applied only when
`origin is not None`. Setting `cost_function` and forgetting `position` silently disables
cost-awareness with no warning:

```python
next_x = gpo.ask(input_set=bounds, acquisition_function="variance",
                 position=current_motor_position)["x"]   # ← required
```

### Recipes

**L2 (Euclidean)**
```python
def l2_cost(origin, x):
    return 1.0 + np.linalg.norm(x - origin, axis=1)
```

**L1 (Manhattan, axis-by-axis stages)**
```python
def l1_cost(origin, x):
    return 1.0 + np.sum(np.abs(x - origin), axis=1)
```

**Anisotropic** (per-axis speed) — parameters bound by closure, *not* read from `arguments`
```python
def make_anisotropic_cost(speeds):
    speeds = np.asarray(speeds, dtype=float)
    def anisotropic_cost(origin, x):
        return 1.0 + np.sum(np.abs(x - origin) * speeds, axis=1)
    return anisotropic_cost
```

**Directional** (asymmetric in one axis)
```python
def directional_cost(origin, x):
    diff = x - origin
    fwd  = np.maximum( diff[:, 0], 0) * 1.0
    back = np.maximum(-diff[:, 0], 0) * 5.0
    lat  = np.sum(np.abs(diff[:, 1:]), axis=1)
    return 1.0 + fwd + back + lat
```

**Settling time**
```python
def settling_cost(origin, x):
    d = np.linalg.norm(x - origin, axis=1)
    settling = np.where(d > 2.0, 3.0, 0.0)
    return 1.0 + 0.5 * d + settling
```

**Zone-based penalty**
```python
def zone_cost(origin, x):
    d = np.linalg.norm(x - origin, axis=1)
    zone = np.where(x[:, 0] > 8.0, 10.0, 0.0)
    return 1.0 + d + zone
```

### Wiring it up
```python
gpo = GPOptimizer(
    x_data, y_data,
    cost_function=make_anisotropic_cost([1.0, 3.0, 0.5]),   # closure, not args=
)
next_x = gpo.ask(input_set=bounds, acquisition_function="variance",
                 position=current_motor_position)["x"]
```

`args=` is **not** a channel to the cost function — gpCAM never forwards it there. It
reaches *acquisition* functions only, and only as `gpo.args`.

### Calibrating from observed moves
Fit the offset/slope of an L1/L2 cost model to observed move timings with SciPy directly:

```python
from scipy.optimize import differential_evolution
# observations: [{"origin": (D,), "point": (D,), "cost": seconds}, ...]
d = np.array([np.linalg.norm(o["point"] - o["origin"]) for o in observations])
t = np.array([o["cost"] for o in observations])
keep = np.abs(t - t.mean()) <= 2 * t.std()          # ±2σ outlier rejection
res = differential_evolution(
    lambda p: np.sum((p[0] + p[1] * d[keep] - t[keep]) ** 2), [(0, 100), (0, 100)])
offset, slope = res.x
```

> ⚠️ **`gpcam.cost_functions` does not exist.** The old
> `from gpcam.cost_functions import update_l2_cost_function` line was an
> `ImportError` — the module is absent in every version checked (8.2.4 → 8.4.x); the
> package ships only `gp_optimizer`, `gp_optimizer_base`, `surrogate_model`,
> `autonomous_experimenter`, `kernels`, `gp_mcmc`, `deep_kernel_network`.

### Cost pitfalls
- Cost must be **> 0** — zero divides by zero; negative inverts the ranking.
- Forgetting `ask(position=...)` disables cost-awareness **silently**. This is the single
  most common cost bug.
- If cost dominates the acquisition magnitude, the optimizer never explores. Balance the
  scales — the acquisition is *divided* by the cost.
- `origin` matters — cost depends on *where you are*, not just where you're going.
- Vectorize over `x`: `origin` is one `(D,)` point, `x` is `(V, D)`. Broadcasting handles
  this, but don't assume `origin` is a batch.

---

## Hyperparameter coordination (READ THIS — most bugs live here)

Kernel, prior mean, and noise functions **share one hyperparameter vector**. You must:

1. Decide the index layout up front.
2. Add one row to `hyperparameter_bounds` for **every** hp consumed.
3. Document the layout in a comment.

Example layout (2D kernel + linear mean + learnable noise):
```python
# hps[0]   = signal variance       (kernel)      bounds [0.001, 100]
# hps[1:3] = length scales         (kernel)      bounds [0.01, 50]
# hps[3]   = intercept             (mean)        bounds [-10, 10]
# hps[4:6] = slopes                (mean)        bounds [-5, 5]
# hps[6]   = noise std             (noise)       bounds [0.001, 10]
hp_bounds = np.array([
    [0.001, 100.0],
    [0.01, 50.0], [0.01, 50.0],
    [-10.0, 10.0],
    [-5.0, 5.0], [-5.0, 5.0],
    [0.001, 10.0],
])
```

**Cost functions are separate** — fixed parameters via `args=`, no hyperparameter rows.

### Setting initial values / bounds
- Signal variance: init near `np.var(y_data)` or `1.0`; bounds `[0.001, 10·std(y)]`.
- Length scales: init near `0.1·range(x_dim)`; bounds `[0.01, 10·range(x_dim)]`.
- Period (if periodic): init near expected; bounds `[0.5·expected, 2·expected]`.
- Noise: init `0.01·mean(|y|)`; lower bound never 0.

---

## 6. Run defaults — sampling & stopping (⭐ 11BM learned)

**All values live in `config.json → gpcam.sampling` / `gpcam.stopping`; the grid+mask
mechanism is in `gpcam-cog` SKILL → *Min-step guard*.** Never hardcode or restate a number.
**Confirm the `must_confirm` fields with the user before starting** (`beam_size_mm`,
`no_improvement_patience`) and state the resolved values back when presenting the script.
Only the *choices* belong here:

**`min_dist_frac`** — minimum step as a fraction of the beam.
- **→ 1.0 (one full beam)** — the original 11BM setting, from run004: exploit-leaning acquisitions (UCB with low β, or a sharp EI) **collapse to sub-beam re-sampling**, putting 52 pts within 0.06 mm (~3 µm apart) against a 200 µm beam. Measuring finer than the beam is physically redundant. A bounded region also masks out completely once covered → `grid_exhausted` stop.
- **→ small (current default)** — blocks only near-exact repeats. The AE stays free to sample finely and to keep proposing legal points indefinitely, which is what a run-until-stopped experiment needs; the sub-beam guard is effectively off.

Raise it back toward 1.0 the moment a live run starts piling points inside one beam footprint.

**⭐ INVARIANT — the candidate grid is spaced at EXACTLY `min_sample_distance` (⭐ 11BM
learned, run009).** `min_sample_distance` (= `min_dist_frac · beam_size_mm`) is only an
*anti-cluster filter*; the **candidate grid is the actual lattice picks land on**. If the grid
is coarser than `min_sample_distance`, the min-step knob **does nothing** — every pick snaps to
the coarser grid and the filter never bites (run009 bug: with `min_sample_distance`=0.01 mm but
`fine_grid_mm`=0.05 mm, every point snapped to 0.05 mm). **Two knobs that both look like "step
size", and the finer one silently no-ops.** So the generator MUST:

1. **Derive the (fine) candidate spacing FROM `min_sample_distance` by default** — do not read a
   separate `fine_grid_mm` unless an explicit override flag is set
   (`sampling.fine_grid_couple_to_min_step: false` + `sampling.fine_grid_mm`). One knob
   (`min_dist_frac`) then controls resolution and the two cannot silently diverge.
2. **Guard + clamp**: a fine grid coarser than `min_sample_distance` is **forbidden** — log a
   WARNING naming both values and clamp the fine grid down to `min_sample_distance`.
3. **Two-stage case** (a coarse *region-finder* grid + a fine window around top cells, as in the
   orientation daemon): `coarse_grid_mm` stays a region-finder (needn't equal the min step), but
   the **fine window must be auto-sized to TILE the coarse spacing** so shrinking the fine cell
   leaves no gaps — `halfwin_cells ≥ ⌈coarse_grid_mm / (2·fine_spacing)⌉`. Uncovered strips
   between coarse cells are a silent coverage bug.
4. **Startup log states the coupling** so it is verifiable at a glance, e.g.
   `FINE grid = min_sample_distance = 0.010 mm (coupled)` plus the window-vs-coarse coverage
   check. This is the single-stage `spacing = MIN_SAMPLE_DISTANCE` rule in the `gpcam-cog`
   *Min-step guard* generalized to the two-stage grid; `config.template.json`'s sampling comment
   is the canonical invariant.

**`no_improvement_patience`** — the only self-stop. Default RELAXED so the AE doesn't quit
early: eager criteria (low patience / high threshold) stop before the peak or map is resolved
and report a noise-inflated "best". `null` = never self-stop, i.e. run until someone runs
`touch $RUN_DIR/GPCAM_STOP.txt`. Tighten only under explicit beamtime pressure.

---

## Universal pitfalls (apply across all five surfaces)

1. **Mismatched hp count** — `hyperparameter_bounds.shape[0]` must equal the total length of the hp vector consumed by kernel + mean + noise.
2. **Index drift** — if you reorder hps, every `hps[K]` index in every function must change.
3. **PSD violations** — sums/products of valid kernels are valid; differences are not.
4. **Singular matrices** — caused by zero noise, zero-length scale, or duplicate input points.
5. **Wrong return shape** — kernels `(N1, N2)`, mean `(N,)`, noise `(N,)` or `(N, N)`, acquisition `(V,)`, cost `(V,)`.
6. **Slow custom functions** — these are called many times. Vectorize aggressively.
7. **Provide one or the other** — `noise_variances` XOR `noise_function`; never both.

---

## Reference

- [references/choosing-an-acquisition-function.md](references/choosing-an-acquisition-function.md)
  — decision table, nine worked archetypes, gpCAM behaviors that silently differ, and the
  per-version availability tiers. Read before recommending any acquisition.
- `gpcam-cog/reference.md` → **VERSION MATRIX** — the source-verified 8.4.x API surface
  and every delta against the claimed 8.1.13 pin. Read before emitting a version-sensitive
  kwarg or dict key.

Underlying library: `gpcam/surrogate_model.py` (the built-in acquisitions),
`gpcam/kernels.py` (a 1-line re-export of `fvgp.kernels`), and the gpCAM docs
(https://gpcam.readthedocs.io). Note there is **no `gpcam/cost_functions.py`** — cost
functions are user-supplied callables only. For the orchestration / file-protocol layer,
see the `gpcam-cog` skill. For >10k points use `gp2scale-advanced`. For vector-valued
outputs use `multi-task-advanced`. When a customized kernel / mean / noise / cost function
crashes, stalls the loop, or leaves the posterior mis-calibrated, use `gpcam-diagnostics`
— it maps the exception text to the cause, and covers the silent failures (index overlap,
zero-noise Cholesky collapse, the cost function that does nothing without `position=`).
