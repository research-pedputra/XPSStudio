# XPS Studio

A PySide6 desktop application adapted from your `labtools.myxps` fitting and gradient matrix-plot workflow. Uses NumPy, pandas, lmfit, SciPy and an embedded Matplotlib canvas. No external `labtools` installation is required.

## Run on Windows

Double-click **Launch XPS Studio.bat**. Dependencies are installed in this workspace's `.venv`.

On another computer, install Python 3.11 or newer, run **Setup XPS Studio.bat** once, then use the launcher. This is a Python desktop app, not a standalone packaged executable.

From PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
# Optional synthetic two-sheet demonstration:
.\.venv\Scripts\python.exe main.py --demo
```

## Workflow

1. **File → Load data** opens import settings, then lets you select multiple files.
   - **Data from FACTS** is the default for Excel and CSV: skip one introductory row and read the exact columns `Binding energy (eV)` and `Counts per second`, as in the supplied code. Set skipped rows to **0** when headers are on the first line.
   - Excel `.xlsx`, `.xlsm`, `.xls`: each valid sheet is available in the sheet dropdown. Non-spectrum sheets produce an explanatory message without discarding the valid sheets.
   - CSV has one table and therefore no sheets. Choose **Generic two columns** for other CSV or Excel layouts; the first two columns become energy and intensity.
   - `.dat`, `.data`, `.txt`: read the first two whitespace-, comma- or semicolon-separated columns. These bypass FACTS settings and load as a single spectrum. `#` comments are supported.
   - Numeric rows are sorted by energy; repeated energies are averaged; invalid or missing values are removed. At least five distinct points are required.
2. Choose a **file**, then its **sheet**. Full source paths distinguish matching basenames. Each spectrum retains its own region, peaks, parameters and completed result while the application is open.
3. Set energy bounds. The plot updates while you type, and fitting uses **only points inside that range**. Bounds refer to the displayed energy (corrected only after explicitly recording a reference). Background starts at **None**; choosing a type automatically previews it and reveals only its relevant controls. Add Gaussian, Lorentzian, pseudo-Voigt or Voigt components. Name each component and select its gradient colormap.
4. In **Parameters**, edit values, minimum/maximum bounds, Vary checkboxes and optional lmfit expressions. Blank bounds mean unbounded. For example, `p1_center + 1.2` constrains a second peak's position. A parameter with an expression is derived rather than independently optimized. Removing a referenced peak requires updating its dependent expressions.
5. Use **Edit → Preview initial model** to inspect your starting guesses. Press **Fit spectrum** to optimize in a worker thread. The model, residuals and parameter values update during fitting. On completion, optimized values become the current settings. Stop fitting cancels and retains any prior completed result; temporary live values are discarded.
6. **Save fitted CSV** writes three related files:
   - `name.csv`: measured energy/intensity, total fitted intensity **including background**, background, residual and each background-free peak component at the measured energy points.
   - `name_peaks.csv`: label, source, model, peak position, height, analytical full area, numerical area within the fit region, FWHM, shape parameters, available standard errors, fit status and reduced chi-square.
   - `name_parameters.json`: reusable region, charge shift, recorded reference details, background, component definitions, optimized parameters, bounds, fixed flags and expressions. Peak-summary CSVs also identify the charge-reference source, sheet, peak and energies.
7. **File → Save parameters / Load parameters** reuses a fitting setup on the currently selected sheet. On load, the energy coordinates are translated to the active session's recorded shift, or to raw energy if correction is off. Loading a parameter file **does not enable charge correction**. The target data must overlap the saved physical region. Only load parameter files you trust; expressions are evaluated by lmfit's expression interpreter.
8. **File → Save all fitted spectra** exports every completed sheet into one directory. Duplicate output names receive numeric suffixes. Session data itself is not automatically saved; export results and parameters before exiting.

Changing numerical settings or parameters invalidates the previous result so that exported results cannot silently disagree with current settings. Changing component labels or colors preserves the fit.

## Backgrounds and peak conventions

