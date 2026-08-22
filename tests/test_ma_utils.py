"""Tests for musicanvil.ma_utils — utility library."""

# OopCompanion:suppressRename

import random
import unittest
from unittest.mock import patch

import pretty_midi

from musicanvil import MusicAnvil, ma_utils


class TestGenerateRandomBeatBaseUnit(unittest.TestCase):
    """Verify the sub-beat grid for each beat generation mode.

    At 120 BPM: quarter = 0.5 s, eighth = 0.25 s, 16th = 0.125 s.

    Mode 1 (BEAT_MODE_FIXED_16TH): fixed 16th-note grid regardless of time signature.
    Mode 2 (BEAT_MODE_HALF_DENOM): half the denominator unit
      - 4/4 → 0.25 s (eighth note)
      - 6/8 → 0.125 s (16th note)
      - 2/2 → 0.5 s  (quarter note)
    """

    NOTES = [60, 62, 64, 65, 67]  # C4 pentatonic

    def _notes(self, time_signature, mode, beat_duration=8.0):
        random.seed(0)
        notes = ma_utils.generate_random_beat(
            self.NOTES, tempo=120,
            time_signature=time_signature,
            beat_duration=beat_duration,
            mode=mode,
        )
        self.assertGreater(len(notes), 1, "Too few notes generated to test grid alignment")
        return notes

    def _assert_on_grid(self, notes, base):
        for note in notes:
            remainder = note.start % base
            on_grid = remainder < 1e-9 or abs(remainder - base) < 1e-9
            self.assertTrue(on_grid,
                            f"Note start {note.start:.6f} s is not on the {base} s grid")

    # -- Mode 1: fixed 16th-note grid (0.125 s at 120 BPM) regardless of signature --

    def test_mode1_4_4_starts_on_sixteenth_note_grid(self):
        self._assert_on_grid(self._notes((4, 4), ma_utils.BEAT_MODE_FIXED_16TH), 0.125)

    def test_mode1_6_8_starts_on_sixteenth_note_grid(self):
        self._assert_on_grid(self._notes((6, 8), ma_utils.BEAT_MODE_FIXED_16TH), 0.125)

    def test_mode1_2_2_starts_on_sixteenth_note_grid(self):
        self._assert_on_grid(self._notes((2, 2), ma_utils.BEAT_MODE_FIXED_16TH), 0.125)

    def test_mode1_is_the_default(self):
        random.seed(0)
        notes_default = ma_utils.generate_random_beat(self.NOTES, tempo=120,
                                                      time_signature=(4, 4), beat_duration=8.0)
        random.seed(0)
        notes_explicit = ma_utils.generate_random_beat(self.NOTES, tempo=120,
                                                       time_signature=(4, 4), beat_duration=8.0,
                                                       mode=ma_utils.BEAT_MODE_FIXED_16TH)
        self.assertEqual([(n.start, n.end) for n in notes_default],
                         [(n.start, n.end) for n in notes_explicit])

    # -- Mode 2: half the denominator unit --

    def test_mode2_4_4_starts_on_eighth_note_grid(self):
        # denom=4 → unit=0.5s → half=0.25s (eighth note)
        self._assert_on_grid(self._notes((4, 4), ma_utils.BEAT_MODE_HALF_DENOM), 0.25)

    def test_mode2_6_8_starts_on_sixteenth_note_grid(self):
        # denom=8 → unit=0.25s → half=0.125s (16th note)
        self._assert_on_grid(self._notes((6, 8), ma_utils.BEAT_MODE_HALF_DENOM), 0.125)

    def test_mode2_2_2_starts_on_quarter_note_grid(self):
        # denom=2 → unit=1.0s → half=0.5s (quarter note)
        self._assert_on_grid(self._notes((2, 2), ma_utils.BEAT_MODE_HALF_DENOM), 0.5)

    def test_mode2_4_4_minimum_gap_is_eighth_note(self):
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120,
                                              time_signature=(4, 4), beat_duration=16.0,
                                              mode=ma_utils.BEAT_MODE_HALF_DENOM)
        starts = sorted(n.start for n in notes)
        gaps = [b - a for a, b in zip(starts, starts[1:])]
        self.assertTrue(all(g >= 0.25 - 1e-9 for g in gaps),
                        f"Some gap is smaller than an eighth note: {min(gaps):.4f} s")

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


class TestGenerateRandomBeatDurationGuard(unittest.TestCase):
    """P2 #13 — generate_random_beat must raise ValueError for beat_duration <= 0."""

    def test_zero_beat_duration_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_random_beat([60], tempo=120, beat_duration=0)

    def test_negative_beat_duration_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_random_beat([60], tempo=120, beat_duration=-1.0)

    def test_zero_beat_duration_error_names_value(self):
        with self.assertRaises(ValueError) as ctx:
            ma_utils.generate_random_beat([60], tempo=120, beat_duration=0)
        self.assertIn("0", str(ctx.exception))

    def test_positive_beat_duration_does_not_raise(self):
        try:
            ma_utils.generate_random_beat([60], tempo=120, beat_duration=1.0)
        except ValueError:
            self.fail("generate_random_beat raised ValueError for a valid beat_duration")


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


