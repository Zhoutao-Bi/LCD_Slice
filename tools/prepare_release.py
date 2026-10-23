"""Generate reproducible icon, sample mesh/project, and dependency notices."""
from pathlib import Path
import importlib.metadata as metadata
import json
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from PIL import Image, ImageDraw
import trimesh
from lcd_slicer.core import Settings, demo_model, save_project

(ROOT / "assets").mkdir(exist_ok=True)
(ROOT / "examples").mkdir(exist_ok=True)
icon = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)
draw.rounded_rectangle((12, 12, 244, 244), radius=54, fill="#ed7a32")
draw.rounded_rectangle((72, 56, 100, 194), radius=10, fill="white")
draw.rounded_rectangle((72, 166, 183, 194), radius=10, fill="white")
for x, y in ((130, 88), (158, 116), (186, 144)):
    draw.rectangle((x, y, x + 16, y + 16), fill="#ffd4b7")
icon.save(ROOT / "assets" / "lumaslice.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
settings = Settings()
model = demo_model(settings)
trimesh.Trimesh(model.vertices, model.faces, process=False).export(ROOT / "examples" / "calibration-ring.stl")
save_project(ROOT / "examples" / "calibration-ring.lcdproj", [model], settings, {})

licenses = ROOT / "third_party_licenses"
licenses.mkdir(exist_ok=True)
notices = []
for name in ("PySide6-Essentials", "shiboken6", "numpy", "pillow", "trimesh", "shapely", "pyinstaller"):
    dist = metadata.distribution(name)
    notices.append({"name": name, "version": dist.version,
                    "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                    "project_urls": dist.metadata.get_all("Project-URL") or [],
                    "home_page": dist.metadata.get("Home-page")})
    for file in dist.files or []:
        name_lower = str(file).lower()
        if any(word in name_lower for word in ("license", "copying", "copyright")) and \
                not name_lower.endswith((".py", ".pyc", ".json")):
            source = Path(dist.locate_file(file))
            if source.is_file() and source.stat().st_size < 4_000_000:
                target = licenses / dist.metadata["Name"] / str(file).replace("../", "").replace("..\\", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
(licenses / "dependencies.json").write_text(json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8")
(licenses / "README.txt").write_text(
    "LumaSlice uses dynamically linked Qt / PySide6 libraries. You may replace the compatible DLLs in _internal.\n"
    "Qt / PySide source and licensing: https://code.qt.io/cgit/pyside/pyside-setup.git/\n"
    "Qt source: https://code.qt.io/cgit/qt/ (matching Qt 6.8.3 modules).\n"
    "PySide release source: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/\n"
    "PySide6-Essentials and shiboken6 are distributed under LGPLv3/GPL/commercial alternatives.\n"
    "Original LumaSlice source is provided in the source folder under MIT.\n"
    "Third-party licenses are independent of the LumaSlice MIT license.\n", encoding="utf-8")
print("Prepared icon, calibration example, and dependency notices.")
