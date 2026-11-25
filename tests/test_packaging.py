"""The build lists what PyInstaller cannot see, and pins what was tested."""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _spec_text():
    with open(os.path.join(ROOT, "keithley_suite.spec"), encoding="utf-8") as f:
        return f.read()


def _ctwa_modules():
    mods = set()
    for base, dirs, files in os.walk(os.path.join(ROOT, "ctwa")):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        rel = os.path.relpath(base, ROOT).replace(os.sep, ".")
        for f in files:
            if not f.endswith(".py"):
                continue
            mods.add(rel if f == "__init__.py" else rel + "." + f[:-3])
    return mods


def test_the_spec_lists_every_ctwa_module():
    listed = set(re.findall(r"""['"](ctwa[\w.]*)['"]""", _spec_text()))
    missing = sorted(_ctwa_modules() - listed)
    assert missing == []


def test_the_spec_lists_only_modules_that_exist():
    listed = set(re.findall(r"""['"](ctwa[\w.]*)['"]""", _spec_text()))
    # a package folder without __init__.py (a namespace package) is a name too
    gone = [m for m in listed - _ctwa_modules()
            if not os.path.isdir(os.path.join(ROOT, *m.split(".")))]
    assert sorted(gone) == []


def test_the_ci_build_installs_with_the_pinned_constraints():
    with open(os.path.join(ROOT, "constraints.txt"), encoding="utf-8") as f:
        pins = f.read()
    for pin in ("PySide6==6.10.3", "pyqtgraph==0.13.7", "numpy==2.0.2"):
        assert pin in pins
    assert re.search(r"^keyring==\d", pins, re.M)
    with open(os.path.join(ROOT, ".github", "workflows", "build-release.yml"), encoding="utf-8") as f:
        wf = f.read()
    installs = re.findall(r"pip install [^\n]*", wf)
    assert installs and all("-c constraints.txt" in i for i in installs)
