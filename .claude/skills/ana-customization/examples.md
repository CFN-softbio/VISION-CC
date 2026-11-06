# Annotated Customization Examples

Three real customizations distilled to the parts a future generator must reproduce. Each example shows:

- **What it customizes** (which parent, which slot)
- **The key code change** (just the slot-specific bits, not the boilerplate from `subclass_template.md`)
- **What to copy when a similar request arrives**

---

## Example 1 — `circular_average_q2I_fit`

**Parent:** `Protocols.circular_average_q2I`
**Why:** Need Kratky-style `q²·I(q)` with multi-Gaussian peak fitting and `chi_squared` reporting.

### Slot 3a — binner

```python
line = data.circular_average_q_bin(error=True)

# Convert to q²I (this protocol's whole point)
line.y *= np.square(line.x)
line.y_label = 'q^2*I(q)'
line.y_rlabel = '$q^2 I(q) \\, (\\AA^{-2} \\mathrm{counts/pixel})$'
```

### Slot 3b — fit model (multi-Gaussian + flat background, no slope)

```python
def model(v, x):
    m = v['b']
    for i in range(num_curves):
        m += v['prefactor{:d}'.format(i+1)] * np.exp(
            -np.square(x - v['x_center{:d}'.format(i+1)]) /
            (2 * (v['sigma{:d}'.format(i+1)] ** 2))
        )
    return m

# default num_curves=2; initial x_center is xpeak * (i+1) to seed harmonic peaks
xpeak, ypeak = line.target_y(np.max(line.y))
for i in range(num_curves):
    xpos, ypos = line.target_x(xpeak * (i+1))
    params.add('prefactor{:d}'.format(i+1), value=ypos, min=0)
    params.add('x_center{:d}'.format(i+1), value=xpos,
               min=np.min(line.x), max=np.max(line.x))
    params.add('sigma{:d}'.format(i+1), value=xpos * 0.25, min=0)
```

### Output filenames carry suffix

```python
outfile = self.get_outfile(data.name, output_dir, ext='_q2I.dat')
# ...
outfile = self.get_outfile(data.name, output_dir, ext='_q2I{}'.format(self.default_ext))
```

### When to reuse this pattern

User says:
- "fit Kratky plot peaks"
- "multi-peak Gaussian fit on circular average"
- "q²I with harmonics"

---

## Example 2 — `sector_average_fit`

**Parent:** `Protocols.sector_average`
**Why:** Need a 1D fit on an angular wedge with linear-background Gaussian + derived `d0` (nm) and `grain_size` (nm) annotated on the plot.

### Slot 3a — binner + optional dezinger

```python
if 'dezing' in run_args and run_args['dezing']:
    data.dezinger(sigma=3, tol=100, mode='median', mask=True, fill=False)

line = data.sector_average_q_bin(**run_args)
```

### Slot 3b — fit model (linear background + N Gaussians)

```python
def model(v, x):
    m = v['m']*x + v['b']
    for i in range(num_curves):
        m += v['prefactor{:d}'.format(i+1)] * np.exp(
            -np.square(x - v['x_center{:d}'.format(i+1)]) /
            (2 * (v['sigma{:d}'.format(i+1)] ** 2))
        )
    return m

params.add('m', value=0)
params.add('b', value=np.min(line.y), min=0, max=np.max(line.y))
```

### Derived metrics (added after fit packing)

```python
# d-spacing in nm
d = 0.1 * 2.0 * np.pi / results['{}_x_center1'.format(fit_name)]['value']
results['{}_d0'.format(fit_name)] = d

# grain size in nm via Scherrer-style estimate
xi = (2.0 * np.pi / np.sqrt(2.0 * np.pi)) / results['{}_sigma1'.format(fit_name)]['value']
results['{}_grain_size'.format(fit_name)] = xi
```

### Slot 4 — `_plot_extra` with q₀ / d₀ / σ / ξ annotations

```python
class DataLines_current(DataLines):
    def _plot_extra(self, **plot_args):
        xi, xf, yi, yf = self.ax.axis()
        v_spacing = (yf - yi) * 0.10

        yp = yf
        s = '$q_0 = \\, {:.4f} \\, \\mathrm{{\\AA}}^{{-1}}$'.format(
            self.results['fit_peaks_x_center1']['value'])
        self.ax.text(xf, yp, s, size=20, color='b',
                     verticalalignment='top', horizontalalignment='right')

        yp -= v_spacing
        s = r'$d_0 \approx \, {:.1f} \, \mathrm{{nm}}$'.format(self.results['fit_peaks_d0'])
        self.ax.text(xf, yp, s, size=20, color='b',
                     verticalalignment='top', horizontalalignment='right')

        yp -= v_spacing
        s = '$\\sigma = \\, {:.4f} \\, \\mathrm{{\\AA}}^{{-1}}$'.format(
            self.results['fit_peaks_sigma1']['value'])
        self.ax.text(xf, yp, s, size=20, color='b',
                     verticalalignment='top', horizontalalignment='right')

        yp -= v_spacing
        s = r'$\xi \approx \, {:.1f} \, \mathrm{{nm}}$'.format(self.results['fit_peaks_grain_size'])
        self.ax.text(xf, yp, s, size=20, color='b',
                     verticalalignment='top', horizontalalignment='right')
```

### Multiple instances in the same protocols list

This is the idiomatic way to fit several angular wedges in one run:

```python
protocols = [
    sector_average_fit(name='line30thin', angle=30, dangle=10,
                       q0=0.0110, sigma=0.0008, num_curves=1,
                       trim_range=[0.0070, 0.018]),
    sector_average_fit(name='line45thin', angle=45, dangle=10, ...),
    sector_average_fit(name='line60thin', angle=60, dangle=10, ...),
    sector_average_fit(name='line90thin', angle=90, dangle=10, ...),
]
```

