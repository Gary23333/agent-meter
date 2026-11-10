"""Verify built sdist/wheel metadata and VERSION agree (standard library only)."""
from email.parser import BytesParser
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
version = (ROOT / "VERSION").read_text().strip()
wheels = list((ROOT / "dist").glob("*.whl"))
sdists = list((ROOT / "dist").glob("*.tar.gz"))
if len(wheels) != 1 or len(sdists) != 1:
    raise SystemExit("Expected exactly one wheel and one sdist in dist/; use a clean build directory")
with zipfile.ZipFile(wheels[0]) as wheel:
    names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
    assert len(names) == 1, names
    assert BytesParser().parsebytes(wheel.read(names[0]))["Version"] == version
with tarfile.open(sdists[0], "r:gz") as sdist:
    root = sdists[0].name[:-7]
    assert sdist.extractfile(root + "/VERSION").read().decode().strip() == version
    assert BytesParser().parsebytes(sdist.extractfile(root + "/PKG-INFO").read())["Version"] == version
print("PASS: wheel and sdist use VERSION = " + version)
