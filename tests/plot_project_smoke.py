"""Editable, portable projects and settings-only templates with data replacement."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import copy
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from matplotlib import get_data_path
from PySide6.QtWidgets import QApplication
from xps_studio.app import configure_app
from xps_studio.matrix import MatrixDialog
from xps_studio.plotting import load_export

app = QApplication([]); configure_app(app)


def make_csv(path, center):
    x = np.linspace(280, 292, 60); peak = 300 * np.exp(-((x-center)/.7)**2)
    pd.DataFrame({'binding_energy_eV': x, 'intensity': peak+30, 'fit_total': peak+30,
                  'background': x*0+30, 'residual': x*0, 'p1_component': peak}).to_csv(path, index=False)
    pd.DataFrame([{'peak': 'p1_', 'center_eV': center, 'label': 'Main peak', 'model': 'Gaussian',
                   'source': 'experiment.xlsx', 'sheet': 'C 1s'}]).to_csv(path.with_name(path.stem+'_peaks.csv'), index=False)


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder); a = root/'first.csv'; b = root/'second.csv'
    make_csv(a, 284.2); make_csv(b, 285.4)
    w = MatrixDialog(); w.show(); w.append_dataset(str(a), load_export(a)); w.append_dataset(str(b), load_export(b))
    w.rows.setValue(2); w.columns.setValue(1); w.font.setValue(13)
    w.table.item(1, 0).setText('Custom title β')
    w.table.selectRow(0); w.panel_zero_minimum.setChecked(True)
    w.spectrum_colors['fit'].setText('purple'); w.custom_legend.setChecked(True)
    w.file_legend_controls['title'].setText('Edited legend')
    w.file_legend_controls['font_size'].setValue(11)
    font = Path(get_data_path())/'fonts'/'ttf'/'DejaVuSans.ttf'
    w.import_font(str(font)); w.tabs.setCurrentIndex(3)
    expected = w.plot_configuration(); expected_data = copy.deepcopy(w.datasets)
    project = root/'editable.xpsplot'
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(project), '')):
        w.save_project_button.click()
    assert project.exists() and not w.last_error, w.last_error
    with zipfile.ZipFile(project) as archive:
        assert 'font.ttf' in archive.namelist()
        content = json.loads(archive.read('project.json'))
        assert len(content['datasets']) == 2
    # Project remains editable without original data and resolves its embedded font.
    for path in (a, b, a.with_name('first_peaks.csv'), b.with_name('second_peaks.csv')): path.unlink()
    restored = MatrixDialog(); restored.show()
    with patch('xps_studio.matrix.QFileDialog.getOpenFileName', return_value=(str(project), '')):
        restored.open_project_button.click()
    assert not restored.last_error, restored.last_error
    embedded_font = Path(restored.plot_configuration()['custom_font']['path'])
    assert embedded_font != font and embedded_font.read_bytes() == font.read_bytes()
    assert restored.table.currentRow() == 0 and restored.tabs.currentIndex() == 3
    for (_, data), (_, original) in zip(restored.datasets, expected_data):
        for key in ('x', 'y', 'total', 'background'): np.testing.assert_array_equal(data[key], original[key])
        np.testing.assert_array_equal(data['peaks']['p1_'], original['peaks']['p1_'])
    actual = restored.plot_configuration(); actual['custom_font'] = expected['custom_font']
    assert actual == expected
    np.testing.assert_allclose(restored.peak_positions_frame().peak_position_eV, [284.2, 285.4])
    restored.spectrum_colors['fit'].setText('orange')
    second_project = root/'edited.xpsplot'; restored.save_project_to(second_project)
    third = MatrixDialog(); third.open_project_from(second_project)
    assert third.panel_options[0]['colors']['fit'] == 'orange'

    # Templates contain settings but no spectrum arrays; original JSON presets remain supported.
    template = root/'template.json'; restored.save_configuration_to(template)
    assert 'datasets' not in json.loads(template.read_text(encoding='utf-8'))
    fresh = MatrixDialog(); fresh.load_configuration_from(template)
    assert not fresh.datasets and fresh.rows.value() == 2
    c = root/'new_A.csv'; d = root/'new_B.csv'; make_csv(c, 286.1); make_csv(d, 287.3)
    fresh.append_dataset(str(c), load_export(c)); fresh.append_dataset(str(d), load_export(d)); fresh.preview()
    assert fresh.panel_options[0]['colors']['fit'] == 'orange'

    # Replace data only while preserving per-panel edits and automatically updating filename titles.
    saved_options = copy.deepcopy(restored.panel_options)
    with patch('xps_studio.matrix.QFileDialog.getOpenFileNames', return_value=([str(c), str(d)], '')):
        restored.replace_all_button.click()
    assert not restored.last_error, restored.last_error
    assert restored.panel_options == saved_options
    assert restored.table.item(0, 0).text() == 'new_A'
    assert restored.table.item(1, 0).text() == 'Custom title β'
    np.testing.assert_allclose(restored.peak_positions_frame().peak_position_eV, [286.1, 287.3])
    restored.table.selectRow(1)
    with patch('xps_studio.matrix.QFileDialog.getOpenFileName', return_value=(str(c), '')):
        restored.replace_selected_button.click()
    np.testing.assert_allclose(restored.peak_positions_frame().peak_position_eV, [286.1, 286.1])

    # Broken projects and replacement data never discard the current plot.
    baseline = restored.plot_configuration(); prior_data = list(restored.datasets)
    invalid = root/'broken.xpsplot'
    with zipfile.ZipFile(second_project) as archive: payload = json.loads(archive.read('project.json')); embedded = archive.read('font.ttf')
    payload['configuration']['controls']['data_color'] = 'not-a-color'
    with zipfile.ZipFile(invalid, 'w') as archive:
        archive.writestr('project.json', json.dumps(payload)); archive.writestr('font.ttf', embedded)
    try: restored.open_project_from(invalid)
    except ValueError: pass
    else: raise AssertionError('Invalid project accepted')
    assert restored.plot_configuration() == baseline
    assert restored.datasets[0][1] is prior_data[0][1]
    bad = root/'bad.csv'; bad.write_text('incorrect\n123\n')
    try: restored.replace_datasets({0: c, 1: bad})
    except ValueError: pass
    else: raise AssertionError('Invalid replacement accepted')
    assert restored.datasets[0][1] is prior_data[0][1]
    image = root/'reopened.png'; restored.dpi.setValue(80)
    with patch('xps_studio.matrix.QFileDialog.getSaveFileName', return_value=(str(image), '')): restored.save()
    assert image.exists() and image.with_name('reopened_peak_positions.csv').exists()
    Path('artifacts').mkdir(exist_ok=True)
    restored.tabs.setCurrentIndex(0); restored.preview(); app.processEvents()
    restored.grab().save('artifacts/project-template-controls.png')
    for window in (w, restored, third, fresh): window.close()
    app.processEvents()
print('PASS: project data/settings/font portability, edit/resave, metadata, template reuse, selected/all replacement, rollback and figure export')
