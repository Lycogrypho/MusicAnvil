"""Tests for the piece composition engine (musicanvil.MusicAnvil)."""

# OopCompanion:suppressRename

import os
import random
import tempfile
import unittest
import warnings
from unittest.mock import patch

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


class TestTempoChangeEvents(unittest.TestCase):
    """P3 #15 — render_piece must write MIDI tempo-change events at section boundaries."""

    def _make_two_section_piece(self, tempo_a=120, tempo_b=200):
        piece = MusicAnvil.PieceSpec(
            tempo=tempo_a,
            signature=(4, 4),
            rhythm="Rock",
            scale="major",
            tonic="C",
            roles={
                MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano"),
                MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(),
            },
            sections={
                "A": MusicAnvil.SectionSpec(name="A", bars=2),
                "B": MusicAnvil.SectionSpec(name="B", bars=2, tempo=tempo_b),
            },
            structure=["A", "B"],
        )
        return piece

    def test_single_tempo_piece_has_one_tempo_event(self):
        piece = _make_piece(structure=["A"], bars=2)
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        _, tempos = midi.get_tempo_changes()
        self.assertEqual(len(tempos), 1)
        self.assertAlmostEqual(tempos[0], 120.0, places=1)

    def test_tempo_change_event_written_for_section_override(self):
        piece = self._make_two_section_piece(tempo_a=120, tempo_b=200)
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        _, tempos = midi.get_tempo_changes()
        self.assertIn(True, [abs(t - 120.0) < 0.5 for t in tempos],
                      "Expected a 120 BPM tempo event")
        self.assertIn(True, [abs(t - 200.0) < 0.5 for t in tempos],
                      "Expected a 200 BPM tempo event")

    def test_tempo_change_occurs_at_correct_time(self):
        piece = self._make_two_section_piece(tempo_a=120, tempo_b=200)
        section_a_len = MusicAnvil.section_seconds(2, 120, (4, 4))
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        times, tempos = midi.get_tempo_changes()
        change_times_for_200 = [t for t, bpm in zip(times, tempos) if abs(bpm - 200.0) < 0.5]
        self.assertEqual(len(change_times_for_200), 1)
        self.assertAlmostEqual(change_times_for_200[0], section_a_len, places=2)

    def test_matching_tempo_sections_produce_one_event(self):
        """When every section shares the piece tempo, only the initial event is written."""
        piece = _make_piece(structure=["A", "A"], bars=2)
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        _, tempos = midi.get_tempo_changes()
        self.assertEqual(len(tempos), 1)

    def test_tempo_reverting_to_piece_default_writes_event(self):
        piece = MusicAnvil.PieceSpec(
            tempo=120,
            signature=(4, 4),
            rhythm="Rock",
            scale="major",
            tonic="C",
            roles={
                MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano"),
                MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(),
            },
            sections={
                "A": MusicAnvil.SectionSpec(name="A", bars=2),
                "B": MusicAnvil.SectionSpec(name="B", bars=2, tempo=200),
                "C": MusicAnvil.SectionSpec(name="C", bars=2),
            },
            structure=["A", "B", "C"],
        )
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        _, tempos = midi.get_tempo_changes()
        # Three distinct tempo events: 120 → 200 → 120
        self.assertEqual(len(tempos), 3)


