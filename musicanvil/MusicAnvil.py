"""MusicAnvil — piece composition engine.

Turns a :class:`PieceSpec` — piece-wide defaults, a library of named sections with
optional per-section overrides, and an ordered structure — into a multi-instrument
``pretty_midi.PrettyMIDI`` object.

Section lengths are expressed in bars at the section's own tempo/time signature, so
every seam between sections falls on a bar boundary. Each library section is rendered
once per run and reused verbatim at every occurrence in the structure, so repeated
sections sound identical.

Generation layers per section:
  a) drum line — the genre pattern repeated to fill the section
  b) bass line — random notes from the scale, two octaves down, one per beat
  c) lead line — a rhythmic motif (ma_utils.make_rhythm_cell) stated, repeated and
     then fragmented, with pitches drawn from the scale
  d) accompaniment — a chord per beat, held for as long as the melody stays inside it
     (sustain_chords), selected from ma_utils.chord_definitions to
     fit the lead notes sounding in that beat (via find_compatible_chords), kept within
     the scale or an idiomatic extension (ma_utils.chord_palette_extensions), voiced an
     octave below the lead
  e) support instruments — partial replicas of their role's main line (lead supports
     play only even beats, accompaniment supports only the first half of each bar,
     bass supports only the first beat of each bar)

Every track is then shaped: accelerate_harmony re-strikes held chords into each
cadence, apply_metric_accents/apply_drum_accents turn a note's position in the bar into a
velocity offset (downbeat loudest, off-beat softest) scaled by the section's
``intensity``, apply_final_lengthening stretches the last note of each phrase so endings
breathe, apply_phrase_cadences gives every phrase the open or closed ending its plan
calls for, and add_drum_fills plays into each phrase boundary.
"""

# OopCompanion:suppressRename

import bisect
import random
import warnings
from dataclasses import dataclass, field

import pretty_midi

try:
    from . import ma_utils
except ImportError:  # script-directory launch
    import ma_utils


ROLE_LEAD = "Lead"
ROLE_ACCOMPANIMENT = "Accompaniment"
ROLE_BASS = "Bass"
ROLES = (ROLE_LEAD, ROLE_ACCOMPANIMENT, ROLE_BASS)

DRUM_TRACK = "Drums"

# Constants and defaults are sourced from the external MusicAnvil.json (see
# ma_utils.load_config) so all tunable data lives in one place.
_CFG = ma_utils.load_config()
_PIECE_DEFAULTS = _CFG["piece_defaults"]

# Melodic instrument name -> General MIDI program number.
#
# The config holds the short curated names the GUI offers first ("Piano", "Electric
# Bass", ...); the complete General MIDI set is then merged in under its standard names
# ("Acoustic Grand Piano", "Distortion Guitar", ...) so every GM sound is selectable
# without listing a 128-entry standard in the configuration file. A curated name always
# wins, so the config keeps the last word on what a name means.
GM_PROGRAM_COUNT = 128
INSTRUMENT_PROGRAMS = dict(_CFG["instrument_programs"])
for _program in range(GM_PROGRAM_COUNT):
    INSTRUMENT_PROGRAMS.setdefault(pretty_midi.program_to_instrument_name(_program), _program)
del _program

_VELOCITIES = _CFG["velocities"]
VELOCITY_LEAD = _VELOCITIES["lead"]
VELOCITY_BASS = _VELOCITIES["bass"]
VELOCITY_CHORD = _VELOCITIES["chord"]
VELOCITY_SUPPORT = _VELOCITIES["support"]


@dataclass
class RoleAssignment:
    """The instruments assigned to one role: a main and zero or more supports."""
    main: str | None = None
    supports: list[str] = field(default_factory=list)


@dataclass
class SectionSpec:
    """A named section. Every field except ``name`` and ``bars`` is an optional
    override; ``None`` (or a missing role key) means "inherit the piece default"."""
    name: str
    bars: int = _PIECE_DEFAULTS["section_bars"]
    tempo: int | None = None
    signature: tuple[int, int] | None = None
    rhythm: str | None = None
    scale: str | None = None
    tonic: str | None = None
    tonic_octave: int | None = None
    beat_mode: int | None = None
    phrase_bars: int | None = None
    metric_accent: int | None = None
    intensity: float | None = None
    final_lengthening: float | None = None
    lead_syncopation: float | None = None
    auto_cadence: bool | None = None
    cadence_beats: int | None = None
    drum_fills: bool | None = None
    drums_enabled: list[str] | None = None
    # Articulation overrides (None = inherit piece default)
    lead_rest_prob: float | None = None
    lead_sustain: float | None = None
    lead_velocity_jitter: int | None = None
    lead_step_bias: float | None = None
    bass_gate: float | None = None
    chord_gate: float | None = None
    chord_octave_shift: int | None = None
    roles: dict[str, RoleAssignment] = field(default_factory=dict)


@dataclass
class StructureEntry:
    """One slot in the piece structure: a section name plus an optional beat transformer.

    ``transformer`` must be a key in ``ma_utils.BEAT_TRANSFORMERS`` or ``None``.
    ``transformer_kwargs`` is forwarded verbatim as keyword arguments to the transformer
    function, so ``{"n": 3}`` is the right value for ``tone_shift``. A *note* transformer
    is applied to each instrument's notes; a *phrase* transformer receives the whole
    rendered section in musical time (see ``ma_utils.TRANSFORMER_PHRASE``).
    Plain strings are also accepted wherever a ``StructureEntry`` is expected — use
    ``_as_entry()`` to normalise them.
    """
    section: str
    transformer: str | None = None
    transformer_kwargs: dict = field(default_factory=dict)


@dataclass
class PieceSpec:
    """Piece-wide defaults plus the section library and the ordered structure."""
    tempo: int = _PIECE_DEFAULTS["tempo"]
    signature: tuple[int, int] = tuple(_PIECE_DEFAULTS["signature"])
    rhythm: str = _PIECE_DEFAULTS["rhythm"]
    scale: str = _PIECE_DEFAULTS["scale"]
    tonic: str = _PIECE_DEFAULTS["tonic"]
    tonic_octave: int = _PIECE_DEFAULTS["tonic_octave"]
    beat_mode: int = _PIECE_DEFAULTS["beat_mode"]
    phrase_bars: int = _PIECE_DEFAULTS["phrase_bars"]  # 0 = derive from the section length
    metric_accent: int = _PIECE_DEFAULTS["metric_accent"]  # downbeat velocity above a plain beat
    intensity: float = _PIECE_DEFAULTS["intensity"]        # velocity multiplier for the section
    final_lengthening: float = _PIECE_DEFAULTS["final_lengthening"]  # phrase-final note stretch (1 = off)
    lead_syncopation: float = _PIECE_DEFAULTS["lead_syncopation"]    # chance of an off-beat displacement
    auto_cadence: bool = _PIECE_DEFAULTS["auto_cadence"]     # open/closed endings per phrase
    cadence_beats: int = _PIECE_DEFAULTS["cadence_beats"]    # beats reshaped at a phrase end
    drum_fills: bool = _PIECE_DEFAULTS["drum_fills"]         # fill into every phrase boundary
    drums_enabled: list[str] | None = None
    # Articulation defaults
    lead_rest_prob: float = _PIECE_DEFAULTS["lead_rest_prob"]       # probability of rest (vs note) per sub-unit slot
    lead_sustain: float = _PIECE_DEFAULTS["lead_sustain"]          # note end = start + length * sub_unit * sustain
    lead_velocity_jitter: int = _PIECE_DEFAULTS["lead_velocity_jitter"]  # max ±offset applied to VELOCITY_LEAD per note
    lead_step_bias: float = _PIECE_DEFAULTS["lead_step_bias"]       # probability of choosing ±2 scale degrees from prev
    bass_gate: float = _PIECE_DEFAULTS["bass_gate"]                # bass note length as fraction of beat_len
    chord_gate: float = _PIECE_DEFAULTS["chord_gate"]             # chord note length as fraction of beat_len
    chord_octave_shift: int = _PIECE_DEFAULTS["chord_octave_shift"]  # octaves below lead for chord voicing
    roles: dict[str, RoleAssignment] = field(default_factory=dict)
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    structure: list[StructureEntry | str] = field(default_factory=list)


