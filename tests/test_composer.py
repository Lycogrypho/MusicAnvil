"""Tests for the piece composition engine (musicanvil.composer)."""

# OopCompanion:suppressRename

import random
import unittest

import pretty_midi

from musicanvil import composer, ma_utils


def _make_piece(structure=("A",), bars=2, tempo=120, **section_kwargs):
    """A minimal piece: one section 'A', Piano lead, Guitar accompaniment, Bass bass."""
    piece = composer.PieceSpec(
        tempo=tempo,
        signature=(4, 4),
        rhythm="Rock",
        scale="major",
        tonic="C",
        roles={
            composer.ROLE_LEAD: composer.RoleAssignment(main="Piano"),
            composer.ROLE_ACCOMPANIMENT: composer.RoleAssignment(main="Guitar"),
            composer.ROLE_BASS: composer.RoleAssignment(main="Bass"),
        },
        sections={"A": composer.SectionSpec(name="A", bars=bars, **section_kwargs)},
        structure=list(structure),
    )
    return piece


class TestTimingMath(unittest.TestCase):

    def test_parse_signature_valid(self):
        self.assertEqual(composer.parse_signature("4/4"), (4, 4))
        self.assertEqual(composer.parse_signature("6/8"), (6, 8))

    def test_parse_signature_invalid(self):
        for bad in ("44", "4/4/4", "0/4", "4/0", "x/y"):
            with self.assertRaises(ValueError):
                composer.parse_signature(bad)

    def test_beat_seconds_quarter_note(self):
        # 120 BPM, denominator 4 -> quarter-note beat of 0.5 s
        self.assertAlmostEqual(composer.beat_seconds(120, 4), 0.5)

    def test_beat_seconds_eighth_note(self):
        # denominator 8 -> eighth-note beat, half the quarter length
        self.assertAlmostEqual(composer.beat_seconds(120, 8), 0.25)

    def test_beat_seconds_rejects_bad_tempo(self):
        with self.assertRaises(ValueError):
            composer.beat_seconds(0, 4)
        with self.assertRaises(ValueError):
            composer.beat_seconds(-60, 4)

    def test_section_seconds(self):
        # 4 bars of 4/4 at 120 BPM = 4 * 4 * 0.5 = 8 s
        self.assertAlmostEqual(composer.section_seconds(4, 120, (4, 4)), 8.0)
        # 2 bars of 3/4 at 60 BPM = 2 * 3 * 1.0 = 6 s
        self.assertAlmostEqual(composer.section_seconds(2, 60, (3, 4)), 6.0)

    def test_piece_seconds_sums_structure_occurrences(self):
        piece = _make_piece(structure=["A", "A", "A"], bars=2)  # 2 bars = 4 s each
        self.assertAlmostEqual(composer.piece_seconds(piece), 12.0)

    def test_piece_seconds_unknown_section_raises(self):
        piece = _make_piece(structure=["A", "missing"])
        with self.assertRaises(ValueError):
            composer.piece_seconds(piece)


class TestResolveSection(unittest.TestCase):

    def test_inherits_piece_defaults(self):
        piece = _make_piece()
        resolved = composer.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tempo, piece.tempo)
        self.assertEqual(resolved.signature, piece.signature)
        self.assertEqual(resolved.rhythm, piece.rhythm)
        self.assertEqual(resolved.scale, piece.scale)
        self.assertEqual(resolved.tonic, piece.tonic)
        self.assertEqual(resolved.roles[composer.ROLE_LEAD].main, "Piano")

    def test_overrides_win(self):
        piece = _make_piece(tempo=120)
        piece.sections["A"].tempo = 90
        piece.sections["A"].scale = "blues"
        piece.sections["A"].roles = {
            composer.ROLE_LEAD: composer.RoleAssignment(main="Violin"),
        }
        resolved = composer.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.tempo, 90)
        self.assertEqual(resolved.scale, "blues")
        self.assertEqual(resolved.roles[composer.ROLE_LEAD].main, "Violin")
        # Roles not overridden still inherit
        self.assertEqual(resolved.roles[composer.ROLE_BASS].main, "Bass")


