---
name: ana-customization
description: One-stop skill for customizing existing SciAnalysis protocols at the 11BM beamline — subclass a `Protocols.X`, override its `run`, swap in a different fit model, add derived metrics, or restyle the plot. Open this skill whenever a parameter tweak alone is not enough and a structural change to an existing protocol is needed. Custom classes always live inline at the top of the generated `ana_runXS_<name>.py`. Never used for brand-new protocols written from scratch.
---

# Skill: SciAnalysis Protocol Customization (subclass-only)

Consolidates the canonical pattern for **customizing existing SciAnalysis protocols by subclassing**. Custom classes are placed **inline at the top of the generated `ana_runXS_<name>.py`**, never in a separate module, and never as edits to SciAnalysis source.

This skill is opened **on top of** `ana-cog`, not instead of it. `ana-cog` still defines the runtime, `ProcessorXS` rule, calibration/mask setup, and coordination contract. This skill only governs how to author the custom class itself.

---

## When to open this skill

| Need | Skill |
|---|---|
| Parameter tweak only (`trim_range`, `q0`, `num_curves`, `fit_range`, etc.) | **ana-cog** — pass kwargs to the built-in protocol |
| Different built-in protocol for the same intent (`circular_average` → `sector_average`) | **ana-cog** |
| Change the fit model, replace plot annotations, add derived metrics (`d0`, `grain_size`), chain multiple fits inside one protocol, or apply GISAXS refraction correction | **ana-customization** (this skill) |
| Brand-new extraction that needs a new `data.<binner>` method | Out of scope — flag to the user; do not write |

---

## Required reading

Before writing any code, read:

1. [subclass_template.md](subclass_template.md) — the canonical skeleton
2. [examples.md](examples.md) — annotated real-world customizations

---

## The pattern (mandatory five-slot recipe)

Every customization follows this exact shape — only what's inside each slot changes:

1. **Subclass an existing `Protocols.X`.** Pick the parent whose `data.<binner>` already produces the curve you need (e.g. `Protocols.linecut_qz` for a qz fit, `Protocols.sector_average` for an angular wedge fit).
2. **`__init__`** sets `self.name`, `self.default_ext`, populates `self.run_args` with defaults, then merges `kwargs`.
3. **`run` is decorated** with `@tools.run_default` (or the equivalent `@Protocols.run_default`).
4. **`run` body** calls `data.<binner>(**run_args)` → `DataLine`, saves the `.dat` via `self.get_outfile`, runs a private `_fit_peaks` (lmfit), packs results, builds a nested `DataLines_current(DataLines)` with a `_plot_extra` for annotations, and plots.
5. **Returns a `results` dict.** Keys follow `<fit_name>_<param_name>` mapping to `{'value': param.value, 'error': param.stderr}`. Derived scalars (`d0`, `grain_size`, `chi_squared`, `prefactor_total`) use the same prefix.

---

## Hard rules

- **Subclass only.** Never write a Protocol from scratch.
- **Never edit files under the SciAnalysis source tree.** Customization is additive only.
- **Custom classes go inline** at the top of `ana_runXS_<name>.py`, above the `protocols = [...]` list. They are not imported from a separate module.
- **Use the parent's `data.<binner>`.** Do not re-implement the binner in the subclass.
- **Merge `kwargs` in `__init__`** so caller kwargs override defaults: `self.run_args.update(kwargs)`.
- **Use lmfit** for new fit models. The private `_fit_peaks` (or similarly named) must return `(lm_result, fit_line, fit_line_extended)` to match the pattern.
- **Annotation overlays** belong in a nested `class DataLines_current(DataLines)` with a `_plot_extra(self, **plot_args)` method, instantiated inside `run`. Never monkey-patch the global `DataLines`.
- **Result keys** follow `<fit_name>_<param_name>`. Always include `<fit_name>_chi_squared = lm_result.chisqr / lm_result.nfree`.
- **The custom class can be used in the same `protocols = [...]` list** alongside built-in `Protocols.X(...)`. `ProcessorXS` requires no registration step.

---

## Anti-patterns

- ❌ Editing `SciAnalysis/XSAnalysis/Protocols.py` directly.
- ❌ Re-implementing a binner (`data.circular_average_q_bin`, `data.linecut_qz`, etc.) in the subclass.
- ❌ Forgetting `@tools.run_default` — `run` will not receive merged `run_args`.
- ❌ Hard-coding paths or physical constants that should be passed via `run_args`.
- ❌ Defining the custom class in a separate file and importing it.
- ❌ Calling `super().run(...)` and then patching its output. Override the whole `run` body — the parent's `run` produces a different artifact set.
- ❌ Mutating module-level `DataLines` to add annotations — always use a nested subclass.
- ❌ Returning anything other than a `results` dict from `run`.

---

## Self-check (mechanical)

Before finishing, verify:

- subclass parent is a real `Protocols.X` listed in `ana-cog`'s `reference.md`
- `__init__` sets `name`, `default_ext`, `run_args`, then calls `self.run_args.update(kwargs)`
- `run` is decorated with `@tools.run_default` or `@Protocols.run_default`
- the binner call uses `data.<method>(**run_args)`
- `.dat` saved via `self.get_outfile(data.name, output_dir, ext='.dat')` then `line.save_data(outfile)`
- `_fit_peaks` returns `(lm_result, fit_line, fit_line_extended)`
- `results` dict keys use `<fit_name>_<param_name>`
- `<fit_name>_chi_squared` is included
- custom class is **inline at the top of `ana_runXS_<name>.py`**, above `protocols = [...]`
- no edits made to the SciAnalysis source tree
- custom class appears in the `protocols = [...]` list with `name=`, defaults, and any per-call kwargs