Each instance gets a distinct `name=` so its outputs land in separate subdirectories.

### When to reuse this pattern

User says:
- "fit a wedge of the pattern"
- "I want d₀ and grain size annotated"
- "scan multiple angles and fit each"

---

## Example 3 — `linecut_qz_fit` (GISAXS with refraction correction)

**Parent:** `Protocols.linecut_qz`
**Why:** GISAXS qz fit with negative-slope linear background, optional refraction correction (computes qT and qR for transmitted and reflected beams), and rich annotation including scattering-feature guides (D, H, R, T, Yf, Ys).

### Slot 3a — binner

```python
line = data.linecut_qz(**run_args)
```

### Incident angle auto-extraction from filename

```python
if 'incident_angle' not in run_args:
    run_args['incident_angle'] = 0
    import re
    filename_re = re.compile('^.+_th(-?\\d+\\.\\d+)_.+$')
    m = filename_re.match(data.name)
    if m:
        run_args['incident_angle'] = float(m.groups()[0])
```

### Slot 3b — fit model (negative-slope linear bg + Gaussian) with `q0_expected` seeding

```python
m_slope = (line.y[-1] - line.y[0]) / (line.x[-1] - line.x[0])
b_intercept = line.y[0] - m_slope * line.x[0]
params.add('m', value=m_slope, min=abs(m_slope)*-5, max=0)   # slope MUST be negative
params.add('b', value=b_intercept, min=0)

xpeak, ypeak = line.target_y(np.max(line.y))
if 'q0_expected' in run_args and run_args['q0_expected'] is not None:
    xpeak, ypeak = line.target_x(run_args['q0_expected'])  # seed where user expects

prefactor_seed = ypeak - (m_slope * xpeak + b_intercept)
params.add('prefactor1', value=prefactor_seed, min=0, max=np.max(line.y) * 4)
params.add('x_center1', value=xpeak, min=np.min(line.x), max=np.max(line.x))
params.add('sigma1', value=0.003, min=0, max=xspan * 0.5)
```

### Refraction correction (computes qT, qR)

This is the distinctive GISAXS bit. Guarded by `if 'critical_angle_film' in run_args`:

```python
if 'critical_angle_film' in run_args:
    theta_incident_rad = np.radians(run_args['incident_angle'])
    theta_c_f_rad = np.radians(run_args['critical_angle_film'])
    alpha_i_rad = np.arccos(np.cos(theta_incident_rad) / np.cos(theta_c_f_rad))

    def angle_to_q(two_theta_s_rad):
        k = data.calibration.get_k()
        return 2 * k * np.sin(two_theta_s_rad / 2.0)

    def q_to_angle(q):
        k = data.calibration.get_k()
        return 2.0 * np.arcsin(q / (2.0 * k))

    q0 = results['fit_peaks_x_center1']['value']

    # Transmitted beam
    two_theta_s_rad = q_to_angle(q0)
    theta_f_rad = two_theta_s_rad - theta_incident_rad
    alpha_f_rad = np.arccos(np.cos(theta_f_rad) / np.cos(theta_c_f_rad))
    two_alpha_s_rad = alpha_i_rad + alpha_f_rad
    qT = angle_to_q(two_alpha_s_rad)
    results['fit_peaks_qT'] = qT
    results['fit_peaks_dT'] = 0.1 * 2.0 * np.pi / qT

    # Reflected beam
    two_alpha_s_rad = abs(alpha_f_rad - alpha_i_rad)
    qR = angle_to_q(two_alpha_s_rad)
    results['fit_peaks_qR'] = qR
    results['fit_peaks_dR'] = 0.1 * 2.0 * np.pi / qR
```

### Slot 4 — `_plot_extra` with scattering-feature guides

The plot annotates **D** (direct), **H** (horizon), **R** (specular), **T** (transmitted), **Yf** (Yoneda film), **Ys** (Yoneda substrate). Each is a vertical line at a computed qz with a labeled marker. See `runXS-customized.py` lines 649–710 for the full set.

### When to reuse this pattern

User says:
- "GISAXS qz fit"
- "fit out-of-plane peak with refraction correction"
- "qT and qR for film/substrate"
- "annotate Yoneda / specular / horizon on the qz cut"

---

## Common idioms across all three examples

These show up in every customization — copy them verbatim unless the request specifically overrides:

| Idiom | Code |
|---|---|
| Self-name | `self.name = self.__class__.__name__ if name is None else name` |
| Default plot extension | `self.default_ext = '.png'` |
| Merge user kwargs | `self.run_args.update(kwargs)` |
| Decorator | `@tools.run_default` (or `@Protocols.run_default`) |
| Show region | `if 'show_region' in run_args and run_args['show_region']: data.plot(show=True)` |
| Save `.dat` | `outfile = self.get_outfile(data.name, output_dir, ext='.dat'); line.save_data(outfile)` |
| Pack lmfit results | `results['{}_{}'.format(fit_name, param_name)] = {'value': param.value, 'error': param.stderr}` |
| Chi-squared | `results['{}_chi_squared'.format(fit_name)] = lm_result.chisqr / lm_result.nfree` |
| Convert to nm | `d_nm = 0.1 * 2.0 * np.pi / q_invA` |
| Grain size | `xi_nm = 0.1 * (2.0 * np.pi / np.sqrt(2.0 * np.pi)) / sigma_invA` |
| Plot try/except | `try: lines.plot(save=outfile, **run_args)` / `except ValueError: pass` |
