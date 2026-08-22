"""Tests for MusicAnvil_GUI — verify the module is importable, the app builds its
tabbed interface, and all library symbols it depends on exist.

tkinter is mocked so these tests run headless.
"""

# OopCompanion:suppressRename

import json
import sys
import unittest
import unittest.mock
from unittest.mock import MagicMock, patch, call


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
            self.assertEqual(list(app.sections.keys()),
                             ["Intro", "Verse", "Chorus", "Solo", "Bridge", "Outro"])
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


class TestProjectSerialization(unittest.TestCase):
    """Round-trip PieceSpec -> project dict -> PieceSpec via the GUI's I/O helpers."""

    def _gui(self):
        with _patched_tk():
            return _fresh_gui_module()

    def _sample_piece(self, MA):
        return MA.PieceSpec(
            tempo=132,
            signature=(3, 4),
            rhythm="Jazz",
            scale="dorian",
            tonic="D",
            tonic_octave=3,
            lead_rest_prob=0.2,
            drums_enabled=["Bass Drum", "Snare Drum"],
            roles={
                MA.ROLE_LEAD: MA.RoleAssignment(main="Piano", supports=["Flute"]),
                MA.ROLE_ACCOMPANIMENT: MA.RoleAssignment(main="Guitar"),
                MA.ROLE_BASS: MA.RoleAssignment(main="Bass"),
            },
            sections={
                "Verse": MA.SectionSpec(name="Verse", bars=8, tempo=140,
                                        signature=(4, 4), drums_enabled=["Bass Drum"]),
                "Chorus": MA.SectionSpec(
                    name="Chorus", bars=4,
                    roles={MA.ROLE_LEAD: MA.RoleAssignment(main="Sax")}),
            },
            structure=[
                MA.StructureEntry(section="Verse"),
                MA.StructureEntry(section="Chorus", transformer="tone_shift",
                                  transformer_kwargs={"n": 5}),
            ],
        )

    def test_round_trip_preserves_piece_defaults(self):
        gui = self._gui()
        from musicanvil import MusicAnvil as MA
        piece = self._sample_piece(MA)
        restored, filename = gui.project_dict_to_piece(
            gui.piece_to_project_dict(piece, filename="song"))
        self.assertEqual(filename, "song")
        self.assertEqual(restored.tempo, 132)
        self.assertEqual(restored.signature, (3, 4))
        self.assertEqual(restored.rhythm, "Jazz")
        self.assertEqual(restored.scale, "dorian")
        self.assertEqual(restored.tonic, "D")
        self.assertEqual(restored.tonic_octave, 3)
        self.assertAlmostEqual(restored.lead_rest_prob, 0.2)
        self.assertEqual(restored.drums_enabled, ["Bass Drum", "Snare Drum"])
        self.assertEqual(restored.roles[MA.ROLE_LEAD].main, "Piano")
        self.assertEqual(restored.roles[MA.ROLE_LEAD].supports, ["Flute"])

    def test_round_trip_preserves_sections(self):
        gui = self._gui()
        from musicanvil import MusicAnvil as MA
        restored, _ = gui.project_dict_to_piece(
            gui.piece_to_project_dict(self._sample_piece(MA)))
        self.assertEqual(set(restored.sections), {"Verse", "Chorus"})
        verse = restored.sections["Verse"]
        self.assertEqual(verse.bars, 8)
        self.assertEqual(verse.tempo, 140)
        self.assertEqual(verse.signature, (4, 4))
        self.assertEqual(verse.drums_enabled, ["Bass Drum"])
        # Inherited (unset) fields must remain None so they still inherit on load.
        self.assertIsNone(verse.scale)
        self.assertEqual(restored.sections["Chorus"].roles[MA.ROLE_LEAD].main, "Sax")

    def test_round_trip_preserves_structure(self):
        gui = self._gui()
        from musicanvil import MusicAnvil as MA
        restored, _ = gui.project_dict_to_piece(
            gui.piece_to_project_dict(self._sample_piece(MA)))
        self.assertEqual(len(restored.structure), 2)
        self.assertEqual(restored.structure[0].section, "Verse")
        self.assertEqual(restored.structure[0].all_modifiers(), [])
        self.assertEqual(restored.structure[1].section, "Chorus")
        # A saved project restores its modifier stack; the single-transformer shorthand
        # is one entry in it.
        self.assertEqual(restored.structure[1].all_modifiers(), [("tone_shift", {"n": 5})])

    def test_project_dict_is_json_serialisable(self):
        gui = self._gui()
        from musicanvil import MusicAnvil as MA
        text = json.dumps(gui.piece_to_project_dict(self._sample_piece(MA)))
        restored, _ = gui.project_dict_to_piece(json.loads(text))
        self.assertEqual(restored.tempo, 132)
        self.assertEqual(restored.structure[1].all_modifiers(), [("tone_shift", {"n": 5})])

    def test_rejects_non_project_dict(self):
        gui = self._gui()
        with self.assertRaises(ValueError):
            gui.project_dict_to_piece({"foo": "bar"})