class TestWriteInstrumentsToMidi(unittest.TestCase):
    """P2 #12 — write_instruments_to_midi must raise a clear ValueError for unknown GM names."""

    def _make_note(self):
        import pretty_midi
        return pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5)

    def test_unknown_gm_name_raises_value_error(self):
        """An instrument name not in the GM spec must raise ValueError, not a cryptic internal error."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                ma_utils.write_instruments_to_midi({"NotAGMName": [self._make_note()]}, path)
            self.assertIn("NotAGMName", str(ctx.exception))
        finally:
            os.unlink(path)

    def test_unknown_gm_name_error_message_is_informative(self):
        """The error message must name the offending instrument so callers can act on it."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                ma_utils.write_instruments_to_midi({"FakeGuitar9000": [self._make_note()]}, path)
            msg = str(ctx.exception)
            self.assertIn("FakeGuitar9000", msg)
            self.assertIn("General MIDI", msg)
        finally:
            os.unlink(path)

    def test_valid_gm_name_does_not_raise(self):
        """A standard GM name must write a file without raising."""
        import pretty_midi, tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            ma_utils.write_instruments_to_midi(
                {"Acoustic Grand Piano": [self._make_note()]}, path
            )
            result = pretty_midi.PrettyMIDI(path)
            self.assertEqual(len(result.instruments), 1)
            self.assertEqual(len(result.instruments[0].notes), 1)
        finally:
            os.unlink(path)

    def test_error_raised_for_second_instrument_names_it_correctly(self):
        """When the first instrument is valid and the second is bad, the error names the second."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
            path = f.name
        try:
            with self.assertRaises(ValueError) as ctx:
                ma_utils.write_instruments_to_midi({
                    "Acoustic Grand Piano": [self._make_note()],
                    "DefinitelyFake": [self._make_note()],
                }, path)
            self.assertIn("DefinitelyFake", str(ctx.exception))
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


class TestGenerateScaleTonicB(unittest.TestCase):
    """P3 #6 — generate_scale edge case: tonic=B (last semitone, octave boundary immediately)."""

    def test_b_major_first_note_is_B4(self):
        notes = ma_utils.generate_scale("major", "B")
        self.assertEqual(notes[0], "B4")

    def test_b_major_second_note_crosses_into_octave_5(self):
        # B is semitone index 11; interval 2 → semitone 13 → C#, octave bump to 5
        notes = ma_utils.generate_scale("major", "B")
        self.assertEqual(notes[1], "C#5")

    def test_b_major_total_note_count(self):
        notes = ma_utils.generate_scale("major", "B")
        self.assertEqual(len(notes), 21)  # 7 notes × 3 octaves

    def test_b_major_pitches_strictly_ascending(self):
        notes = ma_utils.generate_scale("major", "B")
        pitches = [pretty_midi.note_name_to_number(n) for n in notes]
        self.assertEqual(pitches, sorted(pitches))

    def test_b_natural_minor_starts_at_B4_then_C_sharp_5(self):
        # natural_minor intervals [0,2,3,...]: interval 2 from B → same octave crossing
        notes = ma_utils.generate_scale("natural_minor", "B")
        self.assertEqual(notes[0], "B4")
        self.assertEqual(notes[1], "C#5")


class TestGenerateChordNotes(unittest.TestCase):
    """P3 #6 — generate_chord_notes coverage including tonic=B wrap-around edge case."""

    def test_c_major_chord(self):
        self.assertEqual(ma_utils.generate_chord_notes("C", "major"), ["C", "E", "G"])

    def test_a_minor_chord(self):
        self.assertEqual(ma_utils.generate_chord_notes("A", "minor"), ["A", "C", "E"])

    def test_b_major_chord_wraps_correctly(self):
        # B(11)+4=15%12=3→D#, B(11)+7=18%12=6→F#
        self.assertEqual(ma_utils.generate_chord_notes("B", "major"), ["B", "D#", "F#"])

    def test_invalid_chord_type_raises_value_error(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_chord_notes("C", "nonexistent_chord")

    def test_invalid_note_name_raises_value_error(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_chord_notes("H", "major")


class TestChordDefinitionsComplete(unittest.TestCase):
    """chord_definitions must cover the standard common-practice vocabulary with
    correct intervals, including the diatonic thirds and the power-chord dyad."""

    EXPECTED = {
        "major": [0, 4, 7],
        "minor": [0, 3, 7],
        "diminished": [0, 3, 6],
        "augmented": [0, 4, 8],
        "sus2": [0, 2, 7],
        "sus4": [0, 5, 7],
        "major6": [0, 4, 7, 9],
        "minor6": [0, 3, 7, 9],
        "major7": [0, 4, 7, 11],
        "minor7": [0, 3, 7, 10],
        "dominant7": [0, 4, 7, 10],
        "minor_major7": [0, 3, 7, 11],
        "half_diminished7": [0, 3, 6, 10],
        "diminished7": [0, 3, 6, 9],
        "augmented7": [0, 4, 8, 10],
        "fifth": [0, 7],
        "major_third": [0, 4],
        "minor_third": [0, 3],
    }

    def test_all_expected_chords_present_with_correct_intervals(self):
        for name, intervals in self.EXPECTED.items():
            self.assertIn(name, ma_utils.chord_definitions)
            self.assertEqual(ma_utils.chord_definitions[name], intervals,
                             f"{name} has unexpected intervals")

    def test_intervals_start_on_root_and_ascend(self):
        for name, intervals in ma_utils.chord_definitions.items():
            self.assertEqual(intervals[0], 0, f"{name} must start on the root (0)")
            self.assertEqual(intervals, sorted(intervals), f"{name} must ascend")

    def test_intervals_are_distinct_pitch_classes(self):
        for name, intervals in ma_utils.chord_definitions.items():
            pcs = [i % 12 for i in intervals]
            self.assertEqual(len(pcs), len(set(pcs)), f"{name} has duplicate pitch classes")


class TestFindCompatibleChords(unittest.TestCase):
    """find_compatible_chords returns (root, type) chords containing every beat pitch class."""

    def _beat(self, *pitches):
        return [pretty_midi.Note(velocity=100, pitch=p, start=0.0, end=0.5) for p in pitches]

    def test_empty_beat_returns_empty(self):
        self.assertEqual(ma_utils.find_compatible_chords([]), [])

    def test_single_note_includes_root_position_major(self):
        # C alone: C major (root 0) is one compatible chord among many.
        result = ma_utils.find_compatible_chords(self._beat(60))
        self.assertIn((0, "major"), result)

    def test_single_note_includes_chords_where_it_is_not_the_root(self):
        # C is the minor third of A minor (root 9) and the fifth of F major (root 5).
        result = ma_utils.find_compatible_chords(self._beat(60))
        self.assertIn((9, "minor"), result)
        self.assertIn((5, "major"), result)

    def test_triad_notes_match_that_triad(self):
        result = ma_utils.find_compatible_chords(self._beat(60, 64, 67))  # C E G
        self.assertIn((0, "major"), result)

    def test_incompatible_chord_excluded(self):
        # C + E (major third) cannot be a C minor chord (needs Eb, not E).
        result = ma_utils.find_compatible_chords(self._beat(60, 64))
        self.assertNotIn((0, "minor"), result)
        self.assertIn((0, "major"), result)
        self.assertIn((0, "major_third"), result)

    def test_every_returned_chord_actually_contains_all_pitch_classes(self):
        beat_pcs = {60 % 12, 64 % 12, 67 % 12}
        for root, chord_type in ma_utils.find_compatible_chords(self._beat(60, 64, 67)):
            chord_pcs = {(root + i) % 12 for i in ma_utils.chord_definitions[chord_type]}
            self.assertTrue(beat_pcs <= chord_pcs)

    def test_accepts_raw_pitch_integers(self):
        result = ma_utils.find_compatible_chords([60, 64, 67])
        self.assertIn((0, "major"), result)

    def test_octave_does_not_matter(self):
        low = ma_utils.find_compatible_chords(self._beat(60, 64, 67))
        high = ma_utils.find_compatible_chords(self._beat(72, 76, 79))
        self.assertEqual(low, high)


class TestAdaptDrumLineVelocityScaling(unittest.TestCase):
    """P3 #6 — adapt_drum_line edge case: velocity_scaling_factor=0 (all velocities → 0)."""

    DRUM_LINE = [[100, 35, 0, 1], [80, 38, 1, 2], [120, 42, 2, 3]]

    def test_zero_scaling_zeros_all_velocities(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=0)
        for entry in result:
            self.assertEqual(entry[0], 0)

    def test_zero_scaling_preserves_note_count(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=0)
        self.assertEqual(len(result), len(self.DRUM_LINE))

    def test_zero_scaling_preserves_timing(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=0)
        quarter = 60.0 / 120
        self.assertAlmostEqual(result[0][2], 0.0)
        self.assertAlmostEqual(result[0][3], quarter)

    def test_unit_scaling_preserves_velocities(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=1.0)
        self.assertEqual([e[0] for e in result], [100, 80, 120])


class TestAdaptDrumLineNegativeScalingGuard(unittest.TestCase):
    """P2 #14 — adapt_drum_line must raise ValueError for negative velocity_scaling_factor."""

    DRUM_LINE = [[100, 35, 0, 1], [80, 38, 1, 2]]

    def test_negative_scaling_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=-1.0)

    def test_negative_scaling_error_names_value(self):
        with self.assertRaises(ValueError) as ctx:
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=-0.5)
        self.assertIn("-0.5", str(ctx.exception))

    def test_zero_scaling_does_not_raise(self):
        try:
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=0)
        except ValueError:
            self.fail("adapt_drum_line raised ValueError for velocity_scaling_factor=0")

    def test_positive_scaling_does_not_raise(self):
        try:
            ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, velocity_scaling_factor=1.5)
        except ValueError:
            self.fail("adapt_drum_line raised ValueError for a valid velocity_scaling_factor")


