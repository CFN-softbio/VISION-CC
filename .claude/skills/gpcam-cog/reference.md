# gpCAM API Reference

gpCAM is a **thin Bayesian-optimization / autonomous-data-acquisition layer on top of
[`fvgp`](https://github.com/lbl-camera/fvgp)**. The actual GP math — kernels,
hyperparameter training, posterior evaluation, MCMC, deep kernels — lives in `fvgp`.
gpCAM adds `ask` / `tell` / `train` / `optimize` and acquisition-function optimization.

`gpcam.kernels`, `gpcam.gp_mcmc`, and `gpcam.deep_kernel_network` are **one-line
re-exports** (`from fvgp.X import *`) — the real definitions are in `fvgp`.

**Install:** `pip install gpcam`
**Dependencies:** `numpy`, `scipy`, `torch`, `dask`, `distributed`, `fvgp`, `hgdl`, `loguru`

---

## ⚠️ VERSION MATRIX — READ FIRST

This document is written against **gpCAM 8.4.x / fvgp ~= 4.8.1**, verified by reading
the source at `gpCAM-master 2/gpcam/`. Older lines differ in ways that will raise
`TypeError` or `KeyError`, not warnings.

| Feature | 8.1.13 (11BM pin, see below) | 8.2.x – 8.3.x | **8.4.x (this doc)** |
|---|---|---|---|
| gp2Scale Dask client kwarg | `gp2Scale_dask_client` | `gp2Scale_dask_client` | **`dask_client`** |
| Sparse linalg kwarg | `gp2Scale_linalg_mode` | `gp2Scale_linalg_mode` | **`linalg_mode`** |
| Cached inverse | `calc_inv=True` | `calc_inv=True` | **`linalg_mode="CholInv"`** (`calc_inv` removed) |
| `tell()` rank-n update | `gp_rank_n_update` | `gp_rank_n_update` | **`rank_n_update`** |
| `ask()` acquisition value key | *claimed* `'f(x)'` | `'f_a(x)'` | **`'f_a(x)'`** |
| `posterior_mean()` key | *claimed* `'f(x)'` | `'m(x)'` | **`'m(x)'`** |
| Built-in acquisition strings | 5 documented | 11 | **14** (adds KG, NEI, target probability) |
| `kernel_function` / `prior_mean_function` / `noise_function` in ctor | *claimed rejected* | accepted | **accepted** |
| `LogGPOptimizer` / `LogitGPOptimizer` | absent | absent | **present** |
| `evaluate_posterior()` | absent | absent | **present** |

> **Vendored pin 8.3.9 (VISION, verified):** `evaluate_acquisition_function` keeps its
> sign (do not negate); a single-point `posterior_mean` is 0-d; `variance_only=True` needs memory
> that grows with V² (chunk large grids); `ask()` with a (V, D) ndarray candidate set fails (use a list,
> or your own masked argmax). See `gpcam-cog/SKILL.md`.

> When writing examples or answering questions, **use the 8.4 names**. Recognize the old
> ones as 8.3-era code, not typos.

### ⚠️ The `'m(x)'` vs `'f(x)'` discrepancy — UNRESOLVED, verify before beamtime

`gpcam-cog/SKILL.md` **Rule A** mandates `posterior_mean(x)["f(x)"]` and states this was
verified empirically on the 11BM install (gpcam 8.1.13). **That claim could not be
reproduced against any source available here:**

- fvgp 4.6.6, 4.6.11, 4.7.9 and 4.8.x all return the posterior mean under **`"m(x)"`**
  (`fvgp/gp_posterior.py`, the single `return` dict).
- gpcam 8.2.4, 8.2.9, 8.3.7 and 8.4.x all *call* `gpo.posterior_mean(x)["m(x)"]`
  internally in `surrogate_model.py` — the built-in acquisitions would be broken
  otherwise.
- Upstream `CLAUDE.md` states explicitly: *"`posterior_mean()` returns `"m(x)"` …
  **NOT `"f(x)"`**"* — i.e. upstream treats `f(x)` as a known misconception.
- `"f(x)"` **is** a real key elsewhere: `gpMCMC` traces (`fvgp/gp_mcmc.py`) and
  `optimize()`'s `'trace f(x)'`. A mis-attributed observation from one of those is the
  most likely origin of Rule A.

No gpcam 8.1.13 install exists on this machine, so 8.1.13 itself cannot be checked.

**Until someone re-runs the check on the actual beamline install, generated daemons
should use the version-safe accessor:**

```python
def _pm(gpo, x, **kw):
    """Posterior mean, tolerant of the m(x)/f(x) key split across gpCAM versions."""
    d = gpo.posterior_mean(x, **kw)
    for k in ("m(x)", "f(x)"):
        if k in d:
            return d[k]
    raise KeyError(f"posterior_mean returned unexpected keys: {list(d)}")
```

The same applies to `ask()`: use `r.get("f_a(x)", r.get("f(x)"))` if the acquisition
value is needed at all (`r["x"]` is stable across every version).

**One-line verification to run on the beamline host:**

```python
import gpcam, fvgp, numpy as np
from gpcam import GPOptimizer
print(gpcam.__version__, fvgp.__version__)
g = GPOptimizer(np.random.rand(5, 2), np.random.rand(5))
print("posterior_mean keys:", list(g.posterior_mean(np.random.rand(2, 2))))
print("ask keys:", list(g.ask(np.array([[0., 1.], [0., 1.]]))))
print("get_data keys:", list(g.get_data()))
```

### The 11BM pin

`gpcam-cog/SKILL.md` documents the beamline install as **8.1.13** with rules A–F. Those
rules remain **mandatory for generated daemons** until the pin is confirmed changed —
`SKILL.md` wins over this file on any conflict, *except* where a rule is version-safe
either way (e.g. `append=True`, which is the default in every version but harmless and
clearer when explicit).

---

## Core Classes

| Class | Purpose |
|---|---|
| `GPOptimizer` | Single-task (scalar output) GP optimizer |
| `fvGPOptimizer` | Multi-task (vector / function-valued output) GP optimizer |
| `LogGPOptimizer` | Single-task, strictly positive `y ∈ (0, ∞)`; GP models `log(y)` **[8.4+]** |
| `LogitGPOptimizer` | Single-task, bounded `y ∈ (0, 1)`; GP models `logit(y)` **[8.4+]** |
| `AutonomousExperimenterGP` / `…FvGP` | Batteries-included loop wrapper. **Not used at 11BM** — the flag-file contract needs an explicit `ask`/`tell` loop. |
| `gpMCMC`, `ProposalDistribution` | MCMC sampling (re-exported from `fvgp`) |

```python
from gpcam import GPOptimizer, fvGPOptimizer, LogGPOptimizer, LogitGPOptimizer
```

Class hierarchy: `GPOptimizerBase(fvgp.GP)` → `GPOptimizer` → `Log*`/`Logit*`;
`fvGPOptimizer(GPOptimizerBase, fvgp.fvGP)`.

---

## `GPOptimizer`

### Constructor — 8.4.x

```python
GPOptimizer(
    x_data=None,
    y_data=None,
    init_hyperparameters=None,
    noise_variances=None,
    compute_device="cpu",
    kernel_function=None,
    kernel_function_grad=None,
    noise_function=None,
    noise_function_grad=None,
    prior_mean_function=None,
    prior_mean_function_grad=None,
    gp2Scale=False,
    dask_client=None,              # 8.3.x: gp2Scale_dask_client
    gp2Scale_batch_size=10000,
    linalg_mode=None,              # 8.3.x: gp2Scale_linalg_mode (+ calc_inv, removed)
    ram_economy=False,
    cost_function=None,
    logging=False,
    args=None,
)
```

#### Parameters

| Parameter | Type / Default | Description |
|---|---|---|
| `x_data` | `ndarray` / `None` | Input positions, shape `(N, D)`. Non-Euclidean: a list of objects. |
| `y_data` | `ndarray` / `None` | Scalar observations, shape `(N,)`. **Must be 1-D** for `GPOptimizer`. |
| `init_hyperparameters` | `ndarray` / `None` | Initial hyperparameter vector. Default ARD kernel → shape `(D+1,)`: index `0` = signal variance, `1…D` = per-dimension length-scales. With a custom `kernel_function`, **its length defines how many hyperparameters exist** — gpCAM infers the count from this vector. |
| `noise_variances` | `ndarray` / `None` | Per-observation noise **variances** `σ²ᵢ`, shape `(N,)`. If `y_data` has `np.nan`, the matching entries must be `np.nan`. Provide **either** this **or** `noise_function`, never both. |
| `compute_device` | `str` / `"cpu"` | `"cpu"` or `"gpu"` (needs CUDA PyTorch). |
| `kernel_function` | `callable` / `None` | `k(x1, x2, hyperparameters)`; `x1` `(N1, D)`, `x2` `(N2, D)` → `(N1, N2)`. Default: anisotropic ARD Matérn-3/2. |
| `kernel_function_grad` | `callable` / `None` | `(x1, x2, hyperparameters, i)` → `(N1, N2)`, `i` = hyperparameter index. Optional; speeds up local training. |
| `noise_function` | `callable` / `None` | `f(x, hyperparameters)` → noise vector `(N,)` or matrix `(N, N)` for correlated noise. |
| `noise_function_grad` | `callable` / `None` | Gradient of the noise function w.r.t. hyperparameters. |
| `prior_mean_function` | `callable` / `None` | `m(x, hyperparameters)` → array of length `N`. |
| `prior_mean_function_grad` | `callable` / `None` | Gradient of the prior mean w.r.t. hyperparameters. |
| `gp2Scale` | `bool` / `False` | Large-scale sparse mode. Switches the default kernel to anisotropic Wendland. |
| `dask_client` | `Client` / `None` | `dask.distributed.Client` for gp2Scale. A local client is created if `None`. |
| `gp2Scale_batch_size` | `int` / `10000` | Kernel entries per Dask batch. |
| `linalg_mode` | `str` / `None` | `"Chol"`, `"sparseLU"`, `"Inv"`, `"CholInv"`. `"CholInv"` replaces the removed `calc_inv=True`. |
| `ram_economy` | `bool` / `False` | Avoid storing large intermediates. Slower, lower peak RAM. |
| `cost_function` | `callable` / `None` | `c(origin, x)` → positive cost per row of `x`. See **Cost Functions** below — the signature is **two positional args**, not three. |
| `logging` | `bool` / `False` | Enable internal `loguru` logging (`logger.disable('gpcam')` is called at import; this re-enables it). |
| `args` | `any` / `None` | Stored on the instance as `gpo.args`. **Read by acquisition functions off the object**, not passed as a call argument — see **Acquisition Functions**. |

**Default noise when none is given:** if neither `noise_variances` nor `noise_function`
is provided, noise variances are set to `abs(np.mean(y_data)) / 100.0`
(`gp_optimizer_base.py:326`). Note this is a **variance**, not a standard deviation, and
it is a *mean*-based, not *magnitude*-based, quantity — for 11BM data with a near-zero
mean it can collapse to nearly zero and make the GP interpolate noise. **Always pass
`noise_variances` explicitly** (see SKILL.md's ⭐ value-proportional default).

> **[8.1.13]** `SKILL.md` Rule D says the constructor **rejects** `kernel_function`,
> `noise_function`, `prior_mean_function` and their `_grad` variants with a `TypeError`,
> and that `gpcam.kernels` is not importable. This is not true of 8.2.4+ — all are
> accepted. Verify against the beamline install before relying on either behavior.

---

### `train`

Inherited from `fvgp.GP.train`.

```python
GPOptimizer.train(
    hyperparameter_bounds=None,
    objective_function=None,
    objective_function_gradient=None,
    objective_function_hessian=None,
    init_hyperparameters=None,
    method="global",
    pop_size=20,
    tolerance=0.0001,
    max_iter=120,
    local_optimizer="L-BFGS-B",
    global_optimizer="genetic",
    constraints=(),
    dask_client=None,
    info=False,
)
```

Maximize the log marginal likelihood over hyperparameters.

| Parameter | Default | Description |
|---|---|---|
| `hyperparameter_bounds` | `None` | `(J, 2)` array of `[lower, upper]` per hyperparameter. Estimated from data if `None` — **do not rely on this**; see SKILL.md Rule F. |
| `objective_function` | `None` | Custom objective (default: log marginal likelihood). With MAP training, add the log prior here. |
| `init_hyperparameters` | `None` | Starting point; defaults to the current hyperparameters. |
| `method` | `"global"` | `"global"`, `"local"`, `"hybrid"`, `"mcmc"`. `fvgp`'s own default is `"mcmc"`; gpCAM examples use `"global"`. |
| `pop_size` | `20` | Population for the genetic global optimizer. |
| `tolerance` | `1e-4` | Convergence tolerance. |
| `max_iter` | `120` | Max optimizer iterations. |
| `local_optimizer` | `"L-BFGS-B"` | Any SciPy-compatible local optimizer name. |
| `global_optimizer` | `"genetic"` | `"genetic"` or `"hgdl"`. |
| `constraints` | `()` | SciPy-format constraints on the hyperparameters. |
| `dask_client` | `None` | Dask client for `hgdl` / distributed training. |
| `info` | `False` | Print progress. |

**Returns:** the optimized hyperparameter vector (`ndarray`). The GP is updated
**in-place** — the return value can be ignored.

**Cost:** `train()` is O(N³) per likelihood evaluation × `max_iter`. In an AE loop this
dominates wall-clock. Retrain on a schedule (`RETRAIN_EVERY`), not every iteration.

---

### `train_async` / `stop_training` / `update_hyperparameters`

```python
opt_obj = gpo.train_async(hyperparameter_bounds=bounds, dask_client=client)
# ... experiment continues; the GP keeps using the OLD hyperparameters ...
gpo.update_hyperparameters(opt_obj)   # pull the current best into the GP
gpo.stop_training(opt_obj)            # halt the hgdl run (leaves the Dask client alive)
```

`train_async` takes the same parameters as `train` and returns an `opt_obj`.
`update_hyperparameters(opt_obj)` **reads the latest result out of a running async
training and applies it** — it does *not* take a hyperparameter array. `stop_training`
halts the optimizer without killing the Dask client (`kill_client()` for that).

---

### `ask` — 8.4.x

```python
GPOptimizer.ask(
    input_set,
    x_out=None,
    acquisition_function="variance",
    position=None,
    n=1,
    method="global",
    pop_size=20,
    max_iter=20,
    tol=1e-6,
    constraints=(),
    x0=None,
    vectorized=True,
    info=False,
    args=None,
    dask_client=None,
    batch_size=None,
)
```

Maximize the acquisition function to find the next measurement location(s).

| Parameter | Default | Description |
|---|---|---|
| `input_set` | — | **Euclidean:** a `(D, 2)` bounds array (continuous search) **or** a `(V, D)` candidate array. **Non-Euclidean:** a list of candidate objects. Must be a 2-D `ndarray` if an array. |
| `x_out` | `None` | Output/task coordinates, 1-D array. Multi-task only. Defaults to `self.x_out`. |
| `acquisition_function` | `"variance"` | A built-in string (14 options, see below) or a callable `f(x, gpo) → 1-D array`. **Always maximized.** |
| `position` | `None` | Current position, passed to the cost function as `origin`. **Omitting it silently disables cost-awareness** even when `cost_function` is set. |
| `n` | `1` | Number of points to suggest. See the override rules below. |
| `method` | `"global"` | `"global"`, `"local"`, `"hgdl"`. |
| `pop_size` | `20` | Population for the global optimizer. Overwritten by the `dask_client` config for `hgdl`. |
| `max_iter` | `20` | Max acquisition-optimizer iterations. |
| `tol` | `1e-6` | Local-optimizer termination tolerance. |
| `constraints` | `()` | SciPy constraint instances. |
| `x0` | `None` | `(N, D)` starting locations for the optimizer. |
| `vectorized` | `True` | Acquisition accepts a batch of points and returns a batch of scores. Forced `False` if `method != "global"`, and for `"total correlation"` / `"relative information entropy"`. |
| `info` | `False` | Print optimization info. |
| `args` | `None` | **Overwrites `self._args` permanently** — this is not a per-call override that reverts. Reaches acquisition functions as `gpo.args`. |
| `dask_client` | `None` | Client for `hgdl`. One is constructed (and closed again) if needed. |
| `batch_size` | `None` | With a candidate set + a Dask client, evaluate the acquisition in parallel batches of this size. |

**Returns:** `dict`

- `'x'` — suggested point(s), shape `(n, D)`
- `'f_a(x)'` — acquisition value(s) at those points — **[8.1.13: SKILL.md claims `'f(x)'`]**
- `'opt_obj'` — optimizer object; queryable for solutions only when `method="hgdl"`

```python
result = gpo.ask(input_set=parameter_bounds, acquisition_function="ucb")
new_x  = result["x"]        # (n, D) — this is what you measure
score  = result["f_a(x)"]   # acquisition value; 8.1.13 may use "f(x)"
```

#### ⚠️ `ask()` silently rewrites your arguments

Three rules in `gp_optimizer_base.py:509-540`, in order:

1. **Array `input_set` + `n > 1` + *callable* acquisition** → `method` is forced to
   `"hgdl"` and a Dask `Client()` is constructed if none was given (a `UserWarning` is
   emitted). Your custom batch acquisition therefore silently requires Dask.
2. **Array `input_set` + `n > 1` + `method != "hgdl"` + *string* acquisition** →
   `vectorized=False`, `method="global"`, the bounds are stacked `n` times, **and unless
   the string is already `"total correlation"` or `"relative information entropy"` it is
   replaced by `"total correlation"`** with a warning. So
   `ask(n=5, acquisition_function="expected improvement")` **does not run EI**.
3. **`"total correlation"` or `"relative information entropy"`** → `vectorized=False`
   regardless of what you passed.

At 11BM the loop asks for `n=1` on a candidate grid, so rule 2 does not fire — but any
future batch mode must ask for a batch-aware acquisition deliberately.

---

### `tell` — 8.4.x

```python
GPOptimizer.tell(x, y, noise_variances=None, append=True, rank_n_update=None)
```

| Parameter | Default | Description |
|---|---|---|
| `x` | — | New positions, `(M, D)` (or a list, non-Euclidean). |
| `y` | — | New observations, `(M,)`. |
| `noise_variances` | `None` | Noise variances **for the new points only**, `(M,)` — not the whole dataset. |
| `append` | `True` | `True` → append to the dataset; `False` → replace it entirely. |
| `rank_n_update` | `None` | 8.3.x name: `gp_rank_n_update`. `True` → rank-n update of the cached inverse (fast, drifts numerically); `False` → force full recomputation; `None` → let gpCAM decide. Only meaningful with an inverse-caching `linalg_mode`. |

**Returns:** `None`.

> **[8.1.13 — SKILL.md Rule C]** *"always pass `append=True` explicitly; the default does
> NOT accumulate."* The signature default has been `append=True` in every version
> inspected here (8.2.4 → 8.4.x), so the failure mode described in Rule C is more likely
> a caller that passed `append=False`. Passing it explicitly costs nothing and documents
> intent — **keep doing it**.

---

### `posterior_mean`

```python
GPOptimizer.posterior_mean(x_pred, hyperparameters=None, x_out=None)
```

| Parameter | Description |
|---|---|
| `x_pred` | `(V, D)` prediction locations, or a list (non-Euclidean). |
| `hyperparameters` | Evaluate under a different hyperparameter vector without changing the model. |
| `x_out` | Task coordinates (multi-task only). |

**Returns:** `dict` with key **`'m(x)'`** → shape `(V,)`, or `(V, len(x_out))` when
`x_out` is given. **[8.1.13: SKILL.md Rule A says `'f(x)'` — see the version matrix; use
the tolerant accessor.]**

---

### `posterior_covariance`

```python
GPOptimizer.posterior_covariance(x_pred, x_out=None, variance_only=False, add_noise=False)
```

| Parameter | Default | Description |
|---|---|---|
| `x_pred` | — | `(V, D)` prediction locations. |
| `x_out` | `None` | Task coordinates (multi-task). |
| `variance_only` | `False` | Return only the diagonal. Much cheaper for large `V`; only takes the genuinely-cheap path when an inverse is cached (`linalg_mode="CholInv"`). |
| `add_noise` | `False` | Add the noise variances → *predictive* rather than *latent* variance. |

**Returns:** `dict` with

- `'v(x)'` — pointwise **variances**, shape `(V,)` (or `(V, len(x_out))` multi-task)
- `'S'` — the full `(V, V)` posterior covariance matrix, present only when
  `variance_only=False`

> The full-matrix key is **`'S'`**, not `'S(x)'` — the old spelling in this file was
> wrong. Verified in `fvgp/gp_posterior.py` and upstream `CLAUDE.md`.

Take a square root for a standard deviation, and clamp first — the diagonal can go
slightly negative from round-off:

```python
std = np.sqrt(np.maximum(gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-12))
```

---

### `posterior_mean_grad`

```python
GPOptimizer.posterior_mean_grad(x_pred, hyperparameters=None, x_out=None, direction=None)
```

**`direction` is the FOURTH parameter and keyword-only in practice.** Calling
`posterior_mean_grad(x, 0)` positionally passes `0` as `hyperparameters` — a silent
wrong answer or a crash, not a `TypeError` about `direction`. The old signature line in
this file (`posterior_mean_grad(x_pred, direction)`) was wrong.

**Returns:** `dict` with key `'dm/dx'`.

| Call | Result shape | Meaning |
|---|---|---|
| `posterior_mean_grad(x)` | `(V, D)` | **Full gradient** — every input dimension |
| `posterior_mean_grad(x, direction=k)` | `(V, D)` | Only column `k` is filled; the rest are zero |

For any gradient-based acquisition you almost always want the **full** gradient:

```python
g = gpo.posterior_mean_grad(x)["dm/dx"]        # (V, D)
norm_g = np.linalg.norm(g, axis=1)             # (V,)
```

This is exactly what the built-in `"gradient"` acquisition does
(`surrogate_model.py:241`).

---

### `posterior_covariance_grad`

```python
GPOptimizer.posterior_covariance_grad(x_pred, x_out=None, direction=None)
```

Gradient of the posterior covariance w.r.t. the prediction location. Same
`direction=None` → full-gradient convention.

---

### `evaluate_posterior` **[8.4+]**

```python
GPOptimizer.evaluate_posterior(x, x_out=None, level=0.95,
                               return_samples=False, n_samples=10000)
```

The posterior of the **original-space observations**, as opposed to `posterior_mean` /
`posterior_covariance` which live in the GP's *modeling* space. For the plain
`GPOptimizer` (identity transform) it just bundles the Gaussian posterior; for
`LogGPOptimizer` / `LogitGPOptimizer` it pushes the Gaussian through the inverse
transform, so medians and credible bounds map exactly and the mean/std use the
closed-form lognormal moments.

**Returns:** `dict` with `"median"`, `"mean"`, `"std"`, `"lower"`, `"upper"`, `"level"`,
plus `"samples"` of shape `(n_points, n_samples)` when `return_samples=True`.

This is the right call for **error bars in a report** — `posterior_covariance` on a
`LogGPOptimizer` gives you log-space variance, which is not what a plot needs.

---

### `evaluate_acquisition_function`

```python
GPOptimizer.evaluate_acquisition_function(x, x_out=None,
                                          acquisition_function="variance",
                                          origin=None, args=None)
```

Evaluate the acquisition **without** optimizing it — the direct way to dump an
acquisition landscape for diagnostics or plotting, and the fastest way to sanity-check a
custom callable.

> **Sign convention (8.3.9 pin, verified):** this method returns the acquisition with
> its **sign unchanged** (higher = better), for built-in strings and callables; do not negate it.
> (Earlier notes said it returned the negated value; on 8.3.9 that turns UCB into an argmin.)
> The built-in `'variance'` returns σ, not the variance. Evaluate large grids in chunks.

```python
land = gpo.evaluate_acquisition_function(grid, acquisition_function="ucb")
```

`origin` is the cost function's starting position; the cost divisor is applied **only
when `origin is not None`** (`surrogate_model.py:196`).

---

### `optimize` — convenience loop

```python
GPOptimizer.optimize(*, func, search_space, x_out=None, hyperparameter_bounds=None,
                     train_at=(10, 20, 50, 100, 200), x0=None, acq_func="lcb",
                     max_iter=100, callback=None, break_condition=None,
                     ask_max_iter=20, ask_pop_size=20, method="global",
                     training_method="global", training_max_iter=20)
```

Keyword-only. Runs `tell`/`ask`/`train` internally against a callable `func(x) → (y, noise)`.
**Returns:** `dict` including `'trace f(x)'` (this is where a legitimate `"f(x)"` key
lives).

**Not usable at 11BM** — the measurement is not a Python callable, it's a flag-file
round-trip through op-cog and ana-cog. Use an explicit `ask`/`tell` loop.

---

### `get_data` and data attributes

```python
GPOptimizer.get_data()
```

**Returns:** `dict` with **space-separated** keys — `'x data'`, `'y data'`,
`'noise variances'`, `'hyperparameters'`, and more. Underscore names raise `KeyError`.
This has been true since at least 8.2.4.

**Prefer the attributes** — they are stable across every version and are what gpCAM's own
acquisition code uses:

```python
gpo.x_data          # (N, D)
gpo.y_data          # (N,)
gpo.hyperparameters # (J,)
gpo.input_space_dimension
gpo.args
```

---

## `fvGPOptimizer` — multi-task

```python
from gpcam import fvGPOptimizer
```

Same constructor and methods as `GPOptimizer`, with:

| Difference | Detail |
|---|---|
| `y_data` shape | `(N, L)`, `L` = number of output channels |
| `x_out` | 1-D array of task coordinates; pass to `ask`, `posterior_mean`, `posterior_covariance` |
| Kernel | Acts on the Cartesian product of input space and output space |
| Hyperparameters | More than `D+1`; the count is set by `init_hyperparameters` |
| Acquisition | Only 9 of the 14 strings are implemented for `x_out is not None` |

```python
import numpy as np
from gpcam import fvGPOptimizer

x_data = np.random.uniform(0, 1, (1000, 1))
y_data = np.stack([np.sin((i + 1) * x_data[:, 0]) for i in range(10)], axis=1)  # (1000, 10)

gp = fvGPOptimizer(x_data, y_data,
                   init_hyperparameters=np.ones(2) / 10.,
                   noise_variances=np.ones_like(y_data) * 0.1)
gp.train(hyperparameter_bounds=np.array([[0.01, 10.], [0.01, 10.]]), max_iter=100)

next_x = gp.ask(input_set=np.array([[0., 1.]]),
                x_out=np.arange(10),
                acquisition_function="relative information entropy set")["x"]
```

> **Do not use plain `"expected improvement"` multi-task.** The `x_out` branch
> (`surrogate_model.py:312-323`) sums the posterior mean over tasks *and sums the
> standard deviations over tasks*, then compares against `np.max(gpo.y_data)`. A sum of
> standard deviations is not the standard deviation of a sum — that needs the cross-task
> covariance — so the number is not the expected improvement of anything.
> `"knowledge gradient"` and `"noisy expected improvement"` scalarize the same
> task-summed objective `g(x) = Σ_t f(x, t)` but build the joint posterior correctly.
> Details: the `multi-task-advanced` skill.

---

## `LogGPOptimizer` / `LogitGPOptimizer` **[8.4+]**

Output-transform wrappers around `GPOptimizer`. Same constructor arguments.

| Class | Domain | GP models | Guarantees |
|---|---|---|---|
| `LogGPOptimizer` | `y > 0` | `log(y)` | Strictly positive predictions and credible bounds; exact lognormal mean/std |
| `LogitGPOptimizer` | `0 < y < 1` | `logit(y)` | Predictions and bounds stay inside `(0, 1)` |

`LogGPOptimizer` raises `ValueError` on any `y ≤ 0`.

**Relevant at 11BM:** scattering intensities, peak prefactors, and integrated areas are
strictly positive and often span orders of magnitude. A plain GP on such data puts
credible intervals below zero and over-weights the large values. `LogGPOptimizer` is the
principled fix — **but it is 8.4+ only**, so it is unavailable if the pin really is
8.1.13. The version-safe equivalent is to model `log(y)` yourself and exponentiate for
reporting.

**Two rules when using them:**

- Inherited `posterior_mean` / `posterior_covariance` operate in **transformed space**.
  Use `evaluate_posterior()` for original-scale numbers.
- Ranking acquisitions (`variance`, `ucb`, `lcb`, `maximum`, `minimum`) pick the same
  points either way because the transforms are monotone. For `"target probability"`,
  pass the band already transformed: `args={"a": np.log(0.95), "b": np.log(1.05)}`.

---

## Acquisition Functions

`ask(acquisition_function=…)` takes a **built-in string** or a **callable**. The value is
always **maximized** — higher = more desirable.

### Built-in strings — single-task (`x_out is None`), 8.4.x

All 14, with what the source actually computes (`surrogate_model.py:218-283`):

| String | Computes | Notes |
|---|---|---|
| `"variance"` | `√v(x)` | ⚠️ Returns the **standard deviation**, not the variance, despite the name. Same argmax, different reported `f_a(x)`. |
| `"relative information entropy"` | `−RIE(x)` over the whole set | Returns a **length-1 array** regardless of `len(x)`; forces `vectorized=False`. |
| `"relative information entropy set"` | `−RIE` per point | Vectorized version; batch-friendly. |
| `"ucb"` | `m(x) + 3.0·√v(x)` | **β is hardcoded to 3.0.** Not tunable — write a callable if you need a different β. |
| `"lcb"` | `−(m(x) − 3.0·√v(x))` | Minimization. β hardcoded to 3.0. |
| `"maximum"` | `m(x)` | Pure exploitation. Will re-measure the same point forever. |
| `"minimum"` | `−m(x)` | Pure exploitation, minimizing. |
| `"gradient"` | `‖∇m(x)‖ · √v(x)` | Change/boundary mapping. Uses the full gradient. |
| `"probability of improvement"` | `Φ((m − y⁺)/σ)` | `y⁺ = np.max(gpo.y_data)` — the largest **noisy observation**. |
| `"expected improvement"` | `σ·(γΦ(γ) + φ(γ))`, `γ = max(m − y⁺, 0)/σ` | See the caveat below. |
| `"total correlation"` | `−total correlation` over the batch | Batch acquisition; forces `vectorized=False`. |
| `"knowledge gradient"` | Expected increase in `max m(x)` after a fantasized measurement (KGCP) | `args={'kg_reference_set_size': int, 'kg_seed': int}`. Maximization only. |
| `"noisy expected improvement"` | EI averaged over the posterior of the incumbent (Letham et al. 2019) | `args={'nei_samples': int, 'nei_reference_set_size': int, 'nei_seed': int}`. Robust to observation noise. Maximization only. |
| `"target probability"` | `P(a ≤ f(x) ≤ b)` | **Requires** `args={"a": …, "b": …}` or it raises. |

### Built-in strings — multi-task (`x_out is not None`)

Only **nine** are implemented: `"variance"`, `"relative information entropy"`,
`"relative information entropy set"`, `"total correlation"`, `"ucb"`, `"lcb"`,
`"expected improvement"`, `"knowledge gradient"`, `"noisy expected improvement"`.
Anything else raises `Exception("No valid acquisition function string provided…")`.

### ⚠️ The EI caveat

gpCAM's EI clips `a = max(m − y⁺, 0)`, so **while no posterior mean anywhere exceeds the
incumbent, `γ = 0` and EI reduces to `σ · φ(0) = 0.3989 · σ(x)`** — identical in ranking
to `"variance"` ([gpCAM #55](https://github.com/lbl-camera/gpCAM/issues/55)). Early in a
run EI is not exploiting at all; it is pure exploration wearing an exploitation label.

And because the incumbent is `np.max(y_data)` — the largest *noisy reading*, not the
posterior mean — EI on noisy data locks onto a noise spike. `"noisy expected
improvement"` exists specifically to fix this.

### ⚠️ Everything hunts maxima

`"expected improvement"`, `"probability of improvement"`, `"ucb"`, `"maximum"`,
`"knowledge gradient"` and `"noisy expected improvement"` all hardcode `np.max(...)` or
the raw posterior mean. Asking for a **minimum** with any of them silently maximizes. Use
`"lcb"`, `"minimum"`, a negating callable, or negate the measurement itself.

### Custom callables — the version-proof option

**Signature: `f(x, gpo) → 1-D array of length `len(x)`.** Exactly two positional
arguments (`surrogate_model.py:200`). Extra configuration is read off `gpo.args`, not
passed in:

```python
def _acq_arg(gpo, key, default):
    a = getattr(gpo, "args", None)
    return a[key] if isinstance(a, dict) and a.get(key) is not None else default

def ucb_tunable(x, gpo):
    beta = _acq_arg(gpo, "beta", 3.0)
    m   = gpo.posterior_mean(x)["m(x)"]
    std = np.sqrt(np.maximum(gpo.posterior_covariance(x, variance_only=True)["v(x)"], 1e-12))
    return m + beta * std

gpo.args = {"beta": 2.0}                      # or GPOptimizer(..., args={"beta": 2.0})
next_x = gpo.ask(input_set=bounds, acquisition_function=ucb_tunable)["x"]
```

Alternatively bind parameters with `functools.partial(f, beta=2.0)` — but note gpCAM
calls the function as `acquisition_function(x, gpo)` positionally, so only **keyword**
parameters can be bound this way.

Callables are the only acquisition surface guaranteed to work across all versions,
because `acquisition_function` is an `ask()` argument, not a constructor argument. Recipes
(target value, threshold/level set, radical gradient, cost-aware, multi-objective) live in
the **`gpcam-customization`** skill and
`gpcam-customization/references/choosing-an-acquisition-function.md`.

**Requirements for a callable:**
- returns a **1-D array**, length `len(x)`, never a scalar
- higher = better (gpCAM maximizes)
- no `NaN`/`inf` — the optimizer will chase them
- vectorized over rows of `x` if `vectorized=True` (the default)

---

## Cost Functions

```python
def my_cost(origin, x):
    """Cost of moving from `origin` to each row of `x`. Must be strictly > 0."""
    return 1.0 + 4.0 * np.abs(x[:, 0] - origin[0])

gpo = GPOptimizer(x_data, y_data, cost_function=my_cost)
next_x = gpo.ask(input_set=bounds, acquisition_function="variance",
                 position=current_motor_position)["x"]
```

**Two rules, both easy to get wrong:**

1. **The signature is `cost_function(origin, x)` — two positional arguments.**
   `surrogate_model.py:196` calls it as `cost_function(origin, x)`. A third
   `hyperparameters` or `arguments` parameter must have a default or the call raises.
2. **`position=` must be passed to `ask()`.** The cost divisor is applied only when
   `origin is not None`. Setting `cost_function` and forgetting `position` silently
   disables cost-awareness — no warning.

The cost **divides** the acquisition (`acq / cost`), so an expensive move has to earn its
score. Cost must be strictly positive; a zero or negative cost inverts or explodes the
ranking.

---

## gp2Scale — large-scale GPs

For `N ≳ 10,000`. Sparse Wendland kernels + Dask for an *exact* (not approximate) GP.

```python
from distributed import Client
from gpcam import GPOptimizer

client = Client()
gpo = GPOptimizer(
    x_data, y_data,
    gp2Scale=True,
    dask_client=client,           # 8.3.x: gp2Scale_dask_client
    gp2Scale_batch_size=10000,
    linalg_mode="Chol",           # 8.3.x: gp2Scale_linalg_mode
)
```

A custom kernel used with gp2Scale **must produce sparse matrices** (compact support).
The default is switched to an anisotropic Wendland kernel automatically. Detail: the
**`gp2scale-advanced`** skill.

**Not relevant to a typical 11BM AE** — those run tens to a few hundred points. Reach for
gp2Scale only if a run accumulates thousands.

---

## Hyperparameter Conventions

Default ARD Matérn-3/2 kernel, `D`-dimensional inputs:

| Index | Meaning |
|---|---|
| `hp[0]` | Signal variance |
| `hp[1] … hp[D]` | Per-dimension length-scales |

Total `J = D + 1`. **Adding a custom `noise_function` or `prior_mean_function` appends
more.** All three share **one flat vector** with **disjoint index ranges** — e.g. kernel
`0…D`, prior mean `D+1…D+2`, noise `D+3`. Two functions reading the same index is a
silent, hard-to-find bug: gradient computation assumes zero cross-derivatives between the
blocks.

`init_hyperparameters` **defines `J`** — gpCAM infers the count from its length.
`hyperparameter_bounds` must then be shape `(J, 2)`.

**Starting bounds (generic):**
- signal variance: `[0.01, 10 · var(y)]`
- length-scales: `[0.01, 10 · range(x_d)]` per dimension

**11BM (SKILL.md Rule F) — tie the bounds to the physical scan, not to defaults:** lower
length-scale bound ≈ the grid spacing / beam size, upper ≈ the scan range. Persist both
`hyperparameter_bounds_initial` and `hyperparameter_bounds_policy` in
`gpcam_metadata.json` when the bounds are recomputed during the run.

---

## Minimal Loop Pattern

```python
import numpy as np
from gpcam import GPOptimizer

x_data = np.random.uniform(0, 1, (20, 1))
y_data = np.sin(5 * x_data[:, 0])
bounds = np.array([[0., 1.]])                    # (D, 2) search space
hp_bounds = np.array([[0.01, 10.], [0.01, 10.]]) # (J, 2), J = D + 1

gpo = GPOptimizer(x_data, y_data,
                  noise_variances=np.full(len(y_data), 0.01))
gpo.train(hyperparameter_bounds=hp_bounds, method="global", max_iter=100)

for i in range(100):
    acq = "variance" if i < 20 else "ucb"        # explore, then exploit
    new_x = gpo.ask(input_set=bounds, acquisition_function=acq)["x"]
    new_y = np.sin(5. * new_x[:, 0])
    gpo.tell(new_x, new_y,
             noise_variances=np.full(len(new_y), 0.01),
             append=True)
    if (i + 1) % 10 == 0:
        gpo.train(hyperparameter_bounds=hp_bounds, method="local", max_iter=100)
```

The 11BM AE loop replaces the `new_y = …` line with a flag-file round-trip
(`GPCAM_NEXT.txt` → op-cog measures → `TRIGGER.txt` → ana-cog → `ANA_DONE.txt` →
read `ana_log.csv`). Canonical shape: `gpcam-cog/SKILL.md`; flag semantics:
`docs/flag-file-contract.md`.

---

## Common Patterns

### Async training (non-blocking)

```python
opt_obj = gpo.train_async(hyperparameter_bounds=hp_bounds, dask_client=client)
# ... several ask/tell iterations happen with the OLD hyperparameters ...
gpo.update_hyperparameters(opt_obj)
gpo.stop_training(opt_obj)
```

### Custom kernel

```python
import numpy as np
from fvgp.kernels import matern_kernel_diff1   # gpcam.kernels re-exports this

def my_kernel(x1, x2, hps):
    d = np.zeros((len(x1), len(x2)))
    for dim in range(x1.shape[1]):
        d += ((x1[:, dim:dim+1] - x2[:, dim]) / hps[dim + 1]) ** 2
    return hps[0] * matern_kernel_diff1(np.sqrt(d), 1.0)

gpo = GPOptimizer(x_data, y_data,
                  init_hyperparameters=np.ones(x_data.shape[1] + 1),
                  kernel_function=my_kernel)
```

Available kernel building blocks (via `gpcam.kernels`, i.e. `fvgp.kernels`):
`get_distance_matrix`, `get_anisotropic_distance_matrix`, `matern_kernel_diff1`
(Matérn-3/2, the default), `matern_kernel_diff2` (Matérn-5/2),
`squared_exponential_kernel`, `sparse_kernel`, `wendland_kernel`, `polynomial_kernel`,
`dot_product_kernel`.

`matern_kernel_diff1(d, ℓ) = (1 + √3·d/ℓ)·exp(−√3·d/ℓ)` —
once differentiable, the physically sensible default for scattering data.
`squared_exponential_kernel` is infinitely differentiable and **over-smooths** real
measurements; prefer Matérn.

### Custom prior mean

```python
def linear_prior(x, hps):
    return hps[D + 1] + hps[D + 2] * x[:, 0]    # indices AFTER the kernel's 0…D

gpo = GPOptimizer(x_data, y_data,
                  init_hyperparameters=np.ones(D + 3),
                  prior_mean_function=linear_prior)
```

The default prior mean is the **data mean**, not zero. Do not index `hps[-1]` — that
collides with whichever block happens to be last.

### Custom noise function

```python
def my_noise(x, hps):
    return np.full(len(x), hps[D + 3])          # a fitted noise level
```

Pass **either** `noise_function` **or** `noise_variances`, never both. For 11BM the ⭐
learned default is a **value-proportional** fixed array, `noise_variances = (0.10·|y|)²`
clipped below — *not* the peak-fit error, which causes edge-piling (`gpcam-customization` §4).

### Constrained acquisition

```python
from scipy.optimize import NonlinearConstraint
constraint = NonlinearConstraint(fun=lambda x: np.linalg.norm(x), lb=0, ub=1)
new_x = gpo.ask(input_set=bounds, constraints=[constraint])["x"]
```

### Minimum-sample-distance guard (11BM)

Continuous `ask()` will happily re-propose a point already measured. The 11BM pattern is not
a constraint but a **candidate grid + exclusion mask + argmax** on
`evaluate_acquisition_function` — exact, cheap, and impossible for the optimizer to talk its
way out of. Code and settings: `gpcam-cog` SKILL → *Min-step guard* (values from
`config.json → gpcam.sampling`).

The one API trap: if every cell is masked, `np.where(mask, acq, -inf)` is all `-inf` and
`.argmax()` silently returns index 0 — the loop then re-proposes that corner forever. Always
branch on `mask.any()` first.

**Coupling invariant:** the candidate grid spacing must equal `min_sample_distance` — a coarser
grid makes the min-step knob a no-op (every pick snaps to the grid). For the single- and
two-stage rule, the guard/clamp, and the startup-log requirement, see `gpcam-customization` §6.

### Non-Euclidean inputs (e.g. strings)

```python
def string_kernel(x1, x2, hps):
    d = np.array([[abs(len(a) - len(b)) for b in x2] for a in x1], dtype=float)
    return hps[0] * matern_kernel_diff1(d, hps[1])

gpo = GPOptimizer(list_of_strings, y_data,
                  init_hyperparameters=np.ones(2),
                  kernel_function=string_kernel)
next_x = gpo.ask(input_set=candidate_string_list)["x"]
```

`input_set` must be a **list of candidates**, not a bounds array.

---

## Performance Guidelines

| Scenario | Recommendation |
|---|---|
| `N < 2000`, many posterior evaluations | `linalg_mode="CholInv"` (8.3.x: `calc_inv=True`) |
| `N > 2000` | default `linalg_mode`, `ram_economy=True` |
| `N > 10,000`, exact GP required | `gp2Scale=True` + Dask client |
| Training dominates the loop | retrain every `k` iterations, or `train_async` |
| Large candidate grids | `variance_only=True`; evaluate the acquisition in chunks |
| GPU | `compute_device="gpu"` with a CUDA PyTorch build |

`train()` is O(N³) per likelihood evaluation. At 11BM iteration cost is dominated by the
measurement, so retraining every ~5–10 points is essentially free — but do not retrain
inside a tight scoring loop.

---

## Common Mistakes

| Mistake | Fix |
|---|---|
| `new_x = gpo.ask(input_set)` used as an array | `gpo.ask(input_set)["x"]` — `ask` returns a dict |
| `gpo.posterior_mean(x)` used as an array | `["m(x)"]` (8.4.x) — and see the version matrix for `"f(x)"` |
| `["S(x)"]` for the full covariance | The key is **`["S"]`**; `["v(x)"]` for variances |
| `posterior_mean_grad(x, 0)` for direction 0 | `posterior_mean_grad(x, direction=0)` — positional `0` becomes `hyperparameters` |
| Expecting `posterior_mean_grad(x)` to need a direction | Omit it: `direction=None` returns the **full** `(V, D)` gradient |
| `ask(n=5, acquisition_function="expected improvement")` | Silently replaced by `"total correlation"`. Ask for a batch acquisition, or use `method="hgdl"` + a callable |
| `"ucb"` with a custom β | β is hardcoded to 3.0. Write a callable |
| EI chosen for early exploration-free exploitation | Until a mean exceeds the incumbent, EI **is** `0.3989·σ` — same ranking as `"variance"` |
| EI/PI/UCB/KG/NEI used to find a **minimum** | They all maximize silently. Use `"lcb"`, `"minimum"`, or negate |
| `cost_function` set but no `position=` in `ask()` | Cost is silently ignored — `origin` must not be `None` |
| `cost_function(origin, x, hyperparameters)` | Called with **two** args; a third needs a default |
| `args` expected as a third acquisition parameter | Callables get `(x, gpo)`; read `gpo.args` |
| `ask(args=…)` expected to be a one-call override | It **overwrites** `self._args` for good |
| `init_hyperparameters=np.ones(3)` with a 5-parameter kernel | The length of `init_hyperparameters` **defines** `J` — it must match |
| `hyperparameter_bounds` shape `(J,)` | Must be `(J, 2)`, each row `[lower, upper]` |
| `x_data` shape `(N,)` for 1-D inputs | `x_data.reshape(-1, 1)` — must be `(N, D)` |
| `y_data` shape `(N, 1)` for single-task | `y_data.reshape(-1)` — must be `(N,)` for `GPOptimizer` |
| `noise_variances` sized to the whole dataset in `tell()` | In `tell()` it covers **only the new points**, length `M` |
| No `noise_variances` at all | Defaults to `abs(mean(y))/100` — near zero for zero-mean data; the GP then interpolates noise |
| Custom acquisition returning a scalar | Must return a 1-D array of length `len(x)` |
| Expecting `train()` to return-and-not-mutate | It updates the GP **in place** immediately |
| `posterior_mean` on a `LogGPOptimizer` for a plot | That's log-space. Use `evaluate_posterior()` |
| `evaluate_acquisition_function` negated before plotting or argmax | On the 8.3.9 pin it returns the acquisition with its sign unchanged; use it as returned |

---

## Resources

- Documentation: https://gpcam.readthedocs.io
- Examples: https://gpcam.lbl.gov/examples
- GitHub: https://github.com/lbl-camera/gpCAM · fvgp: https://github.com/lbl-camera/fvgp
- Migration notes for 8.3 → 8.4: `HISTORY.rst` in the gpCAM repo
-

### Related skills

| Need | Skill |
|---|---|
| Choosing / writing an acquisition function | `gpcam-customization` (+ `references/choosing-an-acquisition-function.md`) |
| Custom kernels, priors, noise models | `gpcam-customization` |
| An error, a stall, or error bars you don't trust | `gpcam-diagnostics` |
| Multi-task / `fvGPOptimizer` | `multi-task-advanced` |
| gp2Scale, Dask, sparse kernels | `gp2scale-advanced` |
| The 11BM AE loop and flag-file contract | `gpcam-cog/SKILL.md`, `docs/flag-file-contract.md` |