class TestTempoValidationError(unittest.TestCase):
    """P3 #19 — _current_piece_spec must raise an informative error for non-integer tempo."""

    def _make_app(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            return gui_mod, app

    def test_non_integer_tempo_raises_value_error(self):
        _, app = self._make_app()
        app.tempo_var.get = MagicMock(return_value="120.5")
        with self.assertRaises(ValueError):
            app._current_piece_spec()

    def test_non_integer_tempo_error_mentions_bpm(self):
        _, app = self._make_app()
        app.tempo_var.get = MagicMock(return_value="fast")
        with self.assertRaises(ValueError) as ctx:
            app._current_piece_spec()
        self.assertIn("BPM", str(ctx.exception))

    def test_non_integer_tempo_error_mentions_whole_number(self):
        _, app = self._make_app()
        app.tempo_var.get = MagicMock(return_value="120.5")
        with self.assertRaises(ValueError) as ctx:
            app._current_piece_spec()
        msg = str(ctx.exception).lower()
        self.assertIn("whole", msg)

    def test_integer_tempo_does_not_raise_on_parse(self):
        _, app = self._make_app()
        app.tempo_var.get = MagicMock(return_value="120")
        app.signature_var.get = MagicMock(return_value="4/4")
        app.scale_var.get = MagicMock(return_value="major")
        app.tonic_var.get = MagicMock(return_value="C")
        app.tonic_octave_var.get = MagicMock(return_value="4")
        try:
            app._current_piece_spec(require_lead=False)
        except ValueError as exc:
            if "BPM" in str(exc) or "whole" in str(exc).lower():
                self.fail(f"_current_piece_spec raised tempo-parse error for valid integer: {exc}")


class TestGenerateSaveDialog(unittest.TestCase):
    """P3 #17 — _generate must use a save-file dialog instead of writing to CWD."""

    def _make_app(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            return gui_mod, app

    def _patch_piece_spec(self, app):
        """Return a context manager that makes _current_piece_spec return a valid mock piece."""
        mock_piece = MagicMock()
        mock_piece.structure = [MagicMock()]
        return patch.object(app, "_current_piece_spec", return_value=mock_piece)

    def test_generate_calls_save_dialog(self):
        gui_mod, app = self._make_app()
        gui_mod.filedialog.asksaveasfilename = MagicMock(return_value="")
        with self._patch_piece_spec(app):
            app._generate()
        gui_mod.filedialog.asksaveasfilename.assert_called_once()

    def test_generate_cancelled_dialog_does_not_call_render(self):
        """If the user cancels the dialog (returns ''), render_piece must not be called."""
        gui_mod, app = self._make_app()
        gui_mod.filedialog.asksaveasfilename = MagicMock(return_value="")
        import musicanvil.MusicAnvil as MA
        with patch.object(MA, "render_piece") as mock_render:
            with self._patch_piece_spec(app):
                app._generate()
            mock_render.assert_not_called()

    def test_generate_writes_to_dialog_path(self):
        """MIDI must be written to the path returned by the save dialog."""
        gui_mod, app = self._make_app()
        expected_path = "/tmp/test_song.mid"
        gui_mod.filedialog.asksaveasfilename = MagicMock(return_value=expected_path)
        import musicanvil.MusicAnvil as MA
        mock_midi = MagicMock()
        with patch.object(MA, "render_piece", return_value=mock_midi):
            with self._patch_piece_spec(app):
                app._generate()
        mock_midi.write.assert_called_once_with(expected_path)

    def test_generate_dialog_uses_default_filename_as_initial(self):
        """The dialog's initialfile must match the filename entry widget."""
        gui_mod, app = self._make_app()
        gui_mod.filedialog.asksaveasfilename = MagicMock(return_value="")
        app.filename_var.get = MagicMock(return_value="my_song")
        with self._patch_piece_spec(app):
            app._generate()
        kwargs = gui_mod.filedialog.asksaveasfilename.call_args.kwargs
        self.assertEqual(kwargs.get("initialfile"), "my_song.mid")


class TestTransformerParameterWidgets(unittest.TestCase):
    """ToDo 4.5 — the GUI builds transformer controls from the declared descriptors."""

    def _app(self):
        gui_mod = _fresh_gui_module()
        return gui_mod, gui_mod.MusicGeneratorApp(MagicMock())

    def test_selecting_a_transformer_builds_its_parameter_vars(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_var.get = lambda: "tone_shift"
            app._build_transformer_params()
            self.assertEqual(list(app.transform_param_vars), ["n"])

    def test_a_parameterless_transformer_builds_nothing(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_var.get = lambda: "invert"
            app._build_transformer_params()
            self.assertEqual(app.transform_param_vars, {})

    def test_none_choice_builds_nothing(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_var.get = lambda: gui_mod.NONE_CHOICE
            app._build_transformer_params()
            self.assertEqual(app.transform_param_vars, {})

    def test_kwargs_are_converted_to_the_declared_type(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_param_vars = {
                "n": (MagicMock(get=lambda: "5"), {"name": "n", "type": "int"}),
                "amount": (MagicMock(get=lambda: "0.25"),
                           {"name": "amount", "type": "float"}),
            }
            self.assertEqual(app._transformer_kwargs(), {"n": 5, "amount": 0.25})

    def test_a_non_numeric_value_is_reported(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_param_vars = {
                "n": (MagicMock(get=lambda: "abc"),
                      {"name": "n", "label": "Shift n", "type": "int"}),
            }
            with self.assertRaises(ValueError) as ctx:
                app._transformer_kwargs()
            self.assertIn("Shift n", str(ctx.exception))

    def test_entry_label_shows_declared_parameters(self):
        from musicanvil import MusicAnvil as MA
        with _patched_tk():
            gui_mod, _ = self._app()
            entry = MA.StructureEntry(section="Verse", transformer="invert")
            self.assertEqual(gui_mod._entry_label(entry), "Verse [invert]")
            entry = MA.StructureEntry(section="Verse", transformer="tone_shift",
                                      transformer_kwargs={"n": 5})
            self.assertEqual(gui_mod._entry_label(entry), "Verse [+5]")
            entry = MA.StructureEntry(section="Verse", transformer="other",
                                      transformer_kwargs={"amount": 0.5})
            self.assertEqual(gui_mod._entry_label(entry), "Verse [other amount=0.5]")


class TestProjectFormatVersionTwo(unittest.TestCase):
    """ToDo 4.5 — the phrasing/dynamics fields travel in the project file, and older
    files still load. (Version 3 added the modifier stack; the fields are unchanged.)"""

    FIELDS = ("phrase_bars", "metric_accent", "intensity", "final_lengthening",
              "lead_syncopation")

    def _piece(self):
        from musicanvil import MusicAnvil as MA
        return MA.PieceSpec(
            tempo=120, signature=(4, 4), rhythm="Rock", scale="major", tonic="C",
            roles={MA.ROLE_LEAD: MA.RoleAssignment(main="Piano")},
            sections={"Verse": MA.SectionSpec(name="Verse", bars=4)},
            structure=["Verse"])

    def test_version_is_at_least_two(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            self.assertGreaterEqual(gui_mod.PROJECT_VERSION, 2)

    def test_new_fields_are_saved(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            data = gui_mod.piece_to_project_dict(self._piece())
            for field in self.FIELDS:
                with self.subTest(field=field):
                    self.assertIn(field, data["piece"])
                    self.assertIn(field, data["sections"][0])

    def test_new_fields_round_trip(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            piece = self._piece()
            piece.phrase_bars = 2
            piece.intensity = 0.8
            piece.sections["Verse"].final_lengthening = 2.5
            piece.sections["Verse"].lead_syncopation = 0.9
            restored, _ = gui_mod.project_dict_to_piece(gui_mod.piece_to_project_dict(piece))
            self.assertEqual(restored.phrase_bars, 2)
            self.assertEqual(restored.intensity, 0.8)
            self.assertEqual(restored.sections["Verse"].final_lengthening, 2.5)
            self.assertEqual(restored.sections["Verse"].lead_syncopation, 0.9)

    def test_a_version_one_file_still_loads(self):
        """Old projects have none of the new keys; they must fall back to the defaults."""
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            data = gui_mod.piece_to_project_dict(self._piece())
            data["version"] = 1
            for field in self.FIELDS:
                data["piece"].pop(field, None)
                data["sections"][0].pop(field, None)
            from musicanvil import MusicAnvil as MA
            restored, _ = gui_mod.project_dict_to_piece(data)
            defaults = MA.PieceSpec()
            for field in self.FIELDS:
                with self.subTest(field=field):
                    self.assertEqual(getattr(restored, field), getattr(defaults, field))
                    self.assertIsNone(getattr(restored.sections["Verse"], field))


class TestMusicalFieldsInTheForm(unittest.TestCase):
    """The P4 fields must be editable in the GUI, not just in the config."""

    def test_every_musical_field_is_offered(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            keys = {key for key, *_ in gui_mod.ARTIC_PARAMS}
            keys |= {key for key, *_ in gui_mod.TOGGLE_PARAMS}
            for field in gui_mod._MUSICAL_FIELDS:
                with self.subTest(field=field):
                    self.assertIn(field, keys)

    def test_toggles_are_booleans_of_the_config_defaults(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            from musicanvil import ma_utils
            for key, _label, default in gui_mod.TOGGLE_PARAMS:
                with self.subTest(key=key):
                    self.assertIsInstance(default, bool)
                    self.assertEqual(default,
                                     bool(ma_utils.get_param("piece_defaults", key)))

    def test_every_articulation_key_has_a_section_override_row(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            for key, *_ in gui_mod.ARTIC_PARAMS:
                with self.subTest(key=key):
                    self.assertIn(key, app.sec_override)

    def test_parse_artic_covers_every_piece_field(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            for key, _label, default, is_int in gui_mod.ARTIC_PARAMS:
                app.artic_vars[key] = MagicMock(get=lambda default=default: default)
            for key, _label, default in gui_mod.TOGGLE_PARAMS:
                app.toggle_vars[key] = MagicMock(get=lambda default=default: default)
            parsed = app._parse_artic()
            from musicanvil import MusicAnvil as MA
            defaults = MA.PieceSpec()
            for key, value in parsed.items():
                with self.subTest(key=key):
                    self.assertEqual(value, getattr(defaults, key))


class TestParameterHelp(unittest.TestCase):
    """Every parameter the Main tab offers must explain itself."""

    def test_help_exists_for_every_piece_parameter(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            keys = [key for key, *_ in gui_mod.ARTIC_PARAMS]
            keys += [key for key, *_ in gui_mod.TOGGLE_PARAMS]
            keys += ["tempo", "signature", "scale", "tonic", "tonic_octave", "beat_mode",
                     "filename", "bars", "rhythm", "drums_enabled", "roles"]
            for key in keys:
                with self.subTest(key=key):
                    self.assertTrue(gui_mod.help_for(key), f"no help text for '{key}'")

    def test_help_text_is_a_sentence(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            for key, text in gui_mod.PARAMETER_HELP.items():
                with self.subTest(key=key):
                    self.assertGreater(len(text), 30)
                    self.assertTrue(text.rstrip().endswith("."))

    def test_unknown_key_has_no_help(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            self.assertEqual(gui_mod.help_for("no_such_parameter"), "")

    def test_the_info_line_mirrors_a_balloon(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            app._describe("hello")
            app.info_label.config.assert_called_with(text="hello")

    def test_a_tooltip_is_attached_to_a_described_widget(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            widget = MagicMock()
            app._with_help(widget, "tempo")
            widget.bind.assert_any_call("<Enter>", unittest.mock.ANY, add="+")

    def test_no_tooltip_without_help_text(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            widget = MagicMock()
            app._with_help(widget, "no_such_parameter")
            widget.bind.assert_not_called()


class TestPieceAndSectionParametersMatch(unittest.TestCase):
    """Anything settable for the whole piece must be overridable per section."""

    def test_every_main_tab_parameter_has_a_section_override(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            expected = [key for key, *_ in gui_mod.ARTIC_PARAMS]
            expected += [key for key, *_ in gui_mod.TOGGLE_PARAMS]
            expected += ["tempo", "signature", "scale", "tonic", "tonic_octave", "beat_mode"]
            for key in expected:
                with self.subTest(key=key):
                    self.assertIn(key, app.sec_override)

    def test_every_section_override_is_a_real_section_field(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            from musicanvil import MusicAnvil as MA
            spec = MA.SectionSpec(name="x")
            for key in app.sec_override:
                with self.subTest(key=key):
                    self.assertTrue(hasattr(spec, key))

    def test_the_switches_are_offered_as_yes_no(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            self.assertEqual(gui_mod.BOOL_CHOICES, ("yes", "no"))

    @staticmethod
    def _var(value):
        """A stand-alone stand-in for a tk variable.

        The mocked tkinter hands out one shared MagicMock for every StringVar(), so each
        variable this test cares about gets its own object instead.
        """
        return MagicMock(get=lambda: value)

    def test_a_switch_override_round_trips_through_the_form(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            app.bars_var = self._var("4")
            app._sec_drums_override_var = self._var(False)
            app.sec_roles_override_var = self._var(False)
            for key, _l, _d, _i in gui_mod.ARTIC_PARAMS:
                app.sec_override[key] = (self._var(False), self._var(""))
            for key in ("tempo", "signature", "rhythm", "scale", "tonic",
                        "tonic_octave", "beat_mode"):
                app.sec_override[key] = (self._var(False), self._var(""))
            for key, _label, _default in gui_mod.TOGGLE_PARAMS:
                app.sec_override[key] = (self._var(True), self._var("no"))

            spec = app._build_section_spec("Verse")
            for key, _label, _default in gui_mod.TOGGLE_PARAMS:
                with self.subTest(key=key):
                    self.assertIs(getattr(spec, key), False)

    def test_a_switch_override_rejects_a_value_that_is_not_yes_or_no(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            app.bars_var = self._var("4")
            app._sec_drums_override_var = self._var(False)
            app.sec_roles_override_var = self._var(False)
            for key, _l, _d, _i in gui_mod.ARTIC_PARAMS:
                app.sec_override[key] = (self._var(False), self._var(""))
            for key in ("tempo", "signature", "rhythm", "scale", "tonic",
                        "tonic_octave", "beat_mode"):
                app.sec_override[key] = (self._var(False), self._var(""))
            key = gui_mod.TOGGLE_PARAMS[0][0]
            app.sec_override[key] = (self._var(True), self._var(""))
            for other, _label, _default in gui_mod.TOGGLE_PARAMS[1:]:
                app.sec_override[other] = (self._var(False), self._var(""))
            with self.assertRaises(ValueError):
                app._build_section_spec("Verse")


class TestWidgetWidths(unittest.TestCase):
    """The dropdowns must be wide enough for the longest name they can show."""

    def test_instrument_width_fits_every_general_midi_name(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            longest = max(len(name) for name in gui_mod.MELODIC_INSTRUMENTS)
            self.assertGreaterEqual(gui_mod.INSTRUMENT_WIDTH, longest)

    def test_rhythm_scale_and_drum_widths_fit_their_lists(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            from musicanvil import ma_utils
            self.assertGreaterEqual(gui_mod.RHYTHM_WIDTH,
                                    max(len(n) for n in ma_utils.drum_lines))
            self.assertGreaterEqual(gui_mod.SCALE_WIDTH,
                                    max(len(n) for n in ma_utils.scale_definitions))
            self.assertGreaterEqual(gui_mod.DRUM_WIDTH,
                                    max(len(n) for n in ma_utils.drum_pitches))

    def test_widths_are_derived_not_hardcoded(self):
        """Adding a longer instrument name must widen the widgets by itself."""
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            self.assertEqual(gui_mod.INSTRUMENT_WIDTH,
                             max(len(n) for n in gui_mod.MELODIC_INSTRUMENTS) + 2)


class TestStructureEditing(unittest.TestCase):
    """ToDo 6.x — duplicate, multi-selection and stacked modifiers."""

    def _app(self, structure=("Verse", "Chorus")):
        gui_mod = _fresh_gui_module()
        app = gui_mod.MusicGeneratorApp(MagicMock())
        from musicanvil import MusicAnvil as MA
        app.structure = [MA.StructureEntry(section=name) for name in structure]
        app.structure_listbox = MagicMock()
        app._update_total = lambda: None
        return gui_mod, app

    def test_duplicate_copies_the_selected_entries(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.structure_listbox.curselection = lambda: (0,)
            app._duplicate_in_structure()
            self.assertEqual([e.section for e in app.structure],
                             ["Verse", "Verse", "Chorus"])

    def test_duplicate_handles_a_multiple_selection(self):
        with _patched_tk():
            gui_mod, app = self._app(("Intro", "Verse", "Chorus"))
            app.structure_listbox.curselection = lambda: (0, 1)
            app._duplicate_in_structure()
            self.assertEqual([e.section for e in app.structure],
                             ["Intro", "Verse", "Intro", "Verse", "Chorus"])

    def test_duplicate_without_a_selection_does_nothing(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.structure_listbox.curselection = lambda: ()
            app._duplicate_in_structure()
            self.assertEqual(len(app.structure), 2)

    def test_a_duplicate_is_independent_of_its_original(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.structure[0] = app.structure[0].with_modifier("tension")
            app.structure_listbox.curselection = lambda: (0,)
            app._duplicate_in_structure()
            app.structure[1] = app.structure[1].with_modifier("invert")
            self.assertEqual([n for n, _ in app.structure[0].all_modifiers()], ["tension"])
            self.assertEqual([n for n, _ in app.structure[1].all_modifiers()],
                             ["tension", "invert"])

    def test_remove_deletes_every_selected_entry(self):
        with _patched_tk():
            gui_mod, app = self._app(("Intro", "Verse", "Chorus"))
            app.structure_listbox.curselection = lambda: (0, 2)
            app._remove_from_structure()
            self.assertEqual([e.section for e in app.structure], ["Verse"])

    def test_the_structure_list_allows_multiple_selection(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            app = gui_mod.MusicGeneratorApp(MagicMock())
            self.assertTrue(hasattr(app, "structure_listbox"))
            self.assertTrue(hasattr(app, "modifier_stack"))

    def test_stacking_two_modifiers(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.transform_var.get = lambda: "tension"
            app.transform_param_vars = {"bars": (MagicMock(get=lambda: "2"),
                                                 {"name": "bars", "type": "int"})}
            app._stack_modifier()
            app.transform_var.get = lambda: "tone_shift"
            app.transform_param_vars = {"n": (MagicMock(get=lambda: "5"),
                                              {"name": "n", "type": "int"})}
            app._stack_modifier()
            self.assertEqual(app.modifier_stack,
                             [("tension", {"bars": 2}), ("tone_shift", {"n": 5})])

    def test_clearing_the_stack(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.modifier_stack = [("invert", {})]
            app._clear_modifier_stack()
            self.assertEqual(app.modifier_stack, [])

    def test_applying_the_stack_to_the_selected_entries(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.modifier_stack = [("tension", {}), ("tone_shift", {"n": 3})]
            app.structure_listbox.curselection = lambda: (1,)
            app._apply_stack_to_selected()
            self.assertEqual(app.structure[0].all_modifiers(), [])
            self.assertEqual(app.structure[1].all_modifiers(),
                             [("tension", {}), ("tone_shift", {"n": 3})])

    def test_the_stack_label_lists_the_modifiers(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.modifier_stack = [("tension", {"bars": 2}), ("tone_shift", {"n": 5})]
            text = app._stack_text()
            self.assertIn("tension bars=2", text)
            self.assertIn("+5", text)

    def test_an_empty_stack_says_so(self):
        with _patched_tk():
            gui_mod, app = self._app()
            app.modifier_stack = []
            self.assertIn("empty", app._stack_text())

    def test_the_entry_label_shows_a_whole_stack(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            from musicanvil import MusicAnvil as MA
            entry = MA.StructureEntry(section="Verse",
                                      modifiers=[("tension", {}), ("tone_shift", {"n": 5})])
            self.assertEqual(gui_mod._entry_label(entry), "Verse [tension | +5]")


class TestTechniqueSummary(unittest.TestCase):
    """The Sections tab must say what the chosen instruments actually switch on."""

    def _piece(self, accompaniment="Guitar", **kwargs):
        from musicanvil import MusicAnvil as MA
        piece = MA.PieceSpec(roles={
            MA.ROLE_LEAD: MA.RoleAssignment(main="Piano"),
            MA.ROLE_ACCOMPANIMENT: MA.RoleAssignment(main=accompaniment),
            MA.ROLE_BASS: MA.RoleAssignment(main="Bass")})
        for key, value in kwargs.items():
            setattr(piece, key, value)
        return piece

    def _section(self):
        from musicanvil import MusicAnvil as MA
        return MA.SectionSpec(name="Verse", bars=4)

    def test_a_distorted_program_reports_power_chords_and_palm_mutes(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            text = gui_mod.describe_techniques(self._piece("Distortion Guitar"), self._section())
            self.assertIn("power chords", text)
            self.assertIn("palm-muted", text)

    def test_a_clean_program_does_not(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            text = gui_mod.describe_techniques(self._piece("Guitar"), self._section())
            self.assertNotIn("power chords", text)
            self.assertIn("full chords", text)

    def test_expression_on_and_off_are_both_explained(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            on = gui_mod.describe_techniques(self._piece(expression=True), self._section())
            off = gui_mod.describe_techniques(self._piece(expression=False), self._section())
            self.assertIn("Expression on", on)
            self.assertIn("vibrato", on)
            self.assertIn("Expression off", off)

    def test_the_channel_caveat_is_stated(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            text = gui_mod.describe_techniques(self._piece(), self._section())
            self.assertIn("lead and bass only", text)

    def test_cadences_and_fills_are_reported(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            text = gui_mod.describe_techniques(self._piece(), self._section())
            self.assertIn("Cadences on", text)
            self.assertIn("Drum fills", text)

    def test_switching_them_off_removes_them(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            text = gui_mod.describe_techniques(
                self._piece(auto_cadence=False, drum_fills=False), self._section())
            self.assertNotIn("Cadences on", text)
            self.assertNotIn("Drum fills", text)

    def test_a_broken_section_does_not_raise(self):
        with _patched_tk():
            gui_mod = _fresh_gui_module()
            from musicanvil import MusicAnvil as MA
            bad = MA.SectionSpec(name="Verse", bars=4, scale="no_such_scale")
            text = gui_mod.describe_techniques(self._piece(), bad)
            self.assertIn("Techniques", text)


if __name__ == "__main__":
    unittest.main()
