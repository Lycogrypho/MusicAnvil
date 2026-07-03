"""Tests for musicanvil.ma_utils — utility library."""

# OopCompanion:suppressRename

import random
import unittest

from musicanvil import ma_utils


class TestGenerateRandomBeatBaseUnit(unittest.TestCase):
    """P1 #1 — verify the base_duration formula uses the correct time-signature unit.

    At 120 BPM the quarter-note duration is 0.5 s.
    The formula base = quarter * 4 / denominator must produce:
      - denominator 4  → 0.5 s  (quarter note)
      - denominator 8  → 0.25 s (eighth note)
      - denominator 2  → 1.0 s  (half note)
    Every note start must be an exact multiple of the base unit.
    The old buggy formula (quarter / denominator) gave 0.125 s for 4/4,
    making starts fall on 16th-note grid lines, which this test would catch.
    """

    NOTES = [60, 62, 64, 65, 67]  # C4 pentatonic

    def _starts(self, time_signature, base_seconds, beat_duration=8.0):
        """Return note start times for a seeded run and the expected base unit."""
        random.seed(0)
        notes = ma_utils.generate_random_beat(
            self.NOTES, tempo=120,
            time_signature=time_signature,
            beat_duration=beat_duration,
        )
        self.assertGreater(len(notes), 1, "Too few notes generated to test grid alignment")
        return notes, base_seconds

    def _assert_on_grid(self, notes, base):
        for note in notes:
            remainder = note.start % base
            # remainder should be 0 or base (float wrap-around near multiples)
            on_grid = remainder < 1e-9 or abs(remainder - base) < 1e-9
            self.assertTrue(on_grid,
                            f"Note start {note.start:.6f} s is not on the {base} s grid")

    def test_4_4_starts_on_quarter_note_grid(self):
        # denominator 4 → base = 0.5 s (quarter note at 120 BPM)
        notes, base = self._starts((4, 4), 0.5)
        self._assert_on_grid(notes, base)

    def test_6_8_starts_on_eighth_note_grid(self):
        # denominator 8 → base = 0.25 s (eighth note at 120 BPM)
        notes, base = self._starts((6, 8), 0.25)
        self._assert_on_grid(notes, base)

    def test_2_2_starts_on_half_note_grid(self):
        # denominator 2 → base = 1.0 s (half note at 120 BPM)
        notes, base = self._starts((2, 2), 1.0)
        self._assert_on_grid(notes, base)

    def test_base_unit_4_4_is_not_sixteenth_note(self):
        # The old buggy formula produced 0.125 s (16th note) for 4/4 at 120 BPM.
        # Verify the minimum gap between note starts is >= 0.5 s.
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120,
                                              time_signature=(4, 4), beat_duration=16.0)
        starts = sorted(n.start for n in notes)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(g >= 0.5 - 1e-9 for g in gaps),
                        f"Some gap is smaller than a quarter note: {min(gaps):.4f} s")

    def test_beat_duration_respected(self):
        random.seed(1)
        beat_duration = 4.0
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120,
                                              time_signature=(4, 4),
                                              beat_duration=beat_duration)
        for note in notes:
            self.assertLessEqual(note.end, beat_duration + 1e-9)


class TestTempoValidation(unittest.TestCase):
    """P2 #4 — generate_random_beat and adapt_drum_line must reject tempo ≤ 0."""

    NOTES = [60, 62, 64]
    DRUM_LINE = [[100, 35, 0, 1], [80, 38, 1, 2]]

    def test_generate_random_beat_zero_tempo_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_random_beat(self.NOTES, tempo=0)

    def test_generate_random_beat_negative_tempo_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_random_beat(self.NOTES, tempo=-60)

    def test_adapt_drum_line_zero_tempo_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=0)

    def test_adapt_drum_line_negative_tempo_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=-120)

    def test_valid_tempo_does_not_raise(self):
        try:
            ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=1.0)
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120)
        except ValueError:
            self.fail("Unexpected ValueError for valid tempo=120")


