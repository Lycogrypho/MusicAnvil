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

    def test_supports_are_quieter_than_their_main_line(self):
        """Support velocities start from VELOCITY_SUPPORT; the metre then accents them
        (ToDo 4.3), so the exact value depends on the bar position — but a support note
        can never be louder than its main line at the same position."""
        span = MusicAnvil.PieceSpec().metric_accent
        for name in ("Violin", "Trumpet"):
            notes = self.tracks.get(name, [])
            self.assertTrue(notes, name)
            for note in notes:
                self.assertLessEqual(note.velocity, MusicAnvil.VELOCITY_SUPPORT + span)
                self.assertLess(note.velocity, MusicAnvil.VELOCITY_LEAD)

    def test_supports_use_support_velocity_without_accents(self):
        """With the metric accent switched off, the base velocity is untouched."""
        piece = _make_piece(bars=2)
        piece.metric_accent = 0
        piece.auto_cadence = False      # the cadence swell is 4.6's, not the base velocity
        piece.roles[MusicAnvil.ROLE_LEAD].supports = ["Violin"]
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        tracks, _ = MusicAnvil.render_section(resolved, random.Random(3))
        self.assertTrue(tracks.get("Violin"))
        for note in tracks["Violin"]:
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


class TestMetricAccents(unittest.TestCase):
    """ToDo 4.3 — velocity must follow the metre, not a symmetric random jitter."""

    def _ctx(self, signature=(4, 4), bars=2):
        piece = _make_piece(bars=bars)
        piece.signature = signature
        return MusicAnvil.make_render_context(
            MusicAnvil.resolve_section(piece.sections["A"], piece))

    def _events(self, ctx, subs):
        return [MusicAnvil.NoteEvent(start_sub=s, length_sub=1, pitch=60, velocity=90)
                for s in subs]

    def test_accent_delta_is_zero_on_a_plain_beat(self):
        weights = ma_utils.metric_accents
        self.assertEqual(MusicAnvil.accent_delta(weights["beat"], 12), 0)

    def test_accent_delta_matches_the_requested_span_on_the_downbeat(self):
        self.assertEqual(MusicAnvil.accent_delta(ma_utils.metric_accents["downbeat"], 12), 12)
        self.assertEqual(MusicAnvil.accent_delta(ma_utils.metric_accents["downbeat"], 20), 20)

    def test_accent_delta_is_negative_off_the_beat(self):
        self.assertLess(MusicAnvil.accent_delta(ma_utils.metric_accents["offbeat"], 12), 0)

    def test_accent_delta_of_zero_amount_is_zero(self):
        for weight in ma_utils.metric_accents.values():
            self.assertEqual(MusicAnvil.accent_delta(weight, 0), 0)

    def test_downbeat_is_louder_than_offbeat(self):
        ctx = self._ctx()
        events = self._events(ctx, [0, 1, ctx.subs_per_beat, 2 * ctx.subs_per_beat])
        MusicAnvil.apply_metric_accents(events, ctx, amount=12)
        downbeat, offbeat, beat_two, beat_three = events
        self.assertGreater(downbeat.velocity, beat_two.velocity)
        self.assertGreater(beat_two.velocity, offbeat.velocity)
        self.assertGreater(beat_three.velocity, beat_two.velocity)  # middle of the bar

    def test_metric_weight_is_recorded_on_the_event(self):
        ctx = self._ctx()
        events = self._events(ctx, [0, 1])
        MusicAnvil.apply_metric_accents(events, ctx, amount=12)
        self.assertEqual(events[0].metric_weight, ma_utils.metric_accents["downbeat"])
        self.assertEqual(events[1].metric_weight, ma_utils.metric_accents["offbeat"])

    def test_zero_amount_leaves_velocities_untouched(self):
        ctx = self._ctx()
        events = self._events(ctx, [0, 1, 5])
        MusicAnvil.apply_metric_accents(events, ctx, amount=0)
        self.assertEqual([e.velocity for e in events], [90, 90, 90])

    def test_intensity_scales_the_whole_section(self):
        ctx = self._ctx()
        quiet = self._events(ctx, [0, 4])
        loud = self._events(ctx, [0, 4])
        MusicAnvil.apply_metric_accents(quiet, ctx, amount=0, intensity=0.5)
        MusicAnvil.apply_metric_accents(loud, ctx, amount=0, intensity=1.2)
        self.assertEqual([e.velocity for e in quiet], [45, 45])
        self.assertEqual([e.velocity for e in loud], [108, 108])

    def test_velocities_stay_in_the_midi_range(self):
        ctx = self._ctx()
        events = [MusicAnvil.NoteEvent(start_sub=0, length_sub=1, pitch=60, velocity=126),
                  MusicAnvil.NoteEvent(start_sub=1, length_sub=1, pitch=60, velocity=2)]
        MusicAnvil.apply_metric_accents(events, ctx, amount=40, intensity=2.0)
        for event in events:
            self.assertGreaterEqual(event.velocity, 1)
            self.assertLessEqual(event.velocity, 127)

    def test_compound_signature_accents_every_third_beat(self):
        ctx = self._ctx(signature=(6, 8))
        events = self._events(ctx, [0, ctx.subs_per_beat, 3 * ctx.subs_per_beat])
        MusicAnvil.apply_metric_accents(events, ctx, amount=12)
        downbeat, beat_two, beat_four = events
        self.assertGreater(downbeat.velocity, beat_four.velocity)
        self.assertGreater(beat_four.velocity, beat_two.velocity)

    def test_drums_are_accented_too(self):
        ctx = self._ctx()
        offbeat = ctx.beat_len / 2
        notes = [pretty_midi.Note(velocity=90, pitch=35, start=0.0, end=0.1),
                 pretty_midi.Note(velocity=90, pitch=42, start=offbeat, end=offbeat + 0.1)]
        shaped = MusicAnvil.apply_drum_accents(notes, ctx, amount=12)
        self.assertGreater(shaped[0].velocity, shaped[1].velocity)
        self.assertEqual([n.pitch for n in shaped], [35, 42])
        self.assertEqual([n.start for n in shaped], [n.start for n in notes])

    def test_rendered_lead_is_louder_on_downbeats_than_off_the_beat(self):
        piece = _make_piece(bars=4)
        piece.lead_velocity_jitter = 0            # isolate the metric contribution
        piece.lead_rest_prob = 0.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(11))
        lead = rendered.events["Piano"]
        downbeats = [e.velocity for e in lead if e.start_sub % rendered.context.subs_per_bar == 0]
        offbeats = [e.velocity for e in lead if e.start_sub % rendered.context.subs_per_beat != 0]
        self.assertTrue(downbeats and offbeats)
        self.assertGreater(min(downbeats), max(offbeats))

    def test_section_intensity_override_changes_the_rendered_velocities(self):
        piece = _make_piece(bars=2)
        piece.lead_velocity_jitter = 0
        loud = MusicAnvil.resolve_section(piece.sections["A"], piece)
        piece.sections["A"].intensity = 0.6
        quiet = MusicAnvil.resolve_section(piece.sections["A"], piece)
        loud_tracks, _ = MusicAnvil.render_section(loud, random.Random(4))
        quiet_tracks, _ = MusicAnvil.render_section(quiet, random.Random(4))
        loud_notes = loud_tracks["Piano"]
        quiet_notes = quiet_tracks["Piano"]
        self.assertEqual(len(loud_notes), len(quiet_notes))
        self.assertTrue(all(q.velocity < l.velocity
                            for q, l in zip(quiet_notes, loud_notes)))

    def test_intensity_defaults_to_neutral(self):
        self.assertEqual(MusicAnvil.PieceSpec().intensity, 1.0)
        self.assertIsNone(MusicAnvil.SectionSpec(name="x").intensity)


