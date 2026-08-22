"""Tests for the musical-time layer (ToDo 4.7).

Generation happens on an integer grid of sub-beat units carrying phrase/metric
provenance, and is converted to seconds exactly once. These tests pin the grid
arithmetic, the phrase plan and the materialisation, and assert that introducing the
layer did not change what the engine renders.
"""

# OopCompanion:suppressRename

import random
import unittest

import pretty_midi

from musicanvil import MusicAnvil, ma_utils


def _piece(bars=4, signature=(4, 4), tempo=120, **kwargs):
    return MusicAnvil.PieceSpec(
        tempo=tempo, signature=signature, rhythm="Rock", scale="major", tonic="C",
        roles={
            MusicAnvil.ROLE_LEAD: MusicAnvil.RoleAssignment(main="Piano", supports=["Flute"]),
            MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(main="Guitar"),
            MusicAnvil.ROLE_BASS: MusicAnvil.RoleAssignment(main="Bass"),
        },
        sections={"A": MusicAnvil.SectionSpec(name="A", bars=bars, **kwargs)},
        structure=["A"],
    )


def _resolved(bars=4, signature=(4, 4), tempo=120, **kwargs):
    piece = _piece(bars=bars, signature=signature, tempo=tempo, **kwargs)
    return MusicAnvil.resolve_section(piece.sections["A"], piece)