@dataclass
class ResolvedSection:
    """A section with every inherited field filled in from the piece defaults."""
    name: str
    bars: int
    tempo: int
    signature: tuple[int, int]
    rhythm: str
    scale: str
    tonic: str
    tonic_octave: int
    beat_mode: int
    phrase_bars: int
    metric_accent: int
    intensity: float
    final_lengthening: float
    lead_syncopation: float
    auto_cadence: bool
    cadence_beats: int
    drum_fills: bool
    drums_enabled: list[str] | None
    lead_rest_prob: float
    lead_sustain: float
    lead_velocity_jitter: int
    lead_step_bias: float
    bass_gate: float
    chord_gate: float
    chord_octave_shift: int
    roles: dict[str, RoleAssignment]


def parse_signature(text):
    """Parse an 'N/D' time-signature string into an (int, int) tuple."""
    parts = str(text).strip().split("/")
    if len(parts) != 2:
        raise ValueError(f"Time signature must be N/D, got '{text}'")
    numerator, denominator = int(parts[0]), int(parts[1])
    if numerator <= 0 or denominator <= 0:
        raise ValueError(f"Time signature values must be positive, got '{text}'")
    return numerator, denominator


def beat_seconds(tempo, denominator):
    """Duration in seconds of one beat, where the signature denominator sets the
    beat unit (denominator 4 = quarter note, 8 = eighth note, ...)."""
    if tempo <= 0:
        raise ValueError("Tempo must be a positive number of BPM.")
    return 60.0 / tempo * 4.0 / denominator


def section_seconds(bars, tempo, signature):
    """Duration in seconds of ``bars`` bars at the given tempo and signature."""
    return bars * signature[0] * beat_seconds(tempo, signature[1])


def resolve_section(section, piece):
    """Fill every inherited (None / missing) field of a section from the piece."""
    roles = {}
    for role in ROLES:
        override = section.roles.get(role)
        roles[role] = override if override is not None else piece.roles.get(role, RoleAssignment())
    def _inh(sec_val, piece_val):
        return sec_val if sec_val is not None else piece_val

    return ResolvedSection(
        name=section.name,
        bars=section.bars,
        tempo=_inh(section.tempo, piece.tempo),
        signature=_inh(section.signature, piece.signature),
        rhythm=_inh(section.rhythm, piece.rhythm),
        scale=_inh(section.scale, piece.scale),
        tonic=_inh(section.tonic, piece.tonic),
        tonic_octave=_inh(section.tonic_octave, piece.tonic_octave),
        beat_mode=_inh(section.beat_mode, piece.beat_mode),
        phrase_bars=_inh(section.phrase_bars, piece.phrase_bars),
        metric_accent=_inh(section.metric_accent, piece.metric_accent),
        intensity=_inh(section.intensity, piece.intensity),
        final_lengthening=_inh(section.final_lengthening, piece.final_lengthening),
        lead_syncopation=_inh(section.lead_syncopation, piece.lead_syncopation),
        auto_cadence=_inh(section.auto_cadence, piece.auto_cadence),
        cadence_beats=_inh(section.cadence_beats, piece.cadence_beats),
        drum_fills=_inh(section.drum_fills, piece.drum_fills),
        drums_enabled=_inh(section.drums_enabled, piece.drums_enabled),
        lead_rest_prob=_inh(section.lead_rest_prob, piece.lead_rest_prob),
        lead_sustain=_inh(section.lead_sustain, piece.lead_sustain),
        lead_velocity_jitter=_inh(section.lead_velocity_jitter, piece.lead_velocity_jitter),
        lead_step_bias=_inh(section.lead_step_bias, piece.lead_step_bias),
        bass_gate=_inh(section.bass_gate, piece.bass_gate),
        chord_gate=_inh(section.chord_gate, piece.chord_gate),
        chord_octave_shift=_inh(section.chord_octave_shift, piece.chord_octave_shift),
        roles=roles,
    )


def _as_entry(item):
    """Normalise a structure item to a StructureEntry (plain strings are accepted)."""
    return item if isinstance(item, StructureEntry) else StructureEntry(section=item)


def piece_seconds(piece):
    """Total duration in seconds of the piece structure."""
    total = 0.0
    for item in piece.structure:
        entry = _as_entry(item)
        if entry.section not in piece.sections:
            raise ValueError(f"Section '{entry.section}' is not in the section library.")
        resolved = resolve_section(piece.sections[entry.section], piece)
        total += section_seconds(resolved.bars, resolved.tempo, resolved.signature)
    return total


def _scale_pitches(scale, tonic, tonic_octave=4):
    """MIDI pitches of the scale over three octaves, ascending."""
    names = ma_utils.generate_scale(scale, tonic, start_octave=tonic_octave)
    return [pretty_midi.note_name_to_number(name) for name in names]


## Musical-time layer -----------------------------------------------------------------
#
# Generation happens on an integer grid of sub-beat units and is converted to seconds
# exactly once, by ``materialise``. Keeping notes in musical time is what lets the
# shaping passes know where a note sits in the bar, which phrase it belongs to and which
# scale degree it is — everything that is lost the moment a note becomes a pair of floats.

PHRASE_ANTECEDENT = "antecedent"
PHRASE_CONSEQUENT = "consequent"
PHRASE_OPEN = "open"      # ends on an unstable degree / weak cadence -> tension
PHRASE_CLOSED = "closed"  # ends on the tonic / authentic cadence -> release


@dataclass
class Phrase:
    """One phrase of a section — the rung between the section and its notes.

    ``function`` is ``PHRASE_ANTECEDENT`` / ``PHRASE_CONSEQUENT`` (question / answer),
    ``ending`` is ``PHRASE_OPEN`` / ``PHRASE_CLOSED``. Beats are section-relative.
    """
    index: int
    start_beat: int
    length_beats: int
    function: str = PHRASE_ANTECEDENT
    ending: str = PHRASE_OPEN

    @property
    def end_beat(self):
        return self.start_beat + self.length_beats

    def contains_beat(self, beat):
        return self.start_beat <= beat < self.end_beat


@dataclass
class RenderContext:
    """The musical frame a section is generated in: grid, metre and scale.

    ``sub_unit`` is the grid step in seconds and ``subs_per_beat`` how many of them make
    one beat, so every position is an exact integer; ``max_note_sub`` is the longest note
    a generator may emit, in grid units. Both come from ``ma_utils.beat_sub_unit``.
    """
    tempo: int
    signature: tuple
    beat_len: float
    sub_unit: float
    subs_per_beat: int
    max_note_sub: int
    bars: int
    scale_pitches: list
    scale: str = ""
    tonic: str = "C"

    @property
    def beats_per_bar(self):
        return self.signature[0]

    @property
    def n_beats(self):
        return self.bars * self.signature[0]

    @property
    def subs_per_bar(self):
        return self.signature[0] * self.subs_per_beat

    @property
    def total_sub(self):
        return self.n_beats * self.subs_per_beat

    @property
    def length(self):
        """Section duration in seconds."""
        return self.n_beats * self.beat_len

    def seconds(self, sub):
        return sub * self.sub_unit

    def beat_of(self, sub):
        return sub // self.subs_per_beat

    def beat_in_bar(self, sub):
        """Position within the bar, in beats (0 = downbeat); fractional off the beat."""
        return (sub % self.subs_per_bar) / self.subs_per_beat


@dataclass
class RhythmCell:
    """A rhythmic motif: onsets ``(start_sub, length_sub)`` filling ``length_sub`` steps.

    A section states its cell, repeats it, and then fragments it — the shape that makes
    a rhythm audible as a rhythm instead of a stream of unrelated durations.
    """
    onsets: list = field(default_factory=list)
    length_sub: int = 0

    def fragmented(self):
        """The continuation form: the cell's first half, stated twice.

        Fragmentation (shortening the repeated unit) is what drives a phrase towards its
        cadence — the same material, arriving twice as often.
        """
        if self.length_sub < 2 or not self.onsets:
            return RhythmCell(list(self.onsets), self.length_sub)
        half = self.length_sub // 2
        head = [(start, min(length, half - start))
                for start, length in self.onsets if start < half]
        if not head:
            return RhythmCell(list(self.onsets), self.length_sub)
        onsets = head + [(start + half, length) for start, length in head]
        return RhythmCell(onsets, self.length_sub)

    def tile(self, total_sub, continuation_from=None):
        """Repeat the cell to fill ``total_sub`` steps.

        From ``continuation_from`` onwards the fragmented form is used, so the second
        half of a section presses forward instead of restating.
        """
        fragment = self.fragmented()
        positions = []
        offset = 0
        while offset < total_sub:
            source = self if (continuation_from is None or offset < continuation_from) else fragment
            for start, length in source.onsets:
                absolute = offset + start
                if absolute >= total_sub:
                    break
                positions.append((absolute, max(1, min(length, total_sub - absolute))))
            offset += max(1, self.length_sub)
        return positions


