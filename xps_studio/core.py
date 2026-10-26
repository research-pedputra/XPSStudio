"""Numerical and persistence layer; independent of Qt."""
from dataclasses import dataclass, field
from pathlib import Path
import copy
import json
import time
import ast
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from scipy.integrate import cumulative_trapezoid, trapezoid
from lmfit.models import GaussianModel, LorentzianModel, PseudoVoigtModel, VoigtModel, LinearModel

MODELS = {'Gaussian': GaussianModel, 'Lorentzian': LorentzianModel,
          'Pseudo-Voigt': PseudoVoigtModel, 'Voigt': VoigtModel}
CMAPS = ['Blues', 'Oranges', 'Reds', 'YlGn', 'PuBu', 'Purples', 'Greys']


@dataclass
class Spectrum:
    source: str
    sheet: str
    x: np.ndarray
    y: np.ndarray
    config: dict = field(default_factory=dict)
    result: object = None

    def __post_init__(self):
        if not self.config:
            self.config = {'region': [float(self.x.min()), float(self.x.max())],
                           'shift': 0., 'background': 'None', 'peaks': [], 'params': {},
                           'shirley_scale': 1., 'tougaard_B': 2866., 'tougaard_C': 1643.,
                           'max_nfev': 3000}

    @property
    def title(self):
        return f'{Path(self.source).name} · {self.sheet}'


def clean_xy(x, y):
    x = pd.to_numeric(x, errors='coerce').to_numpy(dtype=float)
    y = pd.to_numeric(y, errors='coerce').to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    frame = pd.DataFrame({'x': x[valid], 'y': y[valid]}).groupby('x', as_index=False).mean()
    if len(frame) < 5:
        raise ValueError('At least five distinct numeric energy points are required.')
    return frame.x.to_numpy(), frame.y.to_numpy()


def load_file(path, facts=True, skiprows=1):
    """Return valid sheets and sheet-specific errors without discarding useful sheets."""
    path = str(Path(path).resolve())
    suffix = Path(path).suffix.lower()
    excel = suffix in ('.xlsx', '.xls', '.xlsm')
    single = suffix in ('.dat', '.data', '.txt')
    spectra, errors = [], []
    workbook = pd.ExcelFile(path) if excel else None
    sheets = workbook.sheet_names if excel else [Path(path).stem]
    try:
        for sheet in sheets:
            try:
                if excel:
                    df = pd.read_excel(workbook, sheet_name=sheet, skiprows=skiprows if facts else 0,
                                       header=0 if facts else None)
                elif single:
                    df = pd.read_csv(path, sep=r'[\s,;]+', engine='python', comment='#', header=None)
                else:
                    df = pd.read_csv(path, sep=None, engine='python', skiprows=skiprows if facts else 0,
                                     header=0 if facts else None)
                if facts and not single:
                    df.columns = [str(c).strip() for c in df.columns]
                    required = ['Binding energy (eV)', 'Counts per second']
                    if not all(c in df for c in required):
                        raise ValueError('FACTS headers not found. Adjust skipped rows or choose generic two-column import.')
                    x, y = clean_xy(df[required[0]], df[required[1]])
                else:
                    if df.shape[1] < 2:
                        raise ValueError('Expected two columns: energy and intensity.')
                    x, y = clean_xy(df.iloc[:, 0], df.iloc[:, 1])
                spectra.append(Spectrum(path, str(sheet), x, y))
            except Exception as exc:
                errors.append(f'{sheet}: {exc}')
    finally:
        if workbook is not None:
            workbook.close()
    return spectra, errors


def region_arrays(s):
    x = s.x + s.config['shift']
    lo, hi = s.config['region']
    if lo >= hi:
        raise ValueError('Region minimum must be smaller than maximum.')
    mask = (x >= lo) & (x <= hi)
    if mask.sum() < 5:
        raise ValueError('Select a region containing at least five data points.')
    return x[mask], s.y[mask]