class TestRenderContextGrid(unittest.TestCase):
    """The grid must divide the beat exactly, whatever the signature."""

    def test_quarter_note_signature_mode1_is_a_sixteenth_grid(self):
        ctx = MusicAnvil.make_render_context(_resolved(signature=(4, 4), tempo=120))
        self.assertEqual(ctx.subs_per_beat, 4)
        self.assertAlmostEqual(ctx.sub_unit, 0.125)

    def test_eighth_note_signature_mode1_keeps_the_sixteenth_grid(self):
        ctx = MusicAnvil.make_render_context(_resolved(signature=(6, 8), tempo=120))
        self.assertEqual(ctx.subs_per_beat, 2)          # an eighth beat holds two 16ths
        self.assertAlmostEqual(ctx.sub_unit, 0.125)

    def test_half_note_signature_mode1(self):
        ctx = MusicAnvil.make_render_context(_resolved(signature=(2, 2), tempo=120))
        self.assertEqual(ctx.subs_per_beat, 8)
        self.assertAlmostEqual(ctx.sub_unit, 0.125)

    def test_mode2_is_always_two_subs_per_beat(self):
        ctx = MusicAnvil.make_render_context(
            _resolved(signature=(6, 8), tempo=90, beat_mode=ma_utils.BEAT_MODE_HALF_DENOM))
        self.assertEqual(ctx.subs_per_beat, 2)
        self.assertAlmostEqual(ctx.sub_unit, ctx.beat_len / 2)

    def test_grid_divides_the_beat_exactly(self):
        for signature in ((4, 4), (3, 4), (5, 4), (2, 2), (6, 8), (12, 16)):
            for mode in (ma_utils.BEAT_MODE_FIXED_16TH, ma_utils.BEAT_MODE_HALF_DENOM):
                with self.subTest(signature=signature, mode=mode):
                    ctx = MusicAnvil.make_render_context(
                        _resolved(signature=signature, beat_mode=mode))
                    self.assertAlmostEqual(ctx.sub_unit * ctx.subs_per_beat, ctx.beat_len)

    def test_derived_counts(self):
        ctx = MusicAnvil.make_render_context(_resolved(bars=3, signature=(3, 4)))
        self.assertEqual(ctx.beats_per_bar, 3)
        self.assertEqual(ctx.n_beats, 9)
        self.assertEqual(ctx.subs_per_bar, 3 * ctx.subs_per_beat)
        self.assertEqual(ctx.total_sub, 9 * ctx.subs_per_beat)
        self.assertAlmostEqual(ctx.length, MusicAnvil.section_seconds(3, 120, (3, 4)))

    def test_beat_lookups(self):
        ctx = MusicAnvil.make_render_context(_resolved(signature=(4, 4)))
        self.assertEqual(ctx.beat_of(0), 0)
        self.assertEqual(ctx.beat_of(ctx.subs_per_beat * 3 + 1), 3)
        self.assertAlmostEqual(ctx.beat_in_bar(ctx.subs_per_beat * 5), 1.0)  # bar 2, beat 2
        self.assertAlmostEqual(ctx.beat_in_bar(ctx.subs_per_beat // 2), 0.5)  # off the beat


class TestNoteEvent(unittest.TestCase):

    def test_end_sub(self):
        event = MusicAnvil.NoteEvent(start_sub=4, length_sub=3, pitch=60, velocity=90)
        self.assertEqual(event.end_sub, 7)

    def test_copy_overrides_and_leaves_the_original(self):
        event = MusicAnvil.NoteEvent(start_sub=4, length_sub=3, pitch=60, velocity=90)
        copy = event.copy(velocity=68)
        self.assertEqual(copy.velocity, 68)
        self.assertEqual(event.velocity, 90)
        self.assertEqual(copy.pitch, 60)

    def test_defaults(self):
        event = MusicAnvil.NoteEvent(start_sub=0, length_sub=1, pitch=60, velocity=90)
        self.assertEqual(event.gate, 1.0)
        self.assertEqual(event.phrase, 0)
        self.assertFalse(event.is_phrase_final)


class TestMaterialise(unittest.TestCase):

    def setUp(self):
        self.ctx = MusicAnvil.make_render_context(_resolved(bars=1, signature=(4, 4)))

    def test_positions_are_grid_multiples(self):
        events = [MusicAnvil.NoteEvent(start_sub=s, length_sub=1, pitch=60, velocity=90)
                  for s in (0, 1, 5)]
        notes = MusicAnvil.materialise(events, self.ctx)
        self.assertEqual([round(n.start, 9) for n in notes],
                         [round(s * self.ctx.sub_unit, 9) for s in (0, 1, 5)])

    def test_gate_shortens_the_note(self):
        event = MusicAnvil.NoteEvent(start_sub=0, length_sub=4, pitch=60, velocity=90, gate=0.5)
        note = MusicAnvil.materialise([event], self.ctx)[0]
        self.assertAlmostEqual(note.end - note.start, 4 * self.ctx.sub_unit * 0.5)

    def test_note_is_capped_at_the_section_end(self):
        event = MusicAnvil.NoteEvent(start_sub=self.ctx.total_sub - 1, length_sub=99,
                                     pitch=60, velocity=90)
        note = MusicAnvil.materialise([event], self.ctx)[0]
        self.assertLessEqual(note.end, self.ctx.length + 1e-9)

    def test_velocity_and_pitch_pass_through(self):
        event = MusicAnvil.NoteEvent(start_sub=0, length_sub=1, pitch=61, velocity=77)
        note = MusicAnvil.materialise([event], self.ctx)[0]
        self.assertEqual((note.pitch, note.velocity), (61, 77))

    def test_events_from_notes_round_trips(self):
        events = [MusicAnvil.NoteEvent(start_sub=0, length_sub=4, pitch=60, velocity=90, gate=0.85),
                  MusicAnvil.NoteEvent(start_sub=8, length_sub=4, pitch=64, velocity=90, gate=0.85)]
        notes = MusicAnvil.materialise(events, self.ctx)
        back = MusicAnvil.events_from_notes(notes, self.ctx, gate=0.85)
        self.assertEqual([(e.start_sub, e.length_sub) for e in back],
                         [(0, 4), (8, 4)])


class TestPhrasePlan(unittest.TestCase):

    def _ctx(self, bars, signature=(4, 4)):
        return MusicAnvil.make_render_context(_resolved(bars=bars, signature=signature))

    def test_four_bar_section_is_a_two_phrase_period(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(4))
        self.assertEqual(len(phrases), 2)
        self.assertEqual([p.length_beats for p in phrases], [8, 8])
        self.assertEqual(phrases[0].function, MusicAnvil.PHRASE_ANTECEDENT)
        self.assertEqual(phrases[1].function, MusicAnvil.PHRASE_CONSEQUENT)

    def test_antecedent_is_open_and_consequent_closed(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(8))
        self.assertEqual(phrases[0].ending, MusicAnvil.PHRASE_OPEN)
        self.assertEqual(phrases[-1].ending, MusicAnvil.PHRASE_CLOSED)

    def test_eight_bar_section_uses_four_bar_phrases(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(8))
        self.assertEqual([p.length_beats for p in phrases], [16, 16])

    def test_long_section_caps_the_phrase_at_four_bars(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(16))
        self.assertTrue(all(p.length_beats == 16 for p in phrases))
        self.assertEqual(len(phrases), 4)

    def test_single_bar_section_is_one_closed_phrase(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(1))
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0].ending, MusicAnvil.PHRASE_CLOSED)

    def test_explicit_phrase_bars_wins(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(8), phrase_bars=2)
        self.assertEqual(len(phrases), 4)
        self.assertTrue(all(p.length_beats == 8 for p in phrases))

    def test_phrase_bars_longer_than_the_section_is_clamped(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(2), phrase_bars=99)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0].length_beats, 8)

    def test_phrases_tile_the_section_without_gap_or_overlap(self):
        for bars in (1, 2, 3, 4, 5, 7, 8, 16):
            with self.subTest(bars=bars):
                ctx = self._ctx(bars)
                phrases = MusicAnvil.plan_phrases(ctx)
                self.assertEqual(phrases[0].start_beat, 0)
                for previous, following in zip(phrases, phrases[1:]):
                    self.assertEqual(previous.end_beat, following.start_beat)
                self.assertEqual(phrases[-1].end_beat, ctx.n_beats)

    def test_contains_beat(self):
        phrase = MusicAnvil.Phrase(index=0, start_beat=4, length_beats=4)
        self.assertTrue(phrase.contains_beat(4))
        self.assertTrue(phrase.contains_beat(7))
        self.assertFalse(phrase.contains_beat(8))
        self.assertFalse(phrase.contains_beat(3))

    def test_three_four_phrases_are_whole_bars(self):
        phrases = MusicAnvil.plan_phrases(self._ctx(4, signature=(3, 4)))
        self.assertTrue(all(p.length_beats % 3 == 0 for p in phrases))


