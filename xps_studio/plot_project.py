"""Portable editable plot projects: compressed JSON data, settings and optional font."""
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile
import numpy as np


def json_value(value):
    if isinstance(value, np.ndarray): return json_value(value.tolist())
    if isinstance(value, np.generic): return json_value(value.item())
    if isinstance(value, dict): return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [json_value(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def save_project(path, configuration, datasets, selected_panel=0, active_tab=0):
    path = Path(path); config = copy.deepcopy(configuration)
    font_bytes = None; font_name = None
    if config.get('custom_font'):
        source = Path(config['custom_font']['path'])
        if source.suffix.lower() not in ('.ttf', '.otf', '.ttc'): raise ValueError('Unsupported custom font format.')
        font_bytes = source.read_bytes(); font_name = 'font' + source.suffix.lower()
        config['custom_font']['path'] = font_name
    payload = {'schema': 'xps-studio-project-1', 'configuration': config,
               'datasets': [{'source_path': str(source), 'data': json_value(data)} for source, data in datasets],
               'selected_panel': selected_panel, 'active_tab': active_tab}
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix='.xps-project-', suffix='.tmp', dir=path.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('project.json', encoded)
            if font_bytes is not None: archive.writestr(font_name, font_bytes)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()


def read_project(path):
    with zipfile.ZipFile(path) as archive:
        payload = json.loads(archive.read('project.json'))
        if not isinstance(payload, dict) or payload.get('schema') != 'xps-studio-project-1': raise ValueError('Not an XPS Studio plot project.')
        config = payload.get('configuration')
        if not isinstance(config, dict): raise ValueError('Project has no plot configuration.')
        entries = payload.get('datasets')
        if not isinstance(entries, list) or len(entries) > 144: raise ValueError('Invalid project spectrum list.')
        datasets = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('source_path'), str) or not isinstance(entry.get('data'), dict): raise ValueError('Invalid project spectrum.')
            data = entry['data']
            for key in ('x', 'y', 'total', 'background'):
                array = np.asarray(data.get(key), dtype=float)
                if array.ndim != 1 or len(array) < 2 or not np.isfinite(array).all(): raise ValueError(f'Invalid spectrum array: {key}.')
                data[key] = array
            length = len(data['x'])
            if any(len(data[key]) != length for key in ('y', 'total', 'background')) or not np.all(np.diff(data['x']) > 0): raise ValueError('Spectrum arrays must have matching lengths and increasing energies.')
            if not isinstance(data.get('peaks'), dict): raise ValueError('Invalid component data.')
            for key, values in data['peaks'].items():
                array = np.asarray(values, dtype=float)
                if array.shape != (length,) or not np.isfinite(array).all(): raise ValueError(f'Invalid component: {key}.')
                data['peaks'][key] = array
            data['residual'] = data['y'] - data['total']
            datasets.append((entry['source_path'], data))
        if len(config.get('panels', [])) < len(datasets): raise ValueError('Project is missing panel settings.')
        custom = config.get('custom_font')
        if custom:
            if not isinstance(custom, dict) or custom.get('path') not in ('font.ttf', 'font.otf', 'font.ttc'): raise ValueError('Invalid embedded font reference.')
            content = archive.read(custom['path'])
            cache = Path(tempfile.gettempdir()) / 'xps-studio-fonts'; cache.mkdir(exist_ok=True)
            destination = cache / (hashlib.sha256(content).hexdigest() + Path(custom['path']).suffix)
            if not destination.exists(): destination.write_bytes(content)
            custom['path'] = str(destination)
    for name in ('selected_panel', 'active_tab'):
        if type(payload.get(name, 0)) is not int: raise ValueError(f'Invalid project {name}.')
    return config, datasets, payload.get('selected_panel', 0), payload.get('active_tab', 0)