- **Linear**: slope and intercept are fitted jointly with the peaks and appear in the parameter table. The plotted background is also the subtraction baseline.
- **Shirley**: iterative, energy-weighted trapezoidal integration, with damping and an adjustable scale. Scale 1 uses both measured endpoints. The baseline is calculated before optimizing peaks.
- **Tougaard**: a two-parameter loss kernel `B*T/(C+T²)²`, integrated over the measured higher-binding-energy side, plus the high-energy endpoint offset. B and C are editable and held fixed during peak fitting. This finite-window implementation does not extrapolate unmeasured tails; background selection and window length affect quantitative areas.
- **None**: zero baseline.

Shirley and Tougaard use energy distances rather than the original script's sample-index approximations, so their results will not exactly reproduce those approximations. A nonlinear background is precomputed, not jointly optimized with peak parameters.

Model conventions match lmfit:

| Model | Width parameters |
| --- | --- |
| Gaussian | sigma = standard deviation |
| Lorentzian | sigma = half width at half maximum |
| Pseudo-Voigt | sigma = common half width at half maximum; fraction = Lorentzian weight |
| Voigt | sigma = Gaussian standard deviation; gamma = Lorentzian half width, independently adjustable |

Amplitude is the analytical area over the full peak, height is the peak maximum above background, and FWHM is derived. The separately exported region area accounts for truncation by the selected window. The fit is unweighted least squares; reduced chi-square is in intensity-squared units and is not a calibrated goodness-of-fit probability. Standard errors may be unavailable when the covariance cannot be estimated. Inspect the residuals and fit report, including the convergence status.

## Charge-correction workflow

1. Open **Charge Correction → Reference fitting**. Load any file and choose any reference sheet using the usual file/sheet dropdowns. There is no required filename or sheet name.
2. Select the fit range, background and model. **Fit reference spectrum** uses the current components, or adds one reference peak when none exists. Fitting alone does not enable correction.
3. Select the fitted component and its known **Reference (eV)** value (284.8 by default).
4. Press **Apply Charge Correction**. This is the explicit activation step. The app records the source, sheet, component/model, fitted position, reference position, optimized parameters, fit range, quality statistics, report and recording time.
5. The read-only **Charge shift Δ (eV)** is updated. Every subsequently selected sheet or newly loaded spectrum automatically receives the recorded **absolute** shift. Selecting the same sheet again never applies the shift twice. The correction applies across files until you replace or clear it.

The correction is `reference energy − fitted center on the original, unshifted axis`. Re-recording an already corrected reference accounts for its existing shift. Region bounds, peak positions, parameter bounds and expressions translate together. Existing fit intensity arrays, areas and residuals are preserved; the report distinguishes translated parameter values from the original optimizer report.

**Charge Correction → View recorded reference** displays the recorded fit details. **Clear correction** removes the record and returns every loaded spectrum to its raw energy axis. Correction starts **off in each new application session** and stays off unless Apply Charge Correction is pressed. The reference record is included in saved parameters for traceability, but is not silently reactivated when parameters are loaded.

## Matrix plots

**Plot → Matrix plot from saved CSVs** opens a separate composer:

- Add exported **spectrum** CSVs, not `_peaks.csv` summaries. Companion parameter JSON files supply peak labels when present.
- **Layout:** set both **Rows and Columns**, such as 2 × 3 or 3 × 2. Rows = Auto calculates the required rows. Unused cells stay blank; an undersized grid produces an inline message and retains the previous preview, without dropping spectra. Adjust row/column spacing, shared X/Y scales, figure title, physical size, DPI and export format.
- **Panels:** order spectra with the up/down controls; cells fill left to right, then top to bottom. Edit panel titles and independent X/Y labels. Select a panel to override its X/Y limits, tick visibility or legend visibility.
- **Panels → Normalize signal: subtract minimum (min = 0):** subtracts the selected spectrum's minimum measured intensity from its displayed data, total fit and background. Component curves and gradient fills follow the same shifted background, preserving their heights above it. This is `y − min(y)`, not division or scaling to 0–1, so intensity differences remain comparable. The minimum uses the entire loaded spectrum, independently of display zoom. Changes update live, follow the panel when reordered, and are saved in plot configurations. Source data and exported peak positions remain unchanged; existing explicit Y limits still apply to the shifted display.
- **Axes:** independently show ticks and numbers, ticks only, numbers only, or neither on X and Y. Global settings apply to every panel unless overridden in Panels. Also set major intervals, minor ticks, tick direction/length/width/rotation, axis limits, linear/log/symlog scales, reversed X, grid styling and individual spines.
- **Labels:** choose every-panel, outer-axis, shared-figure or selected-panel labels. Blank panel labels inherit the global label in the first two modes. In selected-panel mode, check the panel and leave either label blank to label only the other axis.
- **Style & fonts:** choose a font from families discovered on the system, or **Browse font file…** to import TTF/OTF/TTC. Set label/title/tick sizes, font weight/style, peak colormaps, gradient opacity, data markers and their sizes, line widths/styles, and data/fit/background/figure/panel colors. Imported fonts are available for the current session; keep the source file accessible.
- **Per-spectrum colors:** at the top of **Style & fonts**, select **Edit colors for spectrum**. Enter that file's data, fit and background colors or use the **Choose…** color picker; set its peak colormaps separately. Blank fields inherit the global defaults below. Changes update live, remain attached to the spectrum when reordered, and are saved in plot configurations. The selector stays synchronized with Panels and Legend. **Reset this spectrum’s colors to defaults** affects only the selected file.
- **Legend:** use **Edit legend for file** to select a loaded CSV directly from the Legend tab. File paths distinguish matching filenames. Edit that file's Data/Fit/Background names and individual peak names, or hide individual entries. **Custom legend layout for this file** gives it its own position, anchor coordinates, columns, font size, frame, opacity and title. Each file can show or hide its whole legend independently. Changes update live and stay attached to that file when panels are reordered. **Reset this file’s legend to global defaults** affects only the selected file. Global defaults appear below the per-file controls; a separate, explicit button copies names to all panels.
- **Live preview:** edits update automatically after a brief typing delay; no Update button is required. The preview uses the export aspect ratio and scales font sizes with physical figure size. Invalid partial colors, formulas, JSON or limits show an inline message and preserve the last valid preview. **Refresh** remains available.
- **Export:** PNG/PDF/SVG/TIFF/JPEG with chosen inches, DPI and transparency. Export is built from the current controls at the requested physical size rather than a screenshot of the preview. Saving a figure also writes an associated `<figure-name>_peak_positions.csv`.

### Exporting every plotted peak position

**Export all peak positions CSV…** in the matrix window writes one row for **every deconvoluted component of every loaded panel**. It includes the loaded CSV filename/full path, original experimental filename/path and sheet when available, panel number and matrix row/column, panel title, component ID, peak label, current legend name, peak position in eV, model, charge shift and available center uncertainty. Hiding a legend entry does not remove that peak from the CSV. Data points, the background and the summed fit are not counted as component peaks.

The same table is saved automatically next to each exported figure, for example `matrix.png` and `matrix_peak_positions.csv`. It follows the current panel order, and full paths distinguish spectra with the same filename from different folders.

Peak centers are taken from fitted parameters or the matching `_peaks.csv` summary, with `_parameters.json` as a fallback. Keep these companion files beside the exported spectrum CSV for exact fitted centers and original-file metadata. If only sampled component curves remain, the export uses the component's sampled maximum and marks `position_source` as `sampled_component_maximum`, with an explanatory note. Flat/invalid curves without fitted metadata are retained with an empty position and `unavailable` status. The `peak_position_eV` column is already on the plotted energy axis; the recorded charge shift is not applied again.

### Ordinary text and equations

Titles, axis labels and legend names accept normal text and Unicode such as `α`, `Δ` and `₁`. In **Plain text + math ($...$)** mode, put equations or complex symbols between dollar signs:

```text
Binding energy $E_B$ (eV)
$\mathrm{Cs}\,3d_{5/2}$
$\Delta E = \frac{a}{b}$
```

This uses Matplotlib's built-in **MathText**, a LaTeX-style subset that needs no external LaTeX installation. **Plain text only** renders dollar signs and backslashes literally. The equation font is selectable separately (STIX, Computer Modern or DejaVu), while ordinary text uses the selected system/imported font. Full external LaTeX is available through advanced `text.usetex` only with a working local TeX installation.

