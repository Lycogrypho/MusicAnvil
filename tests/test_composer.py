"""Tests for the piece composition engine (musicanvil.MusicAnvil)."""

# OopCompanion:suppressRename

import random
import unittest

import pretty_midi

from musicanvil import MusicAnvil, ma_utils


def _make_piece(structure=("A",), bars=2, tempo=120, **section_kwargs):
    """A minimal piece: one section 'A', Piano lead, Guitar accompaniment, Bass bass."""
    piece = MusicAnvil.PieceSpec(
        tempo=tempo,
        signature=(4, 4),
        rhythm="Rock",
        scale="major",
        tonic="C",
        roles={
            MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano"),
            MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(main="Guitar"),
            MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(main="Bass"),
        },
        sections={"A": MusicAnvil.SectionSpec(name="A", bars=bars, **section_kwargs)},
        structure=list(structure),
    )
    return piece


class TestTimingMath(unittest.TestCase):

    def test_parse_signature_valid(self):
        self.assertEqual(MusicAnvil.parse_signature("4/4"), (4, 4))
        self.assertEqual(MusicAnvil.parse_signature("6/8"), (6, 8))

    def test_parse_signature_invalid(self):
        for bad in ("44", "4/4/4", "0/4", "4/0", "x/y"):
            with self.assertRaises(ValueError):
                MusicAnvil.parse_signature(bad)

    def test_beat_seconds_quarter_note(self):
        # 120 BPM, denominator 4 -> quarter-note beat of 0.5 s
        self.assertAlmostEqual(MusicAnvil.beat_seconds(120, 4), 0.5)

    def test_beat_seconds_eighth_note(self):
        # denominator 8 -> eighth-note beat, half the quarter length
        self.assertAlmostEqual(MusicAnvil.beat_seconds(120, 8), 0.25)

    def test_beat_seconds_rejects_bad_tempo(self):
        with self.assertRaises(ValueError):
            MusicAnvil.beat_seconds(0, 4)
        with self.assertRaises(ValueError):
            MusicAnvil.beat_seconds(-60, 4)

    def test_section_seconds(self):
        # 4 bars of 4/4 at 120 BPM = 4 * 4 * 0.5 = 8 s
        self.assertAlmostEqual(MusicAnvil.section_seconds(4, 120, (4, 4)), 8.0)
        # 2 bars of 3/4 at 60 BPM = 2 * 3 * 1.0 = 6 s
        self.assertAlmostEqual(MusicAnvil.section_seconds(2, 60, (3, 4)), 6.0)

    def test_piece_seconds_sums_structure_occurrences(self):
        piece = _make_piece(structure=["A", "A", "A"], bars=2)  # 2 bars = 4 s each
        self.assertAlmostEqual(MusicAnvil.piece_seconds(piece), 12.0)

    def test_piece_seconds_unknown_section_raises(self):
        piece = _make_piece(structure=["A", "missing"])
        with self.assertRaises(ValueError):
            MusicAnvil.piece_seconds(piece)


class TestResolveSection(unittest.TestCase):

    def test_inherits_piece_defaults(self):
        piece = _make_piece()
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tempo, piece.tempo)
        self.assertEqual(resolved.signature, piece.signature)
        self.assertEqual(resolved.rhythm, piece.rhythm)
        self.assertEqual(resolved.scale, piece.scale)
        self.assertEqual(resolved.tonic, piece.tonic)
        self.assertEqual(resolved.roles[MusicAnvil.ROLE_LEAD].main, "Piano")

    def test_overrides_win(self):
        piece = _make_piece(tempo=120)
        piece.sections["A"].tempo = 90
        piece.sections["A"].scale = "blues"
        piece.sections["A"].roles = {
            MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Violin"),
        }
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tempo, 90)
        self.assertEqual(resolved.scale, "blues")
        self.assertEqual(resolved.roles[MusicAnvil.ROLE_LEAD].main, "Violin")
        # Roles not overridden still inherit
        self.assertEqual(resolved.roles[MusicAnvil.ROLE_BASS].main, "Bass")


