"""Live matrix composer, with plain-text/MathText labels and native Matplotlib options."""
from pathlib import Path
import copy
import json
import math
import numpy as np
import pandas as pd
import matplotlib as mpl
from matplotlib import colormaps, font_manager
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import is_color_like
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, NullLocator
from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QPlainTextEdit, QPushButton,
    QFileDialog, QMessageBox, QCheckBox, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QScrollArea, QTabWidget, QLabel, QAbstractItemView, QGroupBox, QColorDialog)
from .plotting import AspectPreview, gradient_fill, load_export, component_positions
from .plot_project import save_project, read_project


TICK_MODES = ['Ticks + labels', 'Ticks only', 'Labels only', 'Hidden']
ADVANCED_EXAMPLE = '''{
  "rcParams": {},
  "axes": {},
  "data": {},
  "fit": {},
  "background": {},
  "peaks": {},
  "legend": {}
}'''

PLOT_CONTROLS = '''rows columns width height dpi format transparent mode xlabel ylabel suptitle
hspace wspace sharex sharey xticks yticks tick_direction tick_length tick_width tick_rotation_x
tick_rotation_y minor xstep ystep reverse_x xscale yscale grid grid_alpha grid_style grid_color
font_family font title_size tick_size font_weight font_style text_mode math_font palette gradient
fill_alpha data_color fit_color bg_color figure_color axes_color marker marker_size linewidth
peak_width bg_width fit_style peak_style bg_style legend legend_loc legend_font legend_columns
legend_frame legend_alpha legend_title anchor_x anchor_y data_name fit_name bg_name'''.split()


class MatrixDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('XPS Studio · Live matrix composer')
        self.resize(1460, 950)
        self.datasets = []
        self.panel_options = []
        self.custom_fonts = {}
        self.plot_templates = []
        self.project_path = None
        self._loading = True
        self.render_count = 0
        self.last_error = ''
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(220)
        self.timer.timeout.connect(self.preview)
        layout = QHBoxLayout(self)
        splitter = QSplitter(); layout.addWidget(splitter)
        controls = QWidget(); left = QVBoxLayout(controls)
        add = QPushButton('+ Add fitted spectrum CSVs'); add.clicked.connect(self.add_files); left.addWidget(add)
        projects = QHBoxLayout()
        self.save_project_button = QPushButton('Save Plot Project…'); self.save_project_button.clicked.connect(self.save_plot_project)
        self.open_project_button = QPushButton('Open Plot Project…'); self.open_project_button.clicked.connect(self.open_plot_project)
        self.save_project_button.setToolTip('Save loaded spectra, fitted components and every plot setting in one editable .xpsplot file.')
        self.open_project_button.setToolTip('Restore an editable plot, including its data. Original CSV files are not required.')
        projects.addWidget(self.save_project_button); projects.addWidget(self.open_project_button); left.addLayout(projects)
        presets = QHBoxLayout()
        self.save_config_button = QPushButton('Save Plot Template…')
        self.save_config_button.clicked.connect(self.save_plot_configuration)
        self.load_config_button = QPushButton('Load Plot Template…')
        self.load_config_button.clicked.connect(self.load_plot_configuration)
        presets.addWidget(self.save_config_button); presets.addWidget(self.load_config_button); left.addLayout(presets)
        self.tabs = QTabWidget(); left.addWidget(self.tabs, 1)
        self.build_panels_tab()
        self.build_layout_tab()
        self.build_axes_tab()
        self.build_style_tab()
        self.build_legend_tab()
        self.build_advanced_tab()
        footer = QHBoxLayout()
        update = QPushButton('Refresh'); update.clicked.connect(self.preview); footer.addWidget(update)
        save = QPushButton('Save figure…'); save.setObjectName('primary'); save.clicked.connect(self.save); footer.addWidget(save)
        left.addLayout(footer)
        self.export_positions_button = QPushButton('Export all peak positions CSV…')
        self.export_positions_button.clicked.connect(self.export_peak_positions)
        self.export_positions_button.setToolTip('One row per deconvoluted peak, with its file, panel and fitted center. Also saved automatically with each figure.')
        left.addWidget(self.export_positions_button)
        splitter.addWidget(controls)
        view = QWidget(); right = QVBoxLayout(view)
        self.figure = Figure(figsize=(12, 8), layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        self.preview_host = AspectPreview(self.canvas)
        right.addWidget(self.toolbar); right.addWidget(self.preview_host, 1)
        self.status = QLabel('Add spectrum CSVs to begin. Changes update the plot automatically.')
        self.status.setWordWrap(True); self.status.setMinimumHeight(38); right.addWidget(self.status)
        splitter.addWidget(view); splitter.setSizes([480, 980])
        self._loading = False
        self.preview_host.installEventFilter(self)
        self.table.itemChanged.connect(self.schedule_preview)
        self.table.currentCellChanged.connect(self.select_panel)
        self.legend_table.itemChanged.connect(self.edit_legend)
        self.advanced.textChanged.connect(self.schedule_preview)
        for control in (self.data_name, self.fit_name, self.bg_name):
            control.textChanged.connect(self.select_panel)
        for control in (self.legend_loc, self.legend_font, self.legend_columns, self.legend_frame,
                        self.legend_alpha, self.legend_title, self.anchor_x, self.anchor_y):
            if isinstance(control, QComboBox): control.currentTextChanged.connect(self.select_panel)
            elif isinstance(control, QLineEdit): control.textChanged.connect(self.select_panel)
            elif isinstance(control, QCheckBox): control.toggled.connect(self.select_panel)
            else: control.valueChanged.connect(self.select_panel)
        self.preview()

    def tab(self, title):
        page = QWidget(); layout = QVBoxLayout(page)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return layout

    def spin(self, value, lo=0, hi=100, decimals=None):
        w = QSpinBox() if decimals is None else QDoubleSpinBox()
        w.setRange(lo, hi)
        if decimals is not None: w.setDecimals(decimals)
        w.setValue(value); w.valueChanged.connect(self.schedule_preview)
        return w

    def combo(self, choices, current=None):
        w = QComboBox(); w.addItems(choices)
        if current is not None: w.setCurrentText(current)
        w.currentTextChanged.connect(self.schedule_preview)
        return w

    def text(self, value='', placeholder=''):
        w = QLineEdit(value); w.setPlaceholderText(placeholder); w.textChanged.connect(self.schedule_preview)
        return w

    def check(self, label, checked=False):
        w = QCheckBox(label); w.setChecked(checked); w.toggled.connect(self.schedule_preview)
        return w

    @staticmethod
    def note(layout, text):
        label = QLabel(text); label.setWordWrap(True); label.setStyleSheet('color:#60768a; padding:4px;')
        layout.addWidget(label)

    def build_panels_tab(self):
        layout = self.tab('Panels')
        self.note(layout, 'Panels fill left to right, then top to bottom. Edit titles and axis labels directly. Select a panel to edit its ticks, limits and legend.')
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Title', 'X label', 'Y label', 'Labels'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(0, 140); self.table.setColumnWidth(1, 145); self.table.setColumnWidth(2, 145)
        self.table.setMinimumHeight(230)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        for text, callback in [('↑ Move up', lambda: self.move(-1)), ('↓ Move down', lambda: self.move(1)), ('Remove', self.remove)]:
            b = QPushButton(text); b.clicked.connect(callback); buttons.addWidget(b)
        layout.addLayout(buttons)
        replacements = QHBoxLayout()
        self.replace_selected_button = QPushButton('Replace selected CSV…'); self.replace_selected_button.clicked.connect(self.replace_selected_csv)
        self.replace_all_button = QPushButton('Replace all CSVs…'); self.replace_all_button.clicked.connect(self.replace_all_csvs)
        replacements.addWidget(self.replace_selected_button); replacements.addWidget(self.replace_all_button); layout.addLayout(replacements)
        self.note(layout, 'Replacement changes the spectrum data while preserving colors, legends, labels, normalization and other panel settings.')
        self.panel_heading = QLabel('Selected panel: none'); layout.addWidget(self.panel_heading)
        self.panel_zero_minimum = self.check('Normalize signal: subtract minimum (min = 0)')
        self.panel_zero_minimum.setToolTip('Subtract this spectrum’s minimum measured intensity from data, fit and background. Component heights and relative intensities are preserved; this does not scale to 0–1.')
        self.panel_zero_minimum.toggled.connect(self.panel_changed)
        layout.addWidget(self.panel_zero_minimum)
        self.note(layout, 'Applies to the selected panel and updates live. The minimum is taken over the loaded spectrum. Stored data and fitted peak positions remain unchanged.')
        form = QFormLayout()
        self.panel_xticks = self.combo(['Use global setting'] + TICK_MODES)
        self.panel_yticks = self.combo(['Use global setting'] + TICK_MODES)
        self.panel_legend = self.combo(['Use global setting', 'Show', 'Hide'])
        self.panel_limits = {key: self.text('', 'Auto / global') for key in ('xmin', 'xmax', 'ymin', 'ymax')}
        for label, control in [('X ticks', self.panel_xticks), ('Y ticks', self.panel_yticks),
                               ('Legend', self.panel_legend), ('X minimum', self.panel_limits['xmin']),
                               ('X maximum', self.panel_limits['xmax']), ('Y minimum', self.panel_limits['ymin']),
                               ('Y maximum', self.panel_limits['ymax'])]:
            form.addRow(label, control)
            if isinstance(control, QComboBox): control.currentTextChanged.connect(self.panel_changed)
            else: control.textChanged.connect(self.panel_changed)
        layout.addLayout(form)
        self.note(layout, 'Blank panel limits inherit the global limits. In Selected panels label mode, use the Labels checkboxes; leave X or Y text blank to show only the other label.')
        layout.addStretch()

    def build_layout_tab(self):
        layout = self.tab('Layout'); form = QFormLayout()
        self.rows = self.spin(0, 0, 12); self.rows.setSpecialValueText('Auto')
        self.columns = self.spin(3, 1, 12)
        self.width = self.spin(12, 2, 40, 2); self.height = self.spin(8, 2, 40, 2)
        self.dpi = self.spin(300, 72, 1200)
        self.format = self.combo(['png', 'pdf', 'svg', 'tiff', 'jpeg'])
        self.transparent = self.check('Transparent export')
        self.mode = self.combo(['Every panel', 'Outer axes', 'Shared figure labels', 'Selected panels'])
        self.xlabel = self.text('Binding energy (eV)'); self.ylabel = self.text('Intensity (counts/s)')
        self.suptitle = self.text('', 'Optional figure title')
        self.hspace = self.spin(.15, 0, 1, 2); self.wspace = self.spin(.08, 0, 1, 2)
        self.sharex = self.combo(['None', 'All', 'By column', 'By row'])
        self.sharey = self.combo(['None', 'All', 'By column', 'By row'])
        for label, w in [('Rows (0 = auto)', self.rows), ('Columns', self.columns), ('Width (inches)', self.width),
                         ('Height (inches)', self.height), ('Export DPI', self.dpi), ('Format', self.format),
                         ('', self.transparent), ('Label placement', self.mode), ('Global X label', self.xlabel),
                         ('Global Y label', self.ylabel), ('Figure title', self.suptitle), ('Row spacing', self.hspace),
                         ('Column spacing', self.wspace), ('Share X scale', self.sharex), ('Share Y scale', self.sharey)]:
            form.addRow(label, w)
        layout.addLayout(form)
        self.note(layout, 'Rows and columns define the exact grid. Unused cells remain blank. Increase capacity if the chosen grid is too small; spectra are never silently dropped. Global labels apply to every panel unless a panel has its own label text.')
        layout.addStretch()

    def build_axes_tab(self):
        layout = self.tab('Axes'); form = QFormLayout()
        self.xticks = self.combo(TICK_MODES); self.yticks = self.combo(TICK_MODES)
        self.tick_direction = self.combo(['out', 'in', 'inout'])
        self.tick_length = self.spin(3.5, 0, 20, 1); self.tick_width = self.spin(.8, 0, 5, 1)
        self.tick_rotation_x = self.spin(0, -180, 180); self.tick_rotation_y = self.spin(0, -180, 180)
        self.minor = self.check('Minor ticks')
        self.xstep = self.text('', 'Auto'); self.ystep = self.text('', 'Auto')
        self.reverse_x = self.check('Reverse X axis (XPS)', True)
        self.xscale = self.combo(['linear', 'log', 'symlog']); self.yscale = self.combo(['linear', 'log', 'symlog'])
        self.limits = {key: self.text('', 'Auto') for key in ('xmin', 'xmax', 'ymin', 'ymax')}
        self.grid = self.check('Show grid', True); self.grid_alpha = self.spin(.15, 0, 1, 2)
        self.grid_style = self.combo(['-', '--', ':', '-.'], ':'); self.grid_color = self.text('#a0adb8')
        self.spines = {name: self.check(name.capitalize() + ' spine', name in ('left', 'bottom'))
                       for name in ('left', 'bottom', 'right', 'top')}
        for label, w in [('X ticks / numbers', self.xticks), ('Y ticks / numbers', self.yticks),
                         ('Tick direction', self.tick_direction), ('Tick length', self.tick_length), ('Tick width', self.tick_width),
                         ('X number rotation', self.tick_rotation_x), ('Y number rotation', self.tick_rotation_y), ('', self.minor),
                         ('X tick interval', self.xstep), ('Y tick interval', self.ystep), ('', self.reverse_x),
                         ('X scale', self.xscale), ('Y scale', self.yscale), ('X minimum', self.limits['xmin']),
                         ('X maximum', self.limits['xmax']), ('Y minimum', self.limits['ymin']), ('Y maximum', self.limits['ymax']),
                         ('', self.grid), ('Grid opacity', self.grid_alpha), ('Grid style', self.grid_style), ('Grid color', self.grid_color)]:
            form.addRow(label, w)
        for w in self.spines.values(): form.addRow('', w)
        layout.addLayout(form); layout.addStretch()

    def build_style_tab(self):
        layout = self.tab('Style & fonts'); form = QFormLayout()
        self.style_file = self.combo([])
        self.style_file.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.style_file.setMinimumContentsLength(18)
        self.style_file.currentIndexChanged.connect(self.choose_legend_file)
        selection = QFormLayout(); selection.addRow('Edit colors for spectrum', self.style_file)
        layout.addLayout(selection)
        self.style_path = QLabel('No spectrum selected'); self.style_path.setWordWrap(True); layout.addWidget(self.style_path)
        self.note(layout, 'Choose a spectrum above. These colors affect only that panel and update live. Blank fields use the global defaults below.')
        self.spectrum_color_box = QWidget(); colors_form = QFormLayout(self.spectrum_color_box)
        self.spectrum_colors = {}
        for key, title in [('data', 'Data color'), ('fit', 'Fit color'), ('background', 'Background color'), ('palette', 'Peak colormaps')]:
            field = self.text('', 'Use global default'); self.spectrum_colors[key] = field
            field.textChanged.connect(self.spectrum_colors_changed)
            if key == 'palette': colors_form.addRow(title, field)
            else:
                row = QHBoxLayout(); row.addWidget(field)
                pick = QPushButton('Choose…'); pick.clicked.connect(lambda checked=False, key=key: self.pick_spectrum_color(key))
                row.addWidget(pick); colors_form.addRow(title, row)
        layout.addWidget(self.spectrum_color_box); self.spectrum_color_box.setEnabled(False)
        reset = QPushButton('Reset this spectrum’s colors to defaults'); reset.clicked.connect(self.reset_spectrum_colors)
        layout.addWidget(reset)
        self.note(layout, 'Global style and font defaults (apply to all panels unless overridden above)')
        families = sorted({f.name for f in font_manager.fontManager.ttflist}, key=str.casefold)
        self.font_family = self.combo(families, 'DejaVu Sans')
        self.font_family.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.font_family.setMinimumContentsLength(12)
        browse = QPushButton('Browse font file…'); browse.clicked.connect(self.browse_font)
        self.font = self.spin(12, 6, 60)
        self.title_size = self.spin(0, 0, 80); self.title_size.setSpecialValueText('Auto')
        self.tick_size = self.spin(0, 0, 60); self.tick_size.setSpecialValueText('Auto')
        self.font_weight = self.combo(['normal', 'bold', 'light', 'semibold'])
        self.font_style = self.combo(['normal', 'italic', 'oblique'])
        self.text_mode = self.combo(['Plain text + math ($...$)', 'Plain text only'])
        self.math_font = self.combo(['dejavusans', 'dejavuserif', 'stix', 'stixsans', 'cm'], 'stix')
        self.palette = self.text('Blues, Oranges, Reds, YlGn, PuBu')
        self.gradient = self.check('Gradient peak fills', True)
        self.fill_alpha = self.spin(.65, 0, 1, 2)
        self.data_color = self.text('#26374b'); self.fit_color = self.text('#d34a51'); self.bg_color = self.text('#84929e')
        self.figure_color = self.text('#ffffff'); self.axes_color = self.text('#ffffff')
        self.marker = self.combo(['o', '.', 's', '^', 'v', 'D', '+', 'x', '*', 'None'])
        self.marker_size = self.spin(10, 0, 500, 1)
        self.linewidth = self.spin(1.8, 0, 10, 1); self.peak_width = self.spin(1.4, 0, 10, 1)
        self.bg_width = self.spin(1.4, 0, 10, 1)
        self.fit_style = self.combo(['-', '--', ':', '-.', 'None'])
        self.peak_style = self.combo(['-', '--', ':', '-.', 'None'], '--')
        self.bg_style = self.combo(['-', '--', ':', '-.', 'None'], ':')
        for label, w in [('Font family', self.font_family), ('', browse), ('Label font size', self.font),
                         ('Title font size', self.title_size), ('Tick font size', self.tick_size),
                         ('Font weight', self.font_weight), ('Font style', self.font_style),
                         ('Label input', self.text_mode), ('Equation font', self.math_font), ('Peak colormaps', self.palette),
                         ('', self.gradient), ('Fill opacity', self.fill_alpha), ('Data color', self.data_color),
                         ('Fit color', self.fit_color), ('Background color', self.bg_color), ('Figure color', self.figure_color),
                         ('Panel color', self.axes_color), ('Data marker', self.marker), ('Marker area (pt²)', self.marker_size),
                         ('Fit width', self.linewidth), ('Peak width', self.peak_width), ('Background width', self.bg_width),
                         ('Fit line style', self.fit_style), ('Peak line style', self.peak_style), ('Background style', self.bg_style)]:
            form.addRow(label, w)
        layout.addLayout(form)
        self.note(layout, 'Type normal text, Unicode (α, Δ, ₁), or math enclosed in dollar signs. Examples: Binding energy $E_B$ (eV); $\\mathrm{Cs}\\,3d_{5/2}$; $\\Delta E = \\frac{a}{b}$. No LaTeX installation is needed for Matplotlib MathText. Browse accepts TTF, OTF and TTC font files.')
        layout.addStretch()

    def build_legend_tab(self):
        layout = self.tab('Legend'); form = QFormLayout()
        self.legend_file = self.combo([])
        self.legend_file.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.legend_file.setMinimumContentsLength(18)
        self.legend_file.currentIndexChanged.connect(self.choose_legend_file)
        choose = QFormLayout(); choose.addRow('Edit legend for file', self.legend_file); layout.addLayout(choose)
        self.legend_file_path = QLabel('No file selected'); self.legend_file_path.setWordWrap(True)
        layout.addWidget(self.legend_file_path)
        self.note(layout, 'Edits below affect only this loaded file. Switch files here to edit each legend independently. Names accept ordinary text and $math$.')
        self.legend_table = QTableWidget(0, 3)
        self.legend_table.setHorizontalHeaderLabels(['Curve', 'Legend name', 'Show'])
        self.legend_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.legend_table.setMinimumHeight(180); layout.addWidget(self.legend_table)
        self.file_legend_visibility = self.combo(['Use global setting', 'Show', 'Hide'])
        self.file_legend_visibility.currentTextChanged.connect(self.file_legend_changed)
        visibility = QFormLayout(); visibility.addRow('This file’s legend', self.file_legend_visibility); layout.addLayout(visibility)
        self.custom_legend = self.check('Custom legend layout for this file')
        self.custom_legend.toggled.connect(self.file_legend_changed); layout.addWidget(self.custom_legend)
        self.file_legend_box = QWidget(); custom_form = QFormLayout(self.file_legend_box)
        self.file_legend_controls = {
            'loc': self.combo(['best', 'upper right', 'upper left', 'lower left', 'lower right', 'right',
                               'center left', 'center right', 'lower center', 'upper center', 'center']),
            'font_size': self.spin(0, 0, 60), 'columns': self.spin(1, 1, 12),
            'frame': self.check('Show frame'), 'alpha': self.spin(.8, 0, 1, 2),
            'title': self.text('', 'Optional title'), 'anchor_x': self.text('', 'Automatic'),
            'anchor_y': self.text('', 'Automatic')}
        self.file_legend_controls['font_size'].setSpecialValueText('Auto')
        for key, label in [('loc', 'Position'), ('font_size', 'Font size'), ('columns', 'Columns'),
                           ('frame', ''), ('alpha', 'Frame opacity'), ('title', 'Title'),
                           ('anchor_x', 'Anchor X'), ('anchor_y', 'Anchor Y')]:
            control = self.file_legend_controls[key]; custom_form.addRow(label, control)
            if isinstance(control, QComboBox): control.currentTextChanged.connect(self.file_legend_changed)
            elif isinstance(control, QLineEdit): control.textChanged.connect(self.file_legend_changed)
            elif isinstance(control, QCheckBox): control.toggled.connect(self.file_legend_changed)
            else: control.valueChanged.connect(self.file_legend_changed)
        layout.addWidget(self.file_legend_box); self.file_legend_box.setEnabled(False)
        reset = QPushButton('Reset this file’s legend to global defaults'); reset.clicked.connect(self.reset_file_legend); layout.addWidget(reset)
        apply = QPushButton('Copy these legend names to all panels'); apply.clicked.connect(self.copy_legend_names); layout.addWidget(apply)
        global_box = QGroupBox('Global legend defaults'); global_box.setLayout(form)
        self.legend = self.check('Show legends', True)
        self.legend_loc = self.combo(['best', 'upper right', 'upper left', 'lower left', 'lower right',
                                     'right', 'center left', 'center right', 'lower center', 'upper center', 'center'])
        self.legend_font = self.spin(0, 0, 60); self.legend_font.setSpecialValueText('Auto')
        self.legend_columns = self.spin(1, 1, 12)
        self.legend_frame = self.check('Legend frame')
        self.legend_alpha = self.spin(.8, 0, 1, 2)
        self.legend_title = self.text('', 'Optional legend title')
        self.anchor_x = self.text('', 'Automatic'); self.anchor_y = self.text('', 'Automatic')
        self.data_name = self.text('Data'); self.fit_name = self.text('Fit'); self.bg_name = self.text('Background')
        for label, w in [('', self.legend), ('Location', self.legend_loc), ('Font size', self.legend_font),
                         ('Columns', self.legend_columns), ('', self.legend_frame), ('Frame opacity', self.legend_alpha),
                         ('Title', self.legend_title), ('Anchor X (axes units)', self.anchor_x), ('Anchor Y', self.anchor_y),
                         ('Default data name', self.data_name), ('Default fit name', self.fit_name), ('Default background name', self.bg_name)]:
            form.addRow(label, w)
        layout.addWidget(global_box)
        layout.addStretch()

    def build_advanced_tab(self):
        layout = self.tab('Advanced')
        self.note(layout, 'Additional Matplotlib options as JSON. rcParams supplies plotting defaults; axes/artist properties override their corresponding standard controls. axes accepts Axes.set properties; data/fit/background accept artist properties; peaks maps component prefixes to artist properties; legend accepts Axes.legend keywords.')
        self.advanced = QPlainTextEdit(ADVANCED_EXAMPLE); self.advanced.setMinimumHeight(320)
        layout.addWidget(self.advanced)
        self.note(layout, 'Example: {"rcParams":{"axes.labelpad":8}, "fit":{"alpha":0.8}, "peaks":{"p1_":{"color":"purple"}}, "legend":{"labelspacing":0.3}}.\n\nNative Matplotlib validation reports unsupported names or values below the preview. Full external TeX can be enabled with text.usetex in rcParams if a working TeX installation is available. Built-in MathText handles scientific labels without it.')
        reset = QPushButton('Reset advanced options'); reset.clicked.connect(lambda: self.advanced.setPlainText(ADVANCED_EXAMPLE)); layout.addWidget(reset)
        layout.addStretch()

    def schedule_preview(self, *args):
        if not self._loading: self.timer.start()

    def eventFilter(self, watched, event):
        if watched is self.preview_host and event.type() == QEvent.Type.Resize:
            self.schedule_preview()
        return super().eventFilter(watched, event)

    def sync_options(self):
        while len(self.panel_options) < len(self.datasets):
            self.panel_options.append({'xticks': 'Use global setting', 'yticks': 'Use global setting',
                                       'legend': 'Use global setting', 'limits': {}, 'names': {}, 'visible': {}})

    def append_dataset(self, path, data):
        previous = self._loading; self._loading = True
        self.datasets.append((str(path), data)); self.sync_options()
        row = self.table.rowCount(); self.table.insertRow(row)
        for col, text in enumerate([Path(path).stem, '', '']):
            item = QTableWidgetItem(text)
            item.setToolTip('Blank uses the global axis label' if col else str(path))
            self.table.setItem(row, col, item)
        item = QTableWidgetItem('X + Y'); item.setCheckState(Qt.CheckState.Checked); self.table.setItem(row, 3, item)
        if row < len(self.plot_templates): self.apply_panel_template(row, self.plot_templates[row])
        self._loading = previous
        self.table.selectRow(row)
        self.select_panel()
        self.schedule_preview()

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Select exported spectra', '', 'CSV (*.csv)')
        errors = []
        for path in paths:
            try: self.append_dataset(path, load_export(path))
            except Exception as exc: errors.append(str(exc))
        if errors: QMessageBox.warning(self, 'Some files could not be loaded', '\n'.join(errors))
        self.preview()

    def remove(self):
        row = self.table.currentRow()
        if row >= 0:
            self.sync_options(); self._loading = True
            self.datasets.pop(row); self.panel_options.pop(row); self.table.removeRow(row)
            self._loading = False; self.select_panel(); self.preview()

    def move(self, delta):
        row = self.table.currentRow(); target = row + delta
        if row < 0 or not 0 <= target < len(self.datasets): return
        self.sync_options(); self._loading = True
        self.datasets[row], self.datasets[target] = self.datasets[target], self.datasets[row]
        self.panel_options[row], self.panel_options[target] = self.panel_options[target], self.panel_options[row]
        for col in range(4):
            a, b = self.table.takeItem(row, col), self.table.takeItem(target, col)
            self.table.setItem(row, col, b); self.table.setItem(target, col, a)
        self.table.selectRow(target); self._loading = False; self.select_panel(); self.preview()

    def default_names(self, data):
        names = {'data': self.data_name.text(), 'fit': self.fit_name.text(), 'background': self.bg_name.text()}
        definitions = {p['prefix']: p['label'] for p in data.get('config', {}).get('peaks', [])}
        names.update({key: definitions.get(key, key.rstrip('_')) for key in data['peaks']})
        return names

    def select_panel(self, *args):
        if self._loading: return
        self.sync_options(); row = self.table.currentRow(); self._loading = True
        self.legend_table.setRowCount(0)
        self.legend_file.clear()
        self.style_file.clear()
        for i, (path, _) in enumerate(self.datasets):
            self.legend_file.addItem(f'{i + 1}. {Path(path).name} — {Path(path).parent}', i)
            self.legend_file.setItemData(i, str(path), Qt.ItemDataRole.ToolTipRole)
            self.style_file.addItem(f'{i + 1}. {Path(path).name} — {Path(path).parent}', i)
            self.style_file.setItemData(i, str(path), Qt.ItemDataRole.ToolTipRole)
        self.legend_file.setCurrentIndex(row)
        self.style_file.setCurrentIndex(row)
        if 0 <= row < len(self.datasets):
            options = self.panel_options[row]
            self.style_path.setText(str(self.datasets[row][0]))
            for key, field in self.spectrum_colors.items(): field.setText(options.get('colors', {}).get(key, ''))
            self.panel_heading.setText(f'Selected panel: {row + 1} · {self.table.item(row, 0).text()}')
            self.panel_xticks.setCurrentText(options['xticks']); self.panel_yticks.setCurrentText(options['yticks'])
            self.panel_legend.setCurrentText(options['legend'])
            self.panel_zero_minimum.setChecked(options.get('zero_minimum', False))
            for key, w in self.panel_limits.items(): w.setText(options['limits'].get(key, ''))
            for key, name in self.default_names(self.datasets[row][1]).items():
                r = self.legend_table.rowCount(); self.legend_table.insertRow(r)
                item = QTableWidgetItem(key); item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.legend_table.setItem(r, 0, item)
                self.legend_table.setItem(r, 1, QTableWidgetItem(options['names'].get(key, name)))
                visible = QTableWidgetItem(); visible.setCheckState(Qt.CheckState.Checked if options['visible'].get(key, True) else Qt.CheckState.Unchecked)
                self.legend_table.setItem(r, 2, visible)
            self.legend_file_path.setText(str(self.datasets[row][0]))
            self.file_legend_visibility.setCurrentText(options['legend'])
            custom = options.get('legend_layout')
            self.custom_legend.setChecked(custom is not None)
            values = custom if custom is not None else self.global_legend_values()
            for key, control in self.file_legend_controls.items():
                if isinstance(control, QComboBox): control.setCurrentText(values[key])
                elif isinstance(control, QLineEdit): control.setText(values[key])
                elif isinstance(control, QCheckBox): control.setChecked(values[key])
                else: control.setValue(values[key])
            self.file_legend_box.setEnabled(custom is not None)
        else:
            self.style_path.setText('No spectrum selected')
            for field in self.spectrum_colors.values(): field.clear()
            self.panel_heading.setText('Selected panel: none'); self.legend_file_path.setText('No file selected')
            self.file_legend_box.setEnabled(False)
        selected = 0 <= row < len(self.datasets)
        self.spectrum_color_box.setEnabled(selected)
        self.panel_zero_minimum.setEnabled(selected)
        self.custom_legend.setEnabled(selected); self.file_legend_visibility.setEnabled(selected)
        self._loading = False

    def panel_changed(self, *args):
        row = self.table.currentRow()
        if self._loading or not 0 <= row < len(self.datasets): return
        self.sync_options(); o = self.panel_options[row]
        o['zero_minimum'] = self.panel_zero_minimum.isChecked()
        o.update(xticks=self.panel_xticks.currentText(), yticks=self.panel_yticks.currentText(), legend=self.panel_legend.currentText())
        o['limits'] = {key: w.text() for key, w in self.panel_limits.items()}
        self.file_legend_visibility.blockSignals(True)
        self.file_legend_visibility.setCurrentText(o['legend'])
        self.file_legend_visibility.blockSignals(False)
        self.schedule_preview()

    def choose_legend_file(self, index):
        if self._loading or not 0 <= index < len(self.datasets): return
        self.table.selectRow(index)
        self.select_panel()

    def spectrum_colors_changed(self, *args):
        row = self.table.currentRow()
        if self._loading or not 0 <= row < len(self.datasets): return
        self.sync_options()
        self.panel_options[row]['colors'] = {key: field.text().strip() for key, field in self.spectrum_colors.items() if field.text().strip()}
        self.schedule_preview()

    def pick_spectrum_color(self, key):
        color = QColorDialog.getColor(parent=self, title=f'Choose {key} color for this spectrum')
        if color.isValid(): self.spectrum_colors[key].setText(color.name())

    def reset_spectrum_colors(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.datasets): return
        self.panel_options[row].pop('colors', None); self.select_panel(); self.schedule_preview()

    def global_legend_values(self):
        return {'loc': self.legend_loc.currentText(), 'font_size': self.legend_font.value(),
                'columns': self.legend_columns.value(), 'frame': self.legend_frame.isChecked(),
                'alpha': self.legend_alpha.value(), 'title': self.legend_title.text(),
                'anchor_x': self.anchor_x.text(), 'anchor_y': self.anchor_y.text()}

    def file_legend_changed(self, *args):
        row = self.table.currentRow()
        if self._loading or not 0 <= row < len(self.datasets): return
        self.sync_options(); options = self.panel_options[row]
        options['legend'] = self.file_legend_visibility.currentText()
        self.panel_legend.blockSignals(True); self.panel_legend.setCurrentText(options['legend']); self.panel_legend.blockSignals(False)
        enabled = self.custom_legend.isChecked(); self.file_legend_box.setEnabled(enabled)
        if enabled:
            values = {}
            for key, control in self.file_legend_controls.items():
                if isinstance(control, QComboBox): value = control.currentText()
                elif isinstance(control, QLineEdit): value = control.text()
                elif isinstance(control, QCheckBox): value = control.isChecked()
                else: value = control.value()
                values[key] = value
            options['legend_layout'] = values
        else: options.pop('legend_layout', None)
        self.schedule_preview()

    def reset_file_legend(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.datasets): return
        options = self.panel_options[row]
        options.update(names={}, visible={}, legend='Use global setting')
        options.pop('legend_layout', None)
        self.select_panel(); self.schedule_preview()

    def edit_legend(self, item):
        panel = self.table.currentRow()
        if self._loading or not 0 <= panel < len(self.datasets): return
        self.sync_options(); key = self.legend_table.item(item.row(), 0).text()
        if item.column() == 1: self.panel_options[panel]['names'][key] = item.text()
        elif item.column() == 2:
            self.panel_options[panel]['visible'][key] = item.checkState() == Qt.CheckState.Checked
        self.schedule_preview()

    def copy_legend_names(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.datasets): return
        self.sync_options(); names = self.default_names(self.datasets[row][1]) | self.panel_options[row]['names']
        for options in self.panel_options:
            options['names'] = copy.deepcopy(names); options['visible'] = copy.deepcopy(self.panel_options[row]['visible'])
        self.schedule_preview()

    def import_font(self, path):
        path = str(Path(path).resolve())
        font_manager.fontManager.addfont(path)
        family = font_manager.FontProperties(fname=path).get_name()
        QFontDatabase.addApplicationFont(path)
        self.custom_fonts[family] = path
        if self.font_family.findText(family) < 0: self.font_family.addItem(family)
        self.font_family.setCurrentText(family); self.schedule_preview()
        return family

    def browse_font(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a font file', '', 'Fonts (*.ttf *.otf *.ttc)')
        if path:
            try: self.import_font(path)
            except Exception as exc: self.show_error(f'Font could not be loaded: {exc}')

    def font_properties(self, size, weight=None):
        family = self.font_family.currentText()
        return font_manager.FontProperties(family=family, fname=self.custom_fonts.get(family),
            size=size, weight=weight or self.font_weight.currentText(), style=self.font_style.currentText())

    @staticmethod
    def optional_number(value, label):
        if not value.strip(): return None
        try: number = float(value)
        except ValueError: raise ValueError(f'{label}: enter a number or leave blank for automatic.') from None
        if not np.isfinite(number): raise ValueError(f'{label} must be finite.')
        return number

    def read_advanced(self):
        options = json.loads(self.advanced.toPlainText() or '{}')
        allowed = {'rcParams', 'axes', 'data', 'fit', 'background', 'peaks', 'legend'}
        if not isinstance(options, dict) or set(options) - allowed:
            raise ValueError('Advanced settings must be an object with rcParams, axes, data, fit, background, peaks or legend keys.')
        if any(not isinstance(v, dict) for v in options.values()):
            raise ValueError('Each advanced settings section must be a JSON object.')
        # Backend changes cannot be scoped safely by rc_context in a live Qt application.
        if any(k in options.get('rcParams', {}) for k in ('backend', 'backend_fallback', 'interactive')):
            raise ValueError('Backend and interactive-mode changes are managed by this desktop app.')
        if set(options.get('axes', {})) & {'figure', 'axes', 'transform'}:
            raise ValueError('Figure ownership and transforms are managed by the matrix composer.')
        return options

    def configure_ticks(self, ax, axis, mode, step):
        locator = ax.xaxis if axis == 'x' else ax.yaxis
        marks = mode in ('Ticks + labels', 'Ticks only')
        labels = mode in ('Ticks + labels', 'Labels only')
        kwargs = {'bottom': marks, 'top': False, 'labelbottom': labels, 'labeltop': False} if axis == 'x' else {
            'left': marks, 'right': False, 'labelleft': labels, 'labelright': False}
        ax.tick_params(axis=axis, which='both', direction=self.tick_direction.currentText(),
                       length=self.tick_length.value(), width=self.tick_width.value(),
                       labelrotation=self.tick_rotation_x.value() if axis == 'x' else self.tick_rotation_y.value(), **kwargs)
        if step is not None:
            if step <= 0: raise ValueError('Tick intervals must be positive.')
            if locator.get_scale() != 'linear': raise ValueError('Explicit tick intervals require a linear axis.')
            lo, hi = ax.get_xlim() if axis == 'x' else ax.get_ylim()
            if abs(hi - lo) / step > 1000: raise ValueError('Tick interval would create more than 1,000 ticks; choose a larger interval.')
            locator.set_major_locator(MultipleLocator(step))
        if self.minor.isChecked() and locator.get_scale() == 'linear': locator.set_minor_locator(AutoMinorLocator())
        elif not self.minor.isChecked(): locator.set_minor_locator(NullLocator())
        locator.get_offset_text().set_visible(labels)
        prop = self.font_properties(self.tick_size.value() or max(6, self.font.value() - 1))
        for text in locator.get_ticklabels(which='both') + [locator.get_offset_text()]: text.set_fontproperties(prop)

    def build_figure(self, width, height, dpi=100):
        self.sync_options()
        columns = self.columns.value()
        rows = self.rows.value() or max(1, math.ceil(len(self.datasets) / columns))
        if rows * columns < len(self.datasets):
            raise ValueError(f'{rows} rows × {columns} columns has {rows * columns} cells for {len(self.datasets)} spectra. Increase rows/columns or select Auto rows.')
        maps = [v.strip() for v in self.palette.text().split(',') if v.strip()]
        if not maps or any(m not in colormaps for m in maps): raise ValueError('Enter valid peak colormaps, such as Blues, Oranges, Reds.')
        for w in (self.data_color, self.fit_color, self.bg_color, self.figure_color, self.axes_color, self.grid_color):
            if not is_color_like(w.text()): raise ValueError(f'Invalid color: {w.text()!r}. Use a name or #hex color.')
        advanced = self.read_advanced()
        rc = {'font.family': self.font_family.currentText(), 'mathtext.fontset': self.math_font.currentText(),
              'text.parse_math': self.text_mode.currentIndex() == 0}
        rc.update(advanced.get('rcParams', {}))
        # Validate rcParams before modifying any preview state.
        with mpl.rc_context(rc):
            figure = Figure(figsize=(width, height), dpi=dpi, layout='constrained', facecolor=self.figure_color.text())
            figure.get_layout_engine().set(hspace=self.hspace.value(), wspace=self.wspace.value())
            if not self.datasets:
                ax = figure.add_subplot(); ax.axis('off')
                ax.text(.5, .55, 'Build your spectral matrix', ha='center', fontsize=21, color='#183b56')
                ax.text(.5, .44, 'Add fitted spectrum CSVs, then edit any setting to see it live.', ha='center', fontsize=10, color='#60768a')
                return figure, rc
            share = {'None': False, 'All': 'all', 'By column': 'col', 'By row': 'row'}
            axes = figure.subplots(rows, columns, squeeze=False, sharex=share[self.sharex.currentText()], sharey=share[self.sharey.currentText()])
            font = self.font.value()
            for i, ax in enumerate(axes.flat):
                if i >= len(self.datasets): ax.set_visible(False); continue
                data = self.datasets[i][1]; options = self.panel_options[i]
                colors = options.get('colors', {})
                for key in ('data', 'fit', 'background'):
                    if key in colors and not is_color_like(colors[key]): raise ValueError(f'Panel {i+1}: invalid {key} color {colors[key]!r}.')
                panel_maps = [v.strip() for v in colors['palette'].split(',') if v.strip()] if 'palette' in colors else maps
                if not panel_maps or any(m not in colormaps for m in panel_maps): raise ValueError(f'Panel {i+1}: enter valid peak colormaps.')
                x, y, bg = data['x'], data['y'], data['background']
                offset = float(np.min(y)) if options.get('zero_minimum', False) else 0.
                y = np.asarray(y) - offset
                bg = np.asarray(bg) - offset
                total = np.asarray(data['total']) - offset
                names = self.default_names(data) | options['names']
                def label(key):
                    return names.get(key, key) if options['visible'].get(key, True) and names.get(key, '') else '_nolegend_'
                artists = {}
                marker = self.marker.currentText()
                artists['data'] = ax.scatter(x, y, s=self.marker_size.value(), marker=marker if marker != 'None' else '',
                    color=self.data_color.text(), label=label('data'), zorder=5)
                artists['background'], = ax.plot(x, bg, linestyle=self.bg_style.currentText(), color=self.bg_color.text(),
                    lw=self.bg_width.value(), label=label('background'))
                for j, (key, peak) in enumerate(data['peaks'].items()):
                    cmap = colormaps[panel_maps[j % len(panel_maps)]]; top = peak + bg
                    if self.gradient.isChecked(): gradient_fill(ax, x, bg, top, cmap, self.fill_alpha.value())
                    artists[key], = ax.plot(x, top, linestyle=self.peak_style.currentText(), color=cmap(.8),
                                            lw=self.peak_width.value(), label=label(key), zorder=3)
                artists['fit'], = ax.plot(x, total, linestyle=self.fit_style.currentText(), color=self.fit_color.text(),
                                         lw=self.linewidth.value(), label=label('fit'), zorder=4)
                for key in ('data', 'fit', 'background'):
                    artists[key].set(**advanced.get(key, {}))
                    if key in colors: artists[key].set_color(colors[key])
                for key, props in advanced.get('peaks', {}).items():
                    if key in artists and key in data['peaks']: artists[key].set(**props)
                ax.set_facecolor(self.axes_color.text())
                ax.set_xscale(self.xscale.currentText()); ax.set_yscale(self.yscale.currentText())
                limits = {}
                for key in self.limits:
                    value = options['limits'].get(key, '').strip() or self.limits[key].text()
                    limits[key] = self.optional_number(value, key)
                region = data.get('config', {}).get('region', [min(x), max(x)])
                xlo = region[0] if limits['xmin'] is None else limits['xmin']
                xhi = region[1] if limits['xmax'] is None else limits['xmax']
                all_y = np.concatenate([y, total, bg]); margin = max(float(np.ptp(all_y)) * .12, 1.)
                ylo = float(min(all_y) - margin) if limits['ymin'] is None else limits['ymin']
                yhi = float(max(all_y) + margin) if limits['ymax'] is None else limits['ymax']
                if self.yscale.currentText() == 'log' and limits['ymin'] is None:
                    positive = all_y[all_y > 0]
                    if not len(positive): raise ValueError(f'Panel {i+1} has no positive intensity for a log scale.')
                    ylo = float(positive.min()) * .8
                if xlo >= xhi or ylo >= yhi: raise ValueError(f'Panel {i+1}: axis minimum must be smaller than maximum.')
                if self.xscale.currentText() == 'log' and xlo <= 0: raise ValueError('Log X limits must be positive.')
                if self.yscale.currentText() == 'log' and ylo <= 0: raise ValueError('Log Y limits must be positive.')
                ax.set_xlim((xhi, xlo) if self.reverse_x.isChecked() else (xlo, xhi)); ax.set_ylim(ylo, yhi)
                mode = self.mode.currentIndex(); row, col = divmod(i, columns)
                show = self.table.item(i, 3).checkState() == Qt.CheckState.Checked
                xtext, ytext = self.table.item(i, 1).text(), self.table.item(i, 2).text()
                if mode != 3: xtext, ytext = xtext or self.xlabel.text(), ytext or self.ylabel.text()
                xl = xtext if mode == 0 or mode == 3 and show or mode == 1 and i + columns >= len(self.datasets) else ''
                yl = ytext if mode == 0 or mode == 3 and show or mode == 1 and col == 0 else ''
                ax.set_xlabel(xl, fontproperties=self.font_properties(font)); ax.set_ylabel(yl, fontproperties=self.font_properties(font))
                ax.set_title(self.table.item(i, 0).text(), loc='left', fontproperties=self.font_properties(self.title_size.value() or font + 1, 'bold'))
                for name, control in self.spines.items(): ax.spines[name].set_visible(control.isChecked())
                ax.grid(self.grid.isChecked())
                if self.grid.isChecked(): ax.grid(alpha=self.grid_alpha.value(), linestyle=self.grid_style.currentText(), color=self.grid_color.text())
                ax.set(**advanced.get('axes', {}))
                for axis, global_control, step_control in [('x', self.xticks, self.xstep), ('y', self.yticks, self.ystep)]:
                    tick_mode = options[axis + 'ticks']
                    if tick_mode == 'Use global setting': tick_mode = global_control.currentText()
                    self.configure_ticks(ax, axis, tick_mode, self.optional_number(step_control.text(), axis + ' tick interval'))
                legend = self.legend.isChecked() if options['legend'] == 'Use global setting' else options['legend'] == 'Show'
                if legend:
                    details = options.get('legend_layout', self.global_legend_values())
                    kwargs = dict(loc=details['loc'], prop=self.font_properties(details['font_size'] or max(6, font - 3)),
                                  ncols=details['columns'], frameon=details['frame'],
                                  framealpha=details['alpha'], title=details['title'])
                    anchor = [self.optional_number(details['anchor_x'], 'Legend anchor X'), self.optional_number(details['anchor_y'], 'Legend anchor Y')]
                    if (anchor[0] is None) != (anchor[1] is None): raise ValueError('Specify both legend anchor X and Y, or leave both blank.')
                    if anchor[0] is not None: kwargs['bbox_to_anchor'] = tuple(anchor)
                    elif 'legend_layout' in options: kwargs['bbox_to_anchor'] = None
                    kwargs = (advanced.get('legend', {}) | kwargs) if 'legend_layout' in options else (kwargs | advanced.get('legend', {}))
                    if ax.get_legend_handles_labels()[0]:
                        leg = ax.legend(**kwargs)
                        leg.get_title().set_fontproperties(self.font_properties(details['font_size'] or max(6, font - 3)))
            if self.mode.currentIndex() == 2:
                figure.supxlabel(self.xlabel.text(), fontproperties=self.font_properties(font))
                figure.supylabel(self.ylabel.text(), fontproperties=self.font_properties(font))
            if self.suptitle.text(): figure.suptitle(self.suptitle.text(), fontproperties=self.font_properties(self.title_size.value() or font + 3, 'bold'))
            # Validate math text, font files and artist properties before replacing the last valid preview.
            FigureCanvasAgg(figure).draw()
            return figure, rc

    def render(self):
        self.timer.stop()
        self.preview_host.ratio = self.width.value() / self.height.value(); self.preview_host.fit_canvas()
        # Use the actual export dimensions, with scaled DPI, so text and layout match the export.
        dpi = max(25., self.canvas.width() / self.width.value())
        figure, rc = self.build_figure(self.width.value(), self.height.value(), dpi)
        self.figure = figure; self.canvas.figure = figure; figure.set_canvas(self.canvas)
        self.toolbar.update(); self.render_count += 1
        return rc

    def show_error(self, message):
        self.last_error = str(message)
        self.status.setStyleSheet('color:#a65012;')
        self.status.setText('Preview unchanged · ' + self.last_error)

    def preview(self):
        try:
            rc = self.render()
            with mpl.rc_context(rc): self.canvas.draw()
            self.last_error = ''; self.status.setStyleSheet('color:#087f82;')
            rows = self.rows.value() or max(1, math.ceil(len(self.datasets) / self.columns.value()))
            self.status.setText(f'Live preview · {rows} rows × {self.columns.value()} columns · {len(self.datasets)} spectra · {self.width.value():g} × {self.height.value():g} in')
        except Exception as exc: self.show_error(exc)

    def save(self):
        if not self.datasets: return
        fmt = self.format.currentText()
        path, _ = QFileDialog.getSaveFileName(self, 'Save matrix figure', f'xps_matrix.{fmt}', f'{fmt.upper()} (*.{fmt})')
        if path:
            try:
                self.timer.stop()
                figure, rc = self.build_figure(self.width.value(), self.height.value(), 100)
                positions = self.peak_positions_frame()
                output = Path(path).with_suffix('.' + fmt)
                with mpl.rc_context(rc):
                    figure.savefig(str(output), format=fmt, dpi=self.dpi.value(), transparent=self.transparent.isChecked())
                csv_path = output.with_name(output.stem + '_peak_positions.csv')
                try:
                    positions.to_csv(csv_path, index=False, encoding='utf-8-sig')
                except Exception as exc:
                    self.show_error(f'Figure saved to {output}, but peak-position CSV could not be saved: {exc}')
                    return
                self.last_error = ''; self.status.setStyleSheet('color:#087f82;')
                estimates = int((positions['position_source'] == 'sampled_component_maximum').sum())
                suffix = f' · {estimates} sampled estimates (flagged in CSV)' if estimates else ''
                self.status.setText(f'Saved {output.name} + {csv_path.name} · {len(positions)} deconvoluted peaks' + suffix)
            except Exception as exc: self.show_error('Export failed: ' + str(exc))

    def peak_positions_frame(self):
        if not self.datasets: raise ValueError('Load fitted spectrum CSVs into the plot first.')
        columns = self.columns.value()
        rows = self.rows.value() or math.ceil(len(self.datasets) / columns)
        if rows * columns < len(self.datasets): raise ValueError('Increase the matrix rows/columns to include all loaded spectra before exporting peak positions.')
        self.sync_options(); records = []
        for index, (path, data) in enumerate(self.datasets):
            names = self.default_names(data) | self.panel_options[index]['names']
            for peak in component_positions(data):
                prefix = peak['peak_id']; original = peak.pop('original_source')
                records.append({'file_name': Path(path).name, 'file_path': str(Path(path).resolve()),
                                'original_file_name': Path(original).name if original else '', 'original_file_path': original,
                                'panel_number': index + 1, 'matrix_row': index // columns + 1,
                                'matrix_column': index % columns + 1, 'panel_title': self.table.item(index, 0).text(),
                                **peak, 'legend_label': names.get(prefix, peak['peak_label']),
                                'legend_entry_enabled': self.panel_options[index]['visible'].get(prefix, True)})
        return pd.DataFrame(records, columns=['file_name', 'file_path', 'original_file_name', 'original_file_path',
            'sheet', 'panel_number', 'matrix_row', 'matrix_column', 'panel_title', 'peak_id', 'peak_label',
            'legend_label', 'legend_entry_enabled', 'peak_position_eV', 'position_source', 'position_note',
            'center_stderr_eV', 'model', 'energy_shift_eV'])

    def export_peak_positions(self):
        try:
            frame = self.peak_positions_frame()
            if frame.empty: raise ValueError('The loaded spectra contain no deconvoluted component columns to export.')
        except Exception as exc:
            self.show_error(str(exc)); return
        path, _ = QFileDialog.getSaveFileName(self, 'Export every deconvoluted peak in the matrix', 'matrix_peak_positions.csv', 'CSV (*.csv)')
        if path:
            try:
                output = Path(path).with_suffix('.csv')
                frame.to_csv(output, index=False, encoding='utf-8-sig')
                self.last_error = ''; self.status.setStyleSheet('color:#087f82;')
                estimates = int((frame['position_source'] == 'sampled_component_maximum').sum())
                suffix = f' · {estimates} sampled estimates (flagged in CSV)' if estimates else ''
                self.status.setText(f'Saved {len(frame)} peak positions from {len(self.datasets)} panels to {output.name}' + suffix)
            except Exception as exc: self.show_error('Peak positions not exported: ' + str(exc))

    def closeEvent(self, event):
        self.timer.stop(); super().closeEvent(event)

    def configuration_controls(self):
        controls = {name: getattr(self, name) for name in PLOT_CONTROLS}
        controls.update({f'limits.{key}': widget for key, widget in self.limits.items()})
        controls.update({f'spines.{key}': widget for key, widget in self.spines.items()})
        return controls

    @staticmethod
    def control_value(control):
        if isinstance(control, QComboBox): return control.currentText()
        if isinstance(control, QCheckBox): return control.isChecked()
        if isinstance(control, QLineEdit): return control.text()
        return control.value()

    @staticmethod
    def set_control_value(control, value):
        if isinstance(control, QComboBox): control.setCurrentText(value)
        elif isinstance(control, QCheckBox): control.setChecked(value)
        elif isinstance(control, QLineEdit): control.setText(value)
        else: control.setValue(value)

    def plot_configuration(self, validate_advanced=True):
        self.sync_options()
        panels = copy.deepcopy(self.plot_templates)
        for row, (path, _) in enumerate(self.datasets):
            title = self.table.item(row, 0).text()
            panel = {'title': None if title == Path(path).stem else title,
                     'xlabel': self.table.item(row, 1).text(), 'ylabel': self.table.item(row, 2).text(),
                     'show_labels': self.table.item(row, 3).checkState() == Qt.CheckState.Checked,
                     'options': copy.deepcopy(self.panel_options[row])}
            if row < len(panels): panels[row] = panel
            else: panels.append(panel)
        family = self.font_family.currentText()
        return {'schema': 'xps-studio-plot-1', 'panel_mapping': 'plot_order',
                'controls': {key: self.control_value(control) for key, control in self.configuration_controls().items()},
                'advanced': self.read_advanced() if validate_advanced else {}, 'panels': panels,
                'custom_font': {'family': family, 'path': self.custom_fonts[family]} if family in self.custom_fonts else None}

    def apply_panel_template(self, row, template):
        self.panel_options[row] = copy.deepcopy(template['options'])
        title = template['title'] if template['title'] is not None else Path(self.datasets[row][0]).stem
        for col, value in enumerate([title, template['xlabel'], template['ylabel']]):
            self.table.item(row, col).setText(value)
        self.table.item(row, 3).setCheckState(Qt.CheckState.Checked if template['show_labels'] else Qt.CheckState.Unchecked)

    def validate_control_value(self, control, value, name, custom_family=None):
        if isinstance(control, QComboBox):
            if not isinstance(value, str) or (control.findText(value) < 0 and not (name == 'font_family' and value == custom_family)):
                raise ValueError(f'Invalid saved selection for {name}: {value!r}.')
        elif isinstance(control, QCheckBox):
            if type(value) is not bool: raise ValueError(f'{name} must be true or false.')
        elif isinstance(control, QLineEdit):
            if not isinstance(value, str): raise ValueError(f'{name} must contain text.')
        elif type(value) not in (int, float) or not math.isfinite(value) or not control.minimum() <= value <= control.maximum():
            raise ValueError(f'{name} is outside the supported range.')
        elif isinstance(control, QSpinBox) and type(value) is not int:
            raise ValueError(f'{name} must be an integer.')

    def validate_configuration(self, payload):
        if not isinstance(payload, dict) or payload.get('schema') != 'xps-studio-plot-1':
            raise ValueError('Choose an XPS Studio plot configuration JSON file, not a fitting-parameter file.')
        controls = self.configuration_controls(); saved = payload.get('controls')
        if not isinstance(saved, dict) or set(saved) != set(controls):
            raise ValueError('The plot configuration is incomplete or uses unsupported settings.')
        custom = payload.get('custom_font')
        if custom is not None:
            if not isinstance(custom, dict) or not all(isinstance(custom.get(k), str) for k in ('family', 'path')):
                raise ValueError('Invalid custom-font reference.')
            if not Path(custom['path']).is_file():
                raise ValueError(f"Custom font file is missing: {custom['path']}. Restore it to this location before loading the configuration.")
        for name, control in controls.items():
            self.validate_control_value(control, saved[name], name, custom['family'] if custom else None)
        for name in ('limits.xmin', 'limits.xmax', 'limits.ymin', 'limits.ymax', 'xstep', 'ystep', 'anchor_x', 'anchor_y'):
            value = self.optional_number(saved[name], name)
            if name in ('xstep', 'ystep') and value is not None and value <= 0: raise ValueError('Tick intervals must be positive.')
        panels = payload.get('panels')
        if not isinstance(panels, list) or len(panels) > 144: raise ValueError('Invalid saved panel list (maximum 144 panels).')
        if not isinstance(payload.get('advanced'), dict): raise ValueError('Invalid advanced plot settings.')
        for panel in panels:
            if not isinstance(panel, dict) or 'title' not in panel or panel.get('title') is not None and not isinstance(panel['title'], str):
                raise ValueError('Invalid panel title.')
            if not all(isinstance(panel.get(key), str) for key in ('xlabel', 'ylabel')) or type(panel.get('show_labels')) is not bool:
                raise ValueError('Invalid panel labels.')
            options = panel.get('options')
            if not isinstance(options, dict): raise ValueError('Invalid panel options.')
            colors = options.get('colors', {})
            if not isinstance(colors, dict) or set(colors) - {'data', 'fit', 'background', 'palette'} or any(not isinstance(value, str) for value in colors.values()):
                raise ValueError('Invalid per-spectrum color settings.')
            for key, value in colors.items():
                if key == 'palette':
                    maps = [v.strip() for v in value.split(',') if v.strip()]
                    if not maps or any(m not in colormaps for m in maps): raise ValueError('Invalid per-spectrum peak colormaps.')
                elif not is_color_like(value): raise ValueError(f'Invalid per-spectrum {key} color.')
            if type(options.get('zero_minimum', False)) is not bool:
                raise ValueError('Panel minimum normalization must be true or false.')
            for name in ('xticks', 'yticks'):
                if options.get(name) not in ['Use global setting'] + TICK_MODES: raise ValueError('Invalid panel tick mode.')
            if options.get('legend') not in ('Use global setting', 'Show', 'Hide'): raise ValueError('Invalid panel legend mode.')
            for key, value_type in [('names', str), ('visible', bool), ('limits', str)]:
                values = options.get(key)
                if not isinstance(values, dict) or any(not isinstance(k, str) or type(v) is not value_type for k, v in values.items()):
                    raise ValueError(f'Invalid panel {key}.')
            if set(options['limits']) - set(self.limits): raise ValueError('Unknown panel axis limit.')
            for name, value in options['limits'].items(): self.optional_number(value, name)
            if 'legend_layout' in options:
                details = options['legend_layout']
                if not isinstance(details, dict) or set(details) != set(self.file_legend_controls):
                    raise ValueError('Invalid per-file legend layout.')
                for key, widget in self.file_legend_controls.items():
                    self.validate_control_value(widget, details[key], 'legend.' + key)

    def apply_configuration_values(self, payload):
        self._loading = True; self.timer.stop()
        try:
            custom = payload.get('custom_font')
            if custom:
                family = self.import_font(custom['path'])
                if family != custom['family']: raise ValueError('The custom font file no longer matches its recorded family.')
            for name, control in self.configuration_controls().items(): self.set_control_value(control, payload['controls'][name])
            self.advanced.setPlainText(json.dumps(payload['advanced'], indent=2, ensure_ascii=False))
            self.plot_templates = copy.deepcopy(payload['panels'])
            self.sync_options()
            for row in range(len(self.datasets)):
                if row < len(self.plot_templates): self.apply_panel_template(row, self.plot_templates[row])
        finally:
            self._loading = False
        self.select_panel()

    def save_configuration_to(self, path):
        # Validate the current plot so saved presets do not silently contain a broken setup.
        self.build_figure(self.width.value(), self.height.value(), 50)
        payload = self.plot_configuration()
        self.validate_configuration(payload)
        Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')

    def load_configuration_from(self, path):
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        self.validate_configuration(payload)
        previous = self.plot_configuration(validate_advanced=False)
        previous_advanced = self.advanced.toPlainText()
        # A plot may have fewer preset panels than the current file set: additional
        # panels retain their current settings, and inherit the new global style.
        try:
            self.apply_configuration_values(payload)
            self.build_figure(self.width.value(), self.height.value(), 50)
        except Exception:
            self.apply_configuration_values(previous)
            self._loading = True
            self.advanced.setPlainText(previous_advanced)
            self._loading = False
            raise
        self.preview()

    def save_plot_configuration(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save plot template (settings only)', 'xps_plot_template.json', 'Plot template (*.json)')
        if path:
            try:
                self.save_configuration_to(Path(path).with_suffix('.json'))
                self.last_error = ''; self.status.setStyleSheet('color:#087f82;')
                self.status.setText('Plot template saved (settings only). Load it and add or replace CSV files to reuse the style.')
            except Exception as exc: self.show_error('Configuration not saved: ' + str(exc))

    def load_plot_configuration(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Load plot template (settings only)', '', 'Plot template / legacy configuration (*.json)')
        if path:
            try:
                self.load_configuration_from(path)
                self.status.setText('Plot template loaded · add CSVs or use Panels → Replace selected/all CSVs. Settings follow panel order.')
            except Exception as exc: self.show_error('Configuration not loaded: ' + str(exc))

    def save_project_to(self, path):
        self.build_figure(self.width.value(), self.height.value(), 50)
        config = self.plot_configuration(); self.validate_configuration(config)
        save_project(path, config, self.datasets, self.table.currentRow(), self.tabs.currentIndex())
        self.project_path = str(path)

    def restore_project_workspace(self, config, datasets):
        self.timer.stop(); self._loading = True
        self.datasets = []; self.panel_options = []; self.plot_templates = []
        self.table.setRowCount(0)
        try:
            for path, data in datasets: self.append_dataset(path, data)
        finally:
            self._loading = False
        self.apply_configuration_values(config)

    def open_project_from(self, path):
        config, datasets, selected, tab = read_project(path)
        self.validate_configuration(config)
        previous = self.plot_configuration(validate_advanced=False)
        old_advanced = self.advanced.toPlainText()
        old_data = list(self.datasets); old_row = self.table.currentRow(); old_tab = self.tabs.currentIndex()
        try:
            self.restore_project_workspace(config, datasets)
            self.build_figure(self.width.value(), self.height.value(), 50)
        except Exception:
            self.restore_project_workspace(previous, old_data)
            self._loading = True; self.advanced.setPlainText(old_advanced); self._loading = False
            if old_row >= 0: self.table.selectRow(old_row)
            self.tabs.setCurrentIndex(old_tab)
            raise
        if datasets: self.table.selectRow(max(0, min(selected, len(datasets) - 1)))
        self.tabs.setCurrentIndex(max(0, min(tab, self.tabs.count() - 1)))
        self.select_panel(); self.project_path = str(path); self.preview()

    def save_plot_project(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Save editable plot project (data + settings)', self.project_path or 'xps_plot.xpsplot', 'XPS plot project (*.xpsplot)')
        if path:
            try:
                self.save_project_to(Path(path).with_suffix('.xpsplot'))
                self.last_error = ''; self.status.setStyleSheet('color:#087f82;')
                self.status.setText('Plot project saved with all loaded data and settings. Open it here to continue editing.')
            except Exception as exc: self.show_error('Project not saved: ' + str(exc))

    def open_plot_project(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open editable plot project', '', 'XPS plot project (*.xpsplot)')
        if path:
            try:
                self.open_project_from(path)
                self.status.setText('Plot project restored · data and settings are ready to edit and save again.')
            except Exception as exc: self.show_error('Project not opened: ' + str(exc))

    def replace_datasets(self, replacements):
        """Read all replacement files before changing any current data or settings."""
        if any(not 0 <= index < len(self.datasets) for index in replacements): raise ValueError('Choose a loaded panel to replace.')
        loaded = {index: (str(path), load_export(path)) for index, path in replacements.items()}
        config = self.plot_configuration(); old = list(self.datasets); updated = list(old)
        for index, value in loaded.items(): updated[index] = value
        row = self.table.currentRow()
        try:
            self.restore_project_workspace(config, updated)
            self.build_figure(self.width.value(), self.height.value(), 50)
        except Exception:
            self.restore_project_workspace(config, old)
            if row >= 0: self.table.selectRow(row)
            raise
        if row >= 0: self.table.selectRow(row)
        self.preview()

    def replace_selected_csv(self):
        row = self.table.currentRow()
        if row < 0: self.show_error('Select a panel to replace first.'); return
        path, _ = QFileDialog.getOpenFileName(self, 'Replace selected spectrum; keep plot settings', '', 'Fitted spectrum (*.csv)')
        if path:
            try: self.replace_datasets({row: path})
            except Exception as exc: self.show_error('Spectrum not replaced: ' + str(exc))

    def replace_all_csvs(self):
        if not self.datasets: self.add_files(); return
        paths, _ = QFileDialog.getOpenFileNames(self, f'Select {len(self.datasets)} replacement spectra in panel order', '', 'Fitted spectra (*.csv)')
        if paths:
            if len(paths) != len(self.datasets):
                self.show_error(f'Select exactly {len(self.datasets)} files to keep the current panel arrangement.'); return
            try: self.replace_datasets(dict(enumerate(paths)))
            except Exception as exc: self.show_error('Spectra not replaced: ' + str(exc))