### Advanced Matplotlib properties

The **Advanced** tab accepts JSON for additional Matplotlib options without running Python code. `rcParams` supplies native defaults; explicit UI settings still take precedence over defaults. `axes` passes properties to `Axes.set`, `data`, `fit` and `background` pass properties to those artists, `peaks` maps peak prefixes to artist properties, and `legend` passes keyword options to `Axes.legend`. For example:

```json
{
  "rcParams": {"axes.labelpad": 8, "axes.linewidth": 1.5},
  "axes": {"aspect": "auto"},
  "fit": {"alpha": 0.8},
  "peaks": {"p1_": {"color": "purple"}},
  "legend": {"labelspacing": 0.3}
}
```

These expose native Matplotlib styling beyond the standard controls. Unsupported properties or values receive Matplotlib validation errors in the preview status. Backend changes and figure ownership are managed by the app.

The main plot also has Matplotlib pan, zoom, reset and save controls. XPS energy axes run from high to low.

### Editable plot projects and reusable templates

Use **Save Plot Project…** to save an editable `.xpsplot` file containing all loaded spectra, deconvoluted components, peak metadata and plot settings. Imported fonts are embedded too. **Open Plot Project…** restores the plot for further editing and saving, even if its original CSV files have moved or been deleted. This saves the matrix plotting workspace; figure export remains available separately through **Save figure…**.

Use **Save Plot Template…** to save settings only as a reusable JSON preset. It includes rows/columns, figure size and DPI, export format, labels and equations, fonts, colors, line/marker styles, ticks and axes, spacing, advanced Matplotlib settings, and each panel's legend names, visibility and custom layout. These buttons replace the former Save/Load plot configuration buttons; existing JSON configurations remain compatible.

Open a new matrix window and choose **Load Plot Template…**, either before or after adding the new spectrum CSVs. Panel-specific settings follow **plot order**: the first saved panel applies to the first new CSV, the second to the second CSV, and so on. Reorder the new CSVs to match your intended arrangement. Additional files beyond the preset's panel list use global styling while retaining any existing per-panel edits; increase the grid capacity if needed.

To reuse an existing plot with new data, use **Panels → Replace selected CSV…** or **Replace all CSVs…**. Replacement preserves formatting and updates the plotted spectra and associated peak metadata. Replace all requires the same number of files as existing panels, in panel order. Automatic titles change to the new filenames; custom titles stay unchanged.

The preset contains plotting settings, not spectrum data or old CSV paths. Automatically generated titles use the new CSV filenames; manually edited titles, axis labels, and legend names are retained. Custom-font files are referenced by path and must remain accessible. The app reports missing fonts or invalid presets and keeps the previous configuration instead of applying partial changes.

## Windows release

`release/XPSStudio.exe` is the standalone application: no Python installation is needed.
`release/XPSStudio-v1.1-Setup.exe` installs version 1.1.0 for the current Windows user, adds a Start menu shortcut, offers a desktop shortcut, and provides an uninstaller. It uses the same installation location as version 1.0. Windows 10 (1809+) or Windows 11, x64, is required. The binaries are unsigned.

