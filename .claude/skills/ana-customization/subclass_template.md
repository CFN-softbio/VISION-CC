# Subclass Template — Canonical Skeleton

This is the exact skeleton every customization follows. Fill the four marked slots; leave everything else unchanged.

The class is placed **inline at the top of `ana_runXS_<name>.py`**, above the `protocols = [...]` list. No separate module, no import step.

---

## The skeleton

```python
# ============================================================
# Custom protocol (inline in ana_runXS_<name>.py, above protocols=[...])
# ============================================================

class my_custom_protocol(Protocols.<PARENT>):    # ← SLOT 1: pick the parent
    """
    Subclass of Protocols.<PARENT>.
    Overrides .run() to <one-line reason>.
    """

    def __init__(self, name='<default_name>', **kwargs):

        self.name = self.__class__.__name__ if name is None else name

        self.default_ext = '.png'
        self.run_args = {                         # ← SLOT 2: protocol defaults
            'show_region' : False,
            # 'plot_range' : [...],
            # 'qn_power' : 2.0,
            # ...
        }
        self.run_args.update(kwargs)


    @tools.run_default                            # required decorator
    def run(self, data, output_dir, **run_args):

        results = {}

        # --- Extract curve from data using the PARENT's binner ---
        line = data.<binner>(**run_args)          # ← SLOT 3a: parent's binner

        if 'show_region' in run_args and run_args['show_region']:
            data.plot(show=True)

        # --- Save raw curve ---
        outfile = self.get_outfile(data.name, output_dir, ext='.dat')
        line.save_data(outfile)

        # --- Optional: trim before fitting ---
        if 'fit_range' in run_args:
            line.trim(run_args['fit_range'][0], run_args['fit_range'][1])

        # --- Fit ---
        lm_result, fit_line, fit_line_extended = self._fit_peaks(line, **run_args)

        # --- Pack lmfit params into results ---
        fit_name = 'fit_peaks'
        prefactor_total = 0
        for param_name, param in lm_result.params.items():
            results['{}_{}'.format(fit_name, param_name)] = {
                'value': param.value,
                'error': param.stderr,
            }
            if 'prefactor' in param_name:
                prefactor_total += np.abs(param.value)

        results['{}_prefactor_total'.format(fit_name)] = prefactor_total
        results['{}_chi_squared'.format(fit_name)] = lm_result.chisqr / lm_result.nfree

        # --- Derived metrics (optional) ---
        q0 = results['{}_x_center1'.format(fit_name)]['value']
        results['{}_d0'.format(fit_name)] = 0.1 * 2.0 * np.pi / q0          # nm
        sigma = results['{}_sigma1'.format(fit_name)]['value']
        results['{}_grain_size'.format(fit_name)] = 0.1 * (2.0*np.pi/np.sqrt(2.0*np.pi)) / sigma

        # --- Custom plot annotations ---     ← SLOT 4: annotation overlay
        class DataLines_current(DataLines):
            def _plot_extra(self, **plot_args):
                xi, xf, yi, yf = self.ax.axis()
                v_spacing = (yf - yi) * 0.10

                yp = yf
                s = '$q_0 = \\, {:.4f} \\, \\mathrm{{\\AA}}^{{-1}}$'.format(
                    self.results['fit_peaks_x_center1']['value'])
                self.ax.text(xf, yp, s, size=20, color='b',
                             verticalalignment='top', horizontalalignment='right')
                # ...add more lines as needed...

        lines = DataLines_current([line, fit_line, fit_line_extended])
        lines.copy_labels(line)
        lines.results = results

        outfile = self.get_outfile(data.name, output_dir)
        try:
            lines.plot(save=outfile, **run_args)
        except ValueError:
            pass

        return results


    def _fit_peaks(self, line, num_curves=1, **run_args):
        """Slot 3b: custom fit model. Must return (lm_result, fit_line, fit_line_extended)."""
        import lmfit

        def model(v, x):
            m = v['m'] * x + v['b']
            for i in range(num_curves):
                m += v['prefactor{:d}'.format(i+1)] * np.exp(
                    -np.square(x - v['x_center{:d}'.format(i+1)]) /
                    (2 * (v['sigma{:d}'.format(i+1)] ** 2))
                )
            return m

        def func2minimize(params, x, data):
            v = params.valuesdict()
            return model(v, x) - data

        params = lmfit.Parameters()
        params.add('m', value=0)
        params.add('b', value=np.min(line.y), min=0, max=np.max(line.y))

        xspan = np.max(line.x) - np.min(line.x)
        xpeak, ypeak = line.target_y(np.max(line.y))
        for i in range(num_curves):
            params.add('prefactor{:d}'.format(i+1),
                       value=ypeak - np.min(line.y), min=0, max=np.max(line.y) * 10)
            params.add('x_center{:d}'.format(i+1),
                       value=xpeak, min=np.min(line.x), max=np.max(line.x))
            params.add('sigma{:d}'.format(i+1),
                       value=xspan * 0.20, min=0, max=xspan * 0.50)

        lm_result = lmfit.minimize(func2minimize, params, args=(line.x, line.y))

        if run_args.get('verbosity', 3) >= 5:
            print('Fit results (lmfit):')
            lmfit.report_fit(lm_result.params)

        fit_x = line.x
        fit_y = model(lm_result.params.valuesdict(), fit_x)
        fit_line = DataLine(x=fit_x, y=fit_y,
                            plot_args={'linestyle': '-', 'color': 'b',
                                       'marker': None, 'linewidth': 4.0})

        fit_x = np.linspace(np.min(line.x), np.max(line.x), num=200)
        fit_y = model(lm_result.params.valuesdict(), fit_x)
        fit_line_extended = DataLine(x=fit_x, y=fit_y,
                                     plot_args={'linestyle': '-', 'color': 'b',
                                                'alpha': 0.5, 'marker': None,
                                                'linewidth': 2.0})

        return lm_result, fit_line, fit_line_extended
```

