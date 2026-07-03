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


if __name__ == "__main__":
    unittest.main()