@dataclass
class NoteEvent:
    """A note in musical time, carrying the provenance the shaping passes need.

    ``gate`` is the sounding fraction of ``length_sub`` (0.9 = a 10 % gap before the next
    note), ``degree`` the index into ``RenderContext.scale_pitches`` when the note came
    from the scale, ``phrase`` the index in the section's phrase plan.
    """
    start_sub: int
    length_sub: int
    pitch: int
    velocity: int
    gate: float = 1.0
    degree: int = None
    phrase: int = 0
    metric_weight: float = 1.0
    is_phrase_final: bool = False

    @property
    def end_sub(self):
        return self.start_sub + self.length_sub

    def copy(self, **changes):
        data = dict(self.__dict__)
        data.update(changes)
        return NoteEvent(**data)


@dataclass
class RenderedSection:
    """A rendered section still in musical time — what ``render_piece`` caches.

    Melodic material stays as ``NoteEvent`` lists so per-occurrence transformers can
    reshape it; the drum track is pattern-driven and is kept in seconds.
    """
    name: str
    context: RenderContext
    phrases: list = field(default_factory=list)
    events: dict = field(default_factory=dict)
    drums: list = field(default_factory=list)
    roles: dict = field(default_factory=dict)   # instrument name -> ROLE_* it plays

    @property
    def length(self):
        return self.context.length

    def copy(self):
        """A deep-enough copy: phrase transformers may rewrite events freely without
        touching the cached section that other occurrences reuse."""
        return RenderedSection(
            name=self.name,
            context=self.context,
            phrases=[Phrase(**dict(phrase.__dict__)) for phrase in self.phrases],
            events={instrument: [event.copy() for event in events]
                    for instrument, events in self.events.items()},
            drums=[pretty_midi.Note(velocity=n.velocity, pitch=n.pitch,
                                    start=n.start, end=n.end) for n in self.drums],
            roles=dict(self.roles),
        )

    def tracks(self):
        """Materialise to ``{instrument: [pretty_midi.Note]}``, drums first."""
        tracks = {DRUM_TRACK: list(self.drums)}
        for instrument, events in self.events.items():
            tracks.setdefault(instrument, []).extend(materialise(events, self.context))
        return tracks


def make_render_context(resolved):
    """Build the :class:`RenderContext` of a resolved section."""
    beat_len = beat_seconds(resolved.tempo, resolved.signature[1])
    base_sub, max_note_sub = ma_utils.beat_sub_unit(resolved.tempo, beat_len,
                                                    resolved.beat_mode)
    subs_per_beat = max(1, round(beat_len / base_sub))
    return RenderContext(
        tempo=resolved.tempo,
        signature=tuple(resolved.signature),
        beat_len=beat_len,
        sub_unit=beat_len / subs_per_beat,
        subs_per_beat=subs_per_beat,
        max_note_sub=max_note_sub,
        bars=resolved.bars,
        scale_pitches=_scale_pitches(resolved.scale, resolved.tonic, resolved.tonic_octave),
        scale=resolved.scale,
        tonic=resolved.tonic,
    )


def _standalone_context(scale_pitches, n_beats, beat_len, tempo, mode):
    """Context for the public generator wrappers, which take loose arguments instead of
    a ResolvedSection: the metre is unknown, so the whole span is treated as one bar."""
    base_sub, max_note_sub = ma_utils.beat_sub_unit(tempo, beat_len, mode)
    subs_per_beat = max(1, round(beat_len / base_sub))
    return RenderContext(
        tempo=tempo,
        signature=(max(1, int(n_beats)), 4),
        beat_len=beat_len,
        sub_unit=beat_len / subs_per_beat,
        subs_per_beat=subs_per_beat,
        max_note_sub=max_note_sub,
        bars=1,
        scale_pitches=list(scale_pitches),
    )


