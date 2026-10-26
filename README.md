# XPS Studio

XPS Studio is a Windows desktop application for X-ray photoelectron spectroscopy (XPS) data import, peak fitting, charge correction, matrix plotting, and post-analysis. It is built with Python, PySide6, NumPy, pandas, SciPy, lmfit, and Matplotlib.

## Run from a Python terminal

Use Python 3.11 or newer. Open PowerShell in this folder, create a virtual environment, install the dependencies, and start the app:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

To open the optional synthetic demo data:

```powershell
python main.py --demo
```

The app is started with Python from the terminal. There is no bundled executable or installer in this project.

## Main workflow

1. Choose **File → Load data** and select one or more supported data files.
2. Select the file and (for Excel workbooks) sheet in the main window.
3. Set the energy region, choose a background, and add peak components. Edit component parameters and bounds in the Parameters table.
4. Choose **Edit → Preview initial model** to inspect the starting curves, then select **Fit spectrum**.
5. Export the result with **Save fitted CSV**. This creates the fitted spectrum CSV, a `_peaks.csv` summary, and a `_parameters.json` file. Use **Save all fitted spectra** to export all completed fits.

Supported imports include `.xlsx`, `.xlsm`, `.xls`, `.csv`, `.dat`, `.data`, and `.txt`. Excel sheets and CSV files can use the FACTS column names (`Binding energy (eV)` and `Counts per second`) or the Generic two columns option. Text data uses its first two numeric columns.

## Other features

- **Peak fitting:** Gaussian, Lorentzian, pseudo-Voigt, and Voigt components; None, linear, Shirley, or Tougaard backgrounds.
- **Charge correction:** fit a reference peak, set its known energy, then explicitly apply the correction. The correction is off in a new session.
- **Matrix plotting:** **Plot → Matrix plot from saved CSVs** opens a plot composer for exported spectrum CSVs. It supports multiple panels, styling, plot templates/projects, peak-position export, and PNG/PDF/SVG/TIFF/JPEG output.
- **Post analysis:** **Post Analysis → Atomic %, weight % & doublet separation…** summarizes fitted components and calculates relative composition using editable relative sensitivity factors.

For in-app guidance, use **Help → Workflow** (or the Help menu entry). The `artifacts/` folder contains example screenshots and a sample matrix peak-position CSV.

## Project layout

- `main.py` — Python entry point.
- `xps_studio/` — user interface, spectrum fitting, plotting, matrix tools, and post-analysis modules.
- `requirements.txt` — Python package dependencies.
- `artifacts/` — reference screenshots and sample output.

## Troubleshooting

- If PowerShell blocks virtual-environment activation, run the app directly with `\.venv\Scripts\python.exe main.py` after installing dependencies with that same interpreter.
- If `pip install` fails, confirm that Python 3.11+ is installed and that the terminal is using the `.venv` interpreter.
- Keep exported CSV companion files together when reopening a matrix plot so peak labels and fit metadata can be found.

