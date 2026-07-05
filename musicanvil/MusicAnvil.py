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
  c) lead line — random notes from the scale, 1-2 beats each
  d) accompaniment — one chord per beat, selected from ma_utils.chord_definitions to
     fit the lead notes sounding in that beat (via find_compatible_chords), kept within
     the scale or an idiomatic extension (ma_utils.chord_palette_extensions), voiced an
     octave below the lead
  e) support instruments — partial replicas of their role's main line (lead supports
     play only even beats, accompaniment supports only the first half of each bar,
     bass supports only the first beat of each bar)
"""

# OopCompanion:suppressRename

import random
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
INSTRUMENT_PROGRAMS = _CFG["instrument_programs"]

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
    drums_enabled: list[str] | None = None
    # Articulation overrides (None = inherit piece default)
    lead_rest_prob: float | None = None
    lead_sustain: float | None = None
    lead_velocity_jitter: int | None = None
    lead_step_bias: float | None = None
    bass_gate: float | None = None
    chord_gate: float | None = None
    roles: dict[str, RoleAssignment] = field(default_factory=dict)


@dataclass
class StructureEntry:
    """One slot in the piece structure: a section name plus an optional beat transformer.

    ``transformer`` must be a key in ``ma_utils.BEAT_TRANSFORMERS`` or ``None``.
    ``transformer_kwargs`` is forwarded verbatim as keyword arguments to the transformer
    function, so ``{"n": 3}`` is the right value for ``tone_shift``.
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
    drums_enabled: list[str] | None = None
    # Articulation defaults
    lead_rest_prob: float = _PIECE_DEFAULTS["lead_rest_prob"]       # probability of rest (vs note) per sub-unit slot
    lead_sustain: float = _PIECE_DEFAULTS["lead_sustain"]          # note end = start + length * sub_unit * sustain
    lead_velocity_jitter: int = _PIECE_DEFAULTS["lead_velocity_jitter"]  # max ±offset applied to VELOCITY_LEAD per note
    lead_step_bias: float = _PIECE_DEFAULTS["lead_step_bias"]       # probability of choosing ±2 scale degrees from prev
    bass_gate: float = _PIECE_DEFAULTS["bass_gate"]                # bass note length as fraction of beat_len
    chord_gate: float = _PIECE_DEFAULTS["chord_gate"]             # chord note length as fraction of beat_len
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
    drums_enabled: list[str] | None
    lead_rest_prob: float
    lead_sustain: float
    lead_velocity_jitter: int
    lead_step_bias: float
    bass_gate: float
    chord_gate: float
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
        drums_enabled=_inh(section.drums_enabled, piece.drums_enabled),
        lead_rest_prob=_inh(section.lead_rest_prob, piece.lead_rest_prob),
        lead_sustain=_inh(section.lead_sustain, piece.lead_sustain),
        lead_velocity_jitter=_inh(section.lead_velocity_jitter, piece.lead_velocity_jitter),
        lead_step_bias=_inh(section.lead_step_bias, piece.lead_step_bias),
        bass_gate=_inh(section.bass_gate, piece.bass_gate),
        chord_gate=_inh(section.chord_gate, piece.chord_gate),
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