class TestFinalLengthening(unittest.TestCase):
    """ToDo 4.4 — the last note of a phrase must be held, not cut off."""

    def _setup(self, bars=4, phrase_bars=2):
        piece = _make_piece(bars=bars)
        piece.sections["A"].phrase_bars = phrase_bars
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        ctx = MusicAnvil.make_render_context(resolved)
        phrases = MusicAnvil.plan_phrases(ctx, phrase_bars)
        return ctx, phrases

    def _events(self, ctx, phrases, starts, length_sub=2, gate=0.8):
        events = [MusicAnvil.NoteEvent(start_sub=s, length_sub=length_sub, pitch=60,
                                       velocity=90, gate=gate) for s in starts]
        MusicAnvil.assign_phrases(events, ctx, phrases)
        return events

    def test_phrase_final_note_is_stretched(self):
        ctx, phrases = self._setup()
        first_phrase_end = phrases[0].end_beat * ctx.subs_per_beat
        events = self._events(ctx, phrases, [0, first_phrase_end - 8])
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=2.0)
        self.assertEqual(events[0].length_sub, 2)      # not phrase-final
        self.assertEqual(events[1].length_sub, 4)      # phrase-final, doubled

    def test_phrase_final_note_rings_to_its_full_length(self):
        ctx, phrases = self._setup()
        events = self._events(ctx, phrases, [0, 8], gate=0.8)
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=2.0)
        final = [e for e in events if e.is_phrase_final][0]
        self.assertEqual(final.gate, 1.0)

    def test_a_stretched_note_never_crosses_the_phrase_boundary(self):
        ctx, phrases = self._setup()
        for phrase in phrases:
            end_sub = phrase.end_beat * ctx.subs_per_beat
            events = self._events(ctx, phrases, [end_sub - 2], length_sub=2)
            MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=8.0)
            self.assertLessEqual(events[0].end_sub, end_sub)

    def test_a_note_already_reaching_the_boundary_is_not_shortened(self):
        """Lengthening must never take time away — a note tied over the phrase end keeps
        the length the generator gave it."""
        ctx, phrases = self._setup()
        end_sub = phrases[0].end_beat * ctx.subs_per_beat
        events = self._events(ctx, phrases, [end_sub - 2], length_sub=6)
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=2.0)
        self.assertEqual(events[0].length_sub, 6)

    def test_factor_one_disables_the_pass(self):
        ctx, phrases = self._setup()
        events = self._events(ctx, phrases, [0, 8], gate=0.8)
        before = [(e.length_sub, e.gate) for e in events]
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=1.0)
        self.assertEqual([(e.length_sub, e.gate) for e in events], before)

    def test_non_final_notes_are_untouched(self):
        ctx, phrases = self._setup()
        events = self._events(ctx, phrases, [0, 4, 8], gate=0.8)
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=3.0)
        for event in events:
            if not event.is_phrase_final:
                self.assertEqual((event.length_sub, event.gate), (2, 0.8))

    def test_every_phrase_gets_a_lengthened_note(self):
        ctx, phrases = self._setup(bars=4, phrase_bars=1)
        starts = [phrase.start_beat * ctx.subs_per_beat for phrase in phrases]
        starts += [phrase.end_beat * ctx.subs_per_beat - 4 for phrase in phrases]
        events = self._events(ctx, phrases, sorted(starts))
        MusicAnvil.apply_final_lengthening(events, ctx, phrases, factor=2.0)
        stretched = {e.phrase for e in events if e.length_sub > 2}
        self.assertEqual(stretched, {phrase.index for phrase in phrases})

    def test_rendered_phrase_endings_sound_longer_than_without_the_pass(self):
        """Same seed, pass on vs off: no phrase ending may get shorter and at least one
        must get longer."""
        def render(factor):
            piece = _make_piece(bars=4)
            piece.sections["A"].phrase_bars = 2
            piece.auto_cadence = False      # isolate the agogic pass from 4.6's cadences
            piece.final_lengthening = factor
            resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
            rendered = MusicAnvil._render_section_events(resolved, random.Random(9))
            notes = MusicAnvil.materialise(rendered.events["Piano"], rendered.context)
            finals = [i for i, e in enumerate(rendered.events["Piano"]) if e.is_phrase_final]
            return [notes[i].end - notes[i].start for i in finals]

        plain, stretched = render(1.0), render(2.0)
        self.assertEqual(len(plain), len(stretched))
        self.assertTrue(all(s >= p - 1e-9 for p, s in zip(plain, stretched)))
        self.assertTrue(any(s > p + 1e-9 for p, s in zip(plain, stretched)),
                        "no phrase ending was actually lengthened")

    def test_rendered_phrase_endings_sound_to_the_end_of_their_note(self):
        piece = _make_piece(bars=4)
        piece.final_lengthening = 2.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(9))
        for event in rendered.events["Piano"]:
            if event.is_phrase_final:
                self.assertEqual(event.gate, 1.0)

    def test_notes_still_stay_inside_the_section(self):
        piece = _make_piece(bars=4)
        piece.final_lengthening = 4.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        tracks, length = MusicAnvil.render_section(resolved, random.Random(9))
        for notes in tracks.values():
            for note in notes:
                self.assertLessEqual(note.end, length + 1e-9)

    def test_section_override_wins(self):
        piece = _make_piece(bars=2)
        piece.final_lengthening = 1.0
        piece.sections["A"].final_lengthening = 3.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.final_lengthening, 3.0)

    def test_default_comes_from_the_config(self):
        self.assertEqual(MusicAnvil.PieceSpec().final_lengthening,
                         ma_utils.get_param("piece_defaults", "final_lengthening"))


