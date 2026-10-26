"""Real Qt + Matplotlib checks for the live matrix controls and exports."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np
import matplotlib as mpl
from matplotlib import get_data_path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog
from xps_studio.core import Spectrum, add_peak, fit_spectrum, export_result


app = QApplication([]); configure_app(app)
dialog = MatrixDialog(); dialog.show(); app.processEvents()
errors = []


def live():
    previous = dialog.render_count
    deadline = time.monotonic() + 10
    while dialog.timer.isActive() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.025)
    app.processEvents()
    assert dialog.render_count > previous, ('Live update did not run', dialog.last_error)
    assert not dialog.last_error, dialog.last_error


x = np.linspace(280, 291, 160)
y = 100 + 800 * np.exp(-.5 * ((x - 284.8) / .65) ** 2)
s = Spectrum('test.xlsx', 'C 1s', x, y); s.config['background'] = 'Linear'
add_peak(s, 'Gaussian', 'C 1s main peak'); s.result = fit_spectrum(s)
for key in s.config['params']: s.config['params'][key] = s.result['params'][key]
for i in range(4): dialog.append_dataset(f'Sample {i+1}.csv', copy.deepcopy(s.result))
dialog.rows.setValue(2); dialog.columns.setValue(2); live()
assert len(dialog.figure.axes) == 4
assert all(ax.get_subplotspec().get_gridspec().nrows == 2 for ax in dialog.figure.axes)
assert all(ax.get_subplotspec().get_gridspec().ncols == 2 for ax in dialog.figure.axes)

# Inadequate capacity must retain the last valid figure, without dropping spectra.
previous = dialog.figure
dialog.rows.setValue(1); dialog.preview()
assert dialog.figure is previous and '4 spectra' in dialog.last_error
dialog.rows.setValue(3); live()
assert len(dialog.figure.axes) == 6 and sum(ax.get_visible() for ax in dialog.figure.axes) == 4
dialog.rows.setValue(2); live()

# Independently hide marks/labels on each panel/axis while others retain them.
dialog.table.selectRow(0); dialog.select_panel()
dialog.panel_xticks.setCurrentText('Hidden'); dialog.panel_yticks.setCurrentText('Ticks only'); live()
first, second = dialog.figure.axes[:2]
assert not any(t.tick1line.get_visible() or t.label1.get_visible() for t in first.xaxis.get_major_ticks())
assert any(t.tick1line.get_visible() for t in first.yaxis.get_major_ticks())
assert not any(t.label1.get_visible() for t in first.yaxis.get_major_ticks())
assert any(t.label1.get_visible() for t in second.xaxis.get_major_ticks())
dialog.yticks.setCurrentText('Hidden'); live()
assert not any(t.tick1line.get_visible() for t in dialog.figure.axes[1].yaxis.get_major_ticks())

# Per-panel legend names and label MathText go through the real renderer.
row = next(r for r in range(dialog.legend_table.rowCount()) if dialog.legend_table.item(r, 0).text() == 'p1_')
dialog.legend_table.item(row, 1).setText(r'$\mathrm{C}\,1s_{1/2}$')
dialog.table.item(0, 0).setText(r'Sample α · $\Delta E=\frac{a}{b}$')
dialog.table.item(0, 1).setText(r'Energy $E_{\mathrm{B}}$ (eV)')
dialog.legend_loc.setCurrentText('upper right'); live()
names = [t.get_text() for t in dialog.figure.axes[0].get_legend().get_texts()]
assert r'$\mathrm{C}\,1s_{1/2}$' in names
assert dialog.figure.axes[0].get_xlabel() == r'Energy $E_{\mathrm{B}}$ (eV)'

# Invalid equations do not replace the last successfully rendered figure.
previous = dialog.figure
dialog.table.item(0, 1).setText(r'$\frac{'); dialog.preview()
# An unmatched dollar is interpreted as literal text, so force a balanced invalid formula.
dialog.table.item(0, 1).setText(r'$\frac{a}$'); previous = dialog.figure; dialog.preview()
assert dialog.last_error and dialog.figure is previous
dialog.table.item(0, 1).setText(r'Energy $E_B$ (eV)'); live()

# System font choice and an explicitly imported font file.
assert dialog.font_family.count() > 1
dialog.font_family.setCurrentText('DejaVu Serif'); live()
assert dialog.figure.axes[0].xaxis.label.get_fontproperties().get_family() == ['DejaVu Serif']
custom_path = str(Path(get_data_path()) / 'fonts' / 'ttf' / 'DejaVuSans.ttf')
with patch('xps_studio.matrix.QFileDialog.getOpenFileName', return_value=(custom_path, '')):
    dialog.browse_font()
live()
assert dialog.figure.axes[0].xaxis.label.get_fontproperties().get_file() == str(Path(custom_path).resolve())

# Advanced native Matplotlib styling and no leaked global rcParams.
original_width = mpl.rcParams['axes.linewidth']
dialog.advanced.setPlainText(json.dumps({'rcParams': {'axes.linewidth': 2.5},
    'fit': {'alpha': .4}, 'peaks': {'p1_': {'color': '#8844aa'}}, 'legend': {'labelspacing': .2}})); live()
assert dialog.figure.axes[0].spines['left'].get_linewidth() == 2.5
assert next(line for line in dialog.figure.axes[0].lines if line.get_label() == 'Fit').get_alpha() == .4
assert mpl.rcParams['axes.linewidth'] == original_width
previous = dialog.figure; dialog.advanced.setPlainText('{'); dialog.preview()
assert dialog.last_error and dialog.figure is previous
dialog.advanced.setPlainText('{}'); live()

# Global labels inherit unless overridden, selected-panel labels remain independent.
dialog.xlabel.setText('Global energy'); live()
assert dialog.figure.axes[1].get_xlabel() == 'Global energy'
dialog.mode.setCurrentText('Shared figure labels'); live()
assert dialog.figure._supxlabel.get_text() == 'Global energy'
dialog.mode.setCurrentText('Every panel'); live()

# Per-panel settings stay attached to their dataset when reordered.
dialog.table.selectRow(0); dialog.move(1)
assert dialog.panel_options[1]['xticks'] == 'Hidden'
assert dialog.table.item(1, 0).text().startswith('Sample α')
dialog.move(-1)

# Native Matplotlib line styles, nonblocking errors, physical export sizing.
dialog.fit_style.setCurrentText('None'); live()
assert next(line for line in dialog.figure.axes[0].lines if line.get_label() == 'Fit').get_linestyle() == 'None'
dialog.fit_style.setCurrentText('-'); dialog.font.setValue(11)
dialog.yticks.setCurrentText('Ticks + labels'); dialog.panel_xticks.setCurrentText('Ticks + labels')
dialog.panel_yticks.setCurrentText('Ticks + labels'); dialog.width.setValue(10); dialog.height.setValue(7); dialog.dpi.setValue(120); live()
with tempfile.TemporaryDirectory() as folder:
    for fmt in ('png', 'svg', 'pdf'):
        dialog.format.setCurrentText(fmt)
        path = str(Path(folder) / ('matrix.' + fmt))
        with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(path, '')):
            dialog.save()
        assert not dialog.last_error, dialog.last_error
        assert Path(path).stat().st_size > 1000
        if fmt == 'png':
            from PIL import Image
            with Image.open(path) as image: assert image.size == (1200, 840)
    # Keep a reviewable exported artifact.
    Path('artifacts').mkdir(exist_ok=True)
    figure, rc = dialog.build_figure(10, 7, 100)
    with mpl.rc_context(rc): figure.savefig('artifacts/matrix-options-demo.png', dpi=120)
dialog.tabs.setCurrentIndex(1); dialog.preview(); app.processEvents()
dialog.grab().save('artifacts/matrix-options-window.png')
dialog.close(); app.processEvents()
print('PASS: 2D grids, empty cells/capacity errors, live edits, independent ticks, legend names, Unicode/math labels, system/custom fonts, validated advanced settings, reorder and PNG/SVG/PDF exports')