class TestAssignPhrases(unittest.TestCase):

    def setUp(self):
        self.ctx = MusicAnvil.make_render_context(_resolved(bars=4))
        self.phrases = MusicAnvil.plan_phrases(self.ctx)

    def _events(self, starts):
        return [MusicAnvil.NoteEvent(start_sub=s, length_sub=1, pitch=60, velocity=90)
                for s in starts]

    def test_events_are_tagged_with_their_phrase(self):
        half = self.phrases[1].start_beat * self.ctx.subs_per_beat
        events = self._events([0, half - 1, half, half + 4])
        MusicAnvil.assign_phrases(events, self.ctx, self.phrases)
        self.assertEqual([e.phrase for e in events], [0, 0, 1, 1])

    def test_last_event_of_each_phrase_is_marked(self):
        half = self.phrases[1].start_beat * self.ctx.subs_per_beat
        events = self._events([0, half - 1, half, half + 4])
        MusicAnvil.assign_phrases(events, self.ctx, self.phrases)
        self.assertEqual([e.is_phrase_final for e in events], [False, True, False, True])

    def test_simultaneous_events_are_all_marked_final(self):
        half = self.phrases[1].start_beat * self.ctx.subs_per_beat
        events = self._events([0, half - 1, half - 1])
        MusicAnvil.assign_phrases(events, self.ctx, self.phrases)
        self.assertEqual([e.is_phrase_final for e in events], [False, True, True])

    def test_reassignment_clears_stale_flags(self):
        events = self._events([0, 4])
        MusicAnvil.assign_phrases(events, self.ctx, self.phrases)
        MusicAnvil.assign_phrases(events, self.ctx, self.phrases)
        self.assertEqual(sum(1 for e in events if e.is_phrase_final), 1)