def background(x, y, cfg):
    kind = cfg['background']
    if kind in ('None', 'Linear'):
        return np.zeros_like(y)
    if kind == 'Shirley':
        # Energy-weighted integration: independent of input order and sampling density.
        bg = np.linspace(y[0], y[-1], len(y))
        for _ in range(300):
            integral = cumulative_trapezoid(y - bg, x, initial=0)
            if abs(integral[-1]) < 1e-12:
                break
            proposal = y[0] + cfg['shirley_scale'] * (y[-1] - y[0]) * integral / integral[-1]
            new = .5 * bg + .5 * proposal
            if np.max(np.abs(new - bg)) < 1e-7 * max(1., np.max(np.abs(y))):
                return new
            bg = new
        return bg
    if kind == 'Tougaard':
        # Two-parameter loss kernel B*T/(C+T²)², integrated toward higher BE.
        # Finite measured window, constant high-energy endpoint offset.
        B, C = cfg['tougaard_B'], cfg['tougaard_C']
        if B < 0 or C <= 0:
            raise ValueError('Tougaard requires B ≥ 0 and C > 0.')
        bg = np.full_like(y, y[-1])
        signal = np.maximum(y - y[-1], 0.)
        for i in range(len(x) - 1):
            loss = x[i:] - x[i]
            bg[i] += trapezoid(signal[i:] * B * loss / (C + loss ** 2) ** 2, x[i:])
        return bg
    raise ValueError(f'Unknown background: {kind}')


def add_peak(s, kind='Pseudo-Voigt', label=None):
    x, y = region_arrays(s)
    used = {p['prefix'] for p in s.config['peaks']}
    n = 1
    while f'p{n}_' in used:
        n += 1
    prefix = f'p{n}_'
    s.config['peaks'].append({'prefix': prefix, 'kind': kind, 'label': label or f'Peak {n}',
                              'cmap': CMAPS[(n - 1) % len(CMAPS)]})
    model = MODELS[kind](prefix=prefix)
    params = model.make_params()
    width = max(float(np.ptp(x)) / 25, .01)
    params[prefix + 'center'].set(value=float(x[np.argmax(y)]), min=x.min(), max=x.max())
    params[prefix + 'sigma'].set(value=width, min=1e-6)
    params[prefix + 'amplitude'].set(value=max(float(np.ptp(y)) * width * 2.5, 1.), min=0)
    if kind == 'Voigt':
        params[prefix + 'gamma'].set(value=width, min=1e-6, expr='', vary=True)
    for name, par in params.items():
        if name.endswith(('fwhm', 'height')):
            continue
        s.config['params'][name] = parameter_dict(par)
    s.result = None


def parameter_dict(p):
    return {'value': float(p.value), 'min': float(p.min) if np.isfinite(p.min) else None,
            'max': float(p.max) if np.isfinite(p.max) else None, 'vary': bool(p.vary), 'expr': p.expr or ''}


def charge_reference(s, prefix, reference_energy):
    """Record an absolute correction relative to the ORIGINAL energy axis."""
    r = s.result
    if r is None or not r.get('success'):
        raise ValueError('Complete a successful reference-peak fit before recording charge correction.')
    if prefix not in r['peaks']:
        raise ValueError('Select one of the fitted reference peaks.')
    reference_energy = float(reference_energy)
    if not np.isfinite(reference_energy):
        raise ValueError('Reference energy must be finite.')
    fitted_center = r['params'][prefix + 'center']['value']
    fit_shift = r['config']['shift']
    raw_center = fitted_center - fit_shift
    peak = next(p for p in r['config']['peaks'] if p['prefix'] == prefix)
    return {'source': s.source, 'sheet': s.sheet, 'peak': prefix, 'label': peak['label'],
            'peak_model': peak['kind'], 'fit_components': copy.deepcopy(r['config']['peaks']),
            'recorded_at': datetime.now(timezone.utc).isoformat(),
            'reference_energy_eV': reference_energy, 'fitted_center_eV': fitted_center,
            'fit_axis_shift_eV': fit_shift, 'raw_center_eV': raw_center,
            'shift_eV': reference_energy - raw_center,
            'fit_params': copy.deepcopy(r['params']), 'fit_region': list(r['config']['region']),
            'background': r['config']['background'], 'fit_report': r['report'],
            'fit_success': r['success'], 'nfev': r['nfev'], 'redchi': r['redchi']}