def plan_phrases(ctx, phrase_bars=None):
    """Divide a section into phrases.

    ``phrase_bars`` is the phrase length in bars; ``None`` or 0 means "choose one": half
    the section, capped at four bars, so a 4-bar section becomes a two-phrase
    question/answer period and an 8-bar section two 4-bar phrases. Phrases alternate
    antecedent (open) and consequent (closed), and the last phrase always closes.
    """
    bars = max(1, ctx.bars)
    if not phrase_bars:
        phrase_bars = max(1, min(4, bars // 2))
    phrase_bars = max(1, min(int(phrase_bars), bars))

    phrases = []
    start_bar = 0
    while start_bar < bars:
        span = min(phrase_bars, bars - start_bar)
        index = len(phrases)
        is_antecedent = index % 2 == 0
        phrases.append(Phrase(
            index=index,
            start_beat=start_bar * ctx.beats_per_bar,
            length_beats=span * ctx.beats_per_bar,
            function=PHRASE_ANTECEDENT if is_antecedent else PHRASE_CONSEQUENT,
            ending=PHRASE_OPEN if is_antecedent else PHRASE_CLOSED,
        ))
        start_bar += span
    phrases[-1].function = PHRASE_CONSEQUENT
    phrases[-1].ending = PHRASE_CLOSED
    return phrases


def assign_phrases(events, ctx, phrases):
    """Tag every event with its phrase index and mark the last event of each phrase."""
    if not phrases:
        return events
    bounds = [phrase.start_beat * ctx.subs_per_beat for phrase in phrases]
    for event in events:
        event.phrase = max(0, bisect.bisect_right(bounds, event.start_sub) - 1)
        event.is_phrase_final = False
    for phrase in phrases:
        in_phrase = [event for event in events if event.phrase == phrase.index]
        if in_phrase:
            last_start = max(event.start_sub for event in in_phrase)
            for event in in_phrase:
                if event.start_sub == last_start:
                    event.is_phrase_final = True
    return events


def materialise(events, ctx, length=None):
    """Convert ``NoteEvent`` objects into ``pretty_midi.Note`` objects, in seconds."""
    limit = ctx.length if length is None else length
    notes = []
    for event in events:
        start = ctx.seconds(event.start_sub)
        end = min(start + event.length_sub * ctx.sub_unit * event.gate, limit)
        notes.append(pretty_midi.Note(velocity=event.velocity, pitch=event.pitch,
                                      start=start, end=max(start, end)))
    return notes


def events_from_notes(notes, ctx, gate=1.0):
    """Re-express already-generated notes as grid events — used for the chord line, which
    is chosen harmonically beat by beat rather than on the sub-beat grid."""
    events = []
    span = max(1e-9, ctx.sub_unit * gate)
    for note in notes:
        start_sub = int(round(note.start / ctx.sub_unit))
        length_sub = max(1, int(round((note.end - note.start) / span)))
        events.append(NoteEvent(start_sub=start_sub, length_sub=length_sub,
                                pitch=note.pitch, velocity=note.velocity, gate=gate))
    return events


def make_cell(ctx, rng, syncopation=0.0, bars=None):
    """Build the section's rhythmic motif on ``ctx``'s grid (see ma_utils.make_rhythm_cell)."""
    cell_bars = bars if bars else ma_utils.rhythm_cell.get("cell_bars", 1)
    beats = max(1, int(cell_bars) * ctx.beats_per_bar)
    beats = min(beats, max(1, ctx.n_beats))
    onsets = ma_utils.make_rhythm_cell(rng, ctx.subs_per_beat, beats,
                                       max_length_sub=ctx.max_note_sub,
                                       syncopation=syncopation)
    return RhythmCell(onsets=onsets, length_sub=beats * ctx.subs_per_beat)


def _lead_events(ctx, rng, rest_prob=0.08, sustain=0.95, velocity_jitter=12,
                 step_bias=0.70, syncopation=0.0, cell=None):
    """Melody events on ``ctx``'s grid — the generator behind ``generate_lead_line``."""
    scale_pitches = ctx.scale_pitches
    if cell is None:
        cell = make_cell(ctx, rng, syncopation=syncopation)
    # Presentation in the first half of the section, fragmented continuation in the second.
    continuation = (ctx.total_sub // 2) if ctx.total_sub >= 2 * cell.length_sub else None
    events = []
    prev_idx = None
    for pos, length in cell.tile(ctx.total_sub, continuation_from=continuation):
        if rng.random() >= rest_prob:
            # Stepwise bias: prefer ±2 scale degrees from the previous pitch
            if prev_idx is not None and rng.random() < step_bias:
                lo = max(0, prev_idx - 2)
                hi = min(len(scale_pitches) - 1, prev_idx + 2)
                idx = rng.randint(lo, hi)
            else:
                idx = rng.randrange(len(scale_pitches))
            prev_idx = idx
            jitter = rng.randint(-velocity_jitter, velocity_jitter) if velocity_jitter > 0 else 0
            vel = max(1, min(127, VELOCITY_LEAD + jitter))
            events.append(NoteEvent(start_sub=pos, length_sub=length,
                                    pitch=scale_pitches[idx], velocity=vel,
                                    gate=sustain, degree=idx))
    return events


def generate_lead_line(scale_pitches, n_beats, beat_len, rng,
                       mode=ma_utils.BEAT_MODE_FIXED_16TH, tempo=120,
                       rest_prob=0.08, sustain=0.95, velocity_jitter=12,
                       step_bias=0.70, syncopation=0.0):
    """Random melody within the scale with articulation controls.

    ``mode`` / ``tempo`` set the sub-beat grid (see ``ma_utils.BEAT_MODE_*``).
    ``rest_prob``: probability of a rest per grid slot (0 = no rests, 1 = all rests).
    ``sustain``: note duration as a fraction of its grid span (0.95 = 5 % gap before next).
    ``velocity_jitter``: max ±offset applied to VELOCITY_LEAD each note.
    ``step_bias``: probability of choosing within ±2 scale degrees of the previous pitch.
    ``syncopation``: probability of an off-beat displacement in the rhythmic cell.

    The rhythm comes from a repeated (and then fragmented) motif rather than independent
    random durations — see ``make_cell`` and ``ma_utils.make_rhythm_cell``.
    """
    ctx = _standalone_context(scale_pitches, n_beats, beat_len, tempo, mode)
    events = _lead_events(ctx, rng, rest_prob=rest_prob, sustain=sustain,
                          velocity_jitter=velocity_jitter, step_bias=step_bias,
                          syncopation=syncopation)
    return materialise(events, ctx)


def _bass_events(ctx, rng, gate=0.90):
    """Bass events on ``ctx``'s grid — the generator behind ``generate_bass_line``."""
    first_octave = ctx.scale_pitches[: max(1, len(ctx.scale_pitches) // 3)]
    low_pitches = sorted({max(0, pitch - 24) for pitch in first_octave})
    strong = ma_utils.metric_accents.get("secondary", 0.85)
    events = []
    beat = 0
    while beat < ctx.n_beats:
        weight = ma_utils.metric_weight(beat % ctx.beats_per_bar, ctx.beats_per_bar)
        # Always land on the strong beats; the weak ones are optional, so the bass
        # breathes instead of hammering one note on every beat.
        beats_held = 1
        if weight >= strong or rng.random() < 0.75:
            if rng.random() < 0.25 and beat + 1 < ctx.n_beats:
                beats_held = 2      # hold through the next beat rather than re-striking
            pitch = rng.choice(low_pitches)
            events.append(NoteEvent(start_sub=beat * ctx.subs_per_beat,
                                    length_sub=beats_held * ctx.subs_per_beat, pitch=pitch,
                                    velocity=VELOCITY_BASS, gate=gate))
        beat += beats_held
    return events


def generate_bass_line(scale_pitches, n_beats, beat_len, rng, gate=0.90):
    """Random bass within the scale's first octave transposed two octaves down,
    one note per beat with a 90% hit probability.  ``gate`` shortens each note
    to that fraction of the beat, preventing note-off / note-on collisions."""
    ctx = _standalone_context(scale_pitches, n_beats, beat_len, 120,
                              ma_utils.BEAT_MODE_FIXED_16TH)
    return materialise(_bass_events(ctx, rng, gate=gate), ctx)


def _voice_chord_for_beat(beat_pitches, primary, scale_pcs, tonic_pc, extensions, order,
                          octave_shift=-2):
    """Return the MIDI pitches of the best chord for a beat, or None.

    ``beat_pitches`` are the lead pitches sounding in the beat; ``primary`` is the
    pitch on the downbeat (the preferred root). Candidate chords come from
    ``ma_utils.find_compatible_chords`` and must pass at least one of two gates:
    (a) strictly diatonic — all chord tones within ``scale_pcs``, or (b) an idiomatic
    extension — ``((root - tonic_pc) % 12, chord_type)`` appears in ``extensions``
    (loaded from ``ma_utils.chord_palette_extensions`` for the section's scale).

    Sort order: root on lead note first, then diatonic before extension, then full
    triad, then richer chord, then definition order, then root pitch class. The chosen
    chord is voiced ``octave_shift`` octaves relative to ``primary`` (negative = below).
    """
    primary_pc = primary % 12
    best = None
    best_key = None
    for root, chord_type in ma_utils.find_compatible_chords(beat_pitches):
        intervals = ma_utils.chord_definitions[chord_type]
        chord_pcs = {(root + interval) % 12 for interval in intervals}
        is_diatonic = chord_pcs <= scale_pcs
        is_extended = ((root - tonic_pc) % 12, chord_type) in extensions
        if not is_diatonic and not is_extended:
            continue
        key = (
            0 if root == primary_pc else 1,   # prefer a chord rooted on the lead note
            0 if is_diatonic else 1,           # prefer diatonic within each root category
            0 if len(intervals) == 3 else 1,  # prefer a full triad
            -len(intervals),                  # then richer chords (7ths over dyads)
            order.get(chord_type, len(order)),
            root,
        )
        if best_key is None or key < best_key:
            best_key, best = key, (root, intervals)

    if best is None:
        return None
    root, intervals = best
    base = primary + octave_shift * 12  # target reference point for the chord voicing
    root_midi = base - ((base - root) % 12)  # highest root pitch-class <= base
    return [max(0, root_midi + interval) for interval in intervals]


def generate_chord_line(lead_notes, scale_pitches, n_beats, beat_len,
                        scale_name=None, chord_octave_shift=-2, gate=0.85):
    """One chord per beat, chosen to fit the lead notes sounding in that beat.

    For each beat, the lead notes overlapping it are collected and
    ``ma_utils.find_compatible_chords`` returns every chord from
    ``ma_utils.chord_definitions`` whose tones contain those notes. A candidate passes
    if it is strictly diatonic (all tones within ``scale_pitches``'s pitch classes) OR
    if it appears in ``ma_utils.chord_palette_extensions[scale_name]`` — a per-scale
    whitelist of idiomatic non-diatonic chords (e.g. dominant-7th chords on I, IV, V
    for blues). The best candidate is rooted on the lead note where possible, with
    diatonic preferred over extension within that root group, then full triad, richer
    chord, definition order (see ``_voice_chord_for_beat``). If the full set of beat
    notes has no match, the beat's downbeat note alone is harmonised; beats with no
    lead note are rests. ``gate`` shortens each chord so successive chords breathe.
    """
    scale_pcs = {pitch % 12 for pitch in scale_pitches}
    tonic_pc = scale_pitches[0] % 12 if scale_pitches else 0
    raw_ext = ma_utils.chord_palette_extensions.get(scale_name or "", [])
    extensions = frozenset((offset, ctype) for offset, ctype in raw_ext)
    order = {name: index for index, name in enumerate(ma_utils.chord_definitions)}
    notes = []
    for beat in range(n_beats):
        t = beat * beat_len
        primary = None
        beat_pitches = []
        for note in lead_notes:
            if note.start < t + beat_len - 1e-9 and note.end > t + 1e-9:
                beat_pitches.append(note.pitch)
                if primary is None and note.start <= t + 1e-9 < note.end:
                    primary = note.pitch
        if primary is None:
            continue

        chord = _voice_chord_for_beat(beat_pitches, primary, scale_pcs, tonic_pc, extensions, order,
                                      chord_octave_shift)
        if chord is None:  # fall back to harmonising just the downbeat note
            chord = _voice_chord_for_beat([primary], primary, scale_pcs, tonic_pc, extensions, order,
                                          chord_octave_shift)
        if chord is None:
            continue

        for pitch in chord:
            notes.append(pretty_midi.Note(velocity=VELOCITY_CHORD, pitch=pitch,
                                          start=t, end=t + beat_len * gate))
    return notes


def derive_support_line(notes, beat_len, beats_per_bar, mode):
    """Partial replica of a main line for a support instrument.

    Modes:
    - "even-beats": keep only notes starting on even beats (lead supports)
    - "bar-head": keep only notes starting in the first half of each bar
      (accompaniment supports)
    - "bar-first-beat": keep only notes starting on beat 1 of each bar
      (bass supports)
    """
    kept = []
    for note in notes:
        beat = int(round(note.start / beat_len))
        beat_in_bar = beat % beats_per_bar
        if mode == "even-beats" and beat % 2 != 0:
            continue
        if mode == "bar-head" and beat_in_bar >= max(1, beats_per_bar // 2):
            continue
        if mode == "bar-first-beat" and beat_in_bar != 0:
            continue
        kept.append(pretty_midi.Note(velocity=VELOCITY_SUPPORT, pitch=note.pitch,
                                     start=note.start, end=note.end))
    return kept


def accent_delta(weight, amount, weights=None):
    """Velocity offset for a metric ``weight`` (see ``ma_utils.metric_weight``).

    ``amount`` is how much louder the downbeat is than a plain on-beat note, in MIDI
    velocity units; the reference weight maps to 0, so notes on the beat keep the
    velocity their generator chose and only stronger/weaker positions move.
    """
    table = ma_utils.metric_accents if weights is None else weights
    reference = table.get("reference", table.get("beat", 0.7))
    span = table.get("downbeat", 1.0) - reference
    if not amount or span <= 0:
        return 0
    return int(round((weight - reference) / span * amount))


def apply_metric_accents(events, ctx, amount=12, intensity=1.0):
    """Shape velocities from the metre: emphasis by bar position, scaled by ``intensity``.

    Sets ``metric_weight`` on every event and rewrites its velocity. Any jitter the
    generator applied survives — it is humanisation on top of the metric structure, not
    a substitute for it.
    """
    for event in events:
        weight = ma_utils.metric_weight(ctx.beat_in_bar(event.start_sub), ctx.beats_per_bar)
        event.metric_weight = weight
        velocity = event.velocity * intensity + accent_delta(weight, amount)
        event.velocity = max(1, min(127, int(round(velocity))))
    return events


def apply_drum_accents(notes, ctx, amount=12, intensity=1.0):
    """``apply_metric_accents`` for the drum track, which is already in seconds."""
    shaped = []
    for note in notes:
        beat_in_bar = (note.start / ctx.beat_len) % ctx.beats_per_bar
        weight = ma_utils.metric_weight(beat_in_bar, ctx.beats_per_bar)
        velocity = note.velocity * intensity + accent_delta(weight, amount)
        shaped.append(pretty_midi.Note(velocity=max(1, min(127, int(round(velocity)))),
                                       pitch=note.pitch, start=note.start, end=note.end))
    return shaped


def apply_final_lengthening(events, ctx, phrases, factor=1.5):
    """Stretch the last note of every phrase — the agogic ending.

    Performers systematically slow down at a phrase boundary (group-final lengthening),
    and lengthening a note is the standard way to mark a culmination. Here the
    phrase-final note is stretched by ``factor`` — never beyond the phrase boundary, and
    never shortened — and allowed to ring to its full length (its gate opens) instead of
    being cut short for the note that would have followed. ``factor`` 1.0 disables it.
    """
    if factor <= 1.0 or not phrases:
        return events
    for event in events:
        if not event.is_phrase_final:
            continue
        phrase = phrases[min(event.phrase, len(phrases) - 1)]
        limit_sub = min(ctx.total_sub, phrase.end_beat * ctx.subs_per_beat)
        room = max(1, limit_sub - event.start_sub)
        # Never shorten: a note already running to (or past) the phrase end keeps its
        # length; one with room to breathe takes it, up to the boundary.
        event.length_sub = max(event.length_sub, min(int(round(event.length_sub * factor)), room))
        event.gate = max(event.gate, min(1.0, event.gate * factor))
    return events


def merge_repeated_chords(events, ctx):
    """Hold a chord instead of re-striking it on every beat.

    ``generate_chord_line`` harmonises beat by beat, so an unchanged harmony arrives as
    a machine-gun of identical chords. Consecutive beats with the same set of pitches
    become one sustained chord, which is what a player would do.
    """
    by_start = {}
    for event in events:
        by_start.setdefault(event.start_sub, []).append(event)
    starts = sorted(by_start)

    merged = []
    index = 0
    while index < len(starts):
        start = starts[index]
        group = by_start[start]
        pitches = sorted(event.pitch for event in group)
        span = group[0].length_sub
        follower = index + 1
        while (follower < len(starts) and starts[follower] == start + span
               and sorted(e.pitch for e in by_start[starts[follower]]) == pitches):
            span += by_start[starts[follower]][0].length_sub
            follower += 1
        merged.extend(event.copy(length_sub=span) for event in group)
        index = follower
    return merged


def _lead_pitch_classes_by_beat(lead_events, ctx):
    """{beat index: {pitch class, ...}} for every beat the melody sounds in."""
    by_beat = {}
    for event in lead_events:
        first = event.start_sub // ctx.subs_per_beat
        last = max(first, (event.end_sub - 1) // ctx.subs_per_beat)
        for beat in range(first, last + 1):
            by_beat.setdefault(beat, set()).add(event.pitch % 12)
    return by_beat


def sustain_chords(chord_events, lead_events, ctx):
    """Hold a chord while the melody stays inside it, instead of re-striking each beat.

    ``generate_chord_line`` harmonises one beat at a time, so even a static harmony
    arrives as a machine-gun of identical chords — a large part of what makes the
    accompaniment sound mechanical. Here a chord is held for as long as every lead pitch
    class in the following beat is one of its tones; the moment the melody moves outside
    it, the next chord is struck. Identical neighbours left over are merged.
    """
    if not chord_events:
        return []
    by_start = {}
    for event in chord_events:
        by_start.setdefault(event.start_sub, []).append(event)
    lead_pcs = _lead_pitch_classes_by_beat(lead_events, ctx)

    sustained = []
    held_start = None
    held_group = []
    held_span = 0
    held_pcs = set()
    for start in sorted(by_start):
        group = by_start[start]
        beat = start // ctx.subs_per_beat
        continues = (held_start is not None and start == held_start + held_span
                     and lead_pcs.get(beat, set()) <= held_pcs)
        if continues:
            held_span += group[0].length_sub
            continue
        if held_start is not None:
            sustained.extend(event.copy(length_sub=held_span) for event in held_group)
        held_start, held_group = start, group
        held_span = group[0].length_sub
        held_pcs = {event.pitch % 12 for event in group}
    if held_start is not None:
        sustained.extend(event.copy(length_sub=held_span) for event in held_group)
    return merge_repeated_chords(sustained, ctx)


def _support_events(events, ctx, mode):
    """Event-level ``derive_support_line``: the same three filters, on the grid."""
    kept = []
    for event in events:
        # Nearest beat, matching derive_support_line's attribution of off-beat notes.
        beat = int(round(event.start_sub / ctx.subs_per_beat))
        beat_in_bar = beat % ctx.beats_per_bar
        if mode == "even-beats" and beat % 2 != 0:
            continue
        if mode == "bar-head" and beat_in_bar >= max(1, ctx.beats_per_bar // 2):
            continue
        if mode == "bar-first-beat" and beat_in_bar != 0:
            continue
        kept.append(event.copy(velocity=VELOCITY_SUPPORT))
    return kept


def _drum_notes(resolved, ctx):
    """The section's drum track, in seconds: one bar of the genre pattern fitted to the
    signature (ToDo 3.1) and then tiled across the section."""
    if resolved.rhythm not in ma_utils.drum_lines:
        raise ValueError(f"Rhythm '{resolved.rhythm}' is not defined.")
    drum_line = list(ma_utils.drum_lines[resolved.rhythm])
    if resolved.drums_enabled is not None:
        enabled_pitches = {ma_utils.drum_pitches[n] for n in resolved.drums_enabled
                           if n in ma_utils.drum_pitches}
        drum_line = [e for e in drum_line if e[1] in enabled_pitches]
    if not drum_line:
        return []

    bar_line = ma_utils.fit_drum_line_to_bar(
        drum_line, resolved.tempo, resolved.signature,
        beats_per_pattern=ma_utils.pattern_beats(resolved.rhythm),
    )
    length = ctx.length
    bar_len = ctx.beats_per_bar * ctx.beat_len
    notes = []
    t = 0.0
    while t < length - 1e-9:
        for velocity, pitch, start, end in bar_line:
            if t + start >= length:
                continue
            notes.append(pretty_midi.Note(velocity=velocity, pitch=pitch,
                                          start=t + start, end=min(t + end, length)))
        t += bar_len
    return notes


def _render_section_events(resolved, rng=None):
    """Render one resolved section into musical time.

    Returns a :class:`RenderedSection`: the melodic roles as ``NoteEvent`` lists on the
    section's grid, the drum track in seconds, and the phrase plan. ``render_section``
    materialises this; ``render_piece`` caches it so per-occurrence transformers can
    reshape material that has not yet collapsed into (start, end) floats.
    """
    rng = rng if rng is not None else random.Random()
    ctx = make_render_context(resolved)
    phrases = plan_phrases(ctx, resolved.phrase_bars)
    rendered = RenderedSection(name=resolved.name, context=ctx, phrases=phrases)

    # a) drums: the genre pattern fitted to the bar, tiled across the section
    rendered.drums = _drum_notes(resolved, ctx)

    def add(instrument, events, role=None):
        if instrument and events:
            rendered.events.setdefault(instrument, []).extend(events)
            rendered.roles.setdefault(instrument, role)

    # b) bass line
    bass_role = resolved.roles[ROLE_BASS]
    bass_events = _bass_events(ctx, rng, gate=resolved.bass_gate) if bass_role.main else []
    add(bass_role.main, bass_events, ROLE_BASS)
    for support in bass_role.supports:
        add(support, _support_events(bass_events, ctx, "bar-first-beat"), ROLE_BASS)

    # c) lead line
    lead_role = resolved.roles[ROLE_LEAD]
    lead_events = _lead_events(ctx, rng, rest_prob=resolved.lead_rest_prob,
                               sustain=resolved.lead_sustain,
                               velocity_jitter=resolved.lead_velocity_jitter,
                               step_bias=resolved.lead_step_bias,
                               syncopation=resolved.lead_syncopation) if lead_role.main else []
    add(lead_role.main, lead_events, ROLE_LEAD)
    for support in lead_role.supports:
        add(support, _support_events(lead_events, ctx, "even-beats"), ROLE_LEAD)

    # d) accompaniment chords from the lead line (chosen harmonically, beat by beat,
    #    then re-expressed as grid events)
    accomp_role = resolved.roles[ROLE_ACCOMPANIMENT]
    chord_events = []
    if accomp_role.main:
        chord_notes = generate_chord_line(materialise(lead_events, ctx), ctx.scale_pitches,
                                          ctx.n_beats, ctx.beat_len, scale_name=ctx.scale,
                                          chord_octave_shift=resolved.chord_octave_shift,
                                          gate=resolved.chord_gate)
        chord_events = sustain_chords(
            events_from_notes(chord_notes, ctx, gate=resolved.chord_gate),
            lead_events, ctx)
    add(accomp_role.main, chord_events, ROLE_ACCOMPANIMENT)
    for support in accomp_role.supports:
        add(support, _support_events(chord_events, ctx, "bar-head"), ROLE_ACCOMPANIMENT)

    if accomp_role.main in rendered.events:
        # Harmony accelerates into each cadence before anything else is shaped. Only the
        # main accompaniment: a support line must stay a subset of the line it shadows.
        rendered.events[accomp_role.main] = accelerate_harmony(
            rendered.events[accomp_role.main], ctx, phrases)
    for events in rendered.events.values():
        assign_phrases(events, ctx, phrases)
        apply_metric_accents(events, ctx, resolved.metric_accent, resolved.intensity)
        apply_final_lengthening(events, ctx, phrases, resolved.final_lengthening)
    if resolved.auto_cadence:
        apply_phrase_cadences(rendered, resolved.cadence_beats)
    rendered.drums = apply_drum_accents(rendered.drums, ctx, resolved.metric_accent,
                                        resolved.intensity)
    if resolved.drum_fills:
        rendered.drums = add_drum_fills(rendered.drums, ctx, phrases)
    return rendered


def render_section(resolved, rng=None):
    """Render one resolved section.

    Returns ``(tracks, length)`` where ``tracks`` maps instrument name (or
    ``DRUM_TRACK``) to a list of notes with times relative to the section start,
    and ``length`` is the section duration in seconds. This is the materialised view of
    :func:`_render_section_events`.
    """
    rendered = _render_section_events(resolved, rng)
    return rendered.tracks(), rendered.length


# pretty_midi has no public API for inserting a tempo change into an object being
# built, so _insert_midi_tempo_change reaches for these private members. They exist in
# the pinned pretty_midi==0.2.11; _missing_tempo_internals() checks for them so a
# dependency bump that renames them degrades to a warning instead of an AttributeError
# at render time (see tests/test_composer.py::TestTempoInternalsGuard).
_TEMPO_INTERNALS = ("_tick_scales", "_PrettyMIDI__tick_to_time", "_update_tick_to_time")

_TEMPO_FALLBACK_MESSAGE = (
    "This pretty_midi build does not expose the internals MusicAnvil uses to insert "
    "tempo changes ({details}). The piece is rendered at its initial tempo — section "
    "tempo overrides still change the note timing, but sequencers will show the wrong "
    "bar/beat grid. MusicAnvil is verified against pretty_midi==0.2.11."
)


def _missing_tempo_internals(midi_data):
    """Names from ``_TEMPO_INTERNALS`` that ``midi_data`` is missing (empty = all present)."""
    return [name for name in _TEMPO_INTERNALS if not hasattr(midi_data, name)]


## Phrase transformers -----------------------------------------------------------------
#
# Registered in ma_utils' transformer registry with kind TRANSFORMER_PHRASE, so they are
# attached to one occurrence of a section in the piece structure — "Verse [tension]",
# "Chorus [release]" — and receive the whole rendered section in musical time.

CADENCE_TENSION = "tension"
CADENCE_RELEASE = "release"


def _nearest_pitch(pitch_class, reference, prefer_above=None):
    """The instance of ``pitch_class`` nearest ``reference``, keeping the register.

    ``prefer_above`` True/False biases the choice to at-or-above / at-or-below the
    reference, which is how an open ending is placed over the passage and a closed one
    under it.
    """
    base = reference - (reference % 12) + (pitch_class % 12)
    candidates = [pitch for pitch in (base - 12, base, base + 12) if 0 <= pitch <= 127]
    if not candidates:
        candidates = [max(0, min(127, base))]
    if prefer_above is True:
        above = [pitch for pitch in candidates if pitch >= reference]
        if above:
            return min(above)
    elif prefer_above is False:
        below = [pitch for pitch in candidates if pitch <= reference]
        if below:
            return max(below)
    return min(candidates, key=lambda pitch: (abs(pitch - reference), pitch))


def _degree_of(pitch, scale_pitches):
    """Index of ``pitch`` in the scale, or None when it is not a scale tone."""
    try:
        return scale_pitches.index(pitch)
    except ValueError:
        return None


def _window(events, start_sub):
    """The events of a track that start at or after ``start_sub``, in time order."""
    return sorted((event for event in events if event.start_sub >= start_sub),
                  key=lambda event: (event.start_sub, event.pitch))


def _reshape_contour(events, rising):
    """Re-order the events' own pitches into a rising or falling line.

    Reassigning the pitches the generator already chose (rather than inventing new ones)
    keeps every note inside the scale by construction, while giving the ending the
    ascent that builds tension or the descent that delivers release.
    """
    by_start = {}
    for event in events:
        by_start.setdefault(event.start_sub, []).append(event)
    pitches = sorted(event.pitch for event in events)
    if not rising:
        pitches.reverse()
    index = 0
    for start in sorted(by_start):
        for event in by_start[start]:
            event.pitch = pitches[index]
            index += 1


def _cadence_targets(ctx, rising):
    """(melodic target pitch class, chord pitch classes, chord root) for an ending."""
    tonic_pc = ctx.scale_pitches[0] % 12 if ctx.scale_pitches else 0
    if rising:
        offset = ma_utils.preferred_tendency_degree(ctx.scale)
        target_pc = (tonic_pc + (offset if offset is not None else 7)) % 12
        root_offset = 7
    else:
        target_pc = tonic_pc
        root_offset = 0
    triad = ma_utils.diatonic_triad(ctx.scale, root_offset)
    chord_pcs = [(tonic_pc + pc) % 12 for pc in triad] if triad else None
    return target_pc, chord_pcs, (tonic_pc + root_offset) % 12


def shape_cadence(section, start_sub, end_sub, rising, swell=0.12, taper=0.25):
    """Shape one cadence: the notes in ``[start_sub, end_sub)`` of every role.

    Rising leaves the passage open — the melody climbs to a tendency tone, the harmony
    takes the triad of the fifth, the bass its root, velocities swell. Falling closes it
    on the tonic with a descending line and a taper. The closing note is held to the end
    of the window. Returns the number of tracks it touched.
    """
    ctx = section.context
    target_pc, chord_pcs, root_pc = _cadence_targets(ctx, rising)
    touched = 0

    for instrument, events in section.events.items():
        window = sorted((event for event in events
                         if start_sub <= event.start_sub < end_sub),
                        key=lambda event: (event.start_sub, event.pitch))
        if not window:
            # Nothing starts in the window: shape the note still sounding through it, so
            # a long tied note cannot slip past the cadence unresolved.
            sounding = [event for event in events
                        if event.start_sub < end_sub and event.end_sub > start_sub]
            if not sounding:
                continue
            latest = max(event.start_sub for event in sounding)
            window = sorted((event for event in sounding if event.start_sub == latest),
                            key=lambda event: event.pitch)
        touched += 1
        last_start = max(event.start_sub for event in window)
        closing = [event for event in window if event.start_sub == last_start]
        approach = [event for event in window if event.start_sub != last_start]
        role = section.roles.get(instrument)
        is_chordal = len(closing) > 1 or any(
            len([e for e in window if e.start_sub == event.start_sub]) > 1 for event in window)

        if role == ROLE_BASS:
            # The bass takes the cadence chord's root, in its own register.
            for event in closing:
                event.pitch = _nearest_pitch(root_pc, event.pitch)
                event.degree = _degree_of(event.pitch, ctx.scale_pitches)
        elif is_chordal and chord_pcs:
            # Cadence harmony: the tonic triad closes, the triad of the fifth hangs.
            root = _nearest_pitch(chord_pcs[0], min(event.pitch for event in closing))
            for voice, pitch_class in zip(closing, chord_pcs):
                voice.pitch = max(0, min(127, root + ((pitch_class - chord_pcs[0]) % 12)))
                voice.degree = _degree_of(voice.pitch, ctx.scale_pitches)
        else:
            # Melodic cadence: choose the closing note first — above the passage for an
            # open ending, below it for a closed one — then shape the approach into it.
            reference = (max(event.pitch for event in window) if rising
                         else min(event.pitch for event in window))
            target = _nearest_pitch(target_pc, reference, prefer_above=rising)
            for event in closing:
                event.pitch = max(0, min(127, target))
                event.degree = _degree_of(event.pitch, ctx.scale_pitches)
            _reshape_contour(approach, rising)

        for position, event in enumerate(window):
            share = (position + 1) / len(window)
            factor = (1.0 + swell * share) if rising else (1.0 - taper * share)
            event.velocity = max(1, min(127, int(round(event.velocity * factor))))

        for event in closing:
            event.length_sub = max(event.length_sub, end_sub - event.start_sub)
            event.gate = 1.0
            event.is_phrase_final = True
    return touched


def apply_phrase_cadences(section, beats=1):
    """Give every phrase the ending its plan calls for — the period in miniature.

    An antecedent phrase is left open (tendency tone over the triad of the fifth) and a
    consequent closes on the tonic, so a section poses a question and answers it instead
    of simply stopping. Only the last ``beats`` beat(s) of each phrase are reshaped; the
    explicit `tension` / `release` transformers (4.1) are the stronger, deliberate
    version of the same gesture.
    """
    ctx = section.context
    if not section.events or not section.phrases:
        return section
    span = max(1, int(beats)) * ctx.subs_per_beat
    for phrase in section.phrases:
        end_sub = min(ctx.total_sub, phrase.end_beat * ctx.subs_per_beat)
        start_sub = max(phrase.start_beat * ctx.subs_per_beat, end_sub - span)
        if end_sub > start_sub:
            shape_cadence(section, start_sub, end_sub, phrase.ending == PHRASE_OPEN)
    return section


def accelerate_harmony(events, ctx, phrases, beats=None):
    """Re-strike held chords in the last bar of each phrase.

    Harmonic acceleration towards the cadence is half of what makes a phrase feel like it
    is going somewhere: the same chord arriving twice as often reads as a build. A chord
    held across several beats inside the closing bar is split into one strike per beat.
    """
    if not events or not phrases:
        return events
    window = (beats * ctx.subs_per_beat) if beats else ctx.subs_per_bar
    zones = [(max(phrase.start_beat * ctx.subs_per_beat,
                  phrase.end_beat * ctx.subs_per_beat - window),
              phrase.end_beat * ctx.subs_per_beat) for phrase in phrases]

    accelerated = []
    for event in events:
        inside = any(start <= event.start_sub < end for start, end in zones)
        if not inside or event.length_sub <= ctx.subs_per_beat:
            accelerated.append(event)
            continue
        strikes = event.length_sub // ctx.subs_per_beat
        for index in range(strikes):
            accelerated.append(event.copy(
                start_sub=event.start_sub + index * ctx.subs_per_beat,
                length_sub=ctx.subs_per_beat))
    return sorted(accelerated, key=lambda event: (event.start_sub, event.pitch))


def add_drum_fills(notes, ctx, phrases, spec=None):
    """Play a fill into every phrase boundary, and crash on the landing.

    The drum pattern is otherwise identical bar after bar, which flattens the phrase
    structure the other passes work to build. The last beat of each phrase gets a short
    tom/snare fill (replacing the pattern's own hits there, except the kick), and each
    phrase after the first opens with a crash.
    """
    spec = ma_utils.drum_fill if spec is None else spec
    if not spec or not phrases:
        return notes
    fill_pitches = [ma_utils.drum_pitches[name] for name in spec.get("pitches", [])
                    if name in ma_utils.drum_pitches]
    if not fill_pitches:
        return notes
    per_beat = max(1, int(spec.get("notes_per_beat", 2)))
    velocity = max(1, min(127, int(spec.get("velocity", 100))))
    kick = ma_utils.drum_pitches.get("Bass Drum")
    crash = ma_utils.drum_pitches.get(spec.get("crash", "Crash Cymbal"))
    crash_velocity = max(1, min(127, int(spec.get("crash_velocity", 110))))
    beat_len = ctx.beat_len
    length = ctx.length

    fill_windows = [((phrase.end_beat - 1) * beat_len, phrase.end_beat * beat_len)
                    for phrase in phrases]
    kept = [note for note in notes
            if note.pitch == kick or not any(start - 1e-9 <= note.start < end - 1e-9
                                             for start, end in fill_windows)]

    step = beat_len / per_beat
    for index, (start, end) in enumerate(fill_windows):
        if start >= length - 1e-9:
            continue
        for hit in range(per_beat):
            hit_start = min(start + hit * step, length)
            if hit_start >= length - 1e-9:
                break
            kept.append(pretty_midi.Note(
                velocity=velocity, pitch=fill_pitches[hit % len(fill_pitches)],
                start=hit_start, end=min(hit_start + step, length)))

    if crash is not None:
        for phrase in phrases[1:]:
            start = phrase.start_beat * beat_len
            if start < length - 1e-9:
                kept.append(pretty_midi.Note(velocity=crash_velocity, pitch=crash,
                                             start=start, end=min(start + beat_len, length)))
    return sorted(kept, key=lambda note: (note.start, note.pitch))


def shape_phrase_ending(section, mode=CADENCE_RELEASE, bars=1):
    """Build or release tension over the last ``bars`` bars of a section.

    ``mode`` ``"tension"`` leaves the passage open: the melody rises into an unstable
    degree (the leading tone where the scale has one — see
    ``ma_utils.preferred_tendency_degree``), the harmony lands on the triad of the fifth,
    and velocities swell. ``mode`` ``"release"`` closes it: the melody descends into the
    tonic, the harmony resolves to the tonic triad, and velocities taper. In both cases
    the final note is held to the end of the section.

    The pitch height the ear reads as "tension" is a consequence of this, not the cause:
    an open ending is unstable because of the degree it lands on (ToDo 4.0).
    """
    ctx = section.context
    if not section.events or ctx.total_sub <= 0:
        return section
    span = max(1, int(bars)) * ctx.subs_per_bar
    shape_cadence(section, max(0, ctx.total_sub - span), ctx.total_sub,
                  rising=mode == CADENCE_TENSION)
    return section


def build_tension(section, bars=1):
    """Phrase transformer: leave the passage hanging (see ``shape_phrase_ending``)."""
    return shape_phrase_ending(section, mode=CADENCE_TENSION, bars=bars)


def release_tension(section, bars=1):
    """Phrase transformer: resolve the passage (see ``shape_phrase_ending``)."""
    return shape_phrase_ending(section, mode=CADENCE_RELEASE, bars=bars)


_CADENCE_PARAMS = [{"name": "bars", "label": "Bars", "type": "int",
                    "default": 1, "min": 1, "max": 8}]
ma_utils.register_transformer(CADENCE_TENSION, build_tension,
                              kind=ma_utils.TRANSFORMER_PHRASE, params=_CADENCE_PARAMS)
ma_utils.register_transformer(CADENCE_RELEASE, release_tension,
                              kind=ma_utils.TRANSFORMER_PHRASE, params=_CADENCE_PARAMS)


def _insert_midi_tempo_change(midi_data, time_seconds, tempo_bpm):
    """Insert a MIDI tempo-change event at ``time_seconds`` with ``tempo_bpm`` BPM.

    Updates both ``midi_data._tick_scales`` (used by ``write()``) and the internal
    tick→time lookup table so subsequent ``time_to_tick`` calls remain accurate.

    Returns True when the event was inserted. When the pretty_midi build in use no
    longer exposes those internals, a ``RuntimeWarning`` is emitted and False is
    returned so rendering completes without a tempo map rather than raising.
    """
    missing = _missing_tempo_internals(midi_data)
    if missing:
        warnings.warn(
            _TEMPO_FALLBACK_MESSAGE.format(details="missing: " + ", ".join(missing)),
            RuntimeWarning, stacklevel=2,
        )
        return False

    try:
        resolution = midi_data.resolution
        tick = midi_data.time_to_tick(time_seconds)
        new_tick_scale = 60.0 / (tempo_bpm * resolution)
        keys = [ts[0] for ts in midi_data._tick_scales]
        idx = bisect.bisect_left(keys, tick)
        midi_data._tick_scales.insert(idx, (tick, new_tick_scale))
        current_max = len(midi_data._PrettyMIDI__tick_to_time) - 1
        midi_data._update_tick_to_time(max(current_max, tick + 1))
    except (AttributeError, TypeError, IndexError, ValueError) as exc:
        warnings.warn(
            _TEMPO_FALLBACK_MESSAGE.format(details=f"{type(exc).__name__}: {exc}"),
            RuntimeWarning, stacklevel=2,
        )
        return False
    return True


def _is_power_of_two(value):
    """True for 1, 2, 4, 8, ... — the only denominators a MIDI time signature can carry."""
    return isinstance(value, int) and value > 0 and value & (value - 1) == 0


def _append_midi_time_signature(midi_data, signature, time_seconds):
    """Append a ``pretty_midi.TimeSignature`` event for ``signature`` at ``time_seconds``.

    MIDI stores the denominator as a power-of-two exponent, so a nonstandard
    denominator (e.g. the 12 of "6/12") cannot be represented: such a signature is
    skipped with a ``RuntimeWarning`` rather than silently written as a different one.
    Returns True when the event was appended.
    """
    numerator, denominator = int(signature[0]), int(signature[1])
    if not _is_power_of_two(denominator):
        warnings.warn(
            f"Time signature {numerator}/{denominator} has a denominator that is not a "
            "power of two and cannot be written as a MIDI time-signature event; "
            "no event is emitted for it.",
            RuntimeWarning, stacklevel=2,
        )
        return False
    midi_data.time_signature_changes.append(
        pretty_midi.TimeSignature(numerator, denominator, time_seconds)
    )
    return True


def render_piece(piece, rng=None):
    """Render the whole piece into a ``pretty_midi.PrettyMIDI`` object.

    Each library section is rendered once and reused verbatim at every occurrence
    in the structure, so repeats are identical. When a section's resolved tempo
    differs from the preceding section, a MIDI tempo-change event is inserted at
    the section boundary so sequencers display correct bar/beat positions. The
    resolved time signature is emitted the same way: one event at time 0 and one at
    every later boundary where the signature changes.
    """
    rng = rng if rng is not None else random.Random()
    if not piece.structure:
        raise ValueError("The piece structure is empty — add at least one section.")

    midi_data = pretty_midi.PrettyMIDI(initial_tempo=piece.tempo)
    rendered = {}
    combined = {}
    offset = 0.0
    prev_tempo = piece.tempo
    prev_signature = None  # None until the first section sets the opening signature

    for item in piece.structure:
        entry = _as_entry(item)
        if entry.section not in piece.sections:
            raise ValueError(f"Section '{entry.section}' is not in the section library.")
        resolved = resolve_section(piece.sections[entry.section], piece)
        if resolved.tempo != prev_tempo:
            _insert_midi_tempo_change(midi_data, offset, resolved.tempo)
            prev_tempo = resolved.tempo
        signature = tuple(resolved.signature)
        if signature != prev_signature:
            _append_midi_time_signature(midi_data, signature, offset)
            prev_signature = signature
        if entry.section not in rendered:
            rendered[entry.section] = _render_section_events(resolved, rng)
        section = rendered[entry.section]
        if entry.transformer is not None and \
                ma_utils.transformer_kind(entry.transformer) == ma_utils.TRANSFORMER_PHRASE:
            # Phrase transformers reshape the section in musical time, across every
            # role at once, before it is flattened into notes.
            fn = ma_utils.get_transformer(entry.transformer)
            section = fn(section.copy(), **entry.transformer_kwargs)
        tracks, length = section.tracks(), section.length
        if entry.transformer is not None and \
                ma_utils.transformer_kind(entry.transformer) == ma_utils.TRANSFORMER_NOTE:
            fn = ma_utils.get_transformer(entry.transformer)
            tracks = {
                inst: (notes if inst == DRUM_TRACK else fn(notes, **entry.transformer_kwargs))
                for inst, notes in tracks.items()
            }
        for instrument, notes in tracks.items():
            destination = combined.setdefault(instrument, [])
            for note in notes:
                destination.append(pretty_midi.Note(velocity=note.velocity, pitch=note.pitch,
                                                    start=note.start + offset, end=note.end + offset))
        offset += length

    for instrument_name, notes in combined.items():
        if instrument_name == DRUM_TRACK:
            instrument = pretty_midi.Instrument(program=0, is_drum=True, name=DRUM_TRACK)
        else:
            if instrument_name not in INSTRUMENT_PROGRAMS:
                raise ValueError(
                    f"Unknown instrument '{instrument_name}'. "
                    f"Valid names: {sorted(INSTRUMENT_PROGRAMS)}"
                )
            instrument = pretty_midi.Instrument(program=INSTRUMENT_PROGRAMS[instrument_name],
                                                name=instrument_name)
        instrument.notes.extend(notes)
        midi_data.instruments.append(instrument)
    return midi_data


__all__ = [
    "ROLE_LEAD", "ROLE_ACCOMPANIMENT", "ROLE_BASS", "ROLES", "DRUM_TRACK",
    "INSTRUMENT_PROGRAMS", "GM_PROGRAM_COUNT",
    "VELOCITY_LEAD", "VELOCITY_BASS", "VELOCITY_CHORD", "VELOCITY_SUPPORT",
    "RoleAssignment", "SectionSpec", "StructureEntry", "PieceSpec", "ResolvedSection",
    "Phrase", "RenderContext", "NoteEvent", "RenderedSection",
    "PHRASE_ANTECEDENT", "PHRASE_CONSEQUENT", "PHRASE_OPEN", "PHRASE_CLOSED",
    "make_render_context", "plan_phrases", "assign_phrases", "materialise",
    "events_from_notes", "accent_delta", "apply_metric_accents", "apply_drum_accents",
    "apply_final_lengthening", "RhythmCell", "make_cell", "merge_repeated_chords",
    "sustain_chords", "CADENCE_TENSION", "CADENCE_RELEASE", "shape_phrase_ending",
    "build_tension", "release_tension", "shape_cadence", "apply_phrase_cadences",
    "accelerate_harmony", "add_drum_fills",
    "parse_signature", "beat_seconds", "section_seconds", "resolve_section", "piece_seconds",
    "generate_lead_line", "generate_bass_line", "generate_chord_line", "derive_support_line",
    "render_section", "render_piece",
]