class TestRenderSection(unittest.TestCase):

    def setUp(self):
        self.piece = _make_piece(bars=2)
        self.resolved = MusicAnvil.resolve_section(self.piece.sections["A"], self.piece)
        self.rng = random.Random(42)
        self.tracks, self.length = MusicAnvil.render_section(self.resolved, self.rng)
        self.scale_pitches = [pretty_midi.note_name_to_number(n)
                              for n in ma_utils.generate_scale("major", "C")]

    def test_length_matches_bars(self):
        self.assertAlmostEqual(self.length, MusicAnvil.section_seconds(2, 120, (4, 4)))

    def test_has_drum_track(self):
        self.assertIn(MusicAnvil.DRUM_TRACK, self.tracks)
        self.assertGreater(len(self.tracks[MusicAnvil.DRUM_TRACK]), 0)

    def test_all_notes_within_section(self):
        for notes in self.tracks.values():
            for note in notes:
                self.assertGreaterEqual(note.start, 0.0)
                self.assertLessEqual(note.end, self.length + 1e-9)

    def test_lead_notes_in_scale(self):
        for note in self.tracks.get("Piano", []):
            self.assertIn(note.pitch, self.scale_pitches)

    def test_bass_in_low_register(self):
        low = {max(0, p - 24) for p in self.scale_pitches[:7]}
        bass_notes = self.tracks.get("Bass", [])
        self.assertGreater(len(bass_notes), 0)
        for note in bass_notes:
            self.assertIn(note.pitch, low)

    def test_chords_stay_in_key(self):
        allowed_pitch_classes = {p % 12 for p in self.scale_pitches}
        chord_notes = self.tracks.get("Guitar", [])
        self.assertGreater(len(chord_notes), 0)
        for note in chord_notes:
            self.assertIn(note.pitch % 12, allowed_pitch_classes)

    def test_unknown_rhythm_raises(self):
        self.resolved.rhythm = "NoSuchGenre"
        with self.assertRaises(ValueError):
            MusicAnvil.render_section(self.resolved, self.rng)


class TestGenerateChordLine(unittest.TestCase):
    """The refactored generate_chord_line builds chords from chord_definitions that
    fit the lead notes and stay within the scale."""

    def setUp(self):
        self.scale_pitches = [pretty_midi.note_name_to_number(n)
                              for n in ma_utils.generate_scale("major", "C")]
        self.scale_pcs = {p % 12 for p in self.scale_pitches}
        self.beat_len = 0.5

    def _lead(self, *pitches):
        """One sustained lead note per beat, in order."""
        return [pretty_midi.Note(velocity=100, pitch=p,
                                 start=i * self.beat_len, end=(i + 1) * self.beat_len)
                for i, p in enumerate(pitches)]

    def test_chord_notes_are_diatonic(self):
        lead = self._lead(72, 74, 76, 77)  # C D E F over four beats
        chords = MusicAnvil.generate_chord_line(lead, self.scale_pitches, 4, self.beat_len)
        self.assertGreater(len(chords), 0)
        for note in chords:
            self.assertIn(note.pitch % 12, self.scale_pcs)

    def test_chord_contains_the_lead_pitch_class(self):
        # Each harmonised beat's chord must contain the lead note sounding on it.
        for pitch in (72, 74, 76, 77, 79, 81, 83):
            chords = MusicAnvil.generate_chord_line(self._lead(pitch), self.scale_pitches,
                                                    1, self.beat_len)
            self.assertTrue(chords, f"no chord produced for lead pitch {pitch}")
            chord_pcs = {n.pitch % 12 for n in chords}
            self.assertIn(pitch % 12, chord_pcs)

    def test_c_lead_yields_c_major_triad(self):
        chords = MusicAnvil.generate_chord_line(self._lead(72), self.scale_pitches, 1, self.beat_len)
        self.assertEqual({n.pitch % 12 for n in chords}, {0, 4, 7})  # C E G

    def test_chord_voiced_below_lead(self):
        chords = MusicAnvil.generate_chord_line(self._lead(72), self.scale_pitches, 1, self.beat_len)
        for note in chords:
            self.assertLessEqual(note.pitch, 72)

    def test_no_degenerate_chord_at_top_of_scale(self):
        # ToDo #16: the highest scale pitch used to collapse to a 1-2 note "chord".
        top = self.scale_pitches[-1]
        chords = MusicAnvil.generate_chord_line(self._lead(top), self.scale_pitches, 1, self.beat_len)
        self.assertGreaterEqual(len({n.pitch % 12 for n in chords}), 3)

    def test_beat_without_lead_is_rest(self):
        chords = MusicAnvil.generate_chord_line([], self.scale_pitches, 4, self.beat_len)
        self.assertEqual(chords, [])

    def test_default_chord_octave_shift_is_minus_two(self):
        self.assertEqual(MusicAnvil.PieceSpec().chord_octave_shift, -2)

    def test_chord_voiced_two_octaves_below_lead_by_default(self):
        # C5 (72) lead, C major → C major triad. Default shift=-2 voices root at C3 (48).
        chords = MusicAnvil.generate_chord_line(self._lead(72), self.scale_pitches, 1, self.beat_len)
        root_pitch = min(n.pitch for n in chords)
        self.assertEqual(root_pitch % 12, 0)          # C root
        self.assertLessEqual(root_pitch, 72 - 24)     # at or below 2 octaves down

    def test_chord_octave_shift_controls_voicing_depth(self):
        # shift=-1 vs shift=-2 for the same lead note must differ by exactly one octave.
        chords_m1 = MusicAnvil.generate_chord_line(
            self._lead(72), self.scale_pitches, 1, self.beat_len, chord_octave_shift=-1)
        chords_m2 = MusicAnvil.generate_chord_line(
            self._lead(72), self.scale_pitches, 1, self.beat_len, chord_octave_shift=-2)
        self.assertEqual(
            min(n.pitch for n in chords_m1) - min(n.pitch for n in chords_m2), 12)