class TestRhythmicMotif(unittest.TestCase):
    """ToDo 4.2 — the melody must state a motif, repeat it and then fragment it."""

    def _ctx(self, bars=4, signature=(4, 4)):
        piece = _make_piece(bars=bars)
        piece.signature = signature
        return MusicAnvil.make_render_context(
            MusicAnvil.resolve_section(piece.sections["A"], piece))

    def test_make_cell_spans_one_bar_by_default(self):
        ctx = self._ctx()
        cell = MusicAnvil.make_cell(ctx, random.Random(2))
        self.assertEqual(cell.length_sub, ctx.subs_per_bar)

    def test_make_cell_respects_an_explicit_length(self):
        ctx = self._ctx(bars=4)
        cell = MusicAnvil.make_cell(ctx, random.Random(2), bars=2)
        self.assertEqual(cell.length_sub, 2 * ctx.subs_per_bar)

    def test_cell_never_outlasts_the_section(self):
        ctx = self._ctx(bars=1)
        cell = MusicAnvil.make_cell(ctx, random.Random(2), bars=8)
        self.assertLessEqual(cell.length_sub, ctx.total_sub)

    def test_fragmentation_states_the_first_half_twice(self):
        cell = MusicAnvil.RhythmCell(onsets=[(0, 4), (4, 4), (8, 8)], length_sub=16)
        fragment = cell.fragmented()
        self.assertEqual(fragment.onsets, [(0, 4), (4, 4), (8, 4), (12, 4)])
        self.assertEqual(fragment.length_sub, 16)

    def test_fragmentation_of_a_single_note_cell_is_safe(self):
        cell = MusicAnvil.RhythmCell(onsets=[(0, 16)], length_sub=16)
        fragment = cell.fragmented()
        self.assertEqual(fragment.onsets, [(0, 8), (8, 8)])

    def test_tiling_fills_the_section(self):
        cell = MusicAnvil.RhythmCell(onsets=[(0, 4), (4, 4)], length_sub=8)
        positions = cell.tile(24)
        self.assertEqual(positions[0][0], 0)
        self.assertEqual(positions[-1][0] + positions[-1][1], 24)

    def test_tiling_switches_to_the_fragment_in_the_continuation(self):
        cell = MusicAnvil.RhythmCell(onsets=[(0, 8)], length_sub=8)
        positions = cell.tile(16, continuation_from=8)
        self.assertEqual(positions, [(0, 8), (8, 4), (12, 4)])

    def test_tiling_never_starts_a_note_past_the_end(self):
        cell = MusicAnvil.RhythmCell(onsets=[(0, 4), (4, 4)], length_sub=8)
        for start, length in cell.tile(10):
            self.assertLess(start, 10)
            self.assertLessEqual(start + length, 10)

    def test_the_melody_repeats_its_cell_bar_after_bar(self):
        """With rests switched off, the presentation bars must share one onset pattern —
        the property that a stream of independent random durations cannot have."""
        piece = _make_piece(bars=4)
        piece.lead_rest_prob = 0.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(6))
        ctx = rendered.context
        bars = {}
        for event in rendered.events["Piano"]:
            bars.setdefault(event.start_sub // ctx.subs_per_bar, []).append(
                (event.start_sub % ctx.subs_per_bar, event.length_sub))
        self.assertEqual(bars[0], bars[1], "the motif was not repeated")

    def test_note_lengths_are_not_uniformly_distributed(self):
        """The old generator drew every length from randint(1, 8); the cell vocabulary is
        weighted towards short values."""
        piece = _make_piece(bars=8)
        piece.lead_rest_prob = 0.0
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(6))
        lengths = [e.length_sub for e in rendered.events["Piano"]]
        self.assertGreater(sum(1 for l in lengths if l <= 2), len(lengths) / 2)

    def test_syncopation_puts_more_notes_off_the_beat(self):
        def off_beat_share(amount):
            total = off = 0
            for seed in range(6):
                piece = _make_piece(bars=4)
                piece.lead_rest_prob = 0.0
                piece.lead_syncopation = amount
                resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
                rendered = MusicAnvil._render_section_events(resolved, random.Random(seed))
                spb = rendered.context.subs_per_beat
                for event in rendered.events["Piano"]:
                    total += 1
                    off += 1 if event.start_sub % spb else 0
            return off / max(1, total)

        self.assertGreater(off_beat_share(1.0), off_beat_share(0.0))

    def test_lead_syncopation_defaults_and_overrides(self):
        self.assertEqual(MusicAnvil.PieceSpec().lead_syncopation,
                         ma_utils.get_param("piece_defaults", "lead_syncopation"))
        piece = _make_piece()
        piece.sections["A"].lead_syncopation = 0.9
        self.assertEqual(
            MusicAnvil.resolve_section(piece.sections["A"], piece).lead_syncopation, 0.9)

    def test_lead_notes_still_land_on_the_grid_and_inside_the_section(self):
        for signature in ((4, 4), (3, 4), (6, 8), (5, 4)):
            with self.subTest(signature=signature):
                piece = _make_piece(bars=2)
                piece.signature = signature
                resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
                rendered = MusicAnvil._render_section_events(resolved, random.Random(4))
                for event in rendered.events["Piano"]:
                    self.assertGreaterEqual(event.start_sub, 0)
                    self.assertLess(event.start_sub, rendered.context.total_sub)