class TestTempoInternalsGuard(unittest.TestCase):
    """ToDo 2.1 — _insert_midi_tempo_change reaches into private pretty_midi members.

    The guard must (a) tell us loudly, via a failing test, when a pretty_midi upgrade
    renames them, and (b) degrade to a warning at render time instead of raising
    AttributeError in the middle of a piece.
    """

    def _two_tempo_piece(self):
        piece = _make_piece(structure=["A", "B"], bars=1)
        piece.sections["B"] = MusicAnvil.SectionSpec(name="B", bars=1, tempo=200)
        return piece

    def test_pinned_pretty_midi_still_exposes_the_internals(self):
        """Fails on a dependency bump that renames/removes what we depend on."""
        missing = MusicAnvil._missing_tempo_internals(pretty_midi.PrettyMIDI())
        self.assertEqual(
            missing, [],
            f"pretty_midi no longer exposes {missing}; _insert_midi_tempo_change must be "
            "reworked against the new internals (it currently falls back to no tempo map).",
        )

    def test_insertion_reports_success_on_the_pinned_version(self):
        midi = pretty_midi.PrettyMIDI(initial_tempo=120)
        self.assertTrue(MusicAnvil._insert_midi_tempo_change(midi, 2.0, 200))
        _, tempos = midi.get_tempo_changes()
        self.assertEqual(len(tempos), 2)

    def test_missing_internals_warn_and_return_false(self):
        class Stripped:
            """A pretty_midi that renamed its internals away."""
            resolution = 220

            def time_to_tick(self, time):
                return 0

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            inserted = MusicAnvil._insert_midi_tempo_change(Stripped(), 0.0, 200)
        self.assertFalse(inserted)
        self.assertEqual(len(caught), 1)
        self.assertTrue(issubclass(caught[0].category, RuntimeWarning))
        self.assertIn("_tick_scales", str(caught[0].message))

    def test_internal_failure_is_caught_and_warned(self):
        """Internals present but behaving differently must not escape as an exception."""
        midi = pretty_midi.PrettyMIDI(initial_tempo=120)
        with patch.object(type(midi), "time_to_tick",
                          side_effect=AttributeError("renamed"), create=True):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                inserted = MusicAnvil._insert_midi_tempo_change(midi, 1.0, 200)
        self.assertFalse(inserted)
        self.assertTrue(caught and issubclass(caught[0].category, RuntimeWarning))

    def test_render_piece_still_renders_when_the_internals_are_gone(self):
        piece = self._two_tempo_piece()
        with patch.object(MusicAnvil, "_TEMPO_INTERNALS", ("_no_such_attribute",)):
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertIsInstance(midi, pretty_midi.PrettyMIDI)
        self.assertTrue(any(inst.notes for inst in midi.instruments),
                        "the piece must still contain notes without a tempo map")
        self.assertTrue(any(issubclass(w.category, RuntimeWarning) for w in caught),
                        "the fallback must warn that the tempo map was skipped")

    def test_fallback_render_is_still_writable(self):
        piece = self._two_tempo_piece()
        with patch.object(MusicAnvil, "_TEMPO_INTERNALS", ("_no_such_attribute",)):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                midi = MusicAnvil.render_piece(piece, random.Random(1))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fallback.mid")
            midi.write(path)
            self.assertTrue(os.path.getsize(path) > 0)

    def test_normal_render_emits_no_warning(self):
        piece = self._two_tempo_piece()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            MusicAnvil.render_piece(piece, random.Random(1))
        runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        self.assertEqual(runtime_warnings, [])


