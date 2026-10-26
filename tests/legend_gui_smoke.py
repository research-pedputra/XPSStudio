"""Independent legend editing for loaded files, including files with matching names."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog

app = QApplication([]); configure_app(app)
w = MatrixDialog(); w.show()
x = np.linspace(280, 290, 80); peak = 500 * np.exp(-((x - 285) / .8) ** 2)
data = {'x': x, 'y': peak + 25, 'total': peak + 25, 'background': np.full_like(x, 25),
        'peaks': {'p1_': peak}, 'config': {'peaks': [{'prefix': 'p1_', 'label': 'Peak 1'}]}}
for path in ('first/fit.csv', 'second/fit.csv'): w.append_dataset(path, data)
w.columns.setValue(2); w.rows.setValue(1); w.legend_font.setValue(8)
w.legend_file.setCurrentIndex(0)
assert w.table.currentRow() == 0 and 'first' in w.legend_file_path.text()

def entry(key):
    return next(r for r in range(w.legend_table.rowCount()) if w.legend_table.item(r, 0).text() == key)

def live():
    old = w.render_count; deadline = time.monotonic() + 10
    while w.timer.isActive() and time.monotonic() < deadline:
        app.processEvents(); time.sleep(.025)
    assert not w.last_error, w.last_error
    assert w.render_count > old

w.legend_table.item(entry('fit'), 1).setText('First fitted curve')
w.legend_table.item(entry('p1_'), 1).setText(r'$\mathrm{C}\,1s$')
w.legend_table.item(entry('data'), 2).setCheckState(Qt.CheckState.Unchecked)
w.custom_legend.setChecked(True)
w.file_legend_controls['loc'].setCurrentText('lower left')
w.file_legend_controls['font_size'].setValue(13)
w.file_legend_controls['columns'].setValue(2)
w.file_legend_controls['frame'].setChecked(True)
w.file_legend_controls['alpha'].setValue(.4)
w.file_legend_controls['title'].setText('First sample')
live()
a, b = [ax.get_legend() for ax in w.figure.axes]
assert 'First fitted curve' in [t.get_text() for t in a.get_texts()]
assert 'Data' not in [t.get_text() for t in a.get_texts()]
assert 'Fit' in [t.get_text() for t in b.get_texts()]
assert a.get_texts()[0].get_fontsize() == 13 and b.get_texts()[0].get_fontsize() == 8
assert a.get_title().get_text() == 'First sample' and b.get_title().get_text() == ''
assert a.get_frame_on() and not b.get_frame_on()
assert a.get_frame().get_alpha() == .4

w.legend_file.setCurrentIndex(1)
assert not w.custom_legend.isChecked() and 'second' in w.legend_file_path.text()
assert w.legend_table.item(entry('fit'), 1).text() == 'Fit'
w.legend_table.item(entry('fit'), 1).setText('Second fitted curve')
w.custom_legend.setChecked(True); w.file_legend_controls['loc'].setCurrentText('upper right')
w.file_legend_controls['font_size'].setValue(9); w.file_legend_controls['title'].setText('Second sample')
live()
w.legend_file.setCurrentIndex(0)
assert w.file_legend_controls['title'].text() == 'First sample'
assert w.file_legend_controls['font_size'].value() == 13
assert w.legend_table.item(entry('fit'), 1).text() == 'First fitted curve'
w.move(1)
assert w.legend_file.currentIndex() == 1 and 'first' in w.legend_file_path.text()
assert w.panel_options[1]['legend_layout']['title'] == 'First sample'
w.file_legend_visibility.setCurrentText('Hide'); live()
assert w.figure.axes[1].get_legend() is None and w.figure.axes[0].get_legend() is not None
w.file_legend_visibility.setCurrentText('Show'); live()

# Global changes do not override the custom settings of either file.
w.legend_font.setValue(6); live()
assert w.figure.axes[0].get_legend().get_texts()[0].get_fontsize() == 9
assert w.figure.axes[1].get_legend().get_texts()[0].get_fontsize() == 13
with tempfile.TemporaryDirectory() as folder:
    path = str(Path(folder) / 'independent-legends.png'); w.dpi.setValue(100)
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(path, '')):
        w.save()
    assert Path(path).stat().st_size > 1000 and not w.last_error
Path('artifacts').mkdir(exist_ok=True)
w.tabs.setCurrentIndex(4); w.preview(); app.processEvents()
w.grab().save('artifacts/per-file-legends.png')
w.reset_file_legend(); live()
assert w.figure.axes[1].get_legend().get_title().get_text() == ''
assert w.figure.axes[0].get_legend().get_title().get_text() == 'Second sample'
w.remove()
assert w.legend_file.count() == 1
assert 'second' in w.legend_file.itemText(0)
w.close(); app.processEvents()
print('PASS: file selector, duplicate basenames, independent names/visibility/layout, live updates, selection/reorder/reset/remove and PNG export')