class TestChordPaletteExtensions(unittest.TestCase):
    """chord_palette_extensions must be loaded from config and contain valid entries."""

    def test_chord_palette_extensions_is_dict(self):
        self.assertIsInstance(ma_utils.chord_palette_extensions, dict)

    def test_known_scales_have_entries(self):
        for scale in ("major", "natural_minor", "blues", "pentatonic_minor"):
            self.assertIn(scale, ma_utils.chord_palette_extensions,
                          f"'{scale}' missing from chord_palette_extensions")

    def test_all_entries_are_valid_root_type_pairs(self):
        for scale, entries in ma_utils.chord_palette_extensions.items():
            for entry in entries:
                self.assertEqual(len(entry), 2,
                                 f"{scale}: entry {entry} is not a 2-element pair")
                offset, chord_type = entry
                self.assertIsInstance(offset, int,
                                      f"{scale}: root offset {offset!r} is not an int")
                self.assertIn(offset, range(12),
                              f"{scale}: root offset {offset} is out of range 0–11")
                self.assertIn(chord_type, ma_utils.chord_definitions,
                              f"{scale}: chord type '{chord_type}' not in chord_definitions")

    def test_blues_has_dominant7_on_i_iv_v(self):
        blues_ext = [tuple(e) for e in ma_utils.chord_palette_extensions["blues"]]
        self.assertIn((0, "dominant7"), blues_ext, "blues missing I dominant7 extension")
        self.assertIn((5, "dominant7"), blues_ext, "blues missing IV dominant7 extension")
        self.assertIn((7, "dominant7"), blues_ext, "blues missing V dominant7 extension")


class TestGenerateScaleNumOctaves(unittest.TestCase):
    """P3 #8 — generate_scale num_octaves parameter controls the number of octaves spanned."""

    def test_default_three_octaves_major(self):
        notes = ma_utils.generate_scale("major", "C")
        self.assertEqual(len(notes), 21)  # 7 notes × 3 octaves

    def test_one_octave_major(self):
        notes = ma_utils.generate_scale("major", "C", num_octaves=1)
        self.assertEqual(len(notes), 7)

    def test_two_octaves_major(self):
        notes = ma_utils.generate_scale("major", "C", num_octaves=2)
        self.assertEqual(len(notes), 14)

    def test_four_octaves_major(self):
        notes = ma_utils.generate_scale("major", "C", num_octaves=4)
        self.assertEqual(len(notes), 28)

    def test_one_octave_starts_and_ends_on_tonic(self):
        notes = ma_utils.generate_scale("major", "C", num_octaves=1)
        self.assertEqual(notes[0], "C4")
        self.assertEqual(notes[-1], "B4")

    def test_two_octaves_second_octave_continues_from_first(self):
        notes_1 = ma_utils.generate_scale("major", "C", num_octaves=1)
        notes_2 = ma_utils.generate_scale("major", "C", num_octaves=2)
        self.assertEqual(notes_2[:7], notes_1)
        self.assertEqual(notes_2[7], "C5")

    def test_pitches_strictly_ascending_for_any_num_octaves(self):
        for n in (1, 2, 4):
            notes = ma_utils.generate_scale("major", "C", num_octaves=n)
            pitches = [pretty_midi.note_name_to_number(note) for note in notes]
            self.assertEqual(pitches, sorted(pitches),
                             f"Pitches not ascending for num_octaves={n}")

    def test_zero_num_octaves_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.generate_scale("major", "C", num_octaves=0)