class TestGenerateChordLineExtensions(unittest.TestCase):
    """chord_palette_extensions modify chord selection in generate_chord_line.

    Three key behaviours:
    (a) Diatonic chord on the primary root always beats an extension on the same root.
    (b) Extension chord on the primary root beats a diatonic chord on the wrong root.
    (c) Without scale_name the extension whitelist is empty (pure diatonic behaviour).
    """

    def _blues_scale_pitches(self):
        return [pretty_midi.note_name_to_number(n)
                for n in ma_utils.generate_scale("blues", "C", start_octave=4)]

    def _note(self, pitch, start, end):
        return pretty_midi.Note(velocity=100, pitch=pitch, start=start, end=end)

    def test_diatonic_beats_extension_on_same_root(self):
        # C lead in C blues. C minor {0,3,7} is diatonic. C dominant7 {0,4,7,10} is the
        # I-chord blues extension (4=E not in blues). Diatonic must win.
        blues = self._blues_scale_pitches()
        lead = [self._note(72, 0.0, 0.5)]   # C5
        chords = MusicAnvil.generate_chord_line(lead, blues, 1, 0.5, scale_name="blues")
        self.assertTrue(chords, "No chord was generated")
        chord_pcs = {n.pitch % 12 for n in chords}
        self.assertNotIn(4, chord_pcs,  # E — the hallmark of C dominant7
                         "Extension C dominant7 was chosen over diatonic C minor")
        self.assertIn(0, chord_pcs)   # C root present
        self.assertIn(3, chord_pcs)   # E♭ — hallmark of C minor

    def test_extension_fires_when_no_diatonic_covers_full_beat(self):
        # Beat has both C (0) and E (4). No diatonic chord in C blues contains E,
        # so the C dominant7 extension (I7) must be chosen when scale_name="blues".
        blues = self._blues_scale_pitches()
        beat_len = 0.5
        lead = [self._note(72, 0.0, beat_len),   # C5, pc=0
                self._note(76, 0.0, beat_len)]    # E5, pc=4
        chords = MusicAnvil.generate_chord_line(lead, blues, 1, beat_len, scale_name="blues")
        self.assertTrue(chords, "No chord was generated with blues extensions")
        chord_pcs = {n.pitch % 12 for n in chords}
        self.assertIn(4, chord_pcs,   # E — only present if C dominant7 extension fired
                      "Expected C dominant7 extension but got something else")

    def test_no_scale_name_falls_back_to_diatonic(self):
        # Same beat (C+E) without scale_name: extensions are inactive, so the engine
        # falls back to harmonising just the primary (C alone) → C minor, no E.
        blues = self._blues_scale_pitches()
        beat_len = 0.5
        lead = [self._note(72, 0.0, beat_len),
                self._note(76, 0.0, beat_len)]
        chords = MusicAnvil.generate_chord_line(lead, blues, 1, beat_len)  # no scale_name
        self.assertTrue(chords, "No chord was generated without scale_name")
        chord_pcs = {n.pitch % 12 for n in chords}
        self.assertNotIn(4, chord_pcs,   # E must not appear (only in C dominant7)
                         "Extension chord appeared without scale_name being supplied")

    def test_extension_root_beats_diatonic_wrong_root(self):
        # scale_pitches restricted to {C, E♭, G} (pitch classes 0, 3, 7).
        # Lead = G5. No diatonic chord is rooted on G in this scale (G+anything ∉ {0,3,7}).
        # Blues extension (7, "dominant7") → G dominant7 must win over C minor (diatonic,
        # wrong root), because root preference outranks the diatonic preference.
        restricted = [60, 63, 67]   # C4, Eb4, G4 → pcs {0, 3, 7}
        lead = [self._note(79, 0.0, 0.5)]   # G5
        chords = MusicAnvil.generate_chord_line(lead, restricted, 1, 0.5, scale_name="blues")
        self.assertTrue(chords, "No chord was generated")
        # Chord must be G-rooted (the extension chord), not C-rooted (the diatonic wrong root).
        self.assertEqual(min(n.pitch for n in chords) % 12, 7,
                         "Expected G-rooted extension chord but got a different root")


