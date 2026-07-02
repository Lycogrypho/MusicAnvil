"""Tests for MusicAnvil_GUI — verify the module is importable and all
ma_utils references it depends on are correctly resolved.

These tests mock tkinter so they run in headless environments.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _make_tk_mock():
    """Return a minimal tkinter stub that satisfies every name the GUI uses."""
    tk = types.ModuleType("tkinter")
    # Variable classes
    for cls in ("IntVar", "StringVar"):
        setattr(tk, cls, MagicMock(return_value=MagicMock()))
    # Widget classes — their constructors and grid() are no-ops
    for cls in ("Label", "Entry", "Button", "Listbox"):
        widget = MagicMock()
        widget.return_value.grid = MagicMock()
        widget.return_value.insert = MagicMock()
        widget.return_value.curselection = MagicMock(return_value=())
        setattr(tk, cls, widget)
    tk.MULTIPLE = "multiple"
    tk.END = "end"
    tk.messagebox = MagicMock()
    # Tk root
    tk.Tk = MagicMock(return_value=MagicMock())

    ttk = types.ModuleType("tkinter.ttk")
    combobox = MagicMock()
    combobox.return_value.grid = MagicMock()
    ttk.Combobox = combobox

    messagebox_mod = types.ModuleType("tkinter.messagebox")
    messagebox_mod.showinfo = MagicMock()
    messagebox_mod.showerror = MagicMock()

    return tk, ttk, messagebox_mod


class TestGUIImport(unittest.TestCase):
    """The GUI module must import without errors after the fix."""

    def test_module_imports_cleanly(self):
        """Importing MusicAnvil_GUI should not raise any exception."""
        tk_mock, ttk_mock, mb_mock = _make_tk_mock()
        with patch.dict(sys.modules, {
            "tkinter": tk_mock,
            "tkinter.ttk": ttk_mock,
            "tkinter.messagebox": mb_mock,
        }):
            # Remove cached module so we get a fresh import each time
            sys.modules.pop("musicanvil.MusicAnvil_GUI", None)
            try:
                import musicanvil.MusicAnvil_GUI  # noqa: F401
            except Exception as exc:
                self.fail(f"Importing MusicAnvil_GUI raised: {exc}")

    def test_app_instantiates(self):
        """MusicGeneratorApp.__init__ must complete without raising."""
        tk_mock, ttk_mock, mb_mock = _make_tk_mock()
        with patch.dict(sys.modules, {
            "tkinter": tk_mock,
            "tkinter.ttk": ttk_mock,
            "tkinter.messagebox": mb_mock,
        }):
            sys.modules.pop("musicanvil.MusicAnvil_GUI", None)
            import musicanvil.MusicAnvil_GUI as gui_mod
            root = MagicMock()
            try:
                gui_mod.MusicGeneratorApp(root)
            except Exception as exc:
                self.fail(f"MusicGeneratorApp() raised: {exc}")


class TestGUIDependenciesOnMaUtils(unittest.TestCase):
    """All ma_utils symbols referenced by the GUI must exist and be non-empty."""

    def setUp(self):
        from musicanvil import ma_utils
        self.ma = ma_utils

    def test_notes_in_octave_exists_and_has_12_entries(self):
        self.assertTrue(hasattr(self.ma, "notes_in_octave"))
        self.assertEqual(len(self.ma.notes_in_octave), 12)

    def test_drum_lines_exists_and_non_empty(self):
        self.assertTrue(hasattr(self.ma, "drum_lines"))
        self.assertGreater(len(self.ma.drum_lines), 0)

    def test_scale_definitions_exists_and_non_empty(self):
        self.assertTrue(hasattr(self.ma, "scale_definitions"))
        self.assertGreater(len(self.ma.scale_definitions), 0)

    def test_notes_pitches_does_not_exist(self):
        """notes_pitches was the bug — it must NOT exist; the GUI now uses notes_in_octave."""
        self.assertFalse(hasattr(self.ma, "notes_pitches"),
                         "notes_pitches still present; GUI should use notes_in_octave instead")

    def test_tonic_combobox_values_match_notes_in_octave(self):
        """The GUI populates the Tonic combobox from notes_in_octave; verify it contains C."""
        self.assertIn("C", self.ma.notes_in_octave)

    def test_rhythm_combobox_values_include_rock(self):
        self.assertIn("Rock", self.ma.drum_lines)

    def test_scale_combobox_values_include_major(self):
        self.assertIn("major", self.ma.scale_definitions)


class TestGUIHelpers(unittest.TestCase):
    """Unit-test the pure helper methods on MusicGeneratorApp."""

    def _make_app(self):
        tk_mock, ttk_mock, mb_mock = _make_tk_mock()
        with patch.dict(sys.modules, {
            "tkinter": tk_mock,
            "tkinter.ttk": ttk_mock,
            "tkinter.messagebox": mb_mock,
        }):
            sys.modules.pop("musicanvil.MusicAnvil_GUI", None)
            import musicanvil.MusicAnvil_GUI as gui_mod
            root = MagicMock()
            app = gui_mod.MusicGeneratorApp(root)
            return app

    def test_parse_duration_normal(self):
        app = self._make_app()
        app.duration_var.get = MagicMock(return_value="01:30")
        self.assertEqual(app._parse_duration(), 90)

    def test_parse_duration_zero_minutes(self):
        app = self._make_app()
        app.duration_var.get = MagicMock(return_value="00:45")
        self.assertEqual(app._parse_duration(), 45)

    def test_parse_duration_invalid_raises(self):
        app = self._make_app()
        app.duration_var.get = MagicMock(return_value="90")
        with self.assertRaises(ValueError):
            app._parse_duration()

    def test_parse_signature_4_4(self):
        app = self._make_app()
        app.signature_var.get = MagicMock(return_value="4/4")
        self.assertEqual(app._parse_signature(), (4, 4))

    def test_parse_signature_6_8(self):
        app = self._make_app()
        app.signature_var.get = MagicMock(return_value="6/8")
        self.assertEqual(app._parse_signature(), (6, 8))

    def test_parse_signature_invalid_raises(self):
        app = self._make_app()
        app.signature_var.get = MagicMock(return_value="44")
        with self.assertRaises(ValueError):
            app._parse_signature()


if __name__ == "__main__":
    unittest.main()