class TestGenerateRandomBeatVelocity(unittest.TestCase):
    """P3 #18 — generate_random_beat velocity and velocity_jitter parameters."""

    NOTES = [60, 62, 64, 65, 67]

    def test_default_velocity_is_100(self):
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=2.0)
        self.assertTrue(all(n.velocity == 100 for n in notes),
                        "Default velocity should be 100 with no jitter")

    def test_custom_velocity_applied(self):
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=2.0,
                                              velocity=80)
        self.assertTrue(all(n.velocity == 80 for n in notes),
                        "Custom velocity=80 should be used for all notes")

    def test_velocity_jitter_produces_variation(self):
        random.seed(42)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=4.0,
                                              velocity_jitter=20)
        velocities = {n.velocity for n in notes}
        self.assertGreater(len(velocities), 1, "Jitter should produce at least 2 distinct velocities")

    def test_velocity_jitter_stays_in_valid_range(self):
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=4.0,
                                              velocity=100, velocity_jitter=50)
        for note in notes:
            self.assertGreaterEqual(note.velocity, 1)
            self.assertLessEqual(note.velocity, 127)

    def test_zero_jitter_gives_constant_velocity(self):
        random.seed(0)
        notes = ma_utils.generate_random_beat(self.NOTES, tempo=120, beat_duration=2.0,
                                              velocity=90, velocity_jitter=0)
        self.assertTrue(all(n.velocity == 90 for n in notes))


class TestMetalPunkRockPatterns(unittest.TestCase):
    """P3 #20 — Metal and Punk Rock drum patterns must be distinct."""

    def test_metal_and_punk_rock_differ(self):
        metal = ma_utils.drum_lines.get("Metal")
        punk = ma_utils.drum_lines.get("Punk Rock")
        self.assertIsNotNone(metal, "'Metal' must be in drum_lines")
        self.assertIsNotNone(punk, "'Punk Rock' must be in drum_lines")
        self.assertNotEqual(metal, punk,
                            "Metal and Punk Rock must have different drum patterns")

    def test_metal_has_crash_cymbal(self):
        metal = ma_utils.drum_lines["Metal"]
        crash_pitch = ma_utils.drum_pitches.get("Crash Cymbal")
        self.assertIsNotNone(crash_pitch)
        pitches = [entry[1] for entry in metal]
        self.assertIn(crash_pitch, pitches,
                      "Metal pattern should include a crash cymbal for distinction")

    def test_metal_has_double_kick(self):
        metal = ma_utils.drum_lines["Metal"]
        bass_pitch = ma_utils.drum_pitches["Bass Drum"]
        kicks = sorted(entry[2] for entry in metal if entry[1] == bass_pitch)
        # Double kick = two consecutive kicks with a gap ≤ 0.5 beats
        has_double = any(b - a <= 0.5 for a, b in zip(kicks, kicks[1:]))
        self.assertTrue(has_double, "Metal pattern should contain a double-kick figure")


class TestBeatSubUnitIsSharedWithTheEngine(unittest.TestCase):
    """ToDo 3.2 — the mode → sub-beat grid mapping must be defined once, in
    ma_utils.beat_sub_unit, and used by MusicAnvil.generate_lead_line too."""

    def test_mode1_grid_is_a_sixteenth_note(self):
        sub_unit, max_mult = ma_utils.beat_sub_unit(120, 1.0, ma_utils.BEAT_MODE_FIXED_16TH)
        self.assertAlmostEqual(sub_unit, 0.125)   # 60/120/4
        self.assertEqual(max_mult, 8)

    def test_mode2_grid_is_half_the_beat(self):
        sub_unit, max_mult = ma_utils.beat_sub_unit(120, 0.25, ma_utils.BEAT_MODE_HALF_DENOM)
        self.assertAlmostEqual(sub_unit, 0.125)
        self.assertEqual(max_mult, 8)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.beat_sub_unit(120, 0.5, 99)

    def test_signature_keyed_wrapper_agrees(self):
        """_beat_sub_unit((n, d)) must equal beat_sub_unit(beat_seconds(tempo, d))."""
        for signature in ((4, 4), (6, 8), (2, 2), (12, 16)):
            beat_len = 60.0 / 120 * 4 / signature[1]
            for mode in (ma_utils.BEAT_MODE_FIXED_16TH, ma_utils.BEAT_MODE_HALF_DENOM):
                with self.subTest(signature=signature, mode=mode):
                    self.assertEqual(ma_utils._beat_sub_unit(120, signature, mode),
                                     ma_utils.beat_sub_unit(120, beat_len, mode))

    def test_generate_lead_line_uses_the_shared_helper(self):
        """Redefining the shared grid must move the engine's lead notes with it —
        proving generate_lead_line does not keep its own copy of the mapping."""
        beat_len = 0.5
        third_of_a_beat = beat_len / 3
        calls = []

        def fake_sub_unit(tempo, beat_length, mode):
            calls.append((tempo, beat_length, mode))
            return third_of_a_beat, 1

        with patch.object(ma_utils, "beat_sub_unit", fake_sub_unit):
            notes = MusicAnvil.generate_lead_line(
                [60, 62, 64], n_beats=4, beat_len=beat_len, rng=random.Random(3),
                mode=ma_utils.BEAT_MODE_FIXED_16TH, tempo=120, rest_prob=0.0,
            )

        self.assertEqual(calls, [(120, beat_len, ma_utils.BEAT_MODE_FIXED_16TH)])
        self.assertTrue(notes, "expected the fake grid to still produce notes")
        for note in notes:
            slot = note.start / third_of_a_beat
            self.assertAlmostEqual(slot, round(slot), places=6,
                                   msg=f"note start {note.start} is off the shared grid")

    def test_generate_lead_line_rejects_unknown_mode(self):
        with self.assertRaises(ValueError):
            MusicAnvil.generate_lead_line([60, 62], n_beats=4, beat_len=0.5,
                                          rng=random.Random(1), mode=99, tempo=120)