To rebuild using the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe build_standalone.py
# Compile installer/XPSStudio.iss with Inno Setup 6.
```

The packaged application accepts `--self-test <absolute-report-path>` to run a headless GUI, fitting, Excel, project and figure-export check. Build dependency versions are recorded in `installer/requirements-lock.txt`.

## Post Analysis (version 1.1)

Open **Post Analysis → Atomic %, weight % & doublet separation…**. Use **Load saved fits…** to load fitting parameter JSON, `_peaks.csv` summaries, spectrum CSVs with their companion metadata, or `.xpsplot` projects containing fitted areas. **Use current fitted spectra** imports fits from the main window. Plot templates contain no fit data and cannot be quantified.

The input table lets you edit the sample group, element, core level, RSF, atomic weight and peak label, and include/exclude individual components. Peaks from one original workbook default to the same sample group. Use **Set sample for selected…** to group files from one sample or separate repeated measurements. Select a row to inspect its saved fit details. Loading the same source/sheet/peak again does not count it twice.

The calculation follows the supplied example: sum full analytical amplitudes for the included components, divide by the core-level RSF, then normalize corrected areas to 100% within each sample. Weight % additionally multiplies by atomic weight before normalization. Missing weights leave weight % blank while atomic % remains available. One spectrum/core level per element and sample is allowed to avoid double-counting independent measurements.

The example presets are **Cs 3d: RSF 7.04, weight 132.905; Pb 4f: RSF 9.14, weight 207.2; Br 3d: RSF 2.91, weight 79.904**. They are editable user-supplied factors, not a universal instrument library. Include both doublet peaks when using these whole-doublet factors. Other core levels need their own matching RSF. Fractions are relative to the included elements; they do not infer unmeasured elements.

New parameter exports preserve a fitted-parameter snapshot separately from reusable settings. Legacy parameter-only files cannot prove that fitting occurred; they are marked **Unverified parameters** and unchecked by default. They can be explicitly included if their values are known to be fitted. Saved curves without fitted-area metadata are rejected rather than substituting finite-window integrals or normalized plot heights.

**Doublet separation** reports the absolute difference between the two fitted centers in eV, their individual full areas and the A/B area ratio. Two-peak spectra are paired automatically; for larger fits select the spectrum and both peaks, then add a pair. Pairing does not assign chemical states automatically. This tab has an independent CSV export that needs no RSF.

**Save/Open analysis** preserves inputs, full available fit details, inclusion choices, RSFs, sample assignments and pairs in an editable `.xpspost` file. **Export results CSV** writes composition, `_doublets.csv` and `_inputs.csv` with source filenames, sheet names and peak identities. Changes recalculate live; invalid inputs clear the composition table instead of leaving stale percentages.

## Scope

This app implements the requested XPS peak-fitting, charge-shift, matrix-export and post-analysis workflow. The additional UPS VBM/CBM analyzer is not included in this interface. No experimental workbook was supplied for testing; import verification uses generated FACTS-format workbooks and CSV/DAT fixtures.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe -m tests.gui_smoke
.\.venv\Scripts\python.exe -m tests.charge_gui_smoke
.\.venv\Scripts\python.exe -m tests.matrix_gui_smoke
.\.venv\Scripts\python.exe -m tests.legend_gui_smoke
.\.venv\Scripts\python.exe -m tests.plot_configuration_smoke
.\.venv\Scripts\python.exe -m tests.plot_project_smoke
.\.venv\Scripts\python.exe -m tests.post_analysis_smoke
.\.venv\Scripts\python.exe -m tests.peak_positions_smoke
.\.venv\Scripts\python.exe -m tests.normalization_smoke
.\.venv\Scripts\python.exe -m tests.spectrum_colors_smoke
```

Tests cover analytical peak recovery for all four models, parameter ties/fixed values, cancellation, FACTS multi-sheet import, CSV/DAT import, duplicate energies, background edge cases, CSV/JSON round-trips and the real Qt worker/plot workflow. GUI smoke tests render the app and matrix composer to `artifacts/` using Qt's offscreen platform.

Charge-correction tests cover explicit activation, absolute shifts, repeated selections, replacement/clearing, translated constraints, record persistence, live text entry in energy limits, fit-range enforcement and conditional background controls.

Matrix tests cover explicit 2D grids, blank cells and capacity errors, automatic live updates, independent tick controls, editable legends, Unicode/MathText, system and imported fonts, validation without global Matplotlib-setting leakage, reordered panel settings and physical PNG/SVG/PDF exports.

Legend tests cover direct file selection, matching basenames in different directories, independent names/visibility/layouts, live updates, selection/reorder/reset/remove behavior and exported per-file legends.

Plot-configuration tests cover complete settings round-trips, per-file legend templates, loading before/after new CSVs, new automatic filenames, custom fonts, invalid-file rollback, recovery from an incomplete Advanced edit, and export after restoring a preset.

Peak-position tests cover every component, exact fitted centers versus sampled maxima, original/CSV filenames and sheets, hidden legend entries, edited labels, panel reordering, automatic figure-companion CSVs and explicit estimates/unavailable positions when metadata is missing.