class TestSupportDerivation(unittest.TestCase):

    def setUp(self):
        piece = _make_piece(bars=2)
        piece.roles[MusicAnvil.ROLE_LEAD].supports = ["Violin"]
        piece.roles[MusicAnvil.ROLE_ACCOMPANIMENT].supports = ["Trumpet"]
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.tracks, _ = MusicAnvil.render_section(resolved, random.Random(42))

    def test_lead_support_is_subset_of_lead(self):
        lead = {(n.pitch, round(n.start, 6)) for n in self.tracks.get("Piano", [])}
        support = self.tracks.get("Violin", [])
        for note in support:
            self.assertIn((note.pitch, round(note.start, 6)), lead)

    def test_lead_support_only_even_beats(self):
        beat_len = MusicAnvil.beat_seconds(120, 4)
        for note in self.tracks.get("Violin", []):
            beat = int(round(note.start / beat_len))
            self.assertEqual(beat % 2, 0)

    def test_accompaniment_support_only_bar_head(self):
        beat_len = MusicAnvil.beat_seconds(120, 4)
        for note in self.tracks.get("Trumpet", []):
            beat_in_bar = int(round(note.start / beat_len)) % 4
            self.assertLess(beat_in_bar, 2)

    def test_supports_use_support_velocity(self):
        for name in ("Violin", "Trumpet"):
            for note in self.tracks.get(name, []):
                self.assertEqual(note.velocity, MusicAnvil.VELOCITY_SUPPORT)


