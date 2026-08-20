"""Tests for the repository layout and packaging metadata (ToDo 3.3 / 3.5).

Guards two things the audit flagged: scratch scripts must not sit at the repo root
next to the package (3.3), and the project must declare packaging metadata — including
``MusicAnvil.json`` as package data, without which an installed ``musicanvil`` cannot
load any preset — plus an automated pytest + pip-audit CI job (3.5).
"""

# OopCompanion:suppressRename

import os
import runpy
import sys
import tomllib
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYPROJECT = os.path.join(REPO_ROOT, "pyproject.toml")
EXAMPLES_DIR = os.path.join(REPO_ROOT, "examples")
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")


def _load_pyproject():
    with open(PYPROJECT, "rb") as handle:
        return tomllib.load(handle)


def _workflow_files():
    if not os.path.isdir(WORKFLOW_DIR):
        return []
    return [os.path.join(WORKFLOW_DIR, name) for name in sorted(os.listdir(WORKFLOW_DIR))
            if name.endswith((".yml", ".yaml"))]


class TestExampleScriptsAreNotAtTheRoot(unittest.TestCase):
    """ToDo 3.3 — snippets.py was unimported scratch code at the repo root that wrote a
    MIDI file into the working directory as a side effect of being run."""

    def test_snippets_is_not_at_the_repo_root(self):
        self.assertFalse(os.path.exists(os.path.join(REPO_ROOT, "snippets.py")),
                         "snippets.py must live under examples/, not at the repo root")

    def test_snippets_lives_under_examples(self):
        self.assertTrue(os.path.isfile(os.path.join(EXAMPLES_DIR, "snippets.py")))

    def test_examples_is_not_a_package(self):
        """examples/ is documentation, not importable code shipped with the library."""
        self.assertFalse(os.path.exists(os.path.join(EXAMPLES_DIR, "__init__.py")))

    def test_importing_the_example_writes_no_midi(self):
        """The file must only write its MIDI when run as a script, and never into the
        working directory (the original wrote drum_pattern.mid wherever it was run)."""
        def midi_files(directory):
            return {name for name in os.listdir(directory) if name.endswith(".mid")}

        before_examples = midi_files(EXAMPLES_DIR)
        before_cwd = midi_files(os.getcwd())
        sys.path.insert(0, EXAMPLES_DIR)
        try:
            sys.modules.pop("snippets", None)
            __import__("snippets")
        finally:
            sys.modules.pop("snippets", None)
            sys.path.remove(EXAMPLES_DIR)
        self.assertEqual(midi_files(EXAMPLES_DIR), before_examples,
                         "importing examples/snippets.py must not write a MIDI file")
        self.assertEqual(midi_files(os.getcwd()), before_cwd,
                         "importing examples/snippets.py must not touch the working directory")

    def test_example_builds_a_drum_pattern(self):
        module = runpy.run_path(os.path.join(EXAMPLES_DIR, "snippets.py"))
        midi = module["build_drum_pattern"]()
        self.assertEqual(len(midi.instruments), 1)
        self.assertTrue(midi.instruments[0].is_drum)
        self.assertEqual(len(midi.instruments[0].notes), 3)

    def test_no_stray_scripts_at_the_repo_root(self):
        """Only the package, the tests and examples/ hold Python code."""
        stray = [name for name in os.listdir(REPO_ROOT)
                 if name.endswith(".py") and not name.startswith(".")]
        self.assertEqual(stray, [], f"unexpected Python files at the repo root: {stray}")


class TestPyprojectMetadata(unittest.TestCase):
    """ToDo 3.5 — packaging metadata, with MusicAnvil.json declared as package data."""

    @classmethod
    def setUpClass(cls):
        cls.data = _load_pyproject()

    def test_pyproject_exists(self):
        self.assertTrue(os.path.isfile(PYPROJECT))

    def test_declares_a_build_backend(self):
        self.assertIn("build-system", self.data)
        self.assertTrue(self.data["build-system"].get("build-backend"))
        self.assertTrue(self.data["build-system"].get("requires"))

    def test_project_identity(self):
        project = self.data["project"]
        self.assertEqual(project["name"], "musicanvil")
        self.assertTrue(project.get("version"))
        self.assertTrue(project.get("description"))

    def test_requires_python_313(self):
        self.assertIn("3.13", self.data["project"]["requires-python"])

    def test_runtime_dependency_matches_the_requirements_file(self):
        with open(os.path.join(REPO_ROOT, "requirements.txt"), "r", encoding="utf-8") as handle:
            pinned = [line.strip() for line in handle
                      if line.strip() and not line.startswith("#")]
        self.assertEqual(sorted(self.data["project"]["dependencies"]), sorted(pinned))

    def test_dev_extra_matches_the_dev_requirements_file(self):
        with open(os.path.join(REPO_ROOT, "requirements-dev.txt"), "r", encoding="utf-8") as handle:
            pinned = [line.strip() for line in handle
                      if line.strip() and not line.startswith("#")]
        self.assertEqual(sorted(self.data["project"]["optional-dependencies"]["dev"]),
                         sorted(pinned))

    def test_the_musicanvil_package_is_included(self):
        self.assertIn("musicanvil", self.data["tool"]["setuptools"]["packages"])

    def test_config_file_is_declared_as_package_data(self):
        """Without this, ma_utils.load_config() raises FileNotFoundError once installed."""
        package_data = self.data["tool"]["setuptools"]["package-data"]
        self.assertIn("MusicAnvil.json", package_data["musicanvil"])

    def test_the_declared_package_data_actually_exists(self):
        for pattern in self.data["tool"]["setuptools"]["package-data"]["musicanvil"]:
            with self.subTest(pattern=pattern):
                self.assertTrue(os.path.isfile(os.path.join(REPO_ROOT, "musicanvil", pattern)))


class TestContinuousIntegrationWorkflow(unittest.TestCase):
    """ToDo 3.5 — a CI job must run the test suite and pip-audit automatically."""

    @classmethod
    def setUpClass(cls):
        cls.contents = {}
        for path in _workflow_files():
            with open(path, "r", encoding="utf-8") as handle:
                cls.contents[os.path.basename(path)] = handle.read()

    def test_a_workflow_exists(self):
        self.assertTrue(self.contents, f"no CI workflow found under {WORKFLOW_DIR}")

    def test_a_workflow_runs_the_test_suite(self):
        self.assertTrue(any("pytest" in text for text in self.contents.values()),
                        "no CI workflow runs pytest")

    def test_a_workflow_runs_pip_audit(self):
        self.assertTrue(
            any("pip_audit" in text or "pip-audit" in text for text in self.contents.values()),
            "no CI workflow runs pip-audit",
        )

    def test_a_workflow_installs_the_pinned_requirements(self):
        self.assertTrue(any("requirements-lock.txt" in text for text in self.contents.values()),
                        "CI must install the pinned lock file, not float versions")

    def test_a_workflow_uses_python_313(self):
        self.assertTrue(any("3.13" in text for text in self.contents.values()))


if __name__ == "__main__":
    unittest.main()
