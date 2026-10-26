from pathlib import Path
import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PySide6.QtWidgets import QWidget
from .core import CMAPS


def gradient_fill(ax, x, bottom, top, cmap, alpha=.65):
    vertices = np.concatenate([np.column_stack([x, top]), np.column_stack([x[::-1], bottom[::-1]])])
    patch = PathPatch(MplPath(vertices), facecolor='none', edgecolor='none')
    ax.add_patch(patch)
    ymin, ymax = float(np.min(bottom)), float(np.max(top))
    if ymax <= ymin:
        return
    im = ax.imshow(np.linspace(0, 1, 256).reshape(256, 1), extent=[min(x), max(x), ymin, ymax],
                   origin='lower', aspect='auto', cmap=cmap, alpha=alpha, zorder=1)
    im.set_clip_path(patch)


def draw_spectrum(ax, data, title='', fontsize=11, gradient=True, maps=None,
                  data_color='#26374b', fit_color='#d34a51', bg_color='#84929e', xlabel='Binding energy (eV)',
                  ylabel='Intensity (counts/s)', legend=True):
    x, y = data['x'], data['y']
    ax.scatter(x, y, s=10, color=data_color, label='Data', zorder=5, linewidths=0)
    if 'background' in data and 'total' not in data:
        ax.plot(x, data['background'], ':', color=bg_color, lw=1.5, label='Background preview')
    if 'total' in data:
        bg = data['background']
        ax.plot(x, bg, ':', color=bg_color, lw=1.4, label='Background')
        definitions = data.get('config', {}).get('peaks', [])
        for i, (key, peak) in enumerate(data['peaks'].items()):
            definition = next((p for p in definitions if p['prefix'] == key), {})
            name = definition.get('label', key.removesuffix('_component'))
            cmap = colormaps[(maps[i % len(maps)] if maps else definition.get('cmap', CMAPS[i % len(CMAPS)]))]
            top = peak + bg
            if gradient:
                gradient_fill(ax, x, bg, top, cmap)
            ax.plot(x, top, '--', color=cmap(.8), lw=1.4, label=name, zorder=3)
        ax.plot(x, data['total'], color=fit_color, lw=1.8, label='Fit', zorder=4)
        all_y = np.concatenate([y, data['total'], bg])
        margin = max(float(np.ptp(all_y)) * .12, 1.)
        ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
    region = data.get('region', data.get('config', {}).get('region', [min(x), max(x)]))
    ax.set_xlim(region[1], region[0])
    ax.set_xlabel(xlabel, fontsize=fontsize)
    ax.set_ylabel(ylabel, fontsize=fontsize)
    ax.set_title(title, fontsize=fontsize + 1, loc='left', fontweight='bold', pad=12)
    ax.tick_params(labelsize=max(6, fontsize - 1))
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(alpha=.12)
    if legend:
        ax.legend(fontsize=max(6, fontsize - 3), frameon=False, loc='best')


class SpectrumCanvas(FigureCanvasQTAgg):
    def __init__(self):
        self.figure = Figure(figsize=(8, 6), facecolor='white', layout='constrained')
        super().__init__(self.figure)
        self.display(None)

    def display(self, data, title=''):
        self.figure.clear()
        if data is None:
            ax = self.figure.add_subplot()
            ax.axis('off')
            ax.text(.5, .55, 'Your spectra, in focus.', fontsize=24, ha='center', color='#183b56')
            ax.text(.5, .44, 'Load a FACTS workbook or a two-column spectrum to begin.\nOr open the demo from the File menu.',
                    ha='center', va='center', fontsize=12, color='#6d7e8e', linespacing=1.8)
        elif 'message' in data and 'total' not in data:
            ax = self.figure.add_subplot(); ax.axis('off')
            ax.text(.5, .55, 'Adjust the energy range', ha='center', fontsize=19, color='#183b56')
            ax.text(.5, .44, data['message'], ha='center', fontsize=11, color='#6d7e8e', wrap=True)
        elif 'total' in data:
            axes = self.figure.subplots(2, 1, sharex=True, gridspec_kw={'height_ratios': [4, 1]})
            draw_spectrum(axes[0], data, title, xlabel='')
            axes[1].plot(data['x'], data['residual'], color='#168c89', lw=1)
            axes[1].axhline(0, color='#9aa6b2', lw=.7)
            axes[1].set_ylabel('Residual')
            axes[1].set_xlabel('Binding energy (eV)')
            axes[1].spines[['top', 'right']].set_visible(False)
        else:
            draw_spectrum(self.figure.add_subplot(), data, title)
        self.draw_idle()