def generate_lead_line(scale_pitches, n_beats, beat_len, rng,
                       mode=ma_utils.BEAT_MODE_FIXED_16TH, tempo=120,
                       rest_prob=0.08, sustain=0.95, velocity_jitter=12,
                       step_bias=0.70):
    """Random melody within the scale with articulation controls.

    ``mode`` / ``tempo`` set the sub-beat grid (see ``ma_utils.BEAT_MODE_*``).
    ``rest_prob``: probability of a rest per grid slot (0 = no rests, 1 = all rests).
    ``sustain``: note duration as a fraction of its grid span (0.95 = 5 % gap before next).
    ``velocity_jitter``: max ±offset applied to VELOCITY_LEAD each note.
    ``step_bias``: probability of choosing within ±2 scale degrees of the previous pitch.
    """
    if mode == ma_utils.BEAT_MODE_FIXED_16TH:
        sub_unit = 60.0 / tempo / 4
    elif mode == ma_utils.BEAT_MODE_HALF_DENOM:
        sub_unit = beat_len / 2
    else:
        raise ValueError(
            f"Unknown beat_mode {mode!r}. "
            f"Supported: {ma_utils.BEAT_MODE_FIXED_16TH} (fixed 16th), "
            f"{ma_utils.BEAT_MODE_HALF_DENOM} (half-denominator)."
        )

    total_sub = round(n_beats * beat_len / sub_unit)
    section_end = total_sub * sub_unit
    notes = []
    pos = 0
    prev_idx = None
    while pos < total_sub:
        length = min(rng.randint(1, 8), total_sub - pos)
        if rng.random() >= rest_prob:
            # Stepwise bias: prefer ±2 scale degrees from the previous pitch
            if prev_idx is not None and rng.random() < step_bias:
                lo = max(0, prev_idx - 2)
                hi = min(len(scale_pitches) - 1, prev_idx + 2)
                idx = rng.randint(lo, hi)
            else:
                idx = rng.randrange(len(scale_pitches))
            prev_idx = idx
            pitch = scale_pitches[idx]
            jitter = rng.randint(-velocity_jitter, velocity_jitter) if velocity_jitter > 0 else 0
            vel = max(1, min(127, VELOCITY_LEAD + jitter))
            note_end = min(pos * sub_unit + length * sub_unit * sustain, section_end)
            notes.append(pretty_midi.Note(velocity=vel, pitch=pitch,
                                          start=pos * sub_unit, end=note_end))
        pos += length
    return notes