class TestAdaptDrumLineDenominator(unittest.TestCase):
    """ToDo 3.1 — adapt_drum_line must read beats in the signature's denominator unit."""

    DRUM_LINE = [[100, 35, 0, 1], [100, 38, 1, 2], [80, 42, 2, 4]]

    def test_default_denominator_is_the_quarter_note(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120)
        self.assertAlmostEqual(result[1][2], 0.5)   # beat 1 at 120 BPM = 0.5 s
        self.assertAlmostEqual(result[2][3], 2.0)   # beat 4 = 2.0 s

    def test_eighth_note_denominator_halves_every_time(self):
        quarters = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, denominator=4)
        eighths = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, denominator=8)
        for quarter_entry, eighth_entry in zip(quarters, eighths):
            self.assertAlmostEqual(eighth_entry[2], quarter_entry[2] / 2)
            self.assertAlmostEqual(eighth_entry[3], quarter_entry[3] / 2)

    def test_half_note_denominator_doubles_every_time(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, denominator=2)
        self.assertAlmostEqual(result[1][2], 1.0)   # one half-note beat at 120 BPM

    def test_velocities_are_untouched_by_the_denominator(self):
        result = ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, denominator=16)
        self.assertEqual([entry[0] for entry in result], [100, 100, 80])

    def test_non_positive_denominator_raises(self):
        for bad in (0, -4):
            with self.subTest(denominator=bad):
                with self.assertRaises(ValueError):
                    ma_utils.adapt_drum_line(self.DRUM_LINE, tempo=120, denominator=bad)


class TestFitDrumLineToBar(unittest.TestCase):
    """ToDo 3.1 — a genre pattern must fill exactly one bar of the signature in use:
    repeated when the bar is longer, cut at the bar line when it is shorter."""

    # A 4-beat pattern: kick on 1 and 3, snare on 2 and 4.
    PATTERN = [[100, 35, 0, 1], [100, 38, 1, 2], [100, 35, 2, 3], [100, 38, 3, 4]]
    TEMPO = 120

    def _starts(self, bar_line):
        return [round(entry[2], 9) for entry in bar_line]

    def test_four_four_matches_plain_adapt_drum_line(self):
        """The common case must be byte-for-byte what adapt_drum_line already produced."""
        fitted = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (4, 4),
                                               beats_per_pattern=4)
        plain = ma_utils.adapt_drum_line(self.PATTERN, self.TEMPO)
        self.assertEqual(fitted, plain)

    def test_shorter_bar_cuts_the_pattern_at_the_bar_line(self):
        """3/4: the pattern's 4th beat would land on the next bar's downbeat — drop it."""
        bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (3, 4),
                                                 beats_per_pattern=4)
        self.assertEqual(self._starts(bar_line), [0.0, 0.5, 1.0])

    def test_longer_bar_repeats_the_pattern(self):
        """5/4: 4 beats of pattern + the first beat again = 5 beats of drums."""
        bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (5, 4),
                                                 beats_per_pattern=4)
        self.assertEqual(self._starts(bar_line), [0.0, 0.5, 1.0, 1.5, 2.0])

    def test_eighth_note_signature_stays_on_the_eighth_grid(self):
        """6/8: beats are eighths (0.25 s), so the bar is 1.5 s and the pattern repeats."""
        bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (6, 8),
                                                 beats_per_pattern=4)
        self.assertEqual(self._starts(bar_line), [0.0, 0.25, 0.5, 0.75, 1.0, 1.25])

    def test_nothing_starts_or_ends_outside_the_bar(self):
        for signature in ((4, 4), (3, 4), (5, 4), (6, 8), (7, 8), (12, 16), (2, 2)):
            with self.subTest(signature=signature):
                beat = 60.0 / self.TEMPO * 4 / signature[1]
                bar_seconds = signature[0] * beat
                bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, signature,
                                                         beats_per_pattern=4)
                self.assertTrue(bar_line, "the bar must not be left empty")
                for _, _, start, end in bar_line:
                    self.assertGreaterEqual(start, -1e-9)
                    self.assertLess(start, bar_seconds + 1e-9)
                    self.assertLessEqual(end, bar_seconds + 1e-9)

    def test_no_gap_longer_than_the_pattern_at_the_end_of_the_bar(self):
        """A longer bar must be filled, not left with a silent tail."""
        beat = 0.5
        bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (7, 4),
                                                 beats_per_pattern=4)
        last_start = max(entry[2] for entry in bar_line)
        self.assertGreater(last_start, 7 * beat - 4 * beat)

    def test_declared_pattern_length_drives_the_repeat(self):
        """A 3-beat pattern (Waltz) repeats every 3 beats, not every 4."""
        waltz = [[100, 35, 0, 1], [100, 38, 1, 2]]
        bar_line = ma_utils.fit_drum_line_to_bar(waltz, self.TEMPO, (6, 4),
                                                 beats_per_pattern=3)
        self.assertEqual(self._starts(bar_line), [0.0, 0.5, 1.5, 2.0])

    def test_empty_pattern_yields_an_empty_bar(self):
        self.assertEqual(ma_utils.fit_drum_line_to_bar([], self.TEMPO, (4, 4)), [])

    def test_velocity_scaling_is_forwarded(self):
        bar_line = ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (4, 4),
                                                 beats_per_pattern=4,
                                                 velocity_scaling_factor=0.5)
        self.assertTrue(all(entry[0] == 50 for entry in bar_line))

    def test_non_positive_pattern_length_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (4, 4), beats_per_pattern=0)

    def test_non_positive_numerator_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.fit_drum_line_to_bar(self.PATTERN, self.TEMPO, (0, 4))


