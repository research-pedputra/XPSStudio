"""Per-panel zero-minimum display with unchanged numerical fit data."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog

app = QApplication([]); configure_app(app)
w = MatrixDialog(); w.show()
x = np.linspace(0, 10, 51)
peak = 10 * np.exp(-((x - 5) / .8) ** 2)
data = {'x': x, 'y': peak + 50, 'total': peak + 49, 'background': np.full_like(x, 49),
        'peaks': {'p1_': peak}, 'config': {'peaks': [{'prefix': 'p1_', 'label': 'Peak'}]}}
original = copy.deepcopy(data)
w.append_dataset('one.csv', data); w.append_dataset('two.csv', copy.deepcopy(data))
w.columns.setValue(2); w.rows.setValue(1); w.table.selectRow(0)
before = w.peak_positions_frame().copy()
w.panel_zero_minimum.setChecked(True)
deadline = time.monotonic() + 10
while w.timer.isActive() and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.025)
assert not w.last_error, w.last_error
first, second = w.figure.axes
np.testing.assert_allclose(first.collections[0].get_offsets()[:, 1], peak, atol=1e-12)
np.testing.assert_allclose(second.collections[0].get_offsets()[:, 1], peak + 50)
curves = {line.get_label(): line.get_ydata() for line in first.lines}
np.testing.assert_allclose(curves['Fit'], peak - 1)
np.testing.assert_allclose(curves['Background'], -1)
np.testing.assert_allclose(curves['Peak'] - curves['Background'], peak, atol=1e-12)
for key in ('x', 'y', 'total', 'background'): np.testing.assert_array_equal(data[key], original[key])
assert before.equals(w.peak_positions_frame())
w.table.selectRow(1); assert not w.panel_zero_minimum.isChecked()
w.table.selectRow(0); assert w.panel_zero_minimum.isChecked()
w.move(1); assert w.panel_options[1]['zero_minimum']
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'normalized.json'; w.save_configuration_to(path)
    target = MatrixDialog(); target.load_configuration_from(path)
    target.append_dataset('new_one.csv', copy.deepcopy(data)); target.append_dataset('new_two.csv', copy.deepcopy(data))
    target.preview(); assert not target.last_error, target.last_error
    np.testing.assert_allclose(target.figure.axes[1].collections[0].get_offsets()[:, 1], peak, atol=1e-12)
    image = str(Path(folder) / 'normalized.png'); target.dpi.setValue(80)
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(image, '')): target.save()
    assert Path(image).exists() and not target.last_error
    target.close()
w.panel_zero_minimum.setChecked(False); w.preview()
np.testing.assert_allclose(w.figure.axes[1].collections[0].get_offsets()[:, 1], peak + 50)
w.close(); app.processEvents()
print('PASS: live per-panel zero minimum, aligned fit/background/components, unchanged source and peak CSV, selection/reordering, configuration reuse and figure export')
