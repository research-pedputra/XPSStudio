import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from PySide6.QtWidgets import QApplication
from xps_studio.app import MainWindow, configure_app
from xps_studio.post_dialog import PostAnalysisDialog
from xps_studio.post_analysis import save_session, read_session
from tests.test_post_analysis import example

app = QApplication([]); configure_app(app)
main = MainWindow()
menu = next(a.menu() for a in main.menuBar().actions() if 'Analysis' in a.text())
menu.actions()[0].trigger(); app.processEvents()
dialog = main.dialogs[-1]; assert isinstance(dialog, PostAnalysisDialog)
dialog.append_records(example()+example('second.xlsx'))
assert not dialog.last_error, dialog.last_error
assert dialog.composition.rowCount() == 6 and dialog.pair_table.rowCount() == 6
dialog.append_records(example()); assert len(dialog.records) == 12
dialog.table.item(0,4).setText('0'); assert dialog.last_error and dialog.composition.rowCount() == 0
dialog.table.item(0,4).setText('7.04'); assert not dialog.last_error
with tempfile.TemporaryDirectory() as folder:
    root = Path(folder); session = root/'analysis.xpspost'
    with patch('xps_studio.post_dialog.QFileDialog.getSaveFileName', return_value=(str(session),'')): dialog.save_analysis()
    other = PostAnalysisDialog()
    with patch('xps_studio.post_dialog.QFileDialog.getOpenFileName', return_value=(str(session),'')): other.open_analysis()
    assert other.records == dialog.records and len(other.pairs) == 6
    other.export_to(root/'composition.csv')
    assert len(pd.read_csv(root/'composition.csv')) == 6
    assert len(pd.read_csv(root/'composition_doublets.csv')) == 6
    assert len(pd.read_csv(root/'composition_inputs.csv')) == 12
    other.close()
dialog.tabs.setCurrentIndex(1); app.processEvents()
Path('artifacts').mkdir(exist_ok=True); dialog.grab().save('artifacts/post-analysis.png')
dialog.close(); main.close(); app.processEvents()
print('PASS: Post Analysis menu, multi-sample calculation, live validation, deduplication, doublets, session and CSV exports')