class TestRenderPiece(unittest.TestCase):

    def test_returns_pretty_midi_with_expected_instruments(self):
        piece = _make_piece(structure=["A"])
        midi_data = MusicAnvil.render_piece(piece, random.Random(1))
        names = {inst.name for inst in midi_data.instruments}
        self.assertIn("Drums", names)
        self.assertIn("Piano", names)
        self.assertIn("Guitar", names)
        self.assertIn("Bass", names)
        drum_insts = [inst for inst in midi_data.instruments if inst.name == "Drums"]
        self.assertTrue(all(inst.is_drum for inst in drum_insts))

    def test_empty_structure_raises(self):
        piece = _make_piece(structure=[])
        with self.assertRaises(ValueError):
            MusicAnvil.render_piece(piece)

    def test_repeated_sections_are_identical(self):
        """The same library section must produce the same music at every occurrence."""
        piece = _make_piece(structure=["A", "A"], bars=2)
        section_len = MusicAnvil.section_seconds(2, 120, (4, 4))
        midi_data = MusicAnvil.render_piece(piece, random.Random(7))
        for instrument in midi_data.instruments:
            first = sorted((n.pitch, round(n.start, 6)) for n in instrument.notes
                           if n.start < section_len - 1e-9)
            second = sorted((n.pitch, round(n.start - section_len, 6)) for n in instrument.notes
                            if n.start >= section_len - 1e-9)
            self.assertEqual(first, second,
                             f"{instrument.name}: repeat of section A differs from the first occurrence")

    def test_sections_are_collated_in_order(self):
        """Total span of the rendered piece equals the sum of section durations."""
        piece = _make_piece(structure=["A", "A", "A"], bars=1)
        midi_data = MusicAnvil.render_piece(piece, random.Random(3))
        expected_total = MusicAnvil.piece_seconds(piece)
        max_end = max(n.end for inst in midi_data.instruments for n in inst.notes)
        self.assertLessEqual(max_end, expected_total + 1e-9)
        # Drums fill every section, so the last drum note must be in the final section.
        drums = next(inst for inst in midi_data.instruments if inst.name == "Drums")
        last_drum_start = max(n.start for n in drums.notes)
        self.assertGreater(last_drum_start, expected_total * 2 / 3)

    def test_per_section_tempo_override_changes_length(self):
        piece = _make_piece(structure=["A"], bars=2)
        base_len = MusicAnvil.piece_seconds(piece)
        piece.sections["A"].tempo = 60  # half speed -> double length
        self.assertAlmostEqual(MusicAnvil.piece_seconds(piece), base_len * 2)

    def test_unknown_instrument_name_raises(self):
        """An instrument name not in INSTRUMENT_PROGRAMS must raise ValueError, not silently use GM 0."""
        piece = _make_piece(structure=["A"])
        piece.roles[MusicAnvil.ROLE_LEAD] = MusicAnvil.RoleAssignment(main="NotARealInstrument")
        with self.assertRaises(ValueError) as ctx:
            MusicAnvil.render_piece(piece, random.Random(1))
        self.assertIn("NotARealInstrument", str(ctx.exception))

    def test_known_instrument_names_do_not_raise(self):
        """Every name in INSTRUMENT_PROGRAMS must render without error."""
        for name in MusicAnvil.INSTRUMENT_PROGRAMS:
            piece = _make_piece(structure=["A"])
            piece.roles[MusicAnvil.ROLE_LEAD] = MusicAnvil.RoleAssignment(main=name)
            try:
                MusicAnvil.render_piece(piece, random.Random(1))
            except ValueError as exc:
                self.fail(f"render_piece raised ValueError for known instrument '{name}': {exc}")


class TestTonicOctave(unittest.TestCase):
    """Tests for tonic_octave threading through PieceSpec → resolve_section → render."""

    def test_resolve_section_inherits_piece_tonic_octave(self):
        piece = _make_piece()
        piece.tonic_octave = 3
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tonic_octave, 3)

    def test_resolve_section_override_wins(self):
        piece = _make_piece()
        piece.tonic_octave = 3
        piece.sections["A"].tonic_octave = 5
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tonic_octave, 5)

    def test_resolve_section_none_override_inherits(self):
        piece = _make_piece()
        piece.tonic_octave = 2
        piece.sections["A"].tonic_octave = None
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tonic_octave, 2)

    def test_higher_tonic_octave_produces_higher_lead_pitches(self):
        piece_low = _make_piece()
        piece_low.tonic_octave = 2
        piece_high = _make_piece()
        piece_high.tonic_octave = 6
        midi_low = MusicAnvil.render_piece(piece_low, random.Random(42))
        midi_high = MusicAnvil.render_piece(piece_high, random.Random(42))
        piano_low = next(i for i in midi_low.instruments if i.name == "Piano")
        piano_high = next(i for i in midi_high.instruments if i.name == "Piano")
        avg_low = sum(n.pitch for n in piano_low.notes) / max(len(piano_low.notes), 1)
        avg_high = sum(n.pitch for n in piano_high.notes) / max(len(piano_high.notes), 1)
        self.assertGreater(avg_high, avg_low)

    def test_default_piece_tonic_octave_is_4(self):
        piece = MusicAnvil.PieceSpec()
        self.assertEqual(piece.tonic_octave, 4)

    def test_section_spec_tonic_octave_defaults_to_none(self):
        spec = MusicAnvil.SectionSpec(name="test")
        self.assertIsNone(spec.tonic_octave)