class TestBassBreathes(unittest.TestCase):
    """ToDo 4.2 — the bass must not hammer exactly one note on every beat."""

    def _render(self, bars=8, seed=3):
        piece = _make_piece(bars=bars)
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        return MusicAnvil._render_section_events(resolved, random.Random(seed))

    def test_bass_notes_start_on_beats(self):
        rendered = self._render()
        spb = rendered.context.subs_per_beat
        for event in rendered.events["Bass"]:
            self.assertEqual(event.start_sub % spb, 0)

    def test_some_bass_notes_are_held_over_two_beats(self):
        spans = set()
        for seed in range(8):
            rendered = self._render(seed=seed)
            spb = rendered.context.subs_per_beat
            spans.update(event.length_sub // spb for event in rendered.events["Bass"])
        self.assertIn(2, spans, "the bass never holds a note across a beat")

    def test_bass_notes_never_overlap(self):
        for seed in range(8):
            rendered = self._render(seed=seed)
            events = sorted(rendered.events["Bass"], key=lambda e: e.start_sub)
            for current, following in zip(events, events[1:]):
                self.assertLessEqual(current.end_sub, following.start_sub)

    def test_the_downbeat_is_always_played(self):
        for seed in range(6):
            rendered = self._render(seed=seed)
            starts = {event.start_sub for event in rendered.events["Bass"]}
            self.assertIn(0, starts)


class TestChordsAreHeld(unittest.TestCase):
    """ToDo 4.2 — an unchanged harmony is sustained, not re-struck every beat."""

    def _ctx(self):
        piece = _make_piece(bars=2)
        return MusicAnvil.make_render_context(
            MusicAnvil.resolve_section(piece.sections["A"], piece))

    def _chord(self, start, pitches, length=None):
        length = length if length is not None else self._ctx().subs_per_beat
        return [MusicAnvil.NoteEvent(start_sub=start, length_sub=length, pitch=p,
                                     velocity=78, gate=0.85) for p in pitches]

    def test_identical_consecutive_chords_merge(self):
        ctx = self._ctx()
        events = self._chord(0, [60, 64, 67]) + self._chord(4, [60, 64, 67])
        merged = MusicAnvil.merge_repeated_chords(events, ctx)
        self.assertEqual(len(merged), 3)
        self.assertTrue(all(e.start_sub == 0 and e.length_sub == 8 for e in merged))

    def test_different_chords_are_left_alone(self):
        ctx = self._ctx()
        events = self._chord(0, [60, 64, 67]) + self._chord(4, [62, 65, 69])
        merged = MusicAnvil.merge_repeated_chords(events, ctx)
        self.assertEqual(sorted({e.start_sub for e in merged}), [0, 4])
        self.assertTrue(all(e.length_sub == 4 for e in merged))

    def test_a_gap_prevents_merging(self):
        ctx = self._ctx()
        events = self._chord(0, [60, 64, 67]) + self._chord(8, [60, 64, 67])
        merged = MusicAnvil.merge_repeated_chords(events, ctx)
        self.assertEqual(sorted({e.start_sub for e in merged}), [0, 8])

    def test_three_in_a_row_merge_into_one(self):
        ctx = self._ctx()
        events = (self._chord(0, [60, 64]) + self._chord(4, [60, 64])
                  + self._chord(8, [60, 64]))
        merged = MusicAnvil.merge_repeated_chords(events, ctx)
        self.assertEqual({e.length_sub for e in merged}, {12})

    def test_empty_input(self):
        self.assertEqual(MusicAnvil.merge_repeated_chords([], self._ctx()), [])

    def test_a_chord_is_held_while_the_melody_stays_inside_it(self):
        ctx = self._ctx()
        spb = ctx.subs_per_beat
        chords = self._chord(0, [60, 64, 67]) + self._chord(spb, [64, 67, 72])
        lead = [MusicAnvil.NoteEvent(start_sub=0, length_sub=spb, pitch=64, velocity=100),
                MusicAnvil.NoteEvent(start_sub=spb, length_sub=spb, pitch=67, velocity=100)]
        held = MusicAnvil.sustain_chords(chords, lead, ctx)
        self.assertEqual({e.start_sub for e in held}, {0})
        self.assertTrue(all(e.length_sub == 2 * spb for e in held))

    def test_a_new_chord_is_struck_when_the_melody_leaves(self):
        ctx = self._ctx()
        spb = ctx.subs_per_beat
        chords = self._chord(0, [60, 64, 67]) + self._chord(spb, [62, 65, 69])
        lead = [MusicAnvil.NoteEvent(start_sub=0, length_sub=spb, pitch=64, velocity=100),
                MusicAnvil.NoteEvent(start_sub=spb, length_sub=spb, pitch=62, velocity=100)]
        held = MusicAnvil.sustain_chords(chords, lead, ctx)
        self.assertEqual(sorted({e.start_sub for e in held}), [0, spb])

    def test_sustain_chords_handles_no_chords(self):
        self.assertEqual(MusicAnvil.sustain_chords([], [], self._ctx()), [])

    def test_sustain_chords_does_not_bridge_a_silent_beat(self):
        ctx = self._ctx()
        spb = ctx.subs_per_beat
        chords = self._chord(0, [60, 64, 67]) + self._chord(3 * spb, [60, 64, 67])
        held = MusicAnvil.sustain_chords(chords, [], ctx)
        self.assertEqual(sorted({e.start_sub for e in held}), [0, 3 * spb])

    def test_rendered_accompaniment_holds_chords(self):
        piece = _make_piece(bars=4)
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(2))
        spb = rendered.context.subs_per_beat
        spans = [event.length_sub // spb for event in rendered.events["Guitar"]]
        self.assertTrue(spans)
        self.assertTrue(any(span >= 2 for span in spans),
                        "no chord was held across more than one beat")

    def test_held_chords_do_not_overlap_the_next_chord(self):
        piece = _make_piece(bars=4)
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(2))
        notes = sorted(MusicAnvil.materialise(rendered.events["Guitar"], rendered.context),
                       key=lambda n: (n.start, n.pitch))
        starts = sorted({round(n.start, 9) for n in notes})
        for note in notes:
            later = [s for s in starts if s > note.start + 1e-9]
            if later:
                self.assertLessEqual(note.end, later[0] + 1e-9)


