"""Create a source archive and checksums alongside the Windows release."""
import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
release = root / 'release'
archive_path = release / 'XPSStudio-v1.1-source.zip'
with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ('xps_studio', 'tests', 'installer'):
        for path in (root / name).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                archive.write(path, path.relative_to(root))
    for name in ('main.py', 'windows_launcher.py', 'build_standalone.py', 'build_release.ps1', 'requirements.txt',
                 'README.md', 'Launch XPS Studio.bat', 'Setup XPS Studio.bat'):
        archive.write(root / name, name)
lines = []
for name in ('XPSStudio.exe', 'XPSStudio-v1.1-Setup.exe', archive_path.name):
    path = release / name
    lines.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {name}')
(release / 'SHA256SUMS.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
