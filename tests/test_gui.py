"""Tests for MusicAnvil_GUI — verify the module is importable, the app builds its
tabbed interface, and all library symbols it depends on exist.

tkinter is mocked so these tests run headless.
"""

# OopCompanion:suppressRename

import sys
import unittest
from unittest.mock import MagicMock, patch


def _patched_tk():
    """Patch tkinter (and its submodules) with MagicMocks in sys.modules."""
    return patch.dict(sys.modules, {
        "tkinter": MagicMock(),
        "tkinter.ttk": MagicMock(),
        "tkinter.messagebox": MagicMock(),
        "tkinter.simpledialog": MagicMock(),
    })


def _fresh_gui_module():
    """Import MusicAnvil_GUI fresh (tkinter must already be patched)."""
    sys.modules.pop("musicanvil.MusicAnvil_GUI", None)
    import musicanvil.MusicAnvil_GUI as gui_mod
    return gui_mod


class TestGUIImport(unittest.TestCase):

    def test_module_imports_cleanly(self):
        with _patched_tk():
            try:
                _fresh_gui_module()
            except Exception as exc:
                self.fail(f"Importing MusicAnvil_GUI raised: {exc}")

    def test_app_instantiates(self):
        """MusicGeneratorApp.__init__ must build both tabs without raising."""
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            try:
                app = gui_mod.MusicGeneratorApp(MagicMock())
            except Exception as exc:
                self.fail(f"MusicGeneratorApp() raised: {exc}")
            self.assertEqual(app.sections, {})
            self.assertEqual(app.structure, [])

    def test_fmt_mmss(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            self.assertEqual(gui_mod.fmt_mmss(0), "00:00")
            self.assertEqual(gui_mod.fmt_mmss(90), "01:30")
            self.assertEqual(gui_mod.fmt_mmss(3599.6), "60:00")


class TestGUIDependencies(unittest.TestCase):
    """Every library symbol the GUI references must exist and be non-empty."""

    def setUp(self):
        from musicanvil import MusicAnvil, ma_utils


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename


# OopCompanion:suppressRename
        self.ma = ma_utils
        self.composer = MusicAnvil

    def test_notes_in_octave_exists_and_has_12_entries(self):
        self.assertEqual(len(self.ma.notes_in_octave), 12)

    def test_drum_lines_exists_and_non_empty(self):
        self.assertGreater(len(self.ma.drum_lines), 0)

    def test_scale_definitions_exists_and_non_empty(self):
        self.assertGreater(len(self.ma.scale_definitions), 0)

    def test_notes_pitches_does_not_exist(self):
        """notes_pitches was a historical bug — the GUI must use notes_in_octave."""
        self.assertFalse(hasattr(self.ma, "notes_pitches"))

    def test_composer_symbols_used_by_gui(self):
        self.assertGreater(len(self.composer.INSTRUMENT_PROGRAMS), 0)
        self.assertNotIn("Drums", self.composer.INSTRUMENT_PROGRAMS)
        self.assertEqual(len(self.composer.ROLES), 3)
        for symbol in ("PieceSpec", "SectionSpec", "RoleAssignment", "parse_signature",
                       "piece_seconds", "section_seconds", "resolve_section", "render_piece"):
            self.assertTrue(hasattr(self.composer, symbol), f"composer.{symbol} missing")


class TestStructureOperations(unittest.TestCase):
    """Exercise the structure-list logic with mocked widgets."""

    def _make_app(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            return gui_mod, app

    def test_add_to_structure_appends(self):
        gui_mod, app = self._make_app()
        app.add_section_var.get = MagicMock(return_value="intro")
        app._add_to_structure()
        self.assertEqual(len(app.structure), 1)
        self.assertEqual(app.structure[0].section, "intro")

    def test_add_without_selection_does_nothing(self):
        gui_mod, app = self._make_app()
        app.add_section_var.get = MagicMock(return_value="")
        app._add_to_structure()
        self.assertEqual(app.structure, [])

    def test_remove_from_structure(self):
        gui_mod, app = self._make_app()
        app.structure = ["intro", "verse", "chorus"]
        app.structure_listbox.curselection = MagicMock(return_value=(1,))
        app._remove_from_structure()
        self.assertEqual(app.structure, ["intro", "chorus"])

    def test_move_down_swaps(self):
        gui_mod, app = self._make_app()
        app.structure = ["intro", "verse", "chorus"]
        app.structure_listbox.curselection = MagicMock(return_value=(0,))
        app.structure_listbox.get = MagicMock(return_value="intro")
        app._move_in_structure(1)
        self.assertEqual(app.structure, ["verse", "intro", "chorus"])

    def test_move_up_at_top_is_noop(self):
        gui_mod, app = self._make_app()
        app.structure = ["intro", "verse"]
        app.structure_listbox.curselection = MagicMock(return_value=(0,))
        app._move_in_structure(-1)
        self.assertEqual(app.structure, ["intro", "verse"])


if __name__ == "__main__":
    unittest.main()