class TestStructureTransformers(unittest.TestCase):
    """Tests for StructureEntry transformer application inside render_piece."""

    def _pitches(self, midi_data, instrument_name):
        inst = next(i for i in midi_data.instruments if i.name == instrument_name)
        return sorted(n.pitch for n in inst.notes)

    def test_no_transformer_plain_string_still_works(self):
        piece = _make_piece(structure=["A"])
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertTrue(any(i.name == "Piano" for i in midi.instruments))

    def test_structure_entry_without_transformer_is_identical_to_string(self):
        piece_str = _make_piece(structure=["A"])
        piece_entry = _make_piece(structure=[MusicAnvil.StructureEntry(section="A")])
        midi_str = MusicAnvil.render_piece(piece_str, random.Random(5))
        midi_entry = MusicAnvil.render_piece(piece_entry, random.Random(5))
        self.assertEqual(self._pitches(midi_str, "Piano"), self._pitches(midi_entry, "Piano"))

    def test_tone_shift_raises_all_pitches(self):
        piece_base = _make_piece(structure=["A"])
        piece_shifted = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A", transformer="tone_shift",
                                      transformer_kwargs={"n": 12})])
        base = MusicAnvil.render_piece(piece_base, random.Random(7))
        shifted = MusicAnvil.render_piece(piece_shifted, random.Random(7))
        base_pitches = self._pitches(base, "Piano")
        shifted_pitches = self._pitches(shifted, "Piano")
        self.assertEqual(shifted_pitches, [p + 12 for p in base_pitches])

    def test_tone_shift_negative_lowers_pitches(self):
        piece_base = _make_piece(structure=["A"])
        piece_shifted = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A", transformer="tone_shift",
                                      transformer_kwargs={"n": -7})])
        base = MusicAnvil.render_piece(piece_base, random.Random(3))
        shifted = MusicAnvil.render_piece(piece_shifted, random.Random(3))
        base_pitches = self._pitches(base, "Piano")
        shifted_pitches = self._pitches(shifted, "Piano")
        self.assertEqual(shifted_pitches, [max(0, p - 7) for p in base_pitches])

    def test_invert_changes_non_first_pitches(self):
        piece_base = _make_piece(structure=["A"])
        piece_inv = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A", transformer="invert")])
        base = MusicAnvil.render_piece(piece_base, random.Random(9))
        inv = MusicAnvil.render_piece(piece_inv, random.Random(9))
        base_p = self._pitches(base, "Piano")
        inv_p = self._pitches(inv, "Piano")
        # At least one pitch must differ (invert is not an identity)
        self.assertNotEqual(base_p, inv_p)

    def test_drums_not_affected_by_tone_shift(self):
        piece_base = _make_piece(structure=["A"])
        piece_shifted = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A", transformer="tone_shift",
                                      transformer_kwargs={"n": 12})])
        base = MusicAnvil.render_piece(piece_base, random.Random(2))
        shifted = MusicAnvil.render_piece(piece_shifted, random.Random(2))
        drums_base = sorted(n.pitch for i in base.instruments
                            if i.name == MusicAnvil.DRUM_TRACK for n in i.notes)
        drums_shifted = sorted(n.pitch for i in shifted.instruments
                               if i.name == MusicAnvil.DRUM_TRACK for n in i.notes)
        self.assertEqual(drums_base, drums_shifted)

    def test_two_occurrences_different_transformers(self):
        """Same section with different transformers must produce different note sets."""
        piece = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A"),
            MusicAnvil.StructureEntry(section="A", transformer="tone_shift",
                                      transformer_kwargs={"n": 5}),
        ])
        midi = MusicAnvil.render_piece(piece, random.Random(4))
        section_len = MusicAnvil.section_seconds(2, 120, (4, 4))
        piano = next(i for i in midi.instruments if i.name == "Piano")
        first_pitches = sorted(n.pitch for n in piano.notes if n.start < section_len - 1e-9)
        second_pitches = sorted(n.pitch for n in piano.notes if n.start >= section_len - 1e-9)
        self.assertEqual(second_pitches, [p + 5 for p in first_pitches])

    def test_unknown_transformer_raises(self):
        piece = _make_piece(structure=[
            MusicAnvil.StructureEntry(section="A", transformer="no_such_transform")])
        with self.assertRaises(ValueError):
            MusicAnvil.render_piece(piece, random.Random(1))