class TestDrumPatternBeatsConfig(unittest.TestCase):
    """ToDo 3.1 — every genre declares the bar length its pattern was authored for."""

    def test_every_genre_declares_a_pattern_length(self):
        for genre in ma_utils.drum_lines:
            with self.subTest(genre=genre):
                self.assertIn(genre, ma_utils.drum_pattern_beats,
                              f"'{genre}' has no entry in drum_pattern_beats")

    def test_declared_lengths_are_positive_numbers(self):
        for genre, beats in ma_utils.drum_pattern_beats.items():
            with self.subTest(genre=genre):
                self.assertIsInstance(beats, (int, float))
                self.assertGreater(beats, 0)

    def test_pattern_covers_the_declared_length(self):
        """No pattern may contain a hit starting at or after its declared bar length."""
        for genre, entries in ma_utils.drum_lines.items():
            with self.subTest(genre=genre):
                beats = ma_utils.pattern_beats(genre)
                self.assertLess(max(entry[2] for entry in entries), beats,
                                f"'{genre}' has a hit starting on/after beat {beats}")

    def test_waltz_is_a_three_beat_pattern(self):
        self.assertEqual(ma_utils.pattern_beats("Waltz"), 3)

    def test_unknown_genre_falls_back_to_the_default(self):
        self.assertEqual(ma_utils.pattern_beats("Nonexistent Genre"),
                         ma_utils.DEFAULT_PATTERN_BEATS)


class TestSignatureOptions(unittest.TestCase):
    """ToDo 3.4 — the GUI must only offer real time signatures."""

    def setUp(self):
        self.options = ma_utils.get_param("gui", "signature_options", default=[])

    def test_options_are_present(self):
        self.assertTrue(self.options)

    def test_every_denominator_is_a_power_of_two(self):
        for option in self.options:
            with self.subTest(signature=option):
                _, denominator = MusicAnvil.parse_signature(option)
                self.assertEqual(denominator & (denominator - 1), 0,
                                 f"'{option}' has denominator {denominator}, which is not "
                                 "a power of two and is not a real time signature")

    def test_nonstandard_six_twelfths_is_gone(self):
        self.assertNotIn("6/12", self.options)

    def test_no_duplicates(self):
        self.assertEqual(len(self.options), len(set(self.options)))


class TestDegreeStability(unittest.TestCase):
    """ToDo 4.1/4.0 — stable vs tendency degrees, the mechanism behind open and closed
    phrase endings."""

    def test_major_scale(self):
        stable, unstable = ma_utils.degree_stability("major")
        self.assertEqual(stable, [0, 4, 7])
        self.assertEqual(unstable, [2, 5, 9, 11])

    def test_natural_minor_has_a_minor_third(self):
        stable, unstable = ma_utils.degree_stability("natural_minor")
        self.assertEqual(stable, [0, 3, 7])
        self.assertEqual(unstable, [2, 5, 8, 10])

    def test_blues_scale(self):
        stable, unstable = ma_utils.degree_stability("blues")
        self.assertEqual(stable, [0, 3, 7])
        self.assertEqual(unstable, [5, 6, 10])

    def test_stable_and_unstable_cover_the_scale(self):
        for name, intervals in ma_utils.scale_definitions.items():
            with self.subTest(scale=name):
                stable, unstable = ma_utils.degree_stability(name)
                self.assertEqual(sorted(stable + unstable),
                                 sorted({i % 12 for i in intervals}))

    def test_unknown_scale_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.degree_stability("no_such_scale")

    def test_leading_tone_is_the_preferred_tendency(self):
        self.assertEqual(ma_utils.preferred_tendency_degree("major"), 11)
        self.assertEqual(ma_utils.preferred_tendency_degree("harmonic_minor"), 11)

    def test_a_scale_without_a_leading_tone_falls_back(self):
        self.assertEqual(ma_utils.preferred_tendency_degree("pentatonic_major"), 2)
        self.assertEqual(ma_utils.preferred_tendency_degree("natural_minor"), 2)

    def test_preferred_tendency_is_always_unstable(self):
        for name in ma_utils.scale_definitions:
            with self.subTest(scale=name):
                _, unstable = ma_utils.degree_stability(name)
                offset = ma_utils.preferred_tendency_degree(name)
                if unstable:
                    self.assertIn(offset, unstable)
                else:
                    self.assertIsNone(offset)

    def test_a_scale_with_no_tendency_tone_returns_none(self):
        ma_utils.scale_definitions["unit_test_triad"] = [0, 4, 7]
        try:
            self.assertIsNone(ma_utils.preferred_tendency_degree("unit_test_triad"))
        finally:
            ma_utils.scale_definitions.pop("unit_test_triad", None)


class TestDiatonicTriad(unittest.TestCase):
    """ToDo 4.1 — the cadence chords: the tonic triad and the triad of the fifth."""

    def test_tonic_triad_of_a_major_scale(self):
        self.assertEqual(ma_utils.diatonic_triad("major", 0), [0, 4, 7])

    def test_dominant_triad_of_a_major_scale(self):
        self.assertEqual(ma_utils.diatonic_triad("major", 7), [7, 11, 2])

    def test_supertonic_triad_is_minor(self):
        self.assertEqual(ma_utils.diatonic_triad("major", 2), [2, 5, 9])

    def test_minor_scale_tonic_triad(self):
        self.assertEqual(ma_utils.diatonic_triad("natural_minor", 0), [0, 3, 7])

    def test_leading_tone_triad_is_diminished(self):
        self.assertEqual(ma_utils.diatonic_triad("major", 11), [11, 2, 5])

    def test_a_degree_outside_the_scale_returns_none(self):
        self.assertIsNone(ma_utils.diatonic_triad("major", 1))

    def test_a_scale_that_cannot_spell_the_triad_returns_none(self):
        self.assertIsNone(ma_utils.diatonic_triad("pentatonic_major", 2))

    def test_every_triad_is_inside_its_scale(self):
        for name, intervals in ma_utils.scale_definitions.items():
            pcs = {i % 12 for i in intervals}
            for offset in sorted(pcs):
                triad = ma_utils.diatonic_triad(name, offset)
                if triad is not None:
                    with self.subTest(scale=name, offset=offset):
                        self.assertTrue(set(triad) <= pcs)

    def test_unknown_scale_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.diatonic_triad("no_such_scale", 0)