class TestPhraseTransformers(unittest.TestCase):
    """ToDo 4.5 — a phrase transformer receives the whole rendered section in musical
    time, so it can shape a cadence across every role at once."""

    NAME = "test_phrase_transformer"

    def setUp(self):
        self.seen = []

        def transformer(section, semitones=0):
            self.seen.append(section)
            for events in section.events.values():
                for event in events:
                    event.pitch = max(0, min(127, event.pitch + semitones))
            return section

        ma_utils.register_transformer(self.NAME, transformer,
                                      kind=ma_utils.TRANSFORMER_PHRASE,
                                      params=[{"name": "semitones", "label": "Semitones",
                                               "type": "int", "default": 0,
                                               "min": -24, "max": 24}])

    def tearDown(self):
        ma_utils.BEAT_TRANSFORMERS.pop(self.NAME, None)
        ma_utils.TRANSFORMER_SPECS.pop(self.NAME, None)

    def _piece(self, **kwargs):
        piece = _make_piece(structure=["A", MusicAnvil.StructureEntry(
            section="A", transformer=self.NAME, transformer_kwargs=kwargs)], bars=2)
        return piece

    def test_phrase_transformer_receives_a_rendered_section(self):
        MusicAnvil.render_piece(self._piece(), random.Random(1))
        self.assertEqual(len(self.seen), 1)
        section = self.seen[0]
        self.assertIsInstance(section, MusicAnvil.RenderedSection)
        self.assertIsInstance(section.context, MusicAnvil.RenderContext)
        self.assertTrue(section.phrases)
        self.assertTrue(section.events)

    def test_phrase_transformer_output_reaches_the_midi(self):
        midi = MusicAnvil.render_piece(self._piece(semitones=5), random.Random(1))
        piano = [inst for inst in midi.instruments if inst.name == "Piano"][0]
        first = [n for n in piano.notes if n.start < 4.0]
        second = [n for n in piano.notes if n.start >= 4.0]
        self.assertTrue(first and second)
        self.assertEqual([n.pitch + 5 for n in first], [n.pitch for n in second])

    def test_the_cached_section_is_not_mutated(self):
        """A transformed occurrence must not change the other occurrences."""
        piece = _make_piece(structure=[
            "A",
            MusicAnvil.StructureEntry(section="A", transformer=self.NAME,
                                      transformer_kwargs={"semitones": 7}),
            "A",
        ], bars=2)
        midi = MusicAnvil.render_piece(piece, random.Random(1))
        piano = [inst for inst in midi.instruments if inst.name == "Piano"][0]
        first = [n.pitch for n in piano.notes if n.start < 4.0]
        third = [n.pitch for n in piano.notes if n.start >= 8.0]
        self.assertTrue(first)
        self.assertEqual(first, third)

    def test_phrase_transformers_can_touch_the_drums(self):
        def silence_drums(section):
            section.drums = []
            return section

        ma_utils.register_transformer("test_drum_killer", silence_drums,
                                      kind=ma_utils.TRANSFORMER_PHRASE)
        try:
            piece = _make_piece(structure=[MusicAnvil.StructureEntry(
                section="A", transformer="test_drum_killer")], bars=2)
            midi = MusicAnvil.render_piece(piece, random.Random(1))
            drums = [inst for inst in midi.instruments if inst.is_drum]
            self.assertTrue(all(not inst.notes for inst in drums))
        finally:
            ma_utils.BEAT_TRANSFORMERS.pop("test_drum_killer", None)
            ma_utils.TRANSFORMER_SPECS.pop("test_drum_killer", None)

    def test_note_transformers_still_skip_the_drums(self):
        piece = _make_piece(structure=[MusicAnvil.StructureEntry(
            section="A", transformer="tone_shift", transformer_kwargs={"n": 3})], bars=2)
        plain = MusicAnvil.render_piece(_make_piece(structure=["A"], bars=2), random.Random(1))
        shifted = MusicAnvil.render_piece(piece, random.Random(1))

        def drums(midi):
            return [(n.pitch, round(n.start, 6))
                    for inst in midi.instruments if inst.is_drum for n in inst.notes]

        self.assertEqual(drums(plain), drums(shifted))

    def test_rendered_section_copy_is_independent(self):
        piece = _make_piece(bars=2)
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        original = MusicAnvil._render_section_events(resolved, random.Random(1))
        clone = original.copy()
        for events in clone.events.values():
            for event in events:
                event.pitch = 1
        clone.phrases[0].ending = "mangled"
        clone.drums.clear()
        self.assertTrue(all(event.pitch != 1
                            for events in original.events.values() for event in events))
        self.assertNotEqual(original.phrases[0].ending, "mangled")
        self.assertTrue(original.drums)


