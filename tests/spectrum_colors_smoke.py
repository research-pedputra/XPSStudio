import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import tempfile
from pathlib import Path
import numpy as np
from matplotlib.colors import to_rgba
from matplotlib import colormaps
from PySide6.QtWidgets import QApplication
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog

app = QApplication([]); configure_app(app)
w = MatrixDialog(); w.show()
x = np.linspace(280, 290, 51); peak = 20 * np.exp(-((x-285)/.8)**2)
data = {'x': x, 'y': peak+5, 'total': peak+5, 'background': x*0+5, 'peaks': {'p1_': peak}}
for path in ('first/same.csv', 'second/same.csv'): w.append_dataset(path, data)
w.columns.setValue(2); w.rows.setValue(1); w.style_file.setCurrentIndex(0)
assert w.table.currentRow() == 0 and w.legend_file.currentIndex() == 0
w.spectrum_colors['data'].setText('#008800'); w.spectrum_colors['fit'].setText('purple')
w.spectrum_colors['background'].setText('orange'); w.spectrum_colors['palette'].setText('Purples')
deadline = time.monotonic()+10
while w.timer.isActive() and time.monotonic()<deadline: app.processEvents(); time.sleep(.02)
assert not w.last_error, w.last_error
a,b=w.figure.axes
np.testing.assert_allclose(a.collections[0].get_facecolor()[0], to_rgba('#008800'))
assert next(line for line in a.lines if line.get_label()=='Fit').get_color() == 'purple'
assert next(line for line in b.lines if line.get_label()=='Fit').get_color() == w.fit_color.text()
np.testing.assert_allclose(next(line for line in a.lines if line.get_label()=='p1').get_color(), colormaps['Purples'](.8))
w.style_file.setCurrentIndex(1); assert w.spectrum_colors['fit'].text() == ''
w.spectrum_colors['fit'].setText('blue'); w.style_file.setCurrentIndex(0)
assert w.spectrum_colors['fit'].text() == 'purple'
w.move(1); assert 'first' in w.style_path.text() and w.style_file.currentIndex()==1
with tempfile.TemporaryDirectory() as folder:
    path=Path(folder)/'colors.json'; w.save_configuration_to(path)
    other=MatrixDialog(); other.load_configuration_from(path)
    other.append_dataset('new_a.csv',data); other.append_dataset('new_b.csv',data); other.preview()
    assert not other.last_error, other.last_error
    assert next(line for line in other.figure.axes[1].lines if line.get_label()=='Fit').get_color()=='purple'
    other.close()
w.reset_spectrum_colors(); w.preview()
assert next(line for line in w.figure.axes[1].lines if line.get_label()=='Fit').get_color()==w.fit_color.text()
w.tabs.setCurrentIndex(3); app.processEvents(); Path('artifacts').mkdir(exist_ok=True)
w.grab().save('artifacts/spectrum-color-selector.png')
w.close(); app.processEvents()
print('PASS: spectrum selection, independent data/fit/background/peak colors, live updates, reorder, preset reuse and reset')
