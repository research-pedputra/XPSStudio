"""Integration checks for opt-in reference recording and live energy-range controls."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import numpy as np
from lmfit.lineshapes import gaussian
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from xps_studio.app import MainWindow, configure_app
from xps_studio.core import Spectrum, save_parameters


def wait_fit(window):
    deadline = time.monotonic() + 45
    while window.worker is not None and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.01)
    assert window.worker is None, 'Worker did not finish'
    assert window.current.result and window.current.result['success']


app = QApplication([]); configure_app(app)
window = MainWindow(); window.show()
errors = []
window.error = lambda message: errors.append(str(message))
x = np.linspace(280, 294, 400)
y = gaussian(x, 1500, 286.3, .5) + 50
reference = Spectrum('sample.xlsx', 'arbitrary reference sheet', x, y)
target = Spectrum('sample.xlsx', 'another spectrum', x - 220, y)
window.register('sample.xlsx', [reference, target]); app.processEvents()
assert window.charge_record is None and reference.config['shift'] == 0
assert window.bg.currentText() == 'None'
assert not window.shirley.isVisible() and not window.tB.isVisible()
window.sheet_combo.setCurrentIndex(1); window.sheet_combo.setCurrentIndex(0)
assert target.config['shift'] == 0, 'Selecting sheets must not activate charge correction'

# Editing text (without leaving the control) must update the preview immediately.
window.xmin.setFocus(); window.xmin.selectAll(); QTest.keyClicks(window.xmin, '282.0')
window.xmax.setFocus(); window.xmax.selectAll(); QTest.keyClicks(window.xmax, '289.0')
app.processEvents(); window.canvas.draw()
assert reference.config['region'] == [282., 289.]
np.testing.assert_allclose(window.canvas.figure.axes[0].get_xlim(), [289., 282.])
plotted = window.canvas.figure.axes[0].collections[0].get_offsets()[:, 0]
assert plotted.min() >= 282 and plotted.max() <= 289
window.bg.setCurrentText('Shirley'); app.processEvents()
assert window.shirley.isVisible() and not window.tB.isVisible()
assert any(line.get_label() == 'Background preview' for line in window.canvas.figure.axes[0].lines)
window.bg.setCurrentText('Tougaard'); app.processEvents()
assert not window.shirley.isVisible() and window.tB.isVisible() and window.tC.isVisible()
window.bg.setCurrentText('Linear'); app.processEvents()
assert not window.shirley.isVisible() and not window.tB.isVisible()

window.charge_correction(); window.peak_kind.setCurrentText('Gaussian')
window.fit_reference(); wait_fit(window)
assert reference.result['x'].min() >= 282 and reference.result['x'].max() <= 289
assert window.charge_record is None, 'Fitting must not activate correction'
assert window.charge_apply_button.isEnabled()
window.charge_apply_button.click(); app.processEvents()
assert not errors, errors
assert abs(window.charge_record['shift_eV'] + 1.5) < 1e-5
assert reference.result is not None, 'Recording must preserve the reference fit'
assert abs(reference.result['params']['p1_center']['value'] - 284.8) < 1e-5
assert window.shift.isReadOnly()
window.sheet_combo.setCurrentIndex(1); app.processEvents()
assert abs(target.config['shift'] + 1.5) < 1e-5
np.testing.assert_allclose(target.config['region'], [58.5, 72.5], atol=1e-5)
for _ in range(3):
    window.sheet_combo.setCurrentIndex(0); window.sheet_combo.setCurrentIndex(1)
assert abs(target.config['shift'] + 1.5) < 1e-5
new = Spectrum('next.dat', 'next', x, y)
window.register('next.dat', [new]); app.processEvents()
assert abs(new.config['shift'] + 1.5) < 1e-5 and not window.sheet_combo.isEnabled()
window.file_combo.setCurrentIndex(0); window.sheet_combo.setCurrentIndex(0)
window.reference_energy.setValue(285.3); window.charge_apply_button.click()
assert abs(window.charge_record['shift_eV'] + 1.) < 1e-5
window.sheet_combo.setCurrentIndex(1)
assert abs(target.config['shift'] + 1.) < 1e-5

# Saved corrected parameters alone cannot silently enable charge correction.
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'corrected.json'; save_parameters(reference, path)
    fresh = MainWindow(); fresh.error = lambda message: errors.append(str(message))
    fresh.register('fresh.dat', [Spectrum('fresh.dat', 'fresh', x, y)])
    with patch('xps_studio.app.QFileDialog.getOpenFileName', return_value=(str(path), '')):
        fresh.load_params()
    assert fresh.current.config['shift'] == 0 and fresh.charge_record is None
    assert abs(fresh.current.config['params']['p1_center']['value'] - 286.3) < 1e-5
    fresh.close()

window.sheet_combo.setCurrentIndex(0); window.canvas.draw(); app.processEvents()
assert len(window.canvas.figure.axes) == 2, 'Completed fits must display spectrum and residual, not optimizer status as an error'
assert any(line.get_label() == 'Fit' for line in window.canvas.figure.axes[0].lines)
Path('artifacts').mkdir(exist_ok=True)
window.grab().save('artifacts/charge-correction.png')
window.clear_charge_correction()
for spectra in window.files.values():
    for s in spectra.values(): assert s.config['shift'] == 0
assert reference.result is not None
assert abs(reference.result['params']['p1_center']['value'] - 286.3) < 1e-5
assert not errors, errors
window.close(); app.processEvents()
print('PASS: opt-in reference fitting/recording, automatic sheet/file shifts, no cumulative shifts, replacement/clear, inactive saved shifts, live typed range and fit bounds, conditional background preview')
