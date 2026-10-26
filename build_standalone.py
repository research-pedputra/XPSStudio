"""Build the standalone Windows executable using the project virtual environment."""
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
subprocess.check_call([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
    '--distpath', str(root/'release'), str(root/'installer'/'XPSStudio.spec')], cwd=root)
