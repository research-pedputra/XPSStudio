"""Quantification from saved full analytical areas, never from plotted intensities."""
import copy
import json
import math
import re
from pathlib import Path
import pandas as pd

# Values supplied in the user's example, not a universal instrument RSF library.
PRESETS = {'Cs': ('3d', 7.04, 132.905), 'Pb': ('4f', 9.14, 207.2), 'Br': ('3d', 2.91, 79.904)}


def finite(value, name, positive=False):
    try: value = float(value)
    except (TypeError, ValueError): raise ValueError(f'{name} must be numeric.')
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f'{name} must be finite' + (' and greater than zero.' if positive else '.'))
    return value


def record(source, sheet, peak, label, center, area, status, origin, details=None):
    source, sheet, peak = str(source), str(sheet), str(peak)
    item = dict(source=source, sheet=sheet, peak=peak, label=str(label),
                center_eV=finite(center, 'Peak center'), area_full=finite(area, 'Full peak area'),
                sample=source, element='', transition='', rsf='', atomic_weight='',
                included=status == 'Fitted', status=status, origin=str(origin), details=details or {})
    text = sheet + ' ' + str(label)
    for element, (transition, rsf, weight) in PRESETS.items():
        if re.search(r'(?<![A-Za-z])' + element + r'\s*' + transition, text, re.I):
            item.update(element=element, transition=transition, rsf=rsf, atomic_weight=weight)
            break
    return item


def identity(row):
    return (row['source'], row['sheet'], row['peak'])


def from_parameters(payload, origin):
    fit = payload.get('fit')
    config = fit['config'] if fit else payload['config']
    params = fit['params'] if fit else config['params']
    source = (fit or {}).get('source') or payload.get('source') or str(origin)
    sheet = (fit or {}).get('sheet') or payload.get('sheet') or Path(origin).stem
    status = ('Fitted' if fit.get('success') else 'Fit not converged') if fit else 'Unverified parameters'
    rows = []
    for peak in config['peaks']:
        prefix = peak['prefix']
        rows.append(record(source, sheet, prefix, peak['label'], params[prefix+'center']['value'],
                           params[prefix+'amplitude']['value'], status, origin,
                           {'config': copy.deepcopy(config), 'params': copy.deepcopy(params)}))
    return rows


def from_summary(frame, origin):
    required = {'peak', 'center_eV', 'area_full'}
    if not required.issubset(frame.columns):
        raise ValueError('Select an XPS Studio peak summary containing peak, center_eV and area_full.')
    rows = []
    for raw in frame.to_dict('records'):
        row = {k: None if pd.isna(v) else v for k, v in raw.items()}
        success = str(row.get('fit_success')).lower() in ('true', '1', '1.0')
        status = 'Fitted' if success else 'Unverified parameters' if row.get('fit_success') is None else 'Fit not converged'
        rows.append(record(row.get('source') or str(origin), row.get('sheet') or Path(origin).stem,
                           row['peak'], row.get('label') or row['peak'], row['center_eV'], row['area_full'],
                           status, origin, row))
    return rows


def load_records(path):
    path = Path(path)
    if path.suffix.lower() == '.xpsplot':
        from .plot_project import read_project
        _, datasets, _, _ = read_project(path)
        rows = []
        for source, data in datasets:
            if data.get('peak_metadata'):
                rows.extend(from_summary(pd.DataFrame(data['peak_metadata'].values()), source))
            elif data.get('config'):
                rows.extend(from_parameters({'config': data['config']}, source))
            else: raise ValueError(f'{source}: project has no fitted-area metadata. Load its _peaks.csv or parameter JSON.')
        return rows
    if path.suffix.lower() == '.json':
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('schema') != 'xps-studio-1':
            raise ValueError('Use a fitting parameter JSON, not a plot template. Open a post-analysis session separately.')
        return from_parameters(payload, path)
    frame = pd.read_csv(path)
    if {'peak', 'area_full', 'center_eV'}.issubset(frame.columns): return from_summary(frame, path)
    if 'binding_energy_eV' not in frame:
        raise ValueError('This is not a saved XPS Studio fitting output.')
    summary = path.with_name(path.stem + '_peaks.csv')
    parameters = path.with_name(path.stem + '_parameters.json')
    if summary.exists(): return from_summary(pd.read_csv(summary), path)
    if parameters.exists(): return load_records(parameters)
    raise ValueError('Keep the spectrum CSV beside its _peaks.csv or _parameters.json. Full fitted areas are required.')