class TestTensionReleaseModifier(unittest.TestCase):
    """ToDo 4.1 — the requested modifier: build tension over a passage, or release it.

    Tension leaves the ending open (melody rising to a tendency tone, harmony on the
    fifth, velocities swelling); release closes it (melody falling to the tonic, tonic
    triad, velocities tapering). Both hold the final note.
    """

    def _rendered(self, mode, bars=1, scale="major", tonic="C", signature=(4, 4),
                  section_bars=2, seed=5):
        piece = _make_piece(bars=section_bars)
        piece.scale, piece.tonic, piece.signature = scale, tonic, signature
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        section = MusicAnvil._render_section_events(resolved, random.Random(seed))
        return MusicAnvil.shape_phrase_ending(section.copy(), mode=mode, bars=bars), section

    def _closing(self, section, instrument):
        events = section.events[instrument]
        last = max(event.start_sub for event in events)
        return [event for event in events if event.start_sub == last]

    # -- registration ----------------------------------------------------------------

    def test_both_transformers_are_registered_as_phrase_transformers(self):
        for name in (MusicAnvil.CADENCE_TENSION, MusicAnvil.CADENCE_RELEASE):
            with self.subTest(name=name):
                self.assertIn(name, ma_utils.BEAT_TRANSFORMERS)
                self.assertEqual(ma_utils.transformer_kind(name),
                                 ma_utils.TRANSFORMER_PHRASE)

    def test_they_declare_a_bars_parameter(self):
        for name in (MusicAnvil.CADENCE_TENSION, MusicAnvil.CADENCE_RELEASE):
            with self.subTest(name=name):
                params = ma_utils.transformer_params(name)
                self.assertEqual([p["name"] for p in params], ["bars"])
                self.assertEqual(params[0]["default"], 1)

    # -- melody ----------------------------------------------------------------------

    def test_tension_ends_on_a_tendency_tone(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_TENSION)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        _, unstable = ma_utils.degree_stability("major")
        final = self._closing(shaped, "Piano")[0]
        self.assertIn((final.pitch - tonic_pc) % 12, unstable)

    def test_tension_ends_on_the_leading_tone_in_a_major_scale(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_TENSION)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        self.assertEqual((self._closing(shaped, "Piano")[0].pitch - tonic_pc) % 12, 11)

    def test_release_ends_on_the_tonic(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_RELEASE)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        self.assertEqual(self._closing(shaped, "Piano")[0].pitch % 12, tonic_pc)

    def test_tension_rises_above_the_passage(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_TENSION)
        window = [e for e in shaped.events["Piano"]
                  if e.start_sub >= shaped.context.total_sub - shaped.context.subs_per_bar]
        final = max(window, key=lambda e: e.start_sub)
        self.assertGreaterEqual(final.pitch, max(e.pitch for e in window))

    def test_release_falls_below_the_passage(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_RELEASE)
        window = [e for e in shaped.events["Piano"]
                  if e.start_sub >= shaped.context.total_sub - shaped.context.subs_per_bar]
        final = max(window, key=lambda e: e.start_sub)
        self.assertLessEqual(final.pitch, min(e.pitch for e in window))

    def test_the_approach_is_ordered_into_a_line(self):
        for mode, rising in ((MusicAnvil.CADENCE_TENSION, True),
                             (MusicAnvil.CADENCE_RELEASE, False)):
            with self.subTest(mode=mode):
                shaped, _ = self._rendered(mode, section_bars=4, bars=2)
                ctx = shaped.context
                window = sorted((e for e in shaped.events["Piano"]
                                 if e.start_sub >= ctx.total_sub - 2 * ctx.subs_per_bar),
                                key=lambda e: e.start_sub)
                approach = [e.pitch for e in window[:-1]]
                self.assertGreater(len(approach), 1)
                self.assertEqual(approach, sorted(approach, reverse=not rising))

    def test_the_melody_stays_in_the_scale(self):
        for mode in (MusicAnvil.CADENCE_TENSION, MusicAnvil.CADENCE_RELEASE):
            with self.subTest(mode=mode):
                shaped, _ = self._rendered(mode)
                scale_pcs = {p % 12 for p in shaped.context.scale_pitches}
                for event in shaped.events["Piano"]:
                    self.assertIn(event.pitch % 12, scale_pcs)

    # -- harmony and bass ------------------------------------------------------------

    def test_tension_lands_on_the_triad_of_the_fifth(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_TENSION)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        pcs = {(e.pitch - tonic_pc) % 12 for e in self._closing(shaped, "Guitar")}
        self.assertEqual(pcs, set(ma_utils.diatonic_triad("major", 7)))

    def test_release_lands_on_the_tonic_triad(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_RELEASE)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        pcs = {(e.pitch - tonic_pc) % 12 for e in self._closing(shaped, "Guitar")}
        self.assertEqual(pcs, {0, 4, 7})

    def test_the_bass_takes_the_cadence_root(self):
        tension, _ = self._rendered(MusicAnvil.CADENCE_TENSION)
        release, _ = self._rendered(MusicAnvil.CADENCE_RELEASE)
        tonic_pc = tension.context.scale_pitches[0] % 12
        self.assertEqual((self._closing(tension, "Bass")[0].pitch - tonic_pc) % 12, 7)
        self.assertEqual((self._closing(release, "Bass")[0].pitch - tonic_pc) % 12, 0)

    def test_the_bass_stays_in_its_register(self):
        """The cadence root is taken in the bass's own octave — never an octave leap."""
        for mode in (MusicAnvil.CADENCE_TENSION, MusicAnvil.CADENCE_RELEASE):
            with self.subTest(mode=mode):
                shaped, plain = self._rendered(mode)
                closing = self._closing(shaped, "Bass")[0]
                original = next(e for e in plain.events["Bass"]
                                if e.start_sub == closing.start_sub)
                self.assertLess(abs(closing.pitch - original.pitch), 12)

    # -- duration and dynamics --------------------------------------------------------

    def test_the_final_note_is_held_to_the_end_of_the_section(self):
        for mode in (MusicAnvil.CADENCE_TENSION, MusicAnvil.CADENCE_RELEASE):
            with self.subTest(mode=mode):
                shaped, _ = self._rendered(mode)
                final = self._closing(shaped, "Piano")[0]
                self.assertEqual(final.end_sub, shaped.context.total_sub)
                self.assertEqual(final.gate, 1.0)
                self.assertTrue(final.is_phrase_final)

    def test_tension_swells_and_release_tapers(self):
        tension, plain = self._rendered(MusicAnvil.CADENCE_TENSION)
        release, _ = self._rendered(MusicAnvil.CADENCE_RELEASE)
        base = self._closing(plain, "Piano")[0].velocity
        self.assertGreater(self._closing(tension, "Piano")[0].velocity, base)
        self.assertLess(self._closing(release, "Piano")[0].velocity, base)

    # -- scope and robustness ---------------------------------------------------------

    def test_bars_widens_the_reshaped_window(self):
        one, plain = self._rendered(MusicAnvil.CADENCE_RELEASE, bars=1, section_bars=4)
        two, _ = self._rendered(MusicAnvil.CADENCE_RELEASE, bars=2, section_bars=4)

        def changed(shaped):
            original = {e.start_sub: e.pitch for e in plain.events["Piano"]}
            return sum(1 for e in shaped.events["Piano"]
                       if original.get(e.start_sub) != e.pitch)

        self.assertGreater(changed(two), changed(one))

    def test_notes_outside_the_window_are_untouched(self):
        shaped, plain = self._rendered(MusicAnvil.CADENCE_RELEASE, bars=1, section_bars=4)
        cut = shaped.context.total_sub - shaped.context.subs_per_bar
        before = {(e.start_sub, e.pitch, e.velocity) for e in plain.events["Piano"]
                  if e.start_sub < cut}
        after = {(e.start_sub, e.pitch, e.velocity) for e in shaped.events["Piano"]
                 if e.start_sub < cut}
        self.assertEqual(before, after)

    def test_works_in_a_minor_key_and_an_odd_signature(self):
        shaped, _ = self._rendered(MusicAnvil.CADENCE_RELEASE, scale="natural_minor",
                                   tonic="A", signature=(3, 4), section_bars=4)
        tonic_pc = shaped.context.scale_pitches[0] % 12
        self.assertEqual(self._closing(shaped, "Piano")[0].pitch % 12, tonic_pc)
        pcs = {(e.pitch - tonic_pc) % 12 for e in self._closing(shaped, "Guitar")}
        self.assertEqual(pcs, {0, 3, 7})

    def test_a_section_without_accompaniment_still_works(self):
        piece = _make_piece(bars=2)
        piece.roles[MusicAnvil.ROLE_ACCOMPANIMENT] = MusicAnvil.RoleAssignment()
        piece.roles[MusicAnvil.ROLE_BASS] = MusicAnvil.RoleAssignment()
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        section = MusicAnvil._render_section_events(resolved, random.Random(2))
        shaped = MusicAnvil.build_tension(section.copy())
        self.assertTrue(shaped.events["Piano"])

    def test_an_empty_section_is_returned_unchanged(self):
        piece = _make_piece(bars=2)
        for role in MusicAnvil.ROLES:
            piece.roles[role] = MusicAnvil.RoleAssignment()
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        section = MusicAnvil._render_section_events(resolved, random.Random(2))
        self.assertIs(MusicAnvil.release_tension(section), section)

    # -- through the whole piece -------------------------------------------------------

    def test_attached_to_a_structure_entry(self):
        piece = _make_piece(structure=[
            "A",
            MusicAnvil.StructureEntry(section="A", transformer=MusicAnvil.CADENCE_TENSION),
            MusicAnvil.StructureEntry(section="A", transformer=MusicAnvil.CADENCE_RELEASE,
                                      transformer_kwargs={"bars": 1}),
        ], bars=2)
        midi = MusicAnvil.render_piece(piece, random.Random(3))
        piano = [inst for inst in midi.instruments if inst.name == "Piano"][0]
        section_len = MusicAnvil.section_seconds(2, 120, (4, 4))

        def final_pitch(index):
            notes = [n for n in piano.notes
                     if index * section_len <= n.start < (index + 1) * section_len]
            return max(notes, key=lambda n: n.start).pitch

        tonic_pc = pretty_midi.note_name_to_number("C4") % 12
        self.assertEqual((final_pitch(1) - tonic_pc) % 12, 11)   # tension: leading tone
        self.assertEqual((final_pitch(2) - tonic_pc) % 12, 0)    # release: tonic

    def test_the_untransformed_occurrence_is_unaffected(self):
        piece = _make_piece(structure=[
            "A",
            MusicAnvil.StructureEntry(section="A", transformer=MusicAnvil.CADENCE_RELEASE),
            "A",
        ], bars=2)
        midi = MusicAnvil.render_piece(piece, random.Random(3))
        piano = [inst for inst in midi.instruments if inst.name == "Piano"][0]
        section_len = MusicAnvil.section_seconds(2, 120, (4, 4))
        first = [(round(n.start, 6), n.pitch) for n in piano.notes if n.start < section_len]
        third = [(round(n.start - 2 * section_len, 6), n.pitch) for n in piano.notes
                 if n.start >= 2 * section_len]
        self.assertEqual(first, third)