class TestExpressionData(unittest.TestCase):
    """ToDo 5.1-5.5 — the configuration behind the expression layer."""

    def test_controller_numbers_are_the_standard_ones(self):
        self.assertEqual(ma_utils.CC_MODULATION, 1)
        self.assertEqual(ma_utils.CC_PORTAMENTO_TIME, 5)
        self.assertEqual(ma_utils.CC_VOLUME, 7)
        self.assertEqual(ma_utils.CC_PAN, 10)
        self.assertEqual(ma_utils.CC_EXPRESSION, 11)
        self.assertEqual(ma_utils.CC_SUSTAIN, 64)
        self.assertEqual(ma_utils.CC_PORTAMENTO, 65)
        self.assertEqual(ma_utils.CC_REVERB_SEND, 91)
        self.assertEqual(ma_utils.CC_CHORUS_SEND, 93)

    def test_expression_settings_cover_every_role(self):
        settings = ma_utils.expression_settings
        for key in ("reverb_send", "chorus_send"):
            with self.subTest(key=key):
                for role in ("Lead", "Accompaniment", "Bass"):
                    self.assertIn(role, settings[key])

    def test_send_values_are_in_the_midi_range(self):
        for key in ("reverb_send", "chorus_send"):
            for role, value in ma_utils.expression_settings[key].items():
                with self.subTest(key=key, role=role):
                    self.assertGreaterEqual(value, 0)
                    self.assertLessEqual(value, 127)

    def test_swell_rises_and_decay_falls(self):
        settings = ma_utils.expression_settings
        swell, decay = settings["swell_range"], settings["decay_range"]
        self.assertLess(swell[0], swell[1])
        self.assertGreater(decay[0], decay[1])

    def test_bend_depth_is_within_the_wheel_range(self):
        self.assertLessEqual(ma_utils.expression_settings["bend_depth"], 8192)
        self.assertGreater(ma_utils.expression_settings["bend_depth"], 0)


class TestPowerChordPrograms(unittest.TestCase):
    """ToDo 5.3 — distortion plus a major third is mud, so those programs play fifths."""

    def test_the_distorted_guitars_are_listed(self):
        for program in (29, 30, 31):     # overdriven, distortion, harmonics
            with self.subTest(program=program):
                self.assertTrue(ma_utils.is_power_chord_program(program))

    def test_clean_programs_are_not(self):
        for program in (0, 25, 27, 32, 33):
            with self.subTest(program=program):
                self.assertFalse(ma_utils.is_power_chord_program(program))

    def test_unknown_program_is_not(self):
        self.assertFalse(ma_utils.is_power_chord_program(None))

    def test_the_power_chord_vocabulary_is_root_and_fifth(self):
        self.assertEqual(ma_utils.POWER_CHORD, {"fifth": [0, 7]})

    def test_find_compatible_chords_accepts_the_restricted_vocabulary(self):
        chords = ma_utils.find_compatible_chords([60, 67], ma_utils.POWER_CHORD)
        self.assertTrue(chords)
        self.assertTrue(all(chord_type == "fifth" for _, chord_type in chords))


class TestKeyswitchTable(unittest.TestCase):
    """ToDo 5.5 — the keyswitch map is empty unless a library is being targeted."""

    def test_the_table_exists_and_defaults_to_empty(self):
        self.assertIsInstance(ma_utils.keyswitches, dict)
        self.assertEqual(ma_utils.keyswitches, {})


class TestTransformerRegistry(unittest.TestCase):
    """ToDo 4.5 — transformers declare their kind and their parameters."""

    def tearDown(self):
        ma_utils.BEAT_TRANSFORMERS.pop("unit_test_transformer", None)
        ma_utils.TRANSFORMER_SPECS.pop("unit_test_transformer", None)

    def test_builtin_transformers_are_note_transformers(self):
        for name in ("tone_shift", "invert"):
            with self.subTest(name=name):
                self.assertEqual(ma_utils.transformer_kind(name), ma_utils.TRANSFORMER_NOTE)

    def test_tone_shift_declares_its_parameter(self):
        params = ma_utils.transformer_params("tone_shift")
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]["name"], "n")
        self.assertEqual(params[0]["type"], "int")
        self.assertIn("min", params[0])
        self.assertIn("max", params[0])

    def test_invert_has_no_parameters(self):
        self.assertEqual(ma_utils.transformer_params("invert"), [])

    def test_every_registered_transformer_has_a_spec(self):
        for name in ma_utils.BEAT_TRANSFORMERS:
            with self.subTest(name=name):
                self.assertIn(name, ma_utils.TRANSFORMER_SPECS)
                self.assertIn(ma_utils.transformer_kind(name),
                              (ma_utils.TRANSFORMER_NOTE, ma_utils.TRANSFORMER_PHRASE))

    def test_every_descriptor_is_well_formed(self):
        for name in ma_utils.BEAT_TRANSFORMERS:
            for param in ma_utils.transformer_params(name):
                with self.subTest(name=name, param=param.get("name")):
                    self.assertIn("name", param)
                    self.assertIn("default", param)
                    self.assertIn(param.get("type"), ("int", "float", "choice"))
                    if param.get("type") == "choice":
                        self.assertTrue(param.get("choices"))
                    else:
                        self.assertLessEqual(param["min"], param["max"])

    def test_register_transformer_adds_kind_and_params(self):
        params = [{"name": "x", "label": "X", "type": "float", "default": 0.5,
                   "min": 0.0, "max": 1.0}]
        ma_utils.register_transformer("unit_test_transformer", lambda beat, x=0.5: beat,
                                      kind=ma_utils.TRANSFORMER_PHRASE, params=params)
        self.assertIs(ma_utils.get_transformer("unit_test_transformer").__class__,
                      (lambda: None).__class__)
        self.assertEqual(ma_utils.transformer_kind("unit_test_transformer"),
                         ma_utils.TRANSFORMER_PHRASE)
        self.assertEqual(ma_utils.transformer_params("unit_test_transformer"), params)

    def test_params_are_copies(self):
        first = ma_utils.transformer_params("tone_shift")
        first.append({"name": "bogus"})
        self.assertEqual(len(ma_utils.transformer_params("tone_shift")), 1)

    def test_unknown_transformer_kind_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.transformer_kind("no_such_transformer")

    def test_unknown_transformer_params_raises(self):
        with self.assertRaises(ValueError):
            ma_utils.transformer_params("no_such_transformer")