def generate_bass_line(scale_pitches, n_beats, beat_len, rng, gate=0.90):
    """Random bass within the scale's first octave transposed two octaves down,
    one note per beat with a 90% hit probability.  ``gate`` shortens each note
    to that fraction of the beat, preventing note-off / note-on collisions."""
    first_octave = scale_pitches[: max(1, len(scale_pitches) // 3)]
    low_pitches = sorted({max(0, pitch - 24) for pitch in first_octave})
    notes = []
    for beat in range(n_beats):
        if rng.random() < 0.9:
            pitch = rng.choice(low_pitches)
            notes.append(pretty_midi.Note(velocity=VELOCITY_BASS, pitch=pitch,
                                          start=beat * beat_len,
                                          end=beat * beat_len + beat_len * gate))
    return notes


def _voice_chord_for_beat(beat_pitches, primary, scale_pcs, tonic_pc, extensions, order):
    """Return the MIDI pitches of the best chord for a beat, or None.

    ``beat_pitches`` are the lead pitches sounding in the beat; ``primary`` is the
    pitch on the downbeat (the preferred root). Candidate chords come from
    ``ma_utils.find_compatible_chords`` and must pass at least one of two gates:
    (a) strictly diatonic — all chord tones within ``scale_pcs``, or (b) an idiomatic
    extension — ``((root - tonic_pc) % 12, chord_type)`` appears in ``extensions``
    (loaded from ``ma_utils.chord_palette_extensions`` for the section's scale).

    Sort order: root on lead note first, then diatonic before extension, then full
    triad, then richer chord, then definition order, then root pitch class. The chosen
    chord is voiced one octave below ``primary``.
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
    base = primary - 12  # sit one octave below the lead
    root_midi = base - ((base - root) % 12)  # highest pitch <= base with this root pc
    return [max(0, root_midi + interval) for interval in intervals]


def generate_chord_line(lead_notes, scale_pitches, n_beats, beat_len,
                        scale_name=None, gate=0.85):
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

        chord = _voice_chord_for_beat(beat_pitches, primary, scale_pcs, tonic_pc, extensions, order)
        if chord is None:  # fall back to harmonising just the downbeat note
            chord = _voice_chord_for_beat([primary], primary, scale_pcs, tonic_pc, extensions, order)
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


def render_section(resolved, rng=None):
    """Render one resolved section.

    Returns ``(tracks, length)`` where ``tracks`` maps instrument name (or
    ``DRUM_TRACK``) to a list of notes with times relative to the section start,
    and ``length`` is the section duration in seconds.
    """
    rng = rng if rng is not None else random.Random()
    if resolved.rhythm not in ma_utils.drum_lines:
        raise ValueError(f"Rhythm '{resolved.rhythm}' is not defined.")

    beat_len = beat_seconds(resolved.tempo, resolved.signature[1])
    beats_per_bar = resolved.signature[0]
    n_beats = resolved.bars * beats_per_bar
    length = n_beats * beat_len
    scale_pitches = _scale_pitches(resolved.scale, resolved.tonic, resolved.tonic_octave)

    tracks = {}

    def add(instrument, notes):
        if instrument and notes:
            tracks.setdefault(instrument, []).extend(notes)

    # a) drums: repeat the genre pattern until the section is filled
    drum_line = list(ma_utils.drum_lines[resolved.rhythm])
    if resolved.drums_enabled is not None:
        enabled_pitches = {ma_utils.drum_pitches[n] for n in resolved.drums_enabled
                           if n in ma_utils.drum_pitches}
        drum_line = [e for e in drum_line if e[1] in enabled_pitches]
    drum_notes = []
    if drum_line:
        adapted = ma_utils.adapt_drum_line(drum_line, resolved.tempo)
        pattern_len = beats_per_bar * beat_len  # bar length, not max note-end time
        t = 0.0
        while t < length - 1e-9:
            for velocity, pitch, start, end in adapted:
                if t + start >= length:
                    continue
                drum_notes.append(pretty_midi.Note(velocity=velocity, pitch=pitch,
                                                   start=t + start, end=min(t + end, length)))
            t += pattern_len
    tracks[DRUM_TRACK] = drum_notes

    # b) bass line
    bass_role = resolved.roles[ROLE_BASS]
    bass_line = generate_bass_line(scale_pitches, n_beats, beat_len, rng,
                                   gate=resolved.bass_gate) if bass_role.main else []
    add(bass_role.main, bass_line)
    for support in bass_role.supports:
        add(support, derive_support_line(bass_line, beat_len, beats_per_bar, "bar-first-beat"))

    # c) lead line
    lead_role = resolved.roles[ROLE_LEAD]
    lead_line = generate_lead_line(scale_pitches, n_beats, beat_len, rng,
                                   mode=resolved.beat_mode, tempo=resolved.tempo,
                                   rest_prob=resolved.lead_rest_prob,
                                   sustain=resolved.lead_sustain,
                                   velocity_jitter=resolved.lead_velocity_jitter,
                                   step_bias=resolved.lead_step_bias) if lead_role.main else []
    add(lead_role.main, lead_line)
    for support in lead_role.supports:
        add(support, derive_support_line(lead_line, beat_len, beats_per_bar, "even-beats"))

    # d) accompaniment chords from the lead line
    accomp_role = resolved.roles[ROLE_ACCOMPANIMENT]
    chord_line = generate_chord_line(lead_line, scale_pitches, n_beats, beat_len,
                                     scale_name=resolved.scale,
                                     gate=resolved.chord_gate) if accomp_role.main else []
    add(accomp_role.main, chord_line)
    for support in accomp_role.supports:
        add(support, derive_support_line(chord_line, beat_len, beats_per_bar, "bar-head"))

    return tracks, length


def render_piece(piece, rng=None):
    """Render the whole piece into a ``pretty_midi.PrettyMIDI`` object.

    Each library section is rendered once and reused verbatim at every occurrence
    in the structure, so repeats are identical.
    """
    rng = rng if rng is not None else random.Random()
    if not piece.structure:
        raise ValueError("The piece structure is empty — add at least one section.")

    midi_data = pretty_midi.PrettyMIDI(initial_tempo=piece.tempo)
    rendered = {}
    combined = {}
    offset = 0.0
    for item in piece.structure:
        entry = _as_entry(item)
        if entry.section not in piece.sections:
            raise ValueError(f"Section '{entry.section}' is not in the section library.")
        if entry.section not in rendered:
            rendered[entry.section] = render_section(
                resolve_section(piece.sections[entry.section], piece), rng)
        tracks, length = rendered[entry.section]
        if entry.transformer is not None:
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
    "INSTRUMENT_PROGRAMS",
    "VELOCITY_LEAD", "VELOCITY_BASS", "VELOCITY_CHORD", "VELOCITY_SUPPORT",
    "RoleAssignment", "SectionSpec", "StructureEntry", "PieceSpec", "ResolvedSection",
    "parse_signature", "beat_seconds", "section_seconds", "resolve_section", "piece_seconds",
    "generate_lead_line", "generate_bass_line", "generate_chord_line", "derive_support_line",
    "render_section", "render_piece",
]