class TestRenderedSection(unittest.TestCase):

    def setUp(self):
        self.resolved = _resolved(bars=4)
        self.rendered = MusicAnvil._render_section_events(self.resolved, random.Random(5))

    def test_every_role_produced_events(self):
        for instrument in ("Piano", "Guitar", "Bass", "Flute"):
            self.assertIn(instrument, self.rendered.events, instrument)

    def test_drums_are_kept_in_seconds(self):
        self.assertTrue(self.rendered.drums)
        self.assertTrue(all(isinstance(n, pretty_midi.Note) for n in self.rendered.drums))

    def test_events_stay_inside_the_section(self):
        for events in self.rendered.events.values():
            for event in events:
                self.assertGreaterEqual(event.start_sub, 0)
                self.assertLess(event.start_sub, self.rendered.context.total_sub)

    def test_every_event_carries_a_phrase(self):
        phrase_count = len(self.rendered.phrases)
        for events in self.rendered.events.values():
            for event in events:
                self.assertIn(event.phrase, range(phrase_count))

    def test_each_phrase_has_a_final_lead_event(self):
        lead = self.rendered.events["Piano"]
        marked = {event.phrase for event in lead if event.is_phrase_final}
        self.assertEqual(marked, {phrase.index for phrase in self.rendered.phrases})

    def test_lead_events_know_their_scale_degree(self):
        for event in self.rendered.events["Piano"]:
            self.assertIsNotNone(event.degree)
            self.assertEqual(self.rendered.context.scale_pitches[event.degree], event.pitch)

    def test_tracks_materialise_to_the_public_shape(self):
        tracks = self.rendered.tracks()
        self.assertEqual(list(tracks)[0], MusicAnvil.DRUM_TRACK)
        for notes in tracks.values():
            self.assertTrue(all(isinstance(n, pretty_midi.Note) for n in notes))

    def test_render_section_matches_the_event_form(self):
        tracks, length = MusicAnvil.render_section(self.resolved, random.Random(5))
        expected = self.rendered.tracks()
        self.assertAlmostEqual(length, self.rendered.length)
        self.assertEqual(list(tracks), list(expected))
        for instrument, notes in tracks.items():
            self.assertEqual([(n.pitch, n.velocity, round(n.start, 9), round(n.end, 9))
                              for n in notes],
                             [(n.pitch, n.velocity, round(n.start, 9), round(n.end, 9))
                              for n in expected[instrument]])

    def test_unknown_rhythm_still_raises(self):
        resolved = _resolved()
        resolved.rhythm = "NoSuchGenre"
        with self.assertRaises(ValueError):
            MusicAnvil._render_section_events(resolved, random.Random(1))


class TestPhraseBarsField(unittest.TestCase):
    """phrase_bars follows the same piece-default / section-override rules as the rest."""

    def test_piece_default_comes_from_the_config(self):
        self.assertEqual(MusicAnvil.PieceSpec().phrase_bars,
                         ma_utils.get_param("piece_defaults", "phrase_bars"))

    def test_section_override_wins(self):
        piece = _piece(bars=8)
        piece.sections["A"].phrase_bars = 2
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.phrase_bars, 2)
        rendered = MusicAnvil._render_section_events(resolved, random.Random(1))
        self.assertEqual(len(rendered.phrases), 4)

    def test_none_override_inherits(self):
        piece = _piece(bars=8)
        piece.phrase_bars = 4
        piece.sections["A"].phrase_bars = None
        resolved = MusicAnvil.resolve_section(piece.sections["A"], piece)
        self.assertEqual(resolved.phrase_bars, 4)


class TestPublicGeneratorsStillWork(unittest.TestCase):
    """The loose-argument wrappers keep their pre-refactor contract."""

    def test_lead_line_returns_notes_on_the_grid(self):
        notes = MusicAnvil.generate_lead_line(
            [60, 62, 64, 65, 67], n_beats=8, beat_len=0.5, rng=random.Random(3),
            tempo=120, rest_prob=0.0)
        self.assertTrue(notes)
        for note in notes:
            self.assertAlmostEqual(note.start / 0.125, round(note.start / 0.125), places=6)
            self.assertLessEqual(note.end, 8 * 0.5 + 1e-9)

    def test_bass_line_is_one_note_per_beat_at_most(self):
        notes = MusicAnvil.generate_bass_line([60, 62, 64], n_beats=8, beat_len=0.5,
                                              rng=random.Random(3))
        starts = [round(n.start, 9) for n in notes]
        self.assertEqual(len(starts), len(set(starts)))
        for start in starts:
            self.assertAlmostEqual(start / 0.5, round(start / 0.5), places=6)

    def test_bass_gate_shortens_the_note(self):
        """A bass note lasts a whole number of beats times the gate — one beat usually,
        two when it is held over the next one (ToDo 4.2)."""
        notes = MusicAnvil.generate_bass_line([60, 62, 64], n_beats=8, beat_len=0.5,
                                              rng=random.Random(3), gate=0.5)
        self.assertTrue(notes)
        for note in notes:
            beats_held = (note.end - note.start) / (0.5 * 0.5)
            self.assertAlmostEqual(beats_held, round(beats_held), places=6)
            self.assertIn(round(beats_held), (1, 2))


if __name__ == "__main__":
    unittest.main()