class TestTimeSignatureEvents(unittest.TestCase):
    """ToDo 2.2 — render_piece must write MIDI time-signature events, at time 0 and at
    every section boundary where the resolved signature changes."""

    def _piece(self, piece_signature=(4, 4), section_signatures=(None,)):
        sections = {}
        structure = []
        for index, signature in enumerate(section_signatures):
            name = f"S{index}"
            sections[name] = MusicAnvil.SectionSpec(name=name, bars=1, signature=signature)
            structure.append(name)
        return MusicAnvil.PieceSpec(
            tempo=120,
            signature=piece_signature,
            rhythm="Rock",
            scale="major",
            tonic="C",
            roles={
                MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano"),
                MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(),
            },
            sections=sections,
            structure=structure,
        )

    @staticmethod
    def _events(midi):
        return [(ts.numerator, ts.denominator, round(ts.time, 6))
                for ts in midi.time_signature_changes]

    def test_piece_signature_is_written_at_time_zero(self):
        midi = MusicAnvil.render_piece(self._piece((3, 4)), random.Random(1))
        self.assertEqual(self._events(midi), [(3, 4, 0.0)])

    def test_default_four_four_is_written_too(self):
        """Even the default signature is emitted, so nothing relies on the DAW's guess."""
        midi = MusicAnvil.render_piece(self._piece((4, 4)), random.Random(1))
        self.assertEqual(self._events(midi), [(4, 4, 0.0)])

    def test_first_section_override_replaces_the_opening_signature(self):
        piece = self._piece((4, 4), section_signatures=[(6, 8)])
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertEqual(self._events(midi), [(6, 8, 0.0)])

    def test_section_change_lands_at_the_section_boundary(self):
        piece = self._piece((4, 4), section_signatures=[None, (3, 4)])
        first_section = MusicAnvil.section_seconds(1, 120, (4, 4))  # 2.0 s
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertEqual(self._events(midi),
                         [(4, 4, 0.0), (3, 4, round(first_section, 6))])

    def test_unchanged_signature_writes_no_extra_event(self):
        piece = self._piece((4, 4), section_signatures=[None, None, None])
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertEqual(self._events(midi), [(4, 4, 0.0)])

    def test_reverting_to_the_piece_signature_writes_an_event(self):
        piece = self._piece((4, 4), section_signatures=[None, (3, 4), None])
        bar_4_4 = MusicAnvil.section_seconds(1, 120, (4, 4))
        bar_3_4 = MusicAnvil.section_seconds(1, 120, (3, 4))
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertEqual(self._events(midi), [
            (4, 4, 0.0),
            (3, 4, round(bar_4_4, 6)),
            (4, 4, round(bar_4_4 + bar_3_4, 6)),
        ])

    def test_events_survive_a_write_read_round_trip(self):
        piece = self._piece((4, 4), section_signatures=[None, (3, 4)])
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "signatures.mid")
            midi.write(path)
            reloaded = pretty_midi.PrettyMIDI(path)
        events = [(ts.numerator, ts.denominator) for ts in reloaded.time_signature_changes]
        self.assertEqual(events, [(4, 4), (3, 4)])
        boundary = MusicAnvil.section_seconds(1, 120, (4, 4))
        self.assertAlmostEqual(reloaded.time_signature_changes[1].time, boundary, places=2)

    def test_signature_events_coexist_with_tempo_changes(self):
        piece = self._piece((4, 4), section_signatures=[None, (3, 4)])
        piece.sections["S1"].tempo = 200
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        boundary = MusicAnvil.section_seconds(1, 120, (4, 4))
        _, tempos = midi.get_tempo_changes()
        self.assertEqual(len(tempos), 2)
        self.assertEqual(self._events(midi), [(4, 4, 0.0), (3, 4, round(boundary, 6))])

    def test_nonstandard_denominator_is_skipped_with_a_warning(self):
        """A denominator that is not a power of two cannot be encoded in MIDI."""
        piece = self._piece((6, 12))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            midi = MusicAnvil.render_piece(piece, random.Random(1))
        self.assertEqual(self._events(midi), [])
        self.assertTrue(any("6/12" in str(w.message) for w in caught),
                        "expected a warning naming the unrepresentable signature")

    def test_is_power_of_two_helper(self):
        for good in (1, 2, 4, 8, 16, 32):
            self.assertTrue(MusicAnvil._is_power_of_two(good), good)
        for bad in (0, -4, 3, 6, 12, 20):
            self.assertFalse(MusicAnvil._is_power_of_two(bad), bad)


