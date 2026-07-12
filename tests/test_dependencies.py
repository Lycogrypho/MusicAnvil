"""Tests guarding the runtime environment (ToDo 1.1 / 1.2).

These regressions protect against the audit finding where the project's declared
dependencies (notably ``numpy`` and ``six``) were not actually installed inside the
project venv but leaked in from a non-isolated Anaconda base environment
(``include-system-site-packages = true``). If the venv is isolated but a pinned
dependency is missing — or installed at the wrong version — these tests fail, catching
the breakage the isolation fix would otherwise surface only at runtime.
"""

# OopCompanion:suppressRename

import importlib
import importlib.metadata as importlib_metadata
import os
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK_FILE = os.path.join(REPO_ROOT, "requirements-lock.txt")

# Distribution name -> module name to import. The runtime dependency chain of the
# engine and GUI; every one must resolve inside the (isolated) project environment.
RUNTIME_IMPORTS = {
    "pretty_midi": "pretty_midi",
    "numpy": "numpy",
    "mido": "mido",
    "six": "six",
    "importlib_resources": "importlib_resources",
}


def _parse_lock(path):
    """Return {distribution_name: pinned_version} from a ``name==version`` lock file."""
    pinned = {}
    with open(path, "r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "==" not in line:
                continue
            name, version = line.split("==", 1)
            pinned[name.strip()] = version.strip()
    return pinned


class TestPinnedDependenciesInstalled(unittest.TestCase):
    """Every package pinned in requirements-lock.txt is installed at that version."""

    @classmethod
    def setUpClass(cls):
        cls.pinned = _parse_lock(LOCK_FILE)

    def test_lock_file_is_not_empty(self):
        self.assertTrue(self.pinned, "requirements-lock.txt has no pinned dependencies.")

    def test_each_pinned_dependency_is_installed_at_the_locked_version(self):
        for name, expected in self.pinned.items():
            with self.subTest(package=name):
                try:
                    installed = importlib_metadata.version(name)
                except importlib_metadata.PackageNotFoundError:
                    self.fail(
                        f"Dependency '{name}' is pinned in requirements-lock.txt but is "
                        "not installed in this environment. Recreate the venv isolated "
                        "(include-system-site-packages = false) and run "
                        "'pip install -r requirements-lock.txt'."
                    )
                self.assertEqual(
                    installed, expected,
                    f"'{name}' is installed at {installed} but requirements-lock.txt "
                    f"pins {expected}.",
                )


class TestRuntimeDependenciesImportable(unittest.TestCase):
    """The engine/GUI runtime dependencies import cleanly in this environment."""

    def test_runtime_modules_import(self):
        for dist_name, module_name in RUNTIME_IMPORTS.items():
            with self.subTest(package=dist_name):
                try:
                    importlib.import_module(module_name)
                except ImportError as exc:
                    self.fail(f"Runtime dependency '{dist_name}' failed to import: {exc}")


if __name__ == "__main__":
    unittest.main()
