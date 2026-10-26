"""Editable post-fit quantification workspace."""
import copy
import json
from pathlib import Path
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QTabWidget, QWidget, QComboBox, QFileDialog,
    QAbstractItemView, QPlainTextEdit, QSplitter, QInputDialog)
from .post_analysis import (load_records, from_parameters, identity, quantify, doublets,
                            save_session, read_session)

FIELDS = ['included', 'sample', 'element', 'transition', 'rsf', 'atomic_weight',
          'label', 'center_eV', 'area_full', 'source', 'sheet', 'peak', 'status']
HEADERS = ['Use', 'Sample group', 'Element', 'Core level', 'RSF', 'Atomic weight',
           'Peak label', 'Center (eV)', 'Full area', 'Source file', 'Sheet', 'Peak ID', 'Input status']
EDITABLE = {'sample', 'element', 'transition', 'rsf', 'atomic_weight', 'label'}


class PostAnalysisDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('XPS Studio · Post Analysis'); self.resize(1400, 850)
        self.records = []; self.pairs = []; self.last_error = ''; self.loading = False
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        for title, callback in [('Load saved fits…', self.load_files), ('Use current fitted spectra', self.use_current),
                                ('Open analysis…', self.open_analysis), ('Save analysis…', self.save_analysis),
                                ('Export results CSV…', self.export_results)]:
            button = QPushButton(title); button.clicked.connect(callback); bar.addWidget(button)
        layout.addLayout(bar)
        note = QLabel('Atomic % = 100 × (area / RSF) / Σ(area / RSF), normalized separately for each sample group.\n'
                      'Areas are full fitted amplitudes; include both components when using a whole-doublet RSF. '
                      'Cs 3d = 7.04, Pb 4f = 9.14, Br 3d = 2.91 are editable values from your example.\n'
                      'Assign elements and matching RSFs for other core levels. Legacy parameter-only files are unverified and unchecked; '
                      'include them only if you know they contain fitted values. Blank atomic weights leave weight % unavailable.')
        note.setWordWrap(True); layout.addWidget(note)
        self.tabs = QTabWidget(); layout.addWidget(self.tabs)
        inputs = QWidget(); iv = QVBoxLayout(inputs)
        self.table = QTableWidget(0, len(FIELDS)); self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemChanged.connect(self.edit_row); self.table.itemSelectionChanged.connect(self.show_details)
        splitter = QSplitter(Qt.Orientation.Vertical); splitter.addWidget(self.table)
        self.details = QPlainTextEdit(); self.details.setReadOnly(True)
        self.details.setPlaceholderText('Select a peak to inspect its saved fitting parameters and provenance.')
        splitter.addWidget(self.details); splitter.setSizes([480, 150]); iv.addWidget(splitter)
        actions = QHBoxLayout()
        for title, callback in [('Include selected', lambda: self.include_selected(True)),
                                ('Exclude selected', lambda: self.include_selected(False)),
                                ('Set sample for selected…', self.set_sample), ('Remove selected', self.remove_selected)]:
            button = QPushButton(title); button.clicked.connect(callback); actions.addWidget(button)
        iv.addLayout(actions); self.tabs.addTab(inputs, 'Peaks and sensitivity factors')
        self.composition = QTableWidget(); self.composition.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.composition, 'Atomic and weight %')
        pairs_page = QWidget(); pv = QVBoxLayout(pairs_page); row = QHBoxLayout()
        self.spectrum = QComboBox(); self.peak_a = QComboBox(); self.peak_b = QComboBox()
        self.spectrum.setMinimumWidth(360)
        row.addWidget(self.spectrum, 2); row.addWidget(self.peak_a, 1); row.addWidget(self.peak_b, 1)
        add = QPushButton('Add doublet pair'); add.clicked.connect(self.add_pair); row.addWidget(add)
        pv.addLayout(row)
        pv.addWidget(QLabel('Separation = |center A − center B|. Two-peak spectra are paired automatically; choose pairs explicitly for larger fits.'))
        self.pair_table = QTableWidget(); self.pair_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pair_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        pv.addWidget(self.pair_table)
        remove = QPushButton('Remove selected pairs'); remove.clicked.connect(self.remove_pairs); pv.addWidget(remove)
        export_pairs = QPushButton('Export doublets CSV…'); export_pairs.clicked.connect(self.export_doublets); pv.addWidget(export_pairs)
        self.tabs.addTab(pairs_page, 'Doublet separation')
        self.spectrum.currentIndexChanged.connect(self.fill_pair_peaks)
        self.status = QLabel('Load saved fitting parameters, spectrum CSVs, peak summaries, or plot projects.'); self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def error(self, exc):
        self.last_error = str(exc); self.status.setStyleSheet('color:#b64040'); self.status.setText(str(exc))

    def selected_rows(self, table=None):
        target = table if table is not None else self.table
        return sorted({index.row() for index in target.selectionModel().selectedRows()})

    def refresh(self):
        self.loading = True
        self.table.setRowCount(len(self.records))
        for row, data in enumerate(self.records):
            for col, key in enumerate(FIELDS):
                item = QTableWidgetItem('' if key == 'included' else str(data[key]))
                if key == 'included':
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
                    item.setCheckState(Qt.CheckState.Checked if data[key] else Qt.CheckState.Unchecked)
                elif key not in EDITABLE: item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, col, item)
        self.table.resizeColumnsToContents(); self.table.setColumnWidth(1, 210); self.table.setColumnWidth(9, 240)
        current = self.spectrum.currentData(); self.spectrum.clear()
        for source, sheet in dict.fromkeys((r['source'], r['sheet']) for r in self.records):
            self.spectrum.addItem(f'{Path(source).name} · {sheet}', (source, sheet))
            self.spectrum.setItemData(self.spectrum.count()-1, source, Qt.ItemDataRole.ToolTipRole)
        if current:
            index = self.spectrum.findData(current)
            if index >= 0: self.spectrum.setCurrentIndex(index)
        self.fill_pair_peaks(); self.loading = False; self.recalculate()

    def edit_row(self, item):
        if self.loading: return
        key = FIELDS[item.column()]
        self.records[item.row()][key] = item.checkState() == Qt.CheckState.Checked if key == 'included' else item.text().strip()
        if key == 'label': self.fill_pair_peaks()
        self.recalculate()

    def show_details(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.records): self.details.setPlainText(json.dumps(self.records[row], indent=2, ensure_ascii=False))

    @staticmethod
    def fill_result(table, rows):
        table.clear(); table.setRowCount(len(rows)); keys = list(rows[0]) if rows else []
        table.setColumnCount(len(keys)); table.setHorizontalHeaderLabels(keys)
        for i, row in enumerate(rows):
            for j, key in enumerate(keys):
                value = row[key]; text = '' if value is None else f'{value:.8g}' if isinstance(value, float) else str(value)
                table.setItem(i, j, QTableWidgetItem(text))
        table.resizeColumnsToContents()

    def recalculate(self):
        self.fill_result(self.pair_table, doublets(self.records, self.pairs))
        try:
            values = quantify(self.records); self.fill_result(self.composition, values)
            self.last_error = ''; self.status.setStyleSheet('color:#087f82')
            self.status.setText(f'{len(self.records)} peaks · {sum(r["included"] for r in self.records)} included · '
                                f'{len(values)} element results · {len(self.pairs)} doublet pairs. Results update as you edit.')
        except Exception as exc:
            self.fill_result(self.composition, []); self.error(exc)

    def append_records(self, records):
        existing = {identity(r) for r in self.records}
        for r in records:
            if identity(r) not in existing:
                self.records.append(copy.deepcopy(r)); existing.add(identity(r))
        grouped = {}
        for r in self.records: grouped.setdefault((r['source'], r['sheet']), []).append(r)
        for rows in grouped.values():
            if len(rows) == 2:
                pair = {'a': list(identity(rows[0])), 'b': list(identity(rows[1]))}
                if not any({tuple(p['a']), tuple(p['b'])} == {tuple(pair['a']), tuple(pair['b'])} for p in self.pairs): self.pairs.append(pair)
        self.refresh()

    def load_paths(self, paths):
        pending = []
        for path in paths: pending.extend(load_records(path))
        self.append_records(pending)

    def load_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Load saved fitting output', '', 'Fitting output (*.csv *.json *.xpsplot)')
        if paths:
            try: self.load_paths(paths)
            except Exception as exc: self.error(exc)

    def use_current(self):
        owner = self.parent(); records = []
        for spectra in getattr(owner, 'files', {}).values():
            for s in spectra.values():
                if s.result is not None:
                    fit = dict(s.result, source=s.source, sheet=s.sheet)
                    records.extend(from_parameters({'fit': fit}, s.source))
        if records: self.append_records(records)
        else: self.error('No current fitted spectra. Load saved output or fit spectra first.')

    def include_selected(self, include):
        for row in self.selected_rows(): self.records[row]['included'] = include
        self.refresh()

    def set_sample(self):
        rows = self.selected_rows()
        if not rows: self.error('Select the peaks belonging to the same sample first.'); return
        name, accepted = QInputDialog.getText(self, 'Sample group', 'Group selected peaks under this sample:', text=self.records[rows[0]]['sample'])
        if accepted and name.strip():
            for row in rows: self.records[row]['sample'] = name.strip()
            self.refresh()

    def remove_selected(self):
        for row in reversed(self.selected_rows()): self.records.pop(row)
        keys = {identity(r) for r in self.records}
        self.pairs = [p for p in self.pairs if tuple(p['a']) in keys and tuple(p['b']) in keys]
        self.refresh()

    def fill_pair_peaks(self):
        self.peak_a.clear(); self.peak_b.clear()
        selected = self.spectrum.currentData()
        for r in self.records:
            if (r['source'], r['sheet']) == selected:
                for combo in (self.peak_a, self.peak_b): combo.addItem(f"{r['label']} ({r['center_eV']:.5g} eV)", identity(r))
        if self.peak_b.count() > 1: self.peak_b.setCurrentIndex(1)

    def add_pair(self):
        a, b = self.peak_a.currentData(), self.peak_b.currentData()
        if not a or not b or a == b: self.error('Choose two different fitted peaks.'); return
        if any({tuple(p['a']), tuple(p['b'])} == {tuple(a), tuple(b)} for p in self.pairs): return
        self.pairs.append({'a': list(a), 'b': list(b)}); self.recalculate()

    def remove_pairs(self):
        for row in reversed(self.selected_rows(self.pair_table)): self.pairs.pop(row)
        self.recalculate()

    def save_analysis(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save editable post analysis', 'post-analysis.xpspost', 'Post analysis (*.xpspost)')
        if path:
            try: save_session(Path(path).with_suffix('.xpspost'), self.records, self.pairs)
            except Exception as exc: self.error(exc)

    def open_analysis(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open post analysis', '', 'Post analysis (*.xpspost)')
        if path:
            try:
                records, pairs = read_session(path)
                self.records, self.pairs = records, pairs; self.refresh()
            except Exception as exc: self.error(exc)

    def export_to(self, path):
        values = quantify(self.records); pairs = doublets(self.records, self.pairs)
        if not values and not pairs: raise ValueError('No calculated results to export.')
        path = Path(path).with_suffix('.csv')
        pd.DataFrame(values, columns=list(values[0]) if values else ['sample', 'element', 'atomic_percent', 'weight_percent']).to_csv(path, index=False)
        pd.DataFrame(pairs, columns=list(pairs[0]) if pairs else ['source', 'sheet', 'peak_a', 'peak_b', 'separation_eV']).to_csv(path.with_name(path.stem+'_doublets.csv'), index=False)
        pd.DataFrame([{k: v for k, v in r.items() if k != 'details'} for r in self.records]).to_csv(path.with_name(path.stem+'_inputs.csv'), index=False)

    def export_results(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export composition, doublets and input provenance', 'composition.csv', 'CSV (*.csv)')
        if path:
            try:
                self.export_to(path); self.status.setText('Saved composition CSV, _doublets.csv and _inputs.csv.')
            except Exception as exc: self.error(exc)

    def export_doublets(self):
        if not self.pairs: self.error('Add a doublet pair first.'); return
        path, _ = QFileDialog.getSaveFileName(self, 'Export doublet separations', 'doublets.csv', 'CSV (*.csv)')
        if path:
            try:
                pd.DataFrame(doublets(self.records, self.pairs)).to_csv(Path(path).with_suffix('.csv'), index=False)
                self.status.setText('Doublet CSV saved. RSFs are not required for energy separations.')
            except Exception as exc: self.error(exc)