class TestRenderSection(unittest.TestCase):

    def setUp(self):
        self.piece = _make_piece(bars=2)
        self.resolved = composer.resolve_section(self.piece.sections["A"], self.piece)
        self.rng = random.Random(42)
        self.tracks, self.length = composer.render_section(self.resolved, self.rng)
        self.scale_pitches = [pretty_midi.note_name_to_number(n)
                              for n in ma_utils.generate_scale("major", "C")]

    def test_length_matches_bars(self):
        self.assertAlmostEqual(self.length, composer.section_seconds(2, 120, (4, 4)))

    def test_has_drum_track(self):
        self.assertIn(composer.DRUM_TRACK, self.tracks)
        self.assertGreater(len(self.tracks[composer.DRUM_TRACK]), 0)

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
            composer.render_section(self.resolved, self.rng)


class TestSupportDerivation(unittest.TestCase):

    def setUp(self):
        piece = _make_piece(bars=2)
        piece.roles[composer.ROLE_LEAD].supports = ["Violin"]
        piece.roles[composer.ROLE_ACCOMPANIMENT].supports = ["Trumpet"]
        resolved = composer.resolve_section(piece.sections["A"], piece)
        self.tracks, _ = composer.render_section(resolved, random.Random(42))

    def test_lead_support_is_subset_of_lead(self):
        lead = {(n.pitch, round(n.start, 6)) for n in self.tracks.get("Piano", [])}
        support = self.tracks.get("Violin", [])
        for note in support:
            self.assertIn((note.pitch, round(note.start, 6)), lead)

    def test_lead_support_only_even_beats(self):
        beat_len = composer.beat_seconds(120, 4)
        for note in self.tracks.get("Violin", []):
            beat = int(round(note.start / beat_len))
            self.assertEqual(beat % 2, 0)

    def test_accompaniment_support_only_bar_head(self):
        beat_len = composer.beat_seconds(120, 4)
        for note in self.tracks.get("Trumpet", []):
            beat_in_bar = int(round(note.start / beat_len)) % 4
            self.assertLess(beat_in_bar, 2)

    def test_supports_use_support_velocity(self):
        for name in ("Violin", "Trumpet"):
            for note in self.tracks.get(name, []):
                self.assertEqual(note.velocity, composer.VELOCITY_SUPPORT)


class TestRenderPiece(unittest.TestCase):

    def test_returns_pretty_midi_with_expected_instruments(self):
        piece = _make_piece(structure=["A"])
        midi_data = composer.render_piece(piece, random.Random(1))
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
            composer.render_piece(piece)

    def test_repeated_sections_are_identical(self):
        """The same library section must produce the same music at every occurrence."""
        piece = _make_piece(structure=["A", "A"], bars=2)
        section_len = composer.section_seconds(2, 120, (4, 4))
        midi_data = composer.render_piece(piece, random.Random(7))
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
        midi_data = composer.render_piece(piece, random.Random(3))
        expected_total = composer.piece_seconds(piece)
        max_end = max(n.end for inst in midi_data.instruments for n in inst.notes)
        self.assertLessEqual(max_end, expected_total + 1e-9)
        # Drums fill every section, so the last drum note must be in the final section.
        drums = next(inst for inst in midi_data.instruments if inst.name == "Drums")
        last_drum_start = max(n.start for n in drums.notes)
        self.assertGreater(last_drum_start, expected_total * 2 / 3)

    def test_per_section_tempo_override_changes_length(self):
        piece = _make_piece(structure=["A"], bars=2)
        base_len = composer.piece_seconds(piece)
        piece.sections["A"].tempo = 60  # half speed -> double length
        self.assertAlmostEqual(composer.piece_seconds(piece), base_len * 2)


if __name__ == "__main__":
    unittest.main()