class TestAutomaticPhraseCadences(unittest.TestCase):
    """ToDo 4.6 — every phrase should ask a question or answer it, without the user
    attaching a transformer."""

    def _render(self, bars=4, phrase_bars=2, auto=True, seed=5, scale="major", tonic="C"):
        piece = _make_piece(bars=bars)
        piece.scale, piece.tonic = scale, tonic
        piece.auto_cadence = auto
        piece.sections["A"].phrase_bars = phrase_bars
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        return MusicAnvil._render_section_events(resolved, random.Random(seed))

    def _phrase_final(self, section, instrument, phrase_index):
        ctx = section.context
        phrase = section.phrases[phrase_index]
        window = [e for e in section.events[instrument]
                  if phrase.start_beat * ctx.subs_per_beat <= e.start_sub
                  < phrase.end_beat * ctx.subs_per_beat]
        last = max(e.start_sub for e in window)
        return [e for e in window if e.start_sub == last]

    def test_the_antecedent_ends_open_and_the_consequent_closed(self):
        section = self._render()
        tonic_pc = section.context.scale_pitches[0] % 12
        _, unstable = ma_utils.degree_stability("major")
        first = self._phrase_final(section, "Piano", 0)[0]
        last = self._phrase_final(section, "Piano", 1)[0]
        self.assertIn((first.pitch - tonic_pc) % 12, unstable)
        self.assertEqual(last.pitch % 12, tonic_pc)

    def test_the_harmony_follows_the_endings(self):
        section = self._render()
        tonic_pc = section.context.scale_pitches[0] % 12
        opening = {(e.pitch - tonic_pc) % 12 for e in self._phrase_final(section, "Guitar", 0)}
        closing = {(e.pitch - tonic_pc) % 12 for e in self._phrase_final(section, "Guitar", 1)}
        self.assertEqual(opening, set(ma_utils.diatonic_triad("major", 7)))
        self.assertEqual(closing, {0, 4, 7})

    def test_disabling_auto_cadence_leaves_the_material_alone(self):
        shaped = self._render(auto=True)
        plain = self._render(auto=False)
        self.assertNotEqual([e.pitch for e in shaped.events["Piano"]],
                            [e.pitch for e in plain.events["Piano"]])

    def test_cadence_beats_widens_the_window(self):
        """A wider window reshapes more of the approach — checked across seeds, since a
        single-onset window has nothing extra to reshape."""
        differences = 0
        for seed in range(6):
            plain = self._render(auto=False, seed=seed)

            def shaped(beats):
                return {(e.start_sub, e.pitch)
                        for e in MusicAnvil.apply_phrase_cadences(
                            plain.copy(), beats).events["Piano"]}

            if shaped(1) != shaped(4):
                differences += 1
        self.assertGreater(differences, 0, "cadence_beats never changed the outcome")

    def test_the_melody_stays_in_the_scale(self):
        section = self._render(scale="natural_minor", tonic="A")
        scale_pcs = {p % 12 for p in section.context.scale_pitches}
        for event in section.events["Piano"]:
            self.assertIn(event.pitch % 12, scale_pcs)

    def test_notes_stay_inside_the_section(self):
        piece = _make_piece(bars=4)
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        tracks, length = MusicAnvil.render_section(resolved, random.Random(5))
        for notes in tracks.values():
            for note in notes:
                self.assertLessEqual(note.end, length + 1e-9)
                self.assertGreaterEqual(note.start, -1e-9)

    def test_a_single_phrase_section_still_closes(self):
        section = self._render(bars=1, phrase_bars=1)
        tonic_pc = section.context.scale_pitches[0] % 12
        self.assertEqual(self._phrase_final(section, "Piano", 0)[0].pitch % 12, tonic_pc)

    def test_shape_cadence_reports_what_it_touched(self):
        section = self._render(auto=False)
        ctx = section.context
        touched = MusicAnvil.shape_cadence(section, 0, ctx.subs_per_bar, rising=True)
        self.assertGreaterEqual(touched, 3)

    def test_apply_phrase_cadences_without_phrases_is_a_no_op(self):
        section = self._render(auto=False)
        section.phrases = []
        before = [(e.start_sub, e.pitch) for e in section.events["Piano"]]
        MusicAnvil.apply_phrase_cadences(section)
        self.assertEqual([(e.start_sub, e.pitch) for e in section.events["Piano"]], before)