class TestDrumPatternFollowsSignature(unittest.TestCase):
    """ToDo 3.1 — the drum pattern must fill the bar of the section's signature instead
    of assuming a 4-quarter-note bar."""

    def _drums(self, rhythm, signature, bars=2, tempo=120):
        piece = MusicAnvil.PieceSpec(
            tempo=tempo,
            signature=signature,
            rhythm=rhythm,
            scale="major",
            tonic="C",
            roles={
                MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(),
                MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(),
            },
        )
        resolved = MusicAnvil.resolve_section(
            MusicAnvil.SectionSpec(name="A", bars=bars), piece)
        tracks, length = MusicAnvil.render_section(resolved, random.Random(1))
        return tracks[MusicAnvil.DRUM_TRACK], length

    def test_four_four_rendering_is_unchanged(self):
        """The 4/4 case must still be the plain adapted pattern, bar after bar."""
        drums, _ = self._drums("Rock", (4, 4), bars=2)
        expected = ma_utils.adapt_drum_line(ma_utils.drum_lines["Rock"], 120)
        bar_len = 4 * MusicAnvil.beat_seconds(120, 4)
        got = sorted((round(n.start, 6), n.pitch) for n in drums)
        want = sorted([(round(entry[2] + bar * bar_len, 6), entry[1])
                       for bar in (0, 1) for entry in expected])
        self.assertEqual(got, want)

    def test_no_drum_note_crosses_a_bar_line_in_three_four(self):
        """3/4 with a 4-beat pattern: the 4th beat used to spill onto the next downbeat."""
        drums, _ = self._drums("Rock", (3, 4), bars=4)
        bar_len = 3 * MusicAnvil.beat_seconds(120, 4)
        for note in drums:
            bar = int(note.start // bar_len + 1e-9)
            self.assertLessEqual(note.end, (bar + 1) * bar_len + 1e-9,
                                 f"drum note {note.start}-{note.end} crosses the bar line")

    def test_three_four_downbeat_hits_only_the_pattern_start(self):
        """Every bar must open with the pattern's first hit, not a leftover from the last."""
        drums, _ = self._drums("Rock", (3, 4), bars=4)
        bar_len = 3 * MusicAnvil.beat_seconds(120, 4)
        bass_pitch = ma_utils.drum_pitches["Bass Drum"]
        snare_pitch = ma_utils.drum_pitches["Snare Drum"]
        downbeat_pitches = {n.pitch for n in drums
                            if abs(n.start % bar_len) < 1e-9 or abs(n.start % bar_len - bar_len) < 1e-9}
        self.assertIn(bass_pitch, downbeat_pitches)
        self.assertNotIn(snare_pitch, downbeat_pitches,
                         "a snare on the downbeat means the previous bar overran")

    def test_eighth_signature_bar_is_filled_end_to_end(self):
        """6/8: a 4-beat pattern must repeat to cover all six eighths, leaving no gap."""
        drums, length = self._drums("Rock", (6, 8), bars=1)
        beat = MusicAnvil.beat_seconds(120, 8)
        starts = sorted({round(n.start / beat, 6) for n in drums})
        self.assertEqual(starts, [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(length, 6 * beat)

    def test_all_notes_stay_inside_the_section(self):
        for rhythm in ("Rock", "Waltz", "Metal", "Jazz"):
            for signature in ((4, 4), (3, 4), (6, 8), (5, 4)):
                with self.subTest(rhythm=rhythm, signature=signature):
                    drums, length = self._drums(rhythm, signature, bars=2)
                    self.assertTrue(drums)
                    for note in drums:
                        self.assertGreaterEqual(note.start, -1e-9)
                        self.assertLessEqual(note.end, length + 1e-9)

    def test_waltz_pattern_fills_a_four_four_bar(self):
        """The 3-beat Waltz pattern repeats to cover the 4th beat of a 4/4 bar."""
        drums, _ = self._drums("Waltz", (4, 4), bars=1)
        beat = MusicAnvil.beat_seconds(120, 4)
        latest = max(n.start for n in drums)
        self.assertGreaterEqual(latest, 3 * beat - 1e-9,
                                "the 4th beat of the bar was left silent")


if __name__ == "__main__":
    unittest.main()
