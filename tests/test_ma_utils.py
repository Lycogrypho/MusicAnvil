"""Tests for musicanvil.ma_utils — utility library."""

# OopCompanion:suppressRename

import random
import unittest

import pretty_midi

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


class TestGenerateScaleOctave(unittest.TestCase):
    """Tests for the start_octave parameter added to generate_scale."""

    def test_default_octave_4_starts_at_4(self):
        notes = ma_utils.generate_scale("major", "C")
        self.assertEqual(notes[0], "C4")

    def test_start_octave_2_starts_at_2(self):
        notes = ma_utils.generate_scale("major", "C", start_octave=2)
        self.assertEqual(notes[0], "C2")

    def test_start_octave_5_starts_at_5(self):
        notes = ma_utils.generate_scale("major", "C", start_octave=5)
        self.assertEqual(notes[0], "C5")

    def test_octave_numbers_ascend_across_three_octaves(self):
        notes = ma_utils.generate_scale("major", "C", start_octave=3)
        # C major: C D E F G A B — first note octave 3, last octave 5
        self.assertTrue(notes[0].endswith("3"))
        self.assertTrue(notes[-1].endswith("5"))

    def test_start_octave_6_pitches_higher_than_octave_4(self):
        notes_4 = ma_utils.generate_scale("major", "C", start_octave=4)
        notes_6 = ma_utils.generate_scale("major", "C", start_octave=6)
        pitches_4 = [pretty_midi.note_name_to_number(n) for n in notes_4]
        pitches_6 = [pretty_midi.note_name_to_number(n) for n in notes_6]
        self.assertTrue(all(p6 > p4 for p4, p6 in zip(pitches_4, pitches_6)))

    def test_same_note_names_just_shifted(self):
        notes_3 = ma_utils.generate_scale("major", "G", start_octave=3)
        notes_5 = ma_utils.generate_scale("major", "G", start_octave=5)
        # Strip octave digit and compare note names
        names_3 = [n[:-1] for n in notes_3]
        names_5 = [n[:-1] for n in notes_5]
        self.assertEqual(names_3, names_5)