class TestHarmonicAcceleration(unittest.TestCase):
    """ToDo 4.6 — a held chord is re-struck per beat in the bar that closes a phrase."""

    def _ctx_and_phrases(self, bars=4, phrase_bars=2):
        piece = _make_piece(bars=bars)
        piece.sections["A"].phrase_bars = phrase_bars
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        ctx = MusicAnvil.make_render_context(resolved)
        return ctx, MusicAnvil.plan_phrases(ctx, phrase_bars)

    def _chord(self, start, length, pitches=(60, 64, 67)):
        return [MusicAnvil.NoteEvent(start_sub=start, length_sub=length, pitch=p,
                                     velocity=78, gate=0.85) for p in pitches]

    def test_a_held_chord_in_the_closing_bar_is_split_per_beat(self):
        ctx, phrases = self._ctx_and_phrases()
        start = (phrases[0].end_beat - ctx.beats_per_bar) * ctx.subs_per_beat
        events = self._chord(start, 4 * ctx.subs_per_beat)
        accelerated = MusicAnvil.accelerate_harmony(events, ctx, phrases)
        starts = sorted({e.start_sub for e in accelerated})
        self.assertEqual(starts, [start + i * ctx.subs_per_beat for i in range(4)])
        self.assertTrue(all(e.length_sub == ctx.subs_per_beat for e in accelerated))

    def test_a_chord_outside_the_closing_bar_is_untouched(self):
        ctx, phrases = self._ctx_and_phrases(bars=8, phrase_bars=4)
        events = self._chord(0, 4 * ctx.subs_per_beat)
        accelerated = MusicAnvil.accelerate_harmony(events, ctx, phrases)
        self.assertEqual([(e.start_sub, e.length_sub) for e in accelerated],
                         [(e.start_sub, e.length_sub) for e in events])

    def test_a_one_beat_chord_is_untouched(self):
        ctx, phrases = self._ctx_and_phrases()
        start = (phrases[0].end_beat - 1) * ctx.subs_per_beat
        events = self._chord(start, ctx.subs_per_beat)
        self.assertEqual(len(MusicAnvil.accelerate_harmony(events, ctx, phrases)), 3)

    def test_pitches_and_velocities_survive(self):
        ctx, phrases = self._ctx_and_phrases()
        start = (phrases[0].end_beat - ctx.beats_per_bar) * ctx.subs_per_beat
        events = self._chord(start, 2 * ctx.subs_per_beat)
        accelerated = MusicAnvil.accelerate_harmony(events, ctx, phrases)
        self.assertEqual({e.pitch for e in accelerated}, {60, 64, 67})
        self.assertTrue(all(e.velocity == 78 for e in accelerated))

    def test_empty_input_is_safe(self):
        ctx, phrases = self._ctx_and_phrases()
        self.assertEqual(MusicAnvil.accelerate_harmony([], ctx, phrases), [])
        self.assertEqual(MusicAnvil.accelerate_harmony(self._chord(0, 4), ctx, []),
                         self._chord(0, 4))

    def test_the_rendered_accompaniment_accelerates_into_the_cadence(self):
        piece = _make_piece(bars=4)
        piece.sections["A"].phrase_bars = 2
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(5))
        ctx = rendered.context
        closing_bar = (rendered.phrases[0].end_beat - ctx.beats_per_bar) * ctx.subs_per_beat
        closing = [e for e in rendered.events["Guitar"]
                   if closing_bar <= e.start_sub < rendered.phrases[0].end_beat * ctx.subs_per_beat]
        self.assertTrue(closing)
        self.assertTrue(all(e.length_sub <= ctx.subs_per_beat for e in closing))


class TestDrumFills(unittest.TestCase):
    """ToDo 4.6 — the drums must mark the phrase structure, not repeat one bar forever."""

    def _render(self, bars=4, phrase_bars=2, fills=True, seed=5, signature=(4, 4)):
        piece = _make_piece(bars=bars)
        piece.signature = signature
        piece.drum_fills = fills
        piece.sections["A"].phrase_bars = phrase_bars
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        return MusicAnvil._render_section_events(resolved, random.Random(seed))

    def test_a_fill_lands_in_the_last_beat_of_each_phrase(self):
        section = self._render()
        ctx = section.context
        fill_pitches = {ma_utils.drum_pitches[name]
                        for name in ma_utils.drum_fill["pitches"]}
        for phrase in section.phrases:
            start = (phrase.end_beat - 1) * ctx.beat_len
            hits = [n for n in section.drums
                    if start - 1e-9 <= n.start < phrase.end_beat * ctx.beat_len - 1e-9
                    and n.pitch in fill_pitches]
            self.assertTrue(hits, f"no fill at the end of phrase {phrase.index}")

    def test_the_fill_subdivides_the_beat(self):
        section = self._render()
        ctx = section.context
        phrase = section.phrases[0]
        start = (phrase.end_beat - 1) * ctx.beat_len
        step = ctx.beat_len / ma_utils.drum_fill["notes_per_beat"]
        hits = sorted(n.start for n in section.drums
                      if start - 1e-9 <= n.start < phrase.end_beat * ctx.beat_len - 1e-9)
        self.assertTrue(any(abs(hit - (start + step)) < 1e-9 for hit in hits))

    def test_a_crash_opens_every_phrase_after_the_first(self):
        section = self._render()
        ctx = section.context
        crash = ma_utils.drum_pitches[ma_utils.drum_fill["crash"]]
        for phrase in section.phrases[1:]:
            start = phrase.start_beat * ctx.beat_len
            self.assertTrue(any(n.pitch == crash and abs(n.start - start) < 1e-9
                                for n in section.drums),
                            f"no crash at phrase {phrase.index}")

    def test_no_crash_before_the_first_phrase(self):
        section = self._render()
        crash = ma_utils.drum_pitches[ma_utils.drum_fill["crash"]]
        rock_has_crash = any(entry[1] == crash for entry in ma_utils.drum_lines["Rock"])
        if not rock_has_crash:
            self.assertFalse(any(n.pitch == crash and n.start < 1e-9 for n in section.drums))

    def test_fills_stay_inside_the_section(self):
        for signature in ((4, 4), (3, 4), (6, 8)):
            with self.subTest(signature=signature):
                section = self._render(signature=signature)
                for note in section.drums:
                    self.assertLessEqual(note.end, section.length + 1e-9)
                    self.assertGreaterEqual(note.start, -1e-9)

    def test_the_kick_pattern_survives_the_fill(self):
        section = self._render()
        kick = ma_utils.drum_pitches["Bass Drum"]
        self.assertTrue(any(n.pitch == kick for n in section.drums))

    def test_disabling_fills_restores_the_plain_pattern(self):
        with_fills = self._render(fills=True)
        without = self._render(fills=False)
        self.assertGreater(len(with_fills.drums), len(without.drums))

    def test_add_drum_fills_without_phrases_is_a_no_op(self):
        section = self._render(fills=False)
        self.assertEqual(MusicAnvil.add_drum_fills(section.drums, section.context, []),
                         section.drums)

    def test_add_drum_fills_with_an_empty_spec_is_a_no_op(self):
        section = self._render(fills=False)
        self.assertEqual(
            MusicAnvil.add_drum_fills(section.drums, section.context, section.phrases,
                                      spec={}),
            section.drums)


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

    def _drums(self, rhythm, signature, bars=2, tempo=120, drum_fills=False):
        piece = MusicAnvil.PieceSpec(
            tempo=tempo,
            signature=signature,
            rhythm=rhythm,
            drum_fills=drum_fills,   # this class tests the pattern itself, not the fills
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
