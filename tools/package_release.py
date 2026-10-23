from pathlib import Path
import argparse
import shutil
import zipfile
import json

ROOT = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument("--dist-root", default="dist")
parser.add_argument("--verification", default="work/frozen-verification")
parser.add_argument("--output", default="LumaSlice-Windows.zip")
args = parser.parse_args()
release = ROOT / args.dist_root / "LumaSlice"
verification_file = ROOT / args.verification / "verification.json"
report = json.loads(verification_file.read_text(encoding="utf-8"))
if not report.get("ok") or not report.get("frozen"):
    raise RuntimeError("Frozen verification has not passed")

shutil.copy2(ROOT / "Create-DesktopShortcut.vbs", release)
shutil.copytree(ROOT / "third_party_licenses", release / "third_party_licenses", dirs_exist_ok=True)
source = release / "source"
source.mkdir(exist_ok=True)
for folder in ("lcd_slicer", "plugins", "tests", "tools", "assets", "examples", "third_party_licenses"):
    shutil.copytree(ROOT / folder, source / folder, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
for file in ("run.py", "README.md", "LICENSE", "requirements.txt", "requirements-dev.txt", "requirements-lock.txt",
             "pytest.ini", "build.ps1", "Start-LumaSlice.bat", "Create-DesktopShortcut.vbs"):
    shutil.copy2(ROOT / file, source / file)
shutil.copy2(verification_file, release / "verification.json")

destination = ROOT / "outputs" / args.output
with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for file in sorted(release.rglob("*")):
        if file.is_file(): archive.write(file, Path("LumaSlice") / file.relative_to(release))
print(json.dumps({"file": str(destination), "size_bytes": destination.stat().st_size,
                  "unpacked_bytes": sum(p.stat().st_size for p in release.rglob("*") if p.is_file())}))