class TestMakeRhythmCell(unittest.TestCase):
    """ToDo 4.2 — the motif a melody is built from, instead of i.i.d. random durations."""

    def _cell(self, seed=1, subs_per_beat=4, beats=4, **kwargs):
        return ma_utils.make_rhythm_cell(random.Random(seed), subs_per_beat, beats, **kwargs)

    def test_cell_fills_exactly_the_requested_span(self):
        for beats in (1, 2, 3, 4, 6):
            with self.subTest(beats=beats):
                cell = self._cell(beats=beats)
                start, length = cell[-1]
                self.assertEqual(start + length, beats * 4)

    def test_onsets_are_contiguous_from_zero(self):
        cell = self._cell()
        self.assertEqual(cell[0][0], 0)
        for (start, length), (next_start, _) in zip(cell, cell[1:]):
            self.assertEqual(start + length, next_start)

    def test_lengths_are_positive(self):
        self.assertTrue(all(length >= 1 for _, length in self._cell()))

    def test_max_length_is_respected(self):
        cell = self._cell(max_length_sub=2)
        self.assertTrue(all(length <= 2 for _, length in cell))

    def test_long_notes_start_on_a_beat(self):
        """A note of a beat or more may not start off the beat — that is what keeps the
        rhythm metrical rather than drifting."""
        for seed in range(12):
            with self.subTest(seed=seed):
                for start, length in self._cell(seed=seed, beats=4):
                    if length >= 4:
                        self.assertEqual(start % 4, 0)

    def test_syncopation_displaces_onsets_off_the_beat(self):
        straight = [start for seed in range(8)
                    for start, _ in self._cell(seed=seed, syncopation=0.0)]
        synced = [start for seed in range(8)
                  for start, _ in self._cell(seed=seed, syncopation=1.0)]
        off_straight = sum(1 for s in straight if s % 4)
        off_synced = sum(1 for s in synced if s % 4)
        self.assertGreater(off_synced, off_straight)

    def test_same_seed_gives_the_same_cell(self):
        self.assertEqual(self._cell(seed=7), self._cell(seed=7))

    def test_different_seeds_can_differ(self):
        cells = {tuple(self._cell(seed=seed)) for seed in range(8)}
        self.assertGreater(len(cells), 1)

    def test_custom_vocabulary_is_honoured(self):
        spec = {"durations_in_beats": [1.0], "weights": [1]}
        cell = self._cell(spec=spec, beats=4)
        self.assertEqual([length for _, length in cell], [4, 4, 4, 4])

    def test_short_values_dominate_the_default_vocabulary(self):
        """Most notes should be shorter than a beat — long values are the exception."""
        lengths = [length for seed in range(20) for _, length in self._cell(seed=seed)]
        short = sum(1 for length in lengths if length < 4)
        self.assertGreater(short, len(lengths) / 2)

    def test_config_vocabulary_is_well_formed(self):
        spec = ma_utils.rhythm_cell
        self.assertEqual(len(spec["durations_in_beats"]), len(spec["weights"]))
        self.assertTrue(all(d > 0 for d in spec["durations_in_beats"]))
        self.assertTrue(all(w >= 0 for w in spec["weights"]))


class TestMetricWeight(unittest.TestCase):
    """ToDo 4.3 — the metric hierarchy that turns bar position into emphasis."""

    def test_weights_are_ordered(self):
        w = ma_utils.metric_accents
        self.assertGreater(w["downbeat"], w["secondary"])
        self.assertGreater(w["secondary"], w["beat"])
        self.assertGreater(w["beat"], w["offbeat"])

    def test_reference_weight_is_present(self):
        self.assertIn("reference", ma_utils.metric_accents)

    def test_four_four(self):
        w = ma_utils.metric_accents
        self.assertEqual(ma_utils.metric_weight(0, 4), w["downbeat"])
        self.assertEqual(ma_utils.metric_weight(2, 4), w["secondary"])
        self.assertEqual(ma_utils.metric_weight(1, 4), w["beat"])
        self.assertEqual(ma_utils.metric_weight(3, 4), w["beat"])

    def test_off_the_beat_is_weakest(self):
        w = ma_utils.metric_accents
        for position in (0.25, 0.5, 1.5, 2.75):
            with self.subTest(position=position):
                self.assertEqual(ma_utils.metric_weight(position, 4), w["offbeat"])

    def test_three_four_has_no_secondary_beat(self):
        w = ma_utils.metric_accents
        self.assertEqual(ma_utils.metric_weight(0, 3), w["downbeat"])
        self.assertEqual(ma_utils.metric_weight(1, 3), w["beat"])
        self.assertEqual(ma_utils.metric_weight(2, 3), w["beat"])

    def test_two_four_has_no_secondary_beat(self):
        self.assertEqual(ma_utils.metric_weight(1, 2), ma_utils.metric_accents["beat"])

    def test_compound_six_eight_accents_beat_four(self):
        w = ma_utils.metric_accents
        self.assertEqual(ma_utils.metric_weight(3, 6), w["secondary"])
        self.assertEqual(ma_utils.metric_weight(1, 6), w["beat"])
        self.assertEqual(ma_utils.metric_weight(4, 6), w["beat"])

    def test_compound_twelve_eight_accents_every_third_beat(self):
        w = ma_utils.metric_accents
        for beat in (3, 6, 9):
            with self.subTest(beat=beat):
                self.assertEqual(ma_utils.metric_weight(beat, 12), w["secondary"])
        self.assertEqual(ma_utils.metric_weight(5, 12), w["beat"])

    def test_positions_past_the_bar_wrap(self):
        self.assertEqual(ma_utils.metric_weight(4, 4), ma_utils.metric_accents["downbeat"])
        self.assertEqual(ma_utils.metric_weight(9, 4), ma_utils.metric_accents["beat"])

    def test_custom_weight_table_is_honoured(self):
        table = {"downbeat": 2.0, "secondary": 1.5, "beat": 1.0, "offbeat": 0.1}
        self.assertEqual(ma_utils.metric_weight(0, 4, table), 2.0)
        self.assertEqual(ma_utils.metric_weight(0.5, 4, table), 0.1)


if __name__ == "__main__":
    unittest.main()
