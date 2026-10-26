"""Exercise actual Qt widgets and threaded fit using the offscreen platform."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from xps_studio.app import MainWindow, configure_app
from xps_studio.core import export_result
from xps_studio.plotting import MatrixDialog, load_export
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

app = QApplication([]); configure_app(app)
window = MainWindow(); window.show(); window.open_demo(); app.processEvents()
assert window.sheet_combo.count() == 2
window.start_fit()
deadline = time.monotonic() + 60
while window.worker is not None and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.01)
assert window.worker is None, 'Fit thread timed out'
assert window.current.result is not None
assert window.current.result['success']
assert abs(window.current.result['params']['p1_center']['value'] - 284.8) < .05
first = window.current
window.sheet_combo.setCurrentIndex(1); app.processEvents()
assert window.current is not first and window.current.result is None
window.sheet_combo.setCurrentIndex(0); app.processEvents()
assert window.current.result is not None
Path('artifacts').mkdir(exist_ok=True)
window.grab().save('artifacts/main-window.png')
with tempfile.TemporaryDirectory() as folder:
    path = export_result(window.current, Path(folder) / 'demo.csv')
    dialog = MatrixDialog(window); dialog.show()
    for i in range(3):
        dialog.datasets.append((str(path), load_export(path)))
        dialog.table.insertRow(i)
        for col, text in enumerate([f'Sample {i+1}', 'Binding energy (eV)', 'Intensity']):
            dialog.table.setItem(i, col, QTableWidgetItem(text))
        item = QTableWidgetItem('X + Y'); item.setCheckState(Qt.CheckState.Checked); dialog.table.setItem(i, 3, item)
    for mode in range(4):
        dialog.mode.setCurrentIndex(mode); dialog.render(); dialog.canvas.draw()
    dialog.width.setValue(8); dialog.height.setValue(5); dialog.dpi.setValue(120)
    for fmt in ('png', 'pdf', 'svg', 'tiff', 'jpeg'):
        destination = str(Path(folder) / ('matrix.' + fmt))
        dialog.format.setCurrentText(fmt)
        with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(destination, '')):
            dialog.save()
        assert Path(destination).stat().st_size > 1000
        if fmt == 'png':
            from PIL import Image
            with Image.open(destination) as image:
                assert image.size == (960, 600), image.size
    dialog.width.setValue(12); dialog.height.setValue(8); dialog.render(); dialog.canvas.draw()
    dialog.figure.savefig('artifacts/matrix-demo.png', dpi=110)
    app.processEvents(); dialog.grab().save('artifacts/matrix-window.png'); dialog.close()
window.close(); app.processEvents()
print('PASS: threaded fit, optimized controls, sheet isolation, CSV matrix round-trip, four label modes, five export formats and exact PNG dimensions, rendering')
