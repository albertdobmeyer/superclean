# PyInstaller spec: freeze superclean into a single self-contained superclean.exe.
#
# Build:  pyinstaller packaging/superclean.spec --noconfirm
# Output: dist/superclean.exe
#
# The frozen layout must match the wheel layout, because the runtime resolves its
# bundled files relative to the package directory:
#
#   config.py    Path(__file__).parent / "_backend" / "conf"
#   windows.py   Path(__file__).parents[1] / "_backend" / "windows" / "superclean.ps1"
#
# so the data has to land under superclean/_backend/, exactly where the wheel's
# force-include puts it. Keep this in sync with [tool.hatch.build.targets.wheel
# .force-include] in pyproject.toml; if one moves and the other does not, the exe
# builds fine and then cannot find its PowerShell backend at runtime.

from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller

datas = [
    (str(ROOT / "windows"), "superclean/_backend/windows"),
    (str(ROOT / "protect.conf"), "superclean/_backend/conf"),
    (str(ROOT / "targets.conf"), "superclean/_backend/conf"),
    (str(ROOT / "services.conf"), "superclean/_backend/conf"),
]

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=["psutil"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "pytest", "ruff"],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="superclean",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX compression is a reliable way to earn an antivirus false positive
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
