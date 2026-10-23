param([string]$DistRoot = 'dist')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
& .\.venv\Scripts\python.exe tools\prepare_release.py
if ($LASTEXITCODE -ne 0) { throw 'Asset preparation failed' }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --windowed --name LumaSlice --icon assets\lumaslice.ico --add-data 'assets;assets' --collect-all trimesh --hidden-import shapely._geos --hidden-import shapely._geometry_helpers --exclude-module pytest --exclude-module _pytest --exclude-module tkinter --exclude-module matplotlib --distpath $DistRoot --workpath work\pyinstaller run.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
$releaseDirectory = Join-Path $DistRoot 'LumaSlice'
Copy-Item -LiteralPath README.md -Destination $releaseDirectory
Copy-Item -LiteralPath plugins -Destination $releaseDirectory -Recurse -Force
Copy-Item -LiteralPath examples -Destination $releaseDirectory -Recurse -Force
Copy-Item -LiteralPath LICENSE -Destination $releaseDirectory
Copy-Item -LiteralPath third_party_licenses -Destination $releaseDirectory -Recurse -Force