class TestDrumPatternTiling(unittest.TestCase):
    """Drum patterns must repeat at the bar length, not at max note-end time.

    Regression for: render_section used max(entry[3] for entry in adapted) as
    pattern_len. For Waltz the last drum note ends at beat 2.5, but the bar is
    3 beats, causing the pattern to tile 0.5 beats too early every bar.
    """

    def _render_drums(self, rhythm, signature, bars=2, tempo=120):
        piece = MusicAnvil.PieceSpec(
            tempo=tempo,
            signature=signature,
            rhythm=rhythm,
            scale="major",
            tonic="C",
            roles={
                MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano"),
                MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(),
            },
        )
        section = MusicAnvil.SectionSpec(name="A", bars=bars)
        resolved = MusicAnvil.resolve_section(section, piece)
        tracks, _ = MusicAnvil.render_section(resolved, random.Random(1))
        return tracks[MusicAnvil.DRUM_TRACK]

    def _bass_drum_starts_at_bar_boundaries(self, drum_notes, bar_len):
        """Sorted start times of bass drum notes that land exactly on a bar boundary."""
        bass_pitch = ma_utils.drum_pitches["Bass Drum"]
        return sorted(
            round(n.start, 6)
            for n in drum_notes
            if n.pitch == bass_pitch and round(n.start % bar_len, 9) < 1e-6
        )

    def test_waltz_pattern_tiles_at_bar_boundary(self):
        """Waltz: last note ends at beat 2.5, bar = 3 beats → tile period is 1.5 s."""
        beat_len = MusicAnvil.beat_seconds(120, 4)   # 0.5 s
        bar_len = 3 * beat_len                         # 1.5 s
        drum_notes = self._render_drums("Waltz", (3, 4))
        starts = self._bass_drum_starts_at_bar_boundaries(drum_notes, bar_len)
        self.assertEqual(starts, [0.0, round(bar_len, 6)],
                         f"Expected bass drum at bar starts [0.0, {bar_len}], got {starts}")

    def test_bossa_nova_pattern_tiles_at_bar_boundary(self):
        """Bossa Nova: last note ends at beat 3, bar = 4 beats → tile period is 2.0 s."""
        beat_len = MusicAnvil.beat_seconds(120, 4)   # 0.5 s
        bar_len = 4 * beat_len                         # 2.0 s
        drum_notes = self._render_drums("Bossa Nova", (4, 4))
        starts = self._bass_drum_starts_at_bar_boundaries(drum_notes, bar_len)
        self.assertEqual(starts, [0.0, round(bar_len, 6)],
                         f"Expected bass drum at bar starts [0.0, {bar_len}], got {starts}")

    def test_all_drum_notes_within_section_length(self):
        """Every drum note — including tiled repetitions — must end within the section."""
        beat_len = MusicAnvil.beat_seconds(120, 4)
        section_len = 2 * 3 * beat_len  # 2 bars of 3/4 at 120 BPM
        drum_notes = self._render_drums("Waltz", (3, 4))
        for note in drum_notes:
            self.assertLessEqual(note.end, section_len + 1e-9,
                                 f"Drum note ends at {note.end}, beyond section length {section_len}")


if __name__ == "__main__":
    unittest.main()
