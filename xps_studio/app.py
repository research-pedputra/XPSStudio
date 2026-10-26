"""XPS Studio desktop interface."""
import copy
import sys
from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QFont, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QComboBox, QDoubleSpinBox, QSpinBox, QPushButton, QLabel, QGroupBox,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QMessageBox, QDialog, QDialogButtonBox, QCheckBox, QPlainTextEdit, QProgressBar,
    QScrollArea, QAbstractItemView)
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT
from .core import (Spectrum, MODELS, CMAPS, load_file, add_peak, region_arrays, make_model,
    parameter_dict, fit_spectrum, export_result, save_parameters, read_parameters, background, snapshot,
    charge_reference, apply_charge_shift)
from .plotting import SpectrumCanvas
from .matrix import MatrixDialog
from .version import VERSION

STYLE = '''
QMainWindow, QDialog { background: #eff3f7; }
QWidget { font-family: "DejaVu Sans"; font-size: 9pt; color: #23374c; }
QMenuBar, QMenu { background: white; padding: 5px; }
QMenu::item:selected { background: #d9eeee; }
QGroupBox { background: white; border: 1px solid #dbe3eb; border-radius: 8px;
 margin-top: 16px; padding: 14px 10px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton { background: white; border: 1px solid #cdd8e2; border-radius: 6px; padding: 8px 12px; }
QPushButton:hover { background: #e7f3f3; border-color: #148c88; }
QPushButton:disabled { color: #9aa9b7; background: #edf0f3; }
QPushButton#primary { background: #087f82; border: 0; color: white; font-weight: 600; padding: 11px; }
QPushButton#primary:hover { background: #08686b; }
QPushButton#primary:disabled { background: #9dbab9; }
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #ced9e3;
 border-radius: 4px; padding: 5px; selection-background-color: #0b8585; }
QTableWidget, QPlainTextEdit { background: white; border: 1px solid #dbe3eb;
 gridline-color: #eef2f5; selection-background-color: #daefef; selection-color: #183b56; }
QHeaderView::section { background: #f0f5f8; padding: 7px; border: 0; border-bottom: 1px solid #dbe3eb; }
QTabWidget::pane { border: 1px solid #dbe3eb; background: white; }
QTabBar::tab { padding: 9px 18px; background: #e7edf3; }
QTabBar::tab:selected { background: white; color: #087f82; }
QProgressBar { border: 0; background: #e1e9ee; height: 5px; }
QProgressBar::chunk { background: #0d9390; }
QStatusBar { background: white; }
'''


def number(value=0, minimum=-1e9, maximum=1e9, decimals=5):
    box = QDoubleSpinBox(); box.setRange(minimum, maximum); box.setDecimals(decimals)
    box.setValue(value); box.setKeyboardTracking(False)
    return box


class FitWorker(QThread):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, spectrum, parent=None):
        super().__init__(parent)
        self.spectrum = copy.deepcopy(spectrum)

    def run(self):
        try:
            self.completed.emit(fit_spectrum(self.spectrum, self.progress.emit, self.isInterruptionRequested))
        except Exception as exc:
            self.failed.emit(str(exc))


class ImportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle('Import data')
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox(); self.mode.addItems(['Data from FACTS (default)', 'Generic two columns'])
        self.skip = QSpinBox(); self.skip.setRange(0, 100); self.skip.setValue(1)
        form.addRow('Excel / CSV layout', self.mode); form.addRow('Rows before FACTS header', self.skip)
        layout.addLayout(form)
        note = QLabel('FACTS: Binding energy (eV) and Counts per second.\nExcel sheets load separately. CSV is a single table.\nDAT / DATA / TXT always use their first two columns.\nBlank rows and nonnumeric entries are ignored.')
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject); layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'XPS Studio {VERSION} · Spectral analysis')
        self.resize(1450, 940)
        self.files = {}; self.current = None; self.worker = None; self.fit_target = None
        self.loading = False; self.dialogs = []
        self.charge_record = None
        self.build_ui(); self.build_menus()
        self.statusBar().showMessage('Ready · Load a workbook or try File → Open demo')

    def build_ui(self):
        root = QWidget(); self.setCentralWidget(root); layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 12, 18, 10)
        header = QHBoxLayout()
        brand = QLabel('XPS <span style="color:#0b8585">STUDIO</span>'); brand.setStyleSheet('font-size: 23pt; font-weight: 700;')
        header.addWidget(brand); header.addWidget(QLabel('  /  Spectral analysis workspace')); header.addStretch()
        self.load_button = QPushButton('+ Load data'); self.load_button.clicked.connect(self.load_data); header.addWidget(self.load_button)
        layout.addLayout(header)
        splitter = QSplitter(); layout.addWidget(splitter, 1)
        self.controls = QWidget(); side = QVBoxLayout(self.controls); side.setContentsMargins(0, 0, 12, 0)
        source = QGroupBox('01   DATA SOURCE'); source_form = QFormLayout(source)
        self.file_combo = QComboBox(); self.file_combo.setMinimumWidth(160)
        self.file_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.file_combo.setMinimumContentsLength(16)
        self.sheet_combo = QComboBox(); self.file_combo.currentIndexChanged.connect(self.switch_file)
        self.sheet_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sheet_combo.setMinimumContentsLength(12)
        self.sheet_combo.currentIndexChanged.connect(self.switch_sheet)
        source_form.addRow('File', self.file_combo); source_form.addRow('Sheet', self.sheet_combo)
        self.source_info = QLabel('No spectra loaded'); self.source_info.setWordWrap(True); source_form.addRow(self.source_info)
        self.shift = number(); self.shift.setReadOnly(True)
        self.shift.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.shift.setToolTip('Assigned by Apply Charge Correction. Off until you record a fitted reference.')
        source_form.addRow('Charge shift Δ (eV)', self.shift)
        self.charge_status = QLabel('Charge correction off'); self.charge_status.setWordWrap(True)
        source_form.addRow(self.charge_status)
        side.addWidget(source)
        self.charge_box = QGroupBox('CHARGE CORRECTION · REFERENCE FIT')
        charge_form = QFormLayout(self.charge_box)
        intro = QLabel('Select any file and sheet above, choose an energy range, then fit its reference peak.')
        intro.setWordWrap(True); charge_form.addRow(intro)
        self.reference_peak = QComboBox(); self.reference_energy = number(284.8)
        charge_form.addRow('Fitted peak', self.reference_peak); charge_form.addRow('Reference (eV)', self.reference_energy)
        self.reference_fit_button = QPushButton('Fit reference spectrum'); self.reference_fit_button.clicked.connect(self.fit_reference)
        self.charge_apply_button = QPushButton('Apply Charge Correction'); self.charge_apply_button.setObjectName('primary')
        self.charge_apply_button.clicked.connect(self.record_charge_correction)
        self.charge_apply_button.setEnabled(False)
        charge_form.addRow(self.reference_fit_button); charge_form.addRow(self.charge_apply_button)
        self.record_info = QLabel('No reference recorded. Fitting alone does not enable correction.')
        self.record_info.setWordWrap(True); charge_form.addRow(self.record_info)
        side.addWidget(self.charge_box); self.charge_box.hide()
        self.settings_box = QGroupBox('02   ENERGY RANGE & BACKGROUND'); form = QFormLayout(self.settings_box)
        self.region_form = form
        self.xmin = number(); self.xmax = number()
        self.xmin.setKeyboardTracking(True); self.xmax.setKeyboardTracking(True)
        self.bg = QComboBox(); self.bg.addItems(['None', 'Linear', 'Shirley', 'Tougaard'])
        self.shirley = number(1., 0., 2.)
        self.tB = number(2866., 0., 1e9, 2); self.tC = number(1643., .00001, 1e9, 2)
        self.nfev = QSpinBox(); self.nfev.setRange(10, 100000); self.nfev.setValue(3000)
        for label, control in [('Energy min (eV)', self.xmin), ('Energy max (eV)', self.xmax),
                               ('Background', self.bg),
                               ('Shirley scale', self.shirley), ('Tougaard B', self.tB), ('Tougaard C (eV²)', self.tC),
                               ('Max evaluations', self.nfev)]:
            form.addRow(label, control)
            if isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self.settings_changed)
            else:
                control.valueChanged.connect(self.settings_changed)
        self.background_note = QLabel(); self.background_note.setWordWrap(True)
        form.addRow(self.background_note); side.addWidget(self.settings_box)
        self.update_background_controls()
        peaks = QGroupBox('03   PEAK COMPONENTS'); pv = QVBoxLayout(peaks)
        self.peak_kind = QComboBox(); self.peak_kind.addItems(MODELS.keys()); self.peak_kind.setCurrentText('Pseudo-Voigt')
        self.add_button = QPushButton('+ Add peak'); self.add_button.clicked.connect(self.add_component)
        row = QHBoxLayout(); row.addWidget(self.peak_kind); row.addWidget(self.add_button); pv.addLayout(row)
        self.peak_table = QTableWidget(0, 3); self.peak_table.setHorizontalHeaderLabels(['Label', 'Model', 'Gradient'])
        self.peak_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.peak_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.peak_table.setMaximumHeight(170); self.peak_table.itemChanged.connect(self.peak_label_changed)
        pv.addWidget(self.peak_table)
        delete = QPushButton('Remove selected peak'); delete.clicked.connect(self.remove_component); pv.addWidget(delete)
        side.addWidget(peaks)
        self.fit_button = QPushButton('Fit spectrum'); self.fit_button.setObjectName('primary'); self.fit_button.clicked.connect(self.start_fit)
        self.cancel_button = QPushButton('Stop fitting'); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self.cancel_fit)
        # Fit controls live outside disabled input panel so cancellation remains accessible.
        side.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.controls); scroll.setMinimumWidth(375)
        splitter.addWidget(scroll)
        right = QWidget(); rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.canvas = SpectrumCanvas(); rv.addWidget(NavigationToolbar2QT(self.canvas, self))
        vertical = QSplitter(Qt.Orientation.Vertical); vertical.addWidget(self.canvas)
        self.tabs = QTabWidget()
        self.params = QTableWidget(0, 6)
        self.params.setHorizontalHeaderLabels(['Parameter', 'Value', 'Minimum', 'Maximum', 'Vary', 'Expression'])
        self.params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.params.itemChanged.connect(self.parameter_changed)
        self.params.setToolTip('Blank bounds mean unbounded. Amplitude is integrated peak area.\nTie parameters with expressions, e.g. p1_center + 1.2. Expression parameters are not independently fitted.')
        self.tabs.addTab(self.params, 'Parameters')
        self.summary = QTableWidget(0, 6); self.summary.setHorizontalHeaderLabels(['Peak', 'Position (eV)', 'Height', 'Area', 'FWHM (eV)', 'Region area'])
        self.summary.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.summary.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.summary, 'Peak results')
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.tabs.addTab(self.log, 'Fit report')
        vertical.addWidget(self.tabs); vertical.setSizes([560, 245]); rv.addWidget(vertical, 1)
        bar = QHBoxLayout(); self.fit_status = QLabel('No fit yet'); bar.addWidget(self.fit_status, 1)
        bar.addWidget(self.fit_button); bar.addWidget(self.cancel_button)
        self.export_button = QPushButton('Save fitted CSV…'); self.export_button.clicked.connect(self.export_current); bar.addWidget(self.export_button)
        rv.addLayout(bar)
        self.progress = QProgressBar(); self.progress.setTextVisible(False); self.progress.setRange(0, 1); self.progress.setValue(0); rv.addWidget(self.progress)
        splitter.addWidget(right); splitter.setSizes([395, 1055])

    def build_menus(self):
        self.mutation_actions = []
        file = self.menuBar().addMenu('&File')
        self.action(file, 'Load data…', self.load_data, 'Ctrl+O', True)
        self.action(file, 'Open demo', self.open_demo, None, True)
        file.addSeparator()
        self.action(file, 'Save fitted spectrum…', self.export_current, 'Ctrl+S', True)
        self.action(file, 'Save all fitted spectra…', self.export_all, None, True)
        self.action(file, 'Save parameters…', self.save_params, None, True)
        self.action(file, 'Load parameters…', self.load_params, None, True)
        file.addSeparator(); self.action(file, 'Exit', self.close, 'Ctrl+Q')
        edit = self.menuBar().addMenu('&Edit')
        bgmenu = edit.addMenu('Background subtraction')
        for kind in ['Linear', 'Shirley', 'Tougaard', 'None']:
            self.action(bgmenu, kind, lambda checked=False, kind=kind: self.bg.setCurrentText(kind), None, True)
        self.action(edit, 'Preview initial model', self.preview_model, None, True)
        charge = self.menuBar().addMenu('&Charge Correction')
        self.action(charge, 'Reference fitting…', self.charge_correction, None, True)
        self.action(charge, 'Apply fitted reference', self.record_charge_correction, None, True)
        self.action(charge, 'View recorded reference…', self.view_charge_record)
        self.action(charge, 'Clear correction (return to raw energy)', self.clear_charge_correction, None, True)
        plot = self.menuBar().addMenu('&Plot')
        self.action(plot, 'Matrix plot from saved CSVs…', self.open_matrix)
        self.action(plot, 'Save current figure…', self.save_figure)
        post = self.menuBar().addMenu('Post &Analysis')
        self.action(post, 'Atomic %, weight % & doublet separation…', self.open_post_analysis)
        helpmenu = self.menuBar().addMenu('&Help')
        self.action(helpmenu, 'Workflow & parameter conventions', self.help)

    def action(self, menu, title, fn, shortcut=None, mutation=False):
        action = QAction(title, self); action.triggered.connect(fn)
        if shortcut: action.setShortcut(shortcut)
        menu.addAction(action)
        if mutation: self.mutation_actions.append(action)

    def open_post_analysis(self):
        from .post_dialog import PostAnalysisDialog
        dialog = PostAnalysisDialog(self); self.dialogs.append(dialog); dialog.show()

    def error(self, exc):
        QMessageBox.warning(self, 'XPS Studio', str(exc))

    def load_data(self):
        dialog = ImportDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted: return
        paths, _ = QFileDialog.getOpenFileNames(self, 'Load spectra', '', 'Spectra (*.xlsx *.xls *.xlsm *.csv *.dat *.data *.txt);;All files (*)')
        errors = []
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in paths:
                canonical = str(Path(path).resolve())
                if canonical in self.files:
                    self.file_combo.setCurrentIndex(self.file_combo.findData(canonical)); continue
                try:
                    spectra, problems = load_file(path, dialog.mode.currentIndex() == 0, dialog.skip.value())
                    errors.extend(f'{Path(path).name}: {p}' for p in problems)
                    if spectra: self.register(canonical, spectra)
                except Exception as exc:
                    errors.append(f'{Path(path).name}: {exc}')
        except Exception as exc:
            errors.append(str(exc))
        finally:
            QApplication.restoreOverrideCursor()
        if errors: self.error('\n'.join(errors))

    def register(self, key, spectra):
        self.files[key] = {s.sheet: s for s in spectra}
        self.file_combo.addItem(f'{Path(key).name}  —  {Path(key).parent}', key)
        self.file_combo.setItemData(self.file_combo.count() - 1, key, Qt.ItemDataRole.ToolTipRole)
        self.file_combo.setCurrentIndex(self.file_combo.count() - 1)

    def switch_file(self):
        key = self.file_combo.currentData()
        if key not in self.files: return
        self.sheet_combo.blockSignals(True); self.sheet_combo.clear(); self.sheet_combo.addItems(self.files[key])
        self.sheet_combo.blockSignals(False)
        # DAT/CSV are single spectra, without a redundant sheet selector.
        self.sheet_combo.setEnabled(Path(key).suffix.lower() in ('.xlsx', '.xls', '.xlsm'))
        self.switch_sheet()

    def switch_sheet(self):
        key = self.file_combo.currentData(); sheet = self.sheet_combo.currentText()
        if key not in self.files or sheet not in self.files[key]: return
        self.current = self.files[key][sheet]
        self.assign_recorded_shift(self.current)
        self.restore()

    def restore(self):
        s = self.current
        if s is None: return
        self.loading = True
        cfg = s.config
        self.xmin.setValue(cfg['region'][0]); self.xmax.setValue(cfg['region'][1]); self.shift.setValue(cfg['shift'])
        self.bg.setCurrentText(cfg['background']); self.shirley.setValue(cfg['shirley_scale'])
        self.tB.setValue(cfg['tougaard_B']); self.tC.setValue(cfg['tougaard_C']); self.nfev.setValue(cfg['max_nfev'])
        self.source_info.setText(f'{len(s.x):,} points · {s.x.min():.3f}–{s.x.max():.3f} eV')
        self.source_info.setToolTip(s.source)
        self.populate_peaks(); self.populate_params(); self.loading = False
        self.update_background_controls()
        self.show_current()

    def update_background_controls(self):
        kind = self.bg.currentText()
        self.region_form.setRowVisible(self.shirley, kind == 'Shirley')
        self.region_form.setRowVisible(self.tB, kind == 'Tougaard')
        self.region_form.setRowVisible(self.tC, kind == 'Tougaard')
        notes = {'None': 'No background applied. Plot and fit use the selected energy range.',
                 'Linear': 'Linear background is previewed automatically; slope and intercept are optimized during fitting.',
                 'Shirley': 'Shirley background is calculated automatically over the selected range.',
                 'Tougaard': 'Tougaard background is calculated automatically over the selected range.'}
        self.background_note.setText(notes[kind])

    def settings_changed(self):
        if self.loading or self.current is None: return
        cfg = self.current.config
        cfg.update(region=[self.xmin.value(), self.xmax.value()], background=self.bg.currentText(),
                   shirley_scale=self.shirley.value(), tougaard_B=self.tB.value(), tougaard_C=self.tC.value(), max_nfev=self.nfev.value())
        self.update_background_controls(); self.invalidate(); self.populate_params()

    def invalidate(self):
        if self.current:
            self.current.result = None
            self.show_current()

    def populate_peaks(self):
        self.peak_table.blockSignals(True); self.peak_table.setRowCount(0)
        for i, p in enumerate(self.current.config['peaks']):
            self.peak_table.insertRow(i); self.peak_table.setItem(i, 0, QTableWidgetItem(p['label']))
            kind = QTableWidgetItem(p['kind']); kind.setFlags(kind.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.peak_table.setItem(i, 1, kind)
            combo = QComboBox(); combo.addItems(CMAPS); combo.setCurrentText(p['cmap'])
            combo.currentTextChanged.connect(lambda text, prefix=p['prefix']: self.change_color(prefix, text))
            self.peak_table.setCellWidget(i, 2, combo)
        self.peak_table.blockSignals(False)

    def peak_label_changed(self, item):
        if self.loading or not self.current or item.column() != 0: return
        p = self.current.config['peaks'][item.row()]; p['label'] = item.text()
        if self.current.result:
            self.current.result['config']['peaks'] = copy.deepcopy(self.current.config['peaks'])
        self.show_current()

    def change_color(self, prefix, text):
        if not self.current: return
        for p in self.current.config['peaks']:
            if p['prefix'] == prefix: p['cmap'] = text
        if self.current.result:
            self.current.result['config']['peaks'] = copy.deepcopy(self.current.config['peaks'])
        self.show_current()

    def add_component(self):
        if self.current is None: return self.error('Load a spectrum first.')
        try:
            add_peak(self.current, self.peak_kind.currentText()); self.populate_peaks(); self.populate_params(); self.show_current()
        except Exception as exc: self.error(exc)

    def remove_component(self):
        row = self.peak_table.currentRow()
        if self.current is None or row < 0: return
        p = self.current.config['peaks'].pop(row)
        self.current.config['params'] = {k: v for k, v in self.current.config['params'].items() if not k.startswith(p['prefix'])}
        self.invalidate(); self.populate_peaks(); self.populate_params()

    def populate_params(self):
        if self.current is None: return
        cfg = self.current.config
        if cfg['background'] == 'Linear' and cfg['peaks']:
            try:
                _, pars = make_model(self.current)
                for name in ('bkg_slope', 'bkg_intercept'):
                    cfg['params'].setdefault(name, parameter_dict(pars[name]))
            except Exception:
                pass
        self.params.blockSignals(True); self.params.setRowCount(0)
        for name, p in cfg['params'].items():
            if name.startswith('bkg_') and cfg['background'] != 'Linear': continue
            row = self.params.rowCount(); self.params.insertRow(row)
            item = QTableWidgetItem(name); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable); self.params.setItem(row, 0, item)
            for col, key in [(1, 'value'), (2, 'min'), (3, 'max'), (5, 'expr')]:
                val = p.get(key)
                text = '' if val is None else format(val, '.10g') if isinstance(val, (int, float)) else str(val)
                self.params.setItem(row, col, QTableWidgetItem(text))
            check = QTableWidgetItem(); check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check.setCheckState(Qt.CheckState.Checked if p['vary'] else Qt.CheckState.Unchecked); self.params.setItem(row, 4, check)
        self.params.blockSignals(False)

    def parameter_changed(self, item):
        if self.loading or self.current is None: return
        row = item.row(); name = self.params.item(row, 0).text(); p = self.current.config['params'][name]
        try:
            if item.column() == 4: p['vary'] = item.checkState() == Qt.CheckState.Checked
            elif item.column() == 5: p['expr'] = item.text().strip()
            elif item.column() in (1, 2, 3):
                key = {1: 'value', 2: 'min', 3: 'max'}[item.column()]
                text = item.text().strip()
                value = None if not text and key != 'value' else float(text)
                if value is not None and not np.isfinite(value): raise ValueError('Use a finite value or leave bounds blank.')
                p[key] = value
            self.invalidate()
        except Exception as exc:
            self.error(exc); self.populate_params()

    def show_current(self):
        if self.current is None: return
        s = self.current
        self.update_charge_controls()
        if s.result is not None:
            self.canvas.display(s.result, s.title); self.populate_summary(s.result)
            self.log.setPlainText(s.result['report'])
            self.fit_status.setText(f"{'Converged' if s.result['success'] else 'Not converged'} · {s.result['nfev']} evaluations ")
        else:
            self.summary.setRowCount(0); self.log.clear()
            try:
                x, y = region_arrays(s)
                data = {'x': x, 'y': y, 'region': s.config['region']}
                if s.config['background'] == 'Linear':
                    slope = (y[-1] - y[0]) / (x[-1] - x[0])
                    pars = s.config['params']
                    slope = pars.get('bkg_slope', {}).get('value', slope)
                    intercept = pars.get('bkg_intercept', {}).get('value', y[0] - slope * x[0])
                    data['background'] = slope * x + intercept
                elif s.config['background'] != 'None':
                    data['background'] = background(x, y, s.config)
                self.canvas.display(data, s.title)
                self.fit_status.setText(f'Ready to fit · {len(x):,} points in selected range')
            except ValueError as exc:
                self.canvas.display({'message': str(exc)}, s.title)
                self.fit_status.setText(str(exc))

    def preview_model(self):
        if self.current is None: return
        try:
            s = self.current; model, pars = make_model(s); x, y = region_arrays(s)
            self.canvas.display(snapshot(model, pars, x, y, background(x, y, s.config), s.config), s.title + ' · Initial model')
        except Exception as exc: self.error(exc)

    def start_fit(self):
        if self.worker is not None: return
        if self.current is None: return self.error('Load a spectrum first.')
        try: make_model(self.current)
        except Exception as exc: return self.error(exc)
        self.fit_target = self.current
        self.worker = FitWorker(self.current, self)
        self.worker.progress.connect(self.live_update); self.worker.completed.connect(self.fit_done)
        self.worker.failed.connect(self.fit_failed); self.worker.finished.connect(self.worker_finished)
        self.set_busy(True); self.fit_status.setText('Optimizing…'); self.worker.start()

    def set_busy(self, busy):
        self.controls.setEnabled(not busy); self.params.setEnabled(not busy); self.fit_button.setEnabled(not busy)
        self.load_button.setEnabled(not busy); self.export_button.setEnabled(not busy); self.cancel_button.setEnabled(busy)
        for action in self.mutation_actions: action.setEnabled(not busy)
        self.progress.setRange(0, 0 if busy else 1); self.progress.setValue(0)
        self.update_charge_controls()

    def live_update(self, data):
        self.canvas.display(data, self.fit_target.title)
        self.fit_status.setText(f"Fitting · evaluation {data['iteration']} · RMSE {np.sqrt(np.mean(data['residual']**2)):.4g}")
        self.params.blockSignals(True)
        for row in range(self.params.rowCount()):
            name = self.params.item(row, 0).text()
            if name in data['params']:
                self.params.item(row, 1).setText(f"{data['params'][name]['value']:.9g}")
        self.params.blockSignals(False)

    def fit_done(self, data):
        s = self.fit_target; s.result = data
        for key in s.config['params']:
            if key in data['params']: s.config['params'][key] = copy.deepcopy(data['params'][key])
        s.result['config'] = copy.deepcopy(s.config)
        self.populate_params(); self.show_current()
        self.statusBar().showMessage(data['message'])

    def fit_failed(self, message):
        self.populate_params(); self.show_current(); self.log.appendPlainText(message)
        self.statusBar().showMessage(message)
        if 'cancelled' not in message.lower(): self.error(message)

    def worker_finished(self):
        worker = self.worker; self.worker = None; self.set_busy(False)
        if worker: worker.deleteLater()

    def cancel_fit(self):
        if self.worker:
            self.worker.requestInterruption(); self.fit_status.setText('Stopping…')

    def populate_summary(self, r):
        from scipy.integrate import trapezoid
        self.summary.setRowCount(0)
        for peak in r['config']['peaks']:
            prefix = peak['prefix']; p = r['params']; row = self.summary.rowCount(); self.summary.insertRow(row)
            values = [peak['label'], p[prefix+'center']['value'], p[prefix+'height']['value'],
                      p[prefix+'amplitude']['value'], p[prefix+'fwhm']['value'], trapezoid(r['peaks'][prefix], r['x'])]
            for col, value in enumerate(values):
                self.summary.setItem(row, col, QTableWidgetItem(value if isinstance(value, str) else f'{value:.7g}'))

    def export_current(self):
        if not self.current or self.current.result is None: return self.error('Fit the selected spectrum first.')
        path, _ = QFileDialog.getSaveFileName(self, 'Save fitted spectrum and peak summary', self.safe_name(self.current) + '.csv', 'CSV (*.csv)')
        if path:
            try:
                export_result(self.current, path); self.statusBar().showMessage('Saved spectrum CSV, peak summary CSV, and reusable parameter JSON.')
            except Exception as exc: self.error(exc)

    @staticmethod
    def safe_name(s):
        import re
        return re.sub(r'[^\w.-]+', '_', Path(s.source).stem + '_' + s.sheet)

    def export_all(self):
        spectra = [s for file in self.files.values() for s in file.values() if s.result is not None]
        if not spectra: return self.error('There are no fitted spectra to save.')
        folder = QFileDialog.getExistingDirectory(self, 'Save all fitted spectra')
        if not folder: return
        try:
            for s in spectra:
                # Never silently overwrite files from different sources with matching basenames.
                stem = self.safe_name(s); path = Path(folder) / (stem + '.csv'); n = 2
                while path.exists() or path.with_name(path.stem + '_peaks.csv').exists() or path.with_name(path.stem + '_parameters.json').exists():
                    path = Path(folder) / f'{stem}_{n}.csv'; n += 1
                export_result(s, path)
            self.statusBar().showMessage(f'Saved {len(spectra)} fitted spectra and summaries.')
        except Exception as exc: self.error(exc)

    def save_params(self):
        if not self.current: return
        path, _ = QFileDialog.getSaveFileName(self, 'Save reusable parameters', 'parameters.json', 'JSON (*.json)')
        if path:
            try: save_parameters(self.current, path)
            except Exception as exc: self.error(exc)

    def load_params(self):
        if not self.current: return self.error('Load the target spectrum first.')
        path, _ = QFileDialog.getOpenFileName(self, 'Apply parameters to this spectrum', '', 'JSON (*.json)')
        if path:
            try:
                cfg = read_parameters(path)
                candidate = copy.deepcopy(self.current); candidate.config = cfg
                make_model(candidate)
                candidate.result = None
                self.assign_recorded_shift(candidate)
                self.current.config = candidate.config; self.current.result = None; self.restore()
                self.statusBar().showMessage('Parameters applied. Charge shift follows the explicitly recorded session reference.')
            except Exception as exc: self.error(exc)

    def charge_correction(self):
        self.charge_box.show()
        self.update_charge_controls()

    def fit_reference(self):
        if self.current is None: return self.error('Load a file and select its reference sheet first.')
        if not self.current.config['peaks']:
            try:
                add_peak(self.current, self.peak_kind.currentText(), 'Reference peak')
                self.populate_peaks(); self.populate_params()
            except Exception as exc: return self.error(exc)
        self.start_fit()

    def assign_recorded_shift(self, spectrum):
        shift = self.charge_record['shift_eV'] if self.charge_record else 0.
        apply_charge_shift(spectrum, shift, self.charge_record)

    def record_charge_correction(self):
        self.charge_box.show()
        if self.current is None: return self.error('Load and fit a reference spectrum first.')
        try:
            record = charge_reference(self.current, self.reference_peak.currentData(), self.reference_energy.value())
            apply_charge_shift(self.current, record['shift_eV'], record)
            self.charge_record = record
            self.restore()
            self.statusBar().showMessage(f"Recorded charge shift {record['shift_eV']:+.6f} eV · automatically applied on file/sheet selection")
        except Exception as exc: self.error(exc)

    def update_charge_controls(self):
        s = self.current
        selected = self.reference_peak.currentData()
        self.reference_peak.blockSignals(True); self.reference_peak.clear()
        if s:
            for p in s.config['peaks']:
                self.reference_peak.addItem(p['label'], p['prefix'])
        index = self.reference_peak.findData(selected)
        if index >= 0: self.reference_peak.setCurrentIndex(index)
        self.reference_peak.blockSignals(False)
        valid = bool(s and s.result is not None and s.result.get('success'))
        self.charge_apply_button.setEnabled(valid and self.worker is None)
        self.reference_fit_button.setEnabled(s is not None and self.worker is None)
        self.shift.setValue(s.config['shift'] if s else 0.)
        if self.charge_record:
            r = self.charge_record
            self.charge_status.setText(f"Recorded Δ {r['shift_eV']:+.6f} eV · automatic")
            self.record_info.setText(f"Recorded: {Path(r['source']).name} / {r['sheet']} / {r['label']}\n"
                                     f"Raw fitted center: {r['raw_center_eV']:.6f} eV\n"
                                     f"Reference: {r['reference_energy_eV']:.6f} eV\n"
                                     f"Charge shift: {r['shift_eV']:+.6f} eV")
        else:
            self.charge_status.setText('Charge correction off')
            self.record_info.setText('No reference recorded. Fitting alone does not enable correction.')

    def clear_charge_correction(self):
        for spectra in self.files.values():
            for spectrum in spectra.values():
                apply_charge_shift(spectrum, 0., None)
        self.charge_record = None
        if self.current: self.restore()
        else: self.update_charge_controls()
        self.statusBar().showMessage('Charge correction cleared. All loaded spectra use their original energy axes.')

    def view_charge_record(self):
        if self.charge_record is None: return self.error('No charge reference has been recorded. Use Apply Charge Correction after fitting.')
        import json
        dialog = QDialog(self); dialog.setWindowTitle('Recorded charge reference'); dialog.resize(760, 650)
        layout = QVBoxLayout(dialog); text = QPlainTextEdit(); text.setReadOnly(True)
        text.setPlainText(json.dumps(self.charge_record, indent=2)); layout.addWidget(text)
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda: self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show()

    def open_matrix(self):
        dialog = MatrixDialog(self); self.dialogs.append(dialog)
        dialog.finished.connect(lambda: self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show()

    def save_figure(self):
        path, selected = QFileDialog.getSaveFileName(self, 'Save current figure (300 DPI)', 'spectrum.png', 'PNG (*.png);;PDF (*.pdf);;SVG (*.svg);;TIFF (*.tiff)')
        if path:
            try:
                if not Path(path).suffix: path += '.' + selected.split('*.')[1].split(')')[0]
                self.canvas.figure.savefig(path, dpi=300)
            except Exception as exc: self.error(exc)

    def open_demo(self):
        key = 'Demo FACTS.xlsx'
        if key in self.files:
            self.file_combo.setCurrentIndex(self.file_combo.findData(key)); return
        from lmfit.lineshapes import pvoigt
        rng = np.random.default_rng(12); spectra = []
        for sheet, center in [('C 1s', 284.8), ('Br 3d', 68.5)]:
            x = np.linspace(center - 4, center + 7, 420)
            y = 100 + 3 * (x - x[0]) + pvoigt(x, 2000, center, .45, .35) + pvoigt(x, 1000, center + 1.8, .55, .5)
            y += rng.normal(0, 8, len(x))
            s = Spectrum(key, sheet, x, y)
            s.config['background'] = 'Linear'
            add_peak(s, label='Main component'); add_peak(s, label='Secondary component')
            s.config['params']['p1_center']['value'] = center - .2
            s.config['params']['p2_center']['value'] = center + 2.1
            spectra.append(s)
        self.register(key, spectra)

    def help(self):
        QMessageBox.information(self, 'XPS Studio workflow',
            '1. File → Load data. FACTS defaults to skiprows=1; set 0 if the headers are on the first row.\n'
            '2. Choose a file and sheet. Each spectrum retains independent settings and results.\n'
            '3. Select a shifted-energy region, background and peak components. Edit values, bounds, Vary or expressions.\n'
            'Energy limits update the plot while typing; fitting uses only this range. Background starts at None and its controls appear on selection.\n'
            'Charge Correction → Reference fitting opens the reference controls. Fit any sheet, select its peak and reference energy, then press Apply Charge Correction. '
            'Only this explicit action enables the recorded shift for subsequent file/sheet selections. Clear correction restores raw energy.\n'
            '4. Fit spectrum. Live curves and parameter values update; Stop cancels without replacing the previous fit.\n'
            '5. Save fitted CSV exports the spectrum, _peaks.csv summary and _parameters.json.\n'
            '6. Plot → Matrix plot loads exported spectrum CSVs, with editable titles, labels, colors and figure settings.\n\n'
            'Amplitude = full analytical peak area. Height = maximum above background. Region area is numerically integrated.\n'
            'Gaussian sigma is standard deviation; Lorentzian sigma is HWHM; pseudo-Voigt sigma is HWHM and fraction is Lorentzian fraction. '
            'Voigt has independent sigma and gamma. FWHM and height are derived.\n\n'
            'Shirley uses energy-weighted integration. Tougaard uses a finite-window two-parameter loss kernel; choose B/C and the fit window for your data. '
            'These are not the index-based background approximations in the original script.')

    def closeEvent(self, event):
        if self.worker is not None:
            self.cancel_fit(); self.statusBar().showMessage('Stopping fit. Close the window again once it has stopped.'); event.ignore()
        else:
            event.accept()


def configure_app(app):
    # Bundle-accessible font also renders correctly in headless tests and on fresh PCs.
    from matplotlib import get_data_path
    font_dir = Path(get_data_path()) / 'fonts' / 'ttf'
    for name in ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'):
        QFontDatabase.addApplicationFont(str(font_dir / name))
    app.setApplicationName('XPS Studio'); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    app.setApplicationVersion(VERSION)
    app.setFont(QFont('DejaVu Sans', 9))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    configure_app(app)
    window = MainWindow(); window.show()
    if '--demo' in sys.argv: window.open_demo()
    sys.exit(app.exec())
