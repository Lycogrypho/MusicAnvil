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
  d) accompaniment — one diatonic chord per beat, rooted on the lead note sounding
     at that beat (thirds stacked within the scale)
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

# Melodic instrument name -> General MIDI program number.
INSTRUMENT_PROGRAMS = {
    "Piano": 0,        # Acoustic Grand Piano
    "Organ": 19,       # Church Organ
    "Guitar": 25,          # Acoustic Guitar (steel)
    "Electric Guitar": 27, # Electric Guitar (clean)
    "Bass": 32,            # Acoustic Bass
    "Violin": 40,      # Violin
    "Strings": 48,     # String Ensemble 1
    "Trumpet": 56,     # Trumpet
    "Sax": 65,         # Alto Sax
    "Flute": 73,       # Flute
}

VELOCITY_LEAD = 100
VELOCITY_BASS = 90
VELOCITY_CHORD = 78
VELOCITY_SUPPORT = 68


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
    bars: int = 4
    tempo: int | None = None
    signature: tuple[int, int] | None = None
    rhythm: str | None = None
    scale: str | None = None
    tonic: str | None = None
    roles: dict[str, RoleAssignment] = field(default_factory=dict)


@dataclass
class PieceSpec:
    """Piece-wide defaults plus the section library and the ordered structure."""
    tempo: int = 120
    signature: tuple[int, int] = (4, 4)
    rhythm: str = "Rock"
    scale: str = "major"
    tonic: str = "C"
    roles: dict[str, RoleAssignment] = field(default_factory=dict)
    sections: dict[str, SectionSpec] = field(default_factory=dict)
    structure: list[str] = field(default_factory=list)


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
    return ResolvedSection(
        name=section.name,
        bars=section.bars,
        tempo=section.tempo if section.tempo is not None else piece.tempo,
        signature=section.signature if section.signature is not None else piece.signature,
        rhythm=section.rhythm if section.rhythm is not None else piece.rhythm,
        scale=section.scale if section.scale is not None else piece.scale,
        tonic=section.tonic if section.tonic is not None else piece.tonic,
        roles=roles,
    )


def piece_seconds(piece):
    """Total duration in seconds of the piece structure."""
    total = 0.0
    for name in piece.structure:
        if name not in piece.sections:
            raise ValueError(f"Section '{name}' is not in the section library.")
        resolved = resolve_section(piece.sections[name], piece)
        total += section_seconds(resolved.bars, resolved.tempo, resolved.signature)
    return total


def _scale_pitches(scale, tonic):
    """MIDI pitches of the scale over three octaves, ascending."""
    names = ma_utils.generate_scale(scale, tonic)
    return [pretty_midi.note_name_to_number(name) for name in names]


def generate_lead_line(scale_pitches, n_beats, beat_len, rng):
    """Random melody within the scale: 80% note / 20% rest, 1-2 beats per slot."""
    notes = []
    beat = 0
    while beat < n_beats:
        length = min(rng.randint(1, 2), n_beats - beat)
        if rng.random() < 0.8:
            pitch = rng.choice(scale_pitches)
            notes.append(pretty_midi.Note(velocity=VELOCITY_LEAD, pitch=pitch,
                                          start=beat * beat_len, end=(beat + length) * beat_len))
        beat += length
    return notes


def generate_bass_line(scale_pitches, n_beats, beat_len, rng):
    """Random bass within the scale's first octave transposed two octaves down,
    one note per beat with a 90% hit probability."""
    first_octave = scale_pitches[: max(1, len(scale_pitches) // 3)]
    low_pitches = sorted({max(0, pitch - 24) for pitch in first_octave})
    notes = []
    for beat in range(n_beats):
        if rng.random() < 0.9:
            pitch = rng.choice(low_pitches)
            notes.append(pretty_midi.Note(velocity=VELOCITY_BASS, pitch=pitch,
                                          start=beat * beat_len, end=(beat + 1) * beat_len))
    return notes


def generate_chord_line(lead_notes, scale_pitches, n_beats, beat_len):
    """One diatonic chord per beat, rooted on the lead note sounding at that beat.

    The chord is built by stacking thirds within the scale (scale degrees i, i+2,
    i+4) and dropped one octave so it sits under the lead. Beats where no lead
    note sounds are rests.
    """
    notes = []
    for beat in range(n_beats):
        t = beat * beat_len
        root = None
        for note in lead_notes:
            if note.start <= t + 1e-9 < note.end:
                root = note.pitch
                break
        if root is None or root not in scale_pitches:
            continue
        i = scale_pitches.index(root)
        chord = {scale_pitches[min(i + step, len(scale_pitches) - 1)] for step in (0, 2, 4)}
        for pitch in chord:
            notes.append(pretty_midi.Note(velocity=VELOCITY_CHORD, pitch=max(0, pitch - 12),
                                          start=t, end=t + beat_len))
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
    scale_pitches = _scale_pitches(resolved.scale, resolved.tonic)

    tracks = {}

    def add(instrument, notes):
        if instrument and notes:
            tracks.setdefault(instrument, []).extend(notes)

    # a) drums: repeat the genre pattern until the section is filled
    adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines[resolved.rhythm], resolved.tempo)
    pattern_len = max(entry[3] for entry in adapted)
    drum_notes = []
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
    bass_line = generate_bass_line(scale_pitches, n_beats, beat_len, rng) if bass_role.main else []
    add(bass_role.main, bass_line)
    for support in bass_role.supports:
        add(support, derive_support_line(bass_line, beat_len, beats_per_bar, "bar-first-beat"))

    # c) lead line
    lead_role = resolved.roles[ROLE_LEAD]
    lead_line = generate_lead_line(scale_pitches, n_beats, beat_len, rng) if lead_role.main else []
    add(lead_role.main, lead_line)
    for support in lead_role.supports:
        add(support, derive_support_line(lead_line, beat_len, beats_per_bar, "even-beats"))

    # d) accompaniment chords from the lead line
    accomp_role = resolved.roles[ROLE_ACCOMPANIMENT]
    chord_line = generate_chord_line(lead_line, scale_pitches, n_beats, beat_len) if accomp_role.main else []
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
    for name in piece.structure:
        if name not in piece.sections:
            raise ValueError(f"Section '{name}' is not in the section library.")
        if name not in rendered:
            rendered[name] = render_section(resolve_section(piece.sections[name], piece), rng)
        tracks, length = rendered[name]
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
            instrument = pretty_midi.Instrument(program=INSTRUMENT_PROGRAMS.get(instrument_name, 0),
                                                name=instrument_name)
        instrument.notes.extend(notes)
        midi_data.instruments.append(instrument)
    return midi_data


__all__ = [
    "ROLE_LEAD", "ROLE_ACCOMPANIMENT", "ROLE_BASS", "ROLES", "DRUM_TRACK",
    "INSTRUMENT_PROGRAMS",
    "VELOCITY_LEAD", "VELOCITY_BASS", "VELOCITY_CHORD", "VELOCITY_SUPPORT",
    "RoleAssignment", "SectionSpec", "PieceSpec", "ResolvedSection",
    "parse_signature", "beat_seconds", "section_seconds", "resolve_section", "piece_seconds",
    "generate_lead_line", "generate_bass_line", "generate_chord_line", "derive_support_line",
    "render_section", "render_piece",
]
