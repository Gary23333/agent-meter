"""Copy license texts shipped by the selected Python and PyInstaller installs."""
import importlib.metadata
import shutil
import sys
import sysconfig
from pathlib import Path

target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
python_license = Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"
if not python_license.is_file():
    raise SystemExit("The selected Python installation has no LICENSE.txt")
shutil.copyfile(python_license, target / "Python-LICENSE.txt")
distribution = importlib.metadata.distribution("pyinstaller")
licenses = [p for p in distribution.files if str(p).endswith("COPYING.txt")]
if not licenses:
    raise SystemExit("The selected PyInstaller installation has no COPYING.txt")
shutil.copyfile(distribution.locate_file(licenses[0]), target / "PyInstaller-COPYING.txt")