---

## The four slots

| Slot | What you set | How to choose it |
|---|---|---|
| **1. Parent class** | `Protocols.<PARENT>` | Pick the protocol whose `data.<binner>` already produces the curve shape you want to fit. For radial fits → `circular_average`. For wedge fits → `sector_average`. For GISAXS in-plane → `linecut_qr`. For GISAXS out-of-plane → `linecut_qz`. For χ scans → `linecut_angle`. |
| **2. Default `run_args`** | dict of protocol-specific defaults | Inherit sensible defaults from the parent (`show_region=False`, `plot_range`, `linewidth`). Add anything your custom run needs (`qn_power`, `fit_range`, `q0_expected`). |
| **3a. Binner call** | `data.<binner>(**run_args)` | Mirror the parent's binner: `data.circular_average_q_bin`, `data.sector_average_q_bin`, `data.linecut_angle`, `data.linecut_qr`, `data.linecut_qz`. Never re-implement. |
| **3b. `_fit_peaks` body** | lmfit model + params + minimize | Default = Gaussians on linear background. Swap in Voigt, multiple peaks, library fit, refraction-corrected qz, etc. Return signature is fixed: `(lm_result, fit_line, fit_line_extended)`. |
| **4. `_plot_extra`** | annotations to overlay | Read `self.results[...]` and place text via `self.ax.text(...)`. Use `xi, xf, yi, yf = self.ax.axis()` then offsets like `v_spacing = (yf-yi)*0.10`. |

---

## How it gets called

The custom class is dropped into the `protocols = [...]` list alongside built-in protocols:

```python
process = Protocols.ProcessorXS(load_args=load_args, run_args=run_args)

protocols = [
    Protocols.circular_average(ylog=True, plot_range=[0, 0.13, None, None]),
    my_custom_protocol(name='myfit', fit_range=[0.007, 0.019], q0=0.012, sigma=0.0008),
    Protocols.thumbnails(crop=0.25, resize=1.0),
]

process.run(infiles, protocols, output_dir=output_dir, force=False)
```

No registration step is needed. `ProcessorXS` calls `protocol.run(data, output_dir, **run_args)` on each item in the list.

---

## Notes on chaining custom protocols

A custom protocol can pull metadata from a prior protocol's saved results XML. This is the pattern used in `linecut_angle_fit` to auto-load `q0` from a prior `circular_average_q2I_fit`:

```python
if 'q0' not in run_args or run_args['q0'] is None:
    head, tail = os.path.split(output_dir)
    result_file = os.path.join(head, 'results', '{}.xml'.format(data.name))
    prev_results = tools.get_result_xml(result_file, 'circular_average_q2I')
    run_args['q0'] = prev_results['fit_peaks_x_center1']
```

Use this when one custom protocol depends on a fitted parameter from another. Both protocols must appear in the same `protocols = [...]` list in the correct order (the producer before the consumer).
