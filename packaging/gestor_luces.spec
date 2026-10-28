# PyInstaller spec: one-folder, windowed build shared by the portable zip and the installer.
# Run from the repository root:  pyinstaller packaging/gestor_luces.spec --noconfirm
from pathlib import Path
import re

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller

pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
VERSION = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE).group(1)
VERSION_TUPLE = tuple((int(p) for p in (VERSION.split(".") + ["0", "0", "0"])[:3])) + (0,)

datas = [
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "assets"), "assets"),
]
binaries = []
hiddenimports = collect_submodules("gestor_luces") + collect_submodules("webview.platforms")
hiddenimports += ["clr", "clr_loader", "pythonnet", "pyaudiowpatch", "pystray._win32", "winreg"]

# pywebview (WinForms backend), pythonnet and PyAudioWPatch ship native/.NET payloads.
for package in ("webview", "pythonnet", "clr_loader", "pyaudiowpatch"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

version_file = ROOT / "build" / "version_info.txt"
version_file.parent.mkdir(exist_ok=True)
version_file.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={VERSION_TUPLE}, prodvers={VERSION_TUPLE}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Gestor de Luces'),
      StringStruct('FileDescription', 'WiZ Architectural Lighting Console'),
      StringStruct('FileVersion', '{VERSION}'),
      StringStruct('InternalName', 'GestorDeLuces'),
      StringStruct('OriginalFilename', 'GestorDeLuces.exe'),
      StringStruct('ProductName', 'WiZ Architectural Lighting Console'),
      StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ]
)
""",
    encoding="utf-8",
)

a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "gestor_luces" / "main.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "_pytest",
        "py",
        "pluggy",
        "unittest",
        "pydoc",
        "doctest",
        "pdb",
        "sqlite3",
        "xmlrpc",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GestorDeLuces",
    console=False,
    icon=str(ROOT / "assets" / "icon" / "app.ico"),
    version=str(version_file),
    upx=False,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="GestorDeLuces",
)