def _translate_parameters(parameters, delta):
    """Translate both values and constraints to preserve the same physical model."""
    centers = {name for name in parameters if name.endswith('_center')}
    slope = parameters.get('bkg_slope', {}).get('value', 0.)

    class Coordinates(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in centers:
                return ast.BinOp(left=node, op=ast.Sub(), right=ast.Constant(delta))
            if node.id == 'bkg_intercept' and 'bkg_slope' in parameters:
                return ast.BinOp(left=node, op=ast.Add(), right=ast.BinOp(
                    left=ast.Name(id='bkg_slope', ctx=ast.Load()), op=ast.Mult(), right=ast.Constant(delta)))
            return node

    for name, spec in parameters.items():
        offset = delta if name in centers else -slope * delta if name == 'bkg_intercept' else 0.
        for key in ('value', 'min', 'max'):
            if spec.get(key) is not None:
                spec[key] += offset
        if spec.get('expr'):
            tree = Coordinates().visit(ast.parse(spec['expr'], mode='eval'))
            expr = ast.unparse(tree)
            if name in centers:
                expr = f'({expr}) + ({delta!r})'
            elif name == 'bkg_intercept':
                expr = f'({expr}) - bkg_slope * ({delta!r})'
            spec['expr'] = expr


def apply_charge_shift(s, shift, record=None):
    """Set an absolute shift, never add it twice on sheet selection.

    Translate existing fits without recomputing their intensity arrays. Corrections
    preserve the physical selected interval and parameter constraints.
    """
    shift = float(shift)
    if not np.isfinite(shift):
        raise ValueError('Charge shift must be finite.')
    delta = shift - s.config['shift']
    cfg = copy.deepcopy(s.config)
    result = copy.deepcopy(s.result) if s.result is not None else None
    if abs(delta) > 1e-12:
        cfg['region'] = [v + delta for v in cfg['region']]
        _translate_parameters(cfg['params'], delta)
        if result is not None:
            result['x'] = result['x'] + delta
            _translate_parameters(result['params'], delta)
            original = result.setdefault('original_fit_report', result['report'])
            values = '\n'.join(f"  {k}: {p['value']:.10g}" for k, p in result['params'].items())
            result['report'] = (f'Charge shift on current axis: {shift:+.8g} eV\n'
                                'Intensity fit and residuals are unchanged by energy translation.\n'
                                f'Current parameter values:\n{values}\n\n'
                                f'Original optimizer report (original fit axis):\n{original}')
    cfg['shift'] = shift
    cfg['charge_reference'] = copy.deepcopy(record)
    if result is not None:
        result['config'] = copy.deepcopy(cfg)
    s.config, s.result = cfg, result


def make_model(s):
    if not s.config['peaks']:
        raise ValueError('Add at least one peak before fitting.')
    model = None
    params = None
    for peak in s.config['peaks']:
        piece = MODELS[peak['kind']](prefix=peak['prefix'])
        if model is None:
            model, params = piece, piece.make_params()
        else:
            model += piece
            params.update(piece.make_params())
    x, y = region_arrays(s)
    if s.config['background'] == 'Linear':
        linear = LinearModel(prefix='bkg_')
        model += linear
        params.update(linear.make_params())
        slope = (y[-1] - y[0]) / (x[-1] - x[0])
        params['bkg_slope'].set(value=slope)
        params['bkg_intercept'].set(value=y[0] - slope * x[0])
    # Apply values first, expressions second so cross-peak references resolve.
    for name, spec in s.config['params'].items():
        if name not in params:
            continue
        lo = -np.inf if spec['min'] is None else spec['min']
        hi = np.inf if spec['max'] is None else spec['max']
        if lo >= hi or not np.isfinite(spec['value']) or not lo <= spec['value'] <= hi:
            raise ValueError(f'{name}: require min < max and a finite value within bounds.')
        params[name].set(value=spec['value'], min=lo, max=hi, vary=spec['vary'], expr='')
    for name, spec in s.config['params'].items():
        if name in params and spec.get('expr'):
            params[name].set(expr=spec['expr'])
    params.update_constraints()
    return model, params


def snapshot(model, params, x, y, bg, cfg):
    comps = model.eval_components(params=params, x=x)
    baseline = comps.get('bkg_', bg)
    peaks = {p['prefix']: np.asarray(comps[p['prefix']]).copy() for p in cfg['peaks']}
    total = baseline + sum(peaks.values())
    return {'x': x.copy(), 'y': y.copy(), 'background': baseline.copy(), 'total': total,
            'peaks': peaks, 'residual': y - total,
            'params': {k: parameter_dict(v) for k, v in params.items()},
            'config': copy.deepcopy(cfg)}


def fit_spectrum(s, progress=None, cancelled=None):
    x, y = region_arrays(s)
    model, params = make_model(s)
    bg = background(x, y, s.config)
    if sum(p.vary and not p.expr for p in params.values()) >= len(x):
        raise ValueError('Too many free parameters for the selected region.')
    last = [0.]

    def callback(pars, iteration, residual, *args, **kwargs):
        if cancelled and cancelled():
            return True
        now = time.monotonic()
        if progress and now - last[0] >= .12:
            data = snapshot(model, pars, x, y, bg, s.config)
            data['iteration'] = iteration
            progress(data)
            last[0] = now

    result = model.fit(y - bg, params, x=x, method='least_squares',
                       max_nfev=s.config['max_nfev'], iter_cb=callback)
    if result.aborted or (cancelled and cancelled()):
        raise InterruptedError('Fit cancelled; previous committed result retained.')
    data = snapshot(model, result.params, x, y, bg, s.config)
    data.update(success=bool(result.success), message=str(result.message), nfev=result.nfev,
                chisqr=float(result.chisqr), redchi=float(result.redchi), report=result.fit_report())
    data['stderr'] = {k: v.stderr for k, v in result.params.items()}
    return data


def export_result(s, path):
    if s.result is None:
        raise ValueError('Fit this spectrum before exporting.')
    r = s.result
    path = Path(path).with_suffix('.csv')
    frame = pd.DataFrame({'binding_energy_eV': r['x'], 'intensity': r['y'],
                          'fit_total': r['total'], 'background': r['background'], 'residual': r['residual']})
    for prefix, curve in r['peaks'].items():
        frame[f'{prefix}component'] = curve
    frame.to_csv(path, index=False)
    rows = []
    for peak in r['config']['peaks']:
        pre = peak['prefix']
        vals = r['params']
        row = {'source': s.source, 'sheet': s.sheet, 'peak': pre, 'label': peak['label'], 'model': peak['kind'],
               'center_eV': vals[pre + 'center']['value'], 'height': vals[pre + 'height']['value'],
               'area_full': vals[pre + 'amplitude']['value'],
               'area_in_region': trapezoid(r['peaks'][pre], r['x']), 'fwhm_eV': vals[pre + 'fwhm']['value'],
               'sigma_eV': vals[pre + 'sigma']['value'], 'background': r['config']['background'],
               'energy_shift_eV': r['config']['shift'], 'fit_success': r['success'], 'reduced_chisqr': r['redchi']}
        reference = r['config'].get('charge_reference') or {}
        row.update(charge_reference_source=reference.get('source'),
                   charge_reference_sheet=reference.get('sheet'),
                   charge_reference_peak=reference.get('label'),
                   charge_reference_energy_eV=reference.get('reference_energy_eV'),
                   charge_reference_raw_center_eV=reference.get('raw_center_eV'))
        for par in ('center', 'sigma', 'amplitude', 'gamma', 'fraction'):
            if pre + par in vals:
                row[par] = vals[pre + par]['value']
                row[par + '_stderr'] = r['stderr'].get(pre + par)
        rows.append(row)
    pd.DataFrame(rows).to_csv(path.with_name(path.stem + '_peaks.csv'), index=False)
    save_parameters(s, path.with_name(path.stem + '_parameters.json'))
    return path


def save_parameters(s, path):
    payload = {'schema': 'xps-studio-1', 'config': s.config, 'source': s.source, 'sheet': s.sheet}
    if s.result is not None:
        r = s.result
        payload['fit'] = {'config': r['config'], 'params': r['params'], 'source': s.source,
                          'sheet': s.sheet, 'success': r['success'], 'stderr': r.get('stderr', {}),
                          'redchi': r.get('redchi'), 'report': r.get('report', '')}
    Path(path).write_text(json.dumps(payload, indent=2, allow_nan=False), encoding='utf-8')


def read_parameters(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema') != 'xps-studio-1':
        raise ValueError('Not an XPS Studio parameter file.')
    cfg = payload['config']
    if not isinstance(cfg, dict) or cfg['background'] not in ('None', 'Linear', 'Shirley', 'Tougaard'):
        raise ValueError('Invalid background configuration.')
    import re
    prefixes = set()
    for peak in cfg['peaks']:
        if peak['kind'] not in MODELS or not re.fullmatch(r'p[1-9][0-9]*_', peak['prefix']) or peak['prefix'] in prefixes:
            raise ValueError('Invalid or duplicate peak definition.')
        prefixes.add(peak['prefix'])
    return cfg