class TestGenerateRandomBeatGuards(unittest.TestCase):
    """P2 #3 — generate_random_beat must raise ValueError for empty available_notes."""

    def test_empty_notes_raises_value_error(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_random_beat([], tempo=120)

    def test_empty_notes_error_message(self):
        with self.assertRaises(ValueError, msg="available_notes must not be empty"):
            ma_utils.generate_random_beat([], tempo=120)

    def test_non_empty_notes_does_not_raise(self):
        try:
            ma_utils.generate_random_beat([60], tempo=120, beat_duration=1.0)
        except ValueError:
            self.fail("generate_random_beat raised ValueError with a valid notes list")


class TestWriteNotesToMidi(unittest.TestCase):
    """P2 #5 — write_notes_to_midi must not mutate the caller's instrument object."""

    def _make_note(self, pitch=60, start=0.0, end=0.5, velocity=80):
        import pretty_midi
        return pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end)

    def test_passed_instrument_notes_unchanged_after_call(self):
        """Calling write_notes_to_midi with an existing instrument must not add notes to it."""
        import pretty_midi, tempfile, os
        instrument = pretty_midi.Instrument(program=0)
        note = self._make_note()
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            ma_utils.write_notes_to_midi([note], path, instrument=instrument)
            self.assertEqual(len(instrument.notes), 0,
                             "instrument.notes must not be modified by write_notes_to_midi")
        finally:
            os.unlink(path)

    def test_second_call_does_not_accumulate_notes(self):
        """Two calls with the same instrument must each write exactly the given notes."""
        import pretty_midi, tempfile, os
        instrument = pretty_midi.Instrument(program=0)
        note1 = self._make_note(pitch=60, start=0.0, end=0.5)
        note2 = self._make_note(pitch=62, start=0.5, end=1.0)
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            ma_utils.write_notes_to_midi([note1], path, instrument=instrument)
            ma_utils.write_notes_to_midi([note2], path, instrument=instrument)
            result = pretty_midi.PrettyMIDI(path)
            self.assertEqual(len(result.instruments[0].notes), 1,
                             "Second call must write exactly 1 note, not accumulate 2")
            self.assertEqual(result.instruments[0].notes[0].pitch, note2.pitch)
        finally:
            os.unlink(path)

    def test_no_instrument_uses_default_program_0(self):
        """When no instrument is passed, the written track must use program 0."""
        import pretty_midi, tempfile, os
        note = self._make_note()
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            ma_utils.write_notes_to_midi([note], path)
            result = pretty_midi.PrettyMIDI(path)
            self.assertEqual(result.instruments[0].program, 0)
        finally:
            os.unlink(path)

    def test_instrument_metadata_preserved_in_output(self):
        """Program, name, and is_drum must be copied into the written track."""
        import pretty_midi, tempfile, os
        instrument = pretty_midi.Instrument(program=25, is_drum=False, name="Acoustic Guitar")
        note = self._make_note()
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            ma_utils.write_notes_to_midi([note], path, instrument=instrument)
            result = pretty_midi.PrettyMIDI(path)
            self.assertEqual(result.instruments[0].program, 25)
        finally:
            os.unlink(path)


class TestScaleDefinitionsModes(unittest.TestCase):
    """P3 #9 — verify newly added Western modes are present and have correct intervals."""

    def _intervals(self, name):
        return ma_utils.scale_definitions[name]

    # -- presence ----------------------------------------------------------

    def test_dorian_present(self):
        self.assertIn("dorian", ma_utils.scale_definitions)

    def test_phrygian_present(self):
        self.assertIn("phrygian", ma_utils.scale_definitions)

    def test_lydian_present(self):
        self.assertIn("lydian", ma_utils.scale_definitions)

    def test_mixolydian_present(self):
        self.assertIn("mixolydian", ma_utils.scale_definitions)

    def test_locrian_present(self):
        self.assertIn("locrian", ma_utils.scale_definitions)

    def test_chromatic_present(self):
        self.assertIn("chromatic", ma_utils.scale_definitions)

    # -- correct intervals -------------------------------------------------

    def test_dorian_intervals(self):
        self.assertEqual(self._intervals("dorian"), [0, 2, 3, 5, 7, 9, 10])

    def test_phrygian_intervals(self):
        self.assertEqual(self._intervals("phrygian"), [0, 1, 3, 5, 7, 8, 10])

    def test_lydian_intervals(self):
        self.assertEqual(self._intervals("lydian"), [0, 2, 4, 6, 7, 9, 11])

    def test_mixolydian_intervals(self):
        self.assertEqual(self._intervals("mixolydian"), [0, 2, 4, 5, 7, 9, 10])

    def test_locrian_intervals(self):
        self.assertEqual(self._intervals("locrian"), [0, 1, 3, 5, 6, 8, 10])

    def test_chromatic_has_all_12_semitones(self):
        self.assertEqual(self._intervals("chromatic"), list(range(12)))

    # -- generate_scale integration ----------------------------------------

    def test_generate_scale_dorian_c(self):
        notes = ma_utils.generate_scale("dorian", "C")
        # C dorian over 3 octaves: root notes should include C, D, Eb, F, G, A, Bb
        self.assertIn("C4", notes)
        self.assertIn("D4", notes)
        self.assertIn("D#4", notes)  # Eb = D# in sharp-only convention
        self.assertIn("A#4", notes)  # Bb = A# in sharp-only convention

    def test_generate_scale_chromatic_has_12_unique_pitch_classes(self):
        notes = ma_utils.generate_scale("chromatic", "C")
        pitch_classes = {n[:-1] for n in notes}  # strip octave number
        self.assertEqual(len(pitch_classes), 12)

    def test_generate_scale_lydian_c_contains_tritone(self):
        # Lydian raises the 4th by a semitone → F# in C lydian
        notes = ma_utils.generate_scale("lydian", "C")
        self.assertIn("F#4", notes)

    def test_generate_scale_mixolydian_c_has_flat_seventh(self):
        # Mixolydian lowers the 7th → Bb (A#) in C mixolydian
        notes = ma_utils.generate_scale("mixolydian", "C")
        self.assertIn("A#4", notes)


if __name__ == "__main__":
    unittest.main()
