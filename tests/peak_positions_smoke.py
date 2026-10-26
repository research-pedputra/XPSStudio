"""Exact fitted positions for every plotted component, with explicit fallback provenance."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from lmfit.lineshapes import gaussian
from PySide6.QtWidgets import QApplication
from xps_studio.app import configure_app
from xps_studio.core import Spectrum, add_peak, fit_spectrum, export_result
from xps_studio.plotting import load_export, component_positions
from xps_studio.matrix import MatrixDialog

app = QApplication([]); configure_app(app)
x = np.linspace(280, 292, 73)
y = 25 + gaussian(x, 1200, 284.13, .5) + gaussian(x, 650, 287.21, .6)
s = Spectrum('original_sample.xlsx', 'C 1s', x, y); s.config['background'] = 'Linear'
add_peak(s, 'Gaussian', 'Main α'); add_peak(s, 'Gaussian', 'Shoulder')
s.config['params']['p1_center'].update(value=284., min=282., max=286.)
s.config['params']['p2_center'].update(value=287., min=286., max=289.)
s.result = fit_spectrum(s)
assert s.result['success']
for key in s.config['params']: s.config['params'][key] = copy.deepcopy(s.result['params'][key])
s.result['config'] = copy.deepcopy(s.config)
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder); (folder / 'one').mkdir(); (folder / 'two').mkdir()
    p1 = export_result(s, folder / 'one' / 'spectrum.csv')
    p2 = export_result(s, folder / 'two' / 'spectrum.csv')
    first = load_export(p1); second = load_export(p2)
    positions = component_positions(first)
    assert len(positions) == 2 and all(p['position_source'] == 'peak_summary' for p in positions)
    np.testing.assert_allclose([p['peak_position_eV'] for p in positions], [284.13, 287.21], atol=1e-5)
    assert abs(positions[0]['peak_position_eV'] - x[np.argmax(first['peaks']['p1_'])]) > .01
    assert positions[0]['original_source'] == 'original_sample.xlsx'

    w = MatrixDialog(); w.show(); w.rows.setValue(2); w.columns.setValue(1)
    w.append_dataset(str(p1), first); w.append_dataset(str(p2), second)
    w.panel_options[0]['names']['p2_'] = 'Edited shoulder'
    w.panel_options[0]['visible']['p2_'] = False
    w.preview(); assert not w.last_error, w.last_error
    csv = folder / 'all_peaks.csv'
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(csv), '')):
        w.export_positions_button.click()
    frame = pd.read_csv(csv)
    assert len(frame) == 4 and set(frame.peak_id) == {'p1_', 'p2_'}
    assert frame.file_name.tolist() == ['spectrum.csv'] * 4
    assert frame.file_path.nunique() == 2
    assert frame.original_file_name.tolist() == ['original_sample.xlsx'] * 4
    assert frame.sheet.tolist() == ['C 1s'] * 4
    assert frame.matrix_row.tolist() == [1, 1, 2, 2]
    assert frame.matrix_column.tolist() == [1, 1, 1, 1]
    assert frame.legend_label.iloc[1] == 'Edited shoulder' and not frame.legend_entry_enabled.iloc[1]
    assert 'Main α' in frame.peak_label.tolist()
    np.testing.assert_allclose(frame.peak_position_eV, [284.13, 287.21] * 2, atol=1e-5)
    w.table.selectRow(1); w.move(-1)
    reordered = w.peak_positions_frame()
    assert reordered.file_path.iloc[0] == str(p2.resolve())
    image = folder / 'matrix.png'; w.dpi.setValue(100)
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(image), '')):
        w.save()
    assert image.exists() and not w.last_error, w.last_error
    automatic = pd.read_csv(folder / 'matrix_peak_positions.csv')
    assert len(automatic) == 4
    np.testing.assert_allclose(automatic.peak_position_eV, reordered.peak_position_eV)
    Path('artifacts').mkdir(exist_ok=True)
    w.peak_positions_frame().to_csv('artifacts/example_matrix_peak_positions.csv', index=False, encoding='utf-8-sig')

    # Without the summary, saved optimized parameters still provide exact centers.
    p1.with_name('spectrum_peaks.csv').unlink()
    from_parameters = component_positions(load_export(p1))
    assert all(p['position_source'] == 'parameter_file' for p in from_parameters)
    np.testing.assert_allclose([p['peak_position_eV'] for p in from_parameters], [284.13, 287.21], atol=1e-5)
    # Without metadata, estimates use the component alone, not its sloping background.
    p1.with_name('spectrum_parameters.json').unlink()
    sampled = load_export(p1)
    sampled['background'] = sampled['x'] * 10000
    estimates = component_positions(sampled)
    assert all(p['position_source'] == 'sampled_component_maximum' for p in estimates)
    assert estimates[0]['peak_position_eV'] == float(x[np.argmax(sampled['peaks']['p1_'])])
    sampled['peaks']['zero_'] = np.zeros_like(x)
    missing = component_positions(sampled)[-1]
    assert missing['peak_position_eV'] is None and missing['position_source'] == 'unavailable'
    # A figure with no deconvolution never invents peaks from its envelope/background.
    no_components = dict(sampled, peaks={})
    assert component_positions(no_components) == []
    w.close(); app.processEvents()
print('PASS: all components, exact centers, original/CSV filenames, sheets, edited labels, hidden legend entries, reorder, automatic companion export and flagged metadata-free estimates')