def load_export(path):
    df = pd.read_csv(path)
    required = ['binding_energy_eV', 'intensity', 'fit_total', 'background', 'residual']
    if not all(c in df for c in required):
        raise ValueError(f'{Path(path).name}: select a spectrum CSV exported by XPS Studio, not its _peaks.csv summary.')
    df = df.sort_values('binding_energy_eV')
    if len(df) < 5 or not np.isfinite(df[required].to_numpy(dtype=float)).all():
        raise ValueError('Spectrum CSV has invalid numerical data.')
    data = dict(zip(['x', 'y', 'total', 'background', 'residual'], [df[k].to_numpy() for k in required]))
    data['peaks'] = {k.removesuffix('component'): df[k].to_numpy() for k in df if k.endswith('_component')}
    companion = Path(path).with_name(Path(path).stem + '_parameters.json')
    if companion.exists():
        from .core import read_parameters
        data['config'] = read_parameters(companion)
    summary = Path(path).with_name(Path(path).stem + '_peaks.csv')
    if summary.exists():
        try:
            metadata = pd.read_csv(summary)
            if 'peak' not in metadata or metadata['peak'].duplicated().any():
                raise ValueError('Peak summary must contain unique peak IDs.')
            data['peak_metadata'] = {str(row['peak']): {key: None if pd.isna(value) else value
                                      for key, value in row.items()} for row in metadata.to_dict('records')}
        except Exception as exc:
            data['peak_metadata_warning'] = f'Could not read {summary.name}: {exc}'
    return data


def component_positions(data):
    """One record per component, preferring fitted centers over sampled maxima."""
    config = data.get('config', {})
    definitions = {p['prefix']: p for p in config.get('peaks', [])}
    metadata = data.get('peak_metadata', {})
    x = np.asarray(data['x'], dtype=float)

    def numeric(value):
        try:
            value = float(value)
            return value if np.isfinite(value) else None
        except (TypeError, ValueError): return None

    rows = []
    for prefix, component in data['peaks'].items():
        info = metadata.get(prefix, {}); definition = definitions.get(prefix, {})
        center = None; method = ''; stderr = None
        candidates = [
            (data.get('params', {}).get(prefix + 'center', {}).get('value'), 'fitted_parameter', data.get('stderr', {}).get(prefix + 'center')),
            (info.get('center_eV'), 'peak_summary', info.get('center_stderr')),
            (config.get('params', {}).get(prefix + 'center', {}).get('value'), 'parameter_file', None)]
        for value, source, uncertainty in candidates:
            center = numeric(value)
            if center is not None:
                method = source; stderr = numeric(uncertainty); break
        notes = data.get('peak_metadata_warning', '')
        if center is None:
            curve = np.asarray(component, dtype=float)
            valid = np.isfinite(x) & np.isfinite(curve)
            if valid.any() and np.ptp(curve[valid]) > 0:
                center = float(x[valid][np.argmax(curve[valid])])
                method = 'sampled_component_maximum'
                note = 'Estimated from sampled background-free component; fitted-center metadata unavailable.'
            else:
                method = 'unavailable'
                note = 'No fitted-center metadata or unique sampled maximum (flat/invalid component).'
            notes = ' '.join(filter(None, [notes, note]))
        rows.append({'peak_id': prefix, 'peak_label': definition.get('label', info.get('label') or prefix.rstrip('_')),
                     'peak_position_eV': center, 'position_source': method, 'position_note': notes,
                     'center_stderr_eV': stderr, 'model': definition.get('kind', info.get('model', '')),
                     'energy_shift_eV': numeric(config.get('shift', info.get('energy_shift_eV'))),
                     'original_source': info.get('source') or '', 'sheet': info.get('sheet') or ''})
    return rows


class AspectPreview(QWidget):
    """Keep the preview at the physical export aspect ratio inside the window."""
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self.canvas.setParent(self)
        self.ratio = 1.5

    def fit_canvas(self):
        width = max(1, min(self.width(), int(self.height() * self.ratio)))
        height = max(1, int(width / self.ratio))
        self.canvas.setGeometry((self.width() - width) // 2, (self.height() - height) // 2, width, height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_canvas()



def __getattr__(name):
    # Preserve the public import while keeping the richer composer in its own module.
    if name == 'MatrixDialog':
        from .matrix import MatrixDialog
        return MatrixDialog
    raise AttributeError(name)