class TestBeatTransformers(unittest.TestCase):
    """Tests for tone_shift, invert, BEAT_TRANSFORMERS registry, and get_transformer."""

    def _note(self, pitch, start=0.0, end=0.5, velocity=80):
        return pretty_midi.Note(velocity=velocity, pitch=pitch, start=start, end=end)

    def _beat(self, pitches):
        """Build a beat from a list of pitches with sequential 0.5 s slots."""
        return [self._note(p, i * 0.5, (i + 1) * 0.5) for i, p in enumerate(pitches)]

    # ------------------------------------------------------------------ tone_shift

    def test_tone_shift_up(self):
        beat = self._beat([60, 62, 64])
        result = ma_utils.tone_shift(beat, 2)
        self.assertEqual([n.pitch for n in result], [62, 64, 66])

    def test_tone_shift_down(self):
        beat = self._beat([60, 62, 64])
        result = ma_utils.tone_shift(beat, -2)
        self.assertEqual([n.pitch for n in result], [58, 60, 62])

    def test_tone_shift_zero_is_identity(self):
        beat = self._beat([60, 64, 67])
        result = ma_utils.tone_shift(beat, 0)
        self.assertEqual([n.pitch for n in result], [60, 64, 67])

    def test_tone_shift_clamps_at_127(self):
        beat = [self._note(126)]
        result = ma_utils.tone_shift(beat, 5)
        self.assertEqual(result[0].pitch, 127)

    def test_tone_shift_clamps_at_0(self):
        beat = [self._note(1)]
        result = ma_utils.tone_shift(beat, -5)
        self.assertEqual(result[0].pitch, 0)

    def test_tone_shift_preserves_timing_and_velocity(self):
        note = self._note(pitch=60, start=1.0, end=2.0, velocity=90)
        result = ma_utils.tone_shift([note], 3)
        self.assertEqual(result[0].start, 1.0)
        self.assertEqual(result[0].end, 2.0)
        self.assertEqual(result[0].velocity, 90)

    def test_tone_shift_empty_beat(self):
        self.assertEqual(ma_utils.tone_shift([], 5), [])

    def test_tone_shift_does_not_mutate_input(self):
        beat = self._beat([60, 62])
        original_pitches = [n.pitch for n in beat]
        ma_utils.tone_shift(beat, 7)
        self.assertEqual([n.pitch for n in beat], original_pitches)

    # ------------------------------------------------------------------ invert

    def test_invert_example_from_spec(self):
        # E(64)-G(67)-F#(66) → E(64)-C#(61)-D(62)
        beat = self._beat([64, 67, 66])
        result = ma_utils.invert(beat)
        self.assertEqual([n.pitch for n in result], [64, 61, 62])

    def test_invert_keeps_first_note_unchanged(self):
        beat = self._beat([60, 65, 70])
        result = ma_utils.invert(beat)
        self.assertEqual(result[0].pitch, 60)

    def test_invert_single_note_unchanged(self):
        beat = [self._note(72)]
        result = ma_utils.invert(beat)
        self.assertEqual(result[0].pitch, 72)

    def test_invert_empty_beat(self):
        self.assertEqual(ma_utils.invert([]), [])

    def test_invert_clamps_low(self):
        # pivot=5, second note=120 → reflected = 2*5-120 = -110 → 0
        beat = self._beat([5, 120])
        result = ma_utils.invert(beat)
        self.assertEqual(result[1].pitch, 0)

    def test_invert_clamps_high(self):
        # pivot=120, second note=5 → reflected = 2*120-5 = 235 → 127
        beat = self._beat([120, 5])
        result = ma_utils.invert(beat)
        self.assertEqual(result[1].pitch, 127)

    def test_invert_preserves_timing_and_velocity(self):
        note0 = self._note(pitch=60, start=0.0, end=0.5, velocity=100)
        note1 = self._note(pitch=64, start=0.5, end=1.0, velocity=80)
        result = ma_utils.invert([note0, note1])
        self.assertEqual(result[1].start, 0.5)
        self.assertEqual(result[1].end, 1.0)
        self.assertEqual(result[1].velocity, 80)

    def test_invert_does_not_mutate_input(self):
        beat = self._beat([60, 67])
        original_pitches = [n.pitch for n in beat]
        ma_utils.invert(beat)
        self.assertEqual([n.pitch for n in beat], original_pitches)

    def test_invert_is_own_inverse(self):
        beat = self._beat([60, 64, 67, 62])
        self.assertEqual(
            [n.pitch for n in ma_utils.invert(ma_utils.invert(beat))],
            [n.pitch for n in beat],
        )

    # ------------------------------------------------------------------ registry

    def test_beat_transformers_contains_tone_shift(self):
        self.assertIn("tone_shift", ma_utils.BEAT_TRANSFORMERS)

    def test_beat_transformers_contains_invert(self):
        self.assertIn("invert", ma_utils.BEAT_TRANSFORMERS)

    def test_beat_transformers_values_are_callable(self):
        for name, fn in ma_utils.BEAT_TRANSFORMERS.items():
            self.assertTrue(callable(fn), f"BEAT_TRANSFORMERS['{name}'] is not callable")

    def test_get_transformer_returns_correct_function(self):
        self.assertIs(ma_utils.get_transformer("invert"), ma_utils.invert)
        self.assertIs(ma_utils.get_transformer("tone_shift"), ma_utils.tone_shift)

    def test_get_transformer_unknown_raises_value_error(self):
        with self.assertRaises(ValueError):
            ma_utils.get_transformer("nonexistent")

    def test_get_transformer_error_lists_available(self):
        try:
            ma_utils.get_transformer("nonexistent")
        except ValueError as exc:
            self.assertIn("invert", str(exc))
            self.assertIn("tone_shift", str(exc))

    def test_get_transformer_result_is_usable(self):
        fn = ma_utils.get_transformer("invert")
        beat = self._beat([60, 67])
        result = fn(beat)
        self.assertEqual(result[0].pitch, 60)
        self.assertEqual(result[1].pitch, 53)  # 2*60-67


if __name__ == "__main__":
    unittest.main()