def quantify(records):
    selected = [r for r in records if r['included']]
    if not selected: return []
    groups = {}
    for r in selected:
        if not str(r['sample']).strip() or not str(r['element']).strip():
            raise ValueError('Set a sample and element for every included peak.')
        area = finite(r['area_full'], 'Full area')
        if area < 0: raise ValueError('Included peak areas cannot be negative.')
        rsf = finite(r['rsf'], f"RSF for {r['element']}", True)
        key = (r['sample'], r['element'])
        groups.setdefault(key, []).append((r, area, rsf))
    result = []
    for (sample, element), items in groups.items():
        if len({(r['source'], r['sheet'], r['transition']) for r, _, _ in items}) != 1:
            raise ValueError(f'{sample}: choose one spectrum/core level per element ({element}); assign repeated measurements to separate samples.')
        if len({rsf for _, _, rsf in items}) != 1:
            raise ValueError(f'{element}: all components of the selected core level must use the same RSF.')
        weights = [finite(r['atomic_weight'], f'Atomic weight for {element}', True)
                   for r, _, _ in items if str(r['atomic_weight']).strip()]
        if weights and (len(weights) != len(items) or len(set(weights)) != 1):
            raise ValueError(f'{element}: use the same atomic weight for all its components, or leave all blank.')
        area = sum(a for _, a, _ in items); rsf = items[0][2]
        result.append(dict(sample=sample, element=element, transition=items[0][0]['transition'],
                           source=items[0][0]['source'], sheet=items[0][0]['sheet'],
                           peaks='; '.join(r['peak'] for r, _, _ in items), area_full=area,
                           rsf=rsf, corrected_area=area/rsf, atomic_weight=weights[0] if weights else None))
    for sample in {r['sample'] for r in result}:
        subset = [r for r in result if r['sample'] == sample]
        total = sum(r['corrected_area'] for r in subset)
        if total <= 0: raise ValueError(f'{sample}: total corrected area must be positive.')
        mass_total = sum(r['corrected_area'] * r['atomic_weight'] for r in subset) if all(r['atomic_weight'] for r in subset) else None
        for r in subset:
            r['atomic_percent'] = 100*r['corrected_area']/total
            r['weight_percent'] = 100*r['corrected_area']*r['atomic_weight']/mass_total if mass_total else None
    return result


def doublets(records, pairs):
    lookup = {tuple(identity(r)): r for r in records}
    result = []
    for pair in pairs:
        a, b = lookup[tuple(pair['a'])], lookup[tuple(pair['b'])]
        if identity(a) == identity(b) or (a['source'], a['sheet']) != (b['source'], b['sheet']):
            raise ValueError('Choose two different peaks from the same fitted spectrum.')
        result.append(dict(source=a['source'], sheet=a['sheet'], sample=a['sample'],
            peak_a=a['peak'], label_a=a['label'], peak_b=b['peak'], label_b=b['label'],
            center_a_eV=a['center_eV'], center_b_eV=b['center_eV'],
            separation_eV=abs(finite(a['center_eV'], 'Center A')-finite(b['center_eV'], 'Center B')),
            area_a=a['area_full'], area_b=b['area_full'],
            area_ratio_a_over_b=a['area_full']/b['area_full'] if b['area_full'] else None,
            status_a=a['status'], status_b=b['status']))
    return result


def save_session(path, records, pairs):
    Path(path).write_text(json.dumps({'schema': 'xps-studio-post-1', 'records': records, 'pairs': pairs},
                                    indent=2, allow_nan=False), encoding='utf-8')


def read_session(path):
    payload = json.loads(Path(path).read_text(encoding='utf-8'))
    if payload.get('schema') != 'xps-studio-post-1': raise ValueError('Not a post-analysis session.')
    records, pairs = payload['records'], payload['pairs']
    seen = set()
    for r in records:
        if identity(r) in seen: raise ValueError('Duplicate peak in session.')
        seen.add(identity(r))
        finite(r['center_eV'], 'Center'); finite(r['area_full'], 'Area')
        for key in ('sample', 'element', 'transition', 'label', 'status', 'origin'):
            if not isinstance(r[key], str): raise ValueError(f'Invalid {key}.')
        if type(r['included']) is not bool: raise ValueError('Invalid inclusion flag.')
        for key in ('rsf', 'atomic_weight'):
            if not isinstance(r[key], (str, int, float)): raise ValueError(f'Invalid {key}.')
    doublets(records, pairs)
    return records, pairs
