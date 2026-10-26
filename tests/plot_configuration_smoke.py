"""Reusable plot configuration round-trips without retaining old data files."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
from matplotlib import get_data_path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog

app = QApplication([]); configure_app(app)
x = np.linspace(280, 290, 60); peak = 300 * np.exp(-((x - 285) / .8) ** 2)
data = {'x': x, 'y': peak + 25, 'total': peak + 25, 'background': np.full_like(x, 25),
        'peaks': {'p1_': peak}, 'config': {'peaks': [{'prefix': 'p1_', 'label': 'Main peak'}]}}
source = MatrixDialog(); source.show()
source.append_dataset('old_A.csv', data); source.append_dataset('old_B.csv', data)
source.columns.setValue(1); source.rows.setValue(2)
source.font.setValue(14); source.width.setValue(6); source.height.setValue(9)
source.dpi.setValue(150); source.format.setCurrentText('svg')
source.xlabel.setText(r'Energy $E_B$'); source.yticks.setCurrentText('Hidden')
source.table.item(1, 0).setText('Custom β title')
source.table.item(1, 1).setText('Special energy label')
source.legend_file.setCurrentIndex(0); source.custom_legend.setChecked(True)
source.file_legend_controls['title'].setText('Reference legend')
source.file_legend_controls['font_size'].setValue(13)
source.file_legend_controls['loc'].setCurrentText('lower right')
r = next(i for i in range(source.legend_table.rowCount()) if source.legend_table.item(i, 0).text() == 'p1_')
source.legend_table.item(r, 1).setText(r'$\mathrm{C}\,1s$')
source.panel_xticks.setCurrentText('Ticks only')
source.advanced.setPlainText('{"fit":{"alpha":0.6}}')
font_path = str(Path(get_data_path()) / 'fonts' / 'ttf' / 'DejaVuSans.ttf')
source.import_font(font_path)
with tempfile.TemporaryDirectory() as folder:
    path = Path(folder) / 'preset.json'
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(path), '')):
        source.save_config_button.click()
    assert path.exists() and not source.last_error, source.last_error
    preset = json.loads(path.read_text(encoding='utf-8'))
    assert preset['panels'][0]['title'] is None
    assert preset['panels'][1]['title'] == 'Custom β title'
    assert 'old_A.csv' not in path.read_text(encoding='utf-8')
    assert 'x' not in preset and 'datasets' not in preset

    # Load first, add new files later: settings follow positions and auto titles use NEW names.
    target = MatrixDialog(); target.show()
    with patch('xps_studio.matrix.QFileDialog.getOpenFileName', return_value=(str(path), '')):
        target.load_config_button.click()
    assert not target.last_error, target.last_error
    assert target.rows.value() == 2 and target.font.value() == 14 and not target.datasets
    target.append_dataset('new_X.csv', data); target.append_dataset('new_Y.csv', data)
    target.preview(); assert not target.last_error, target.last_error
    assert target.table.item(0, 0).text() == 'new_X'
    assert target.table.item(1, 0).text() == 'Custom β title'
    assert target.table.item(1, 1).text() == 'Special energy label'
    assert target.panel_options[0]['legend_layout']['title'] == 'Reference legend'
    assert target.figure.axes[0].get_legend().get_texts()[0].get_fontsize() == 13
    assert target.panel_options[0]['xticks'] == 'Ticks only'
    assert target.plot_configuration() == preset

    # Loading onto existing new data leaves its arrays and file identities untouched.
    third = MatrixDialog(); third.append_dataset('third.csv', data); third.append_dataset('fourth.csv', data)
    third.load_configuration_from(path)
    assert third.datasets[0][0] == 'third.csv' and third.datasets[0][1] is data
    assert third.table.item(0, 0).text() == 'third'

    # Invalid inputs never partially replace the active controls or per-file options.
    baseline = target.plot_configuration()
    broken = copy.deepcopy(preset); broken['controls']['rows'] = 99
    badpath = Path(folder) / 'invalid.json'; badpath.write_text(json.dumps(broken), encoding='utf-8')
    try: target.load_configuration_from(badpath)
    except ValueError: pass
    else: raise AssertionError('Out-of-range setting accepted')
    assert target.plot_configuration() == baseline
    broken = copy.deepcopy(preset); broken['controls']['data_color'] = 'invalid-colour'; broken['controls']['font'] = 22
    badpath.write_text(json.dumps(broken), encoding='utf-8')
    try: target.load_configuration_from(badpath)
    except ValueError: pass
    else: raise AssertionError('Invalid style accepted')
    assert target.plot_configuration() == baseline

    # A valid preset can recover from a partially typed invalid Advanced editor.
    target.advanced.setPlainText('{'); target.load_configuration_from(path)
    assert target.plot_configuration() == preset
    broken = copy.deepcopy(preset); broken['custom_font']['path'] = str(Path(folder) / 'missing.ttf')
    badpath.write_text(json.dumps(broken), encoding='utf-8')
    try: target.load_configuration_from(badpath)
    except ValueError as exc: assert 'font file is missing' in str(exc)
    else: raise AssertionError('Missing font was silently substituted')

    # Export after restoring a preset uses the restored settings.
    export = Path(folder) / 'restored.svg'
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(export), '')):
        target.save()
    assert export.exists() and not target.last_error
    Path('artifacts').mkdir(exist_ok=True)
    target.tabs.setCurrentIndex(1); target.preview(); app.processEvents()
    target.grab().save('artifacts/saved-plot-configuration.png')
    third.close(); target.close()
source.close(); app.processEvents()
print('PASS: save/load buttons, all-control and per-file legend round-trip, before/after CSV loading, new filenames, custom fonts, rollback, invalid-editor recovery and restored SVG export')
