import json
import os
import random
from typing import Optional

import pretty_midi


## Configuration Loading

# The external configuration file lives next to this module so it is found
# regardless of the current working directory (package import or script launch).
CONFIG_FILENAME = "MusicAnvil.json"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)

_config_cache = None


def load_config(path: Optional[str] = None, force_reload: bool = False) -> dict:
    """Read the MusicAnvil.json configuration file and return it as a dict.

    The parsed configuration is cached after the first read; pass
    ``force_reload=True`` to re-read from disk (e.g. after editing the file).

    Parameters:
    - path: Optional explicit path to a config file. Defaults to ``CONFIG_PATH``.
    - force_reload: When True, bypass the cache and re-read from disk.

    Raises FileNotFoundError if the file is missing and ValueError if it does
    not contain valid JSON.
    """
    global _config_cache
    target = path or CONFIG_PATH
    if _config_cache is not None and not force_reload and path is None:
        return _config_cache

    try:
        with open(target, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {target}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Configuration file '{target}' contains invalid JSON: {exc}")

    if path is None:
        _config_cache = config
    return config


def get_param(*keys: str, default=None):
    """Return a nested configuration value, e.g. ``get_param('piece_defaults', 'tempo')``.

    Returns ``default`` if any key along the path is missing.
    """
    node = load_config()
    for key in keys:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


## Utility Functions

def get_notes_from_user():
    """Prompt the user for note details and return a list of pretty_midi.Note objects."""
    notes = []
    while True:
        user_input = input("Enter note details (pitch, start, end, velocity) or 'done' to finish: ")
        if user_input.lower() == 'done':
            break
        try:
            pitch, start, end, velocity = map(float, user_input.split(','))
            notes.append(pretty_midi.Note(velocity=int(velocity), pitch=int(pitch), start=start, end=end))
        except ValueError:
            print("Invalid input. Please enter the details in the format: pitch,start,end,velocity")
    return notes


def get_notes_from_multiple_instruments():
    """Prompt for instrument names and their notes; return {instrument_name: [Note, ...]}."""
    instrument_notes = {}
    while True:
        instrument_name = input("Enter instrument name (or 'done' to finish): ")
        if instrument_name.lower() == 'done':
            break
        instrument_notes.setdefault(instrument_name, [])
        while True:
            user_input = input(
                f"Enter note details for {instrument_name} (pitch, start, end, velocity) or 'done' to finish: ")
            if user_input.lower() == 'done':
                break
            try:
                pitch, start, end, velocity = map(float, user_input.split(','))
                instrument_notes[instrument_name].append(
                    pretty_midi.Note(velocity=int(velocity), pitch=int(pitch), start=start, end=end))
            except ValueError:
                print("Invalid input. Please enter the details in the format: pitch,start,end,velocity")
    return instrument_notes


def write_notes_to_midi(notes: list, midi_file_path: str,
                        instrument: Optional[pretty_midi.Instrument] = None) -> None:
    """Write a list of pretty_midi.Note objects to a MIDI file.

    If no instrument is supplied, an Acoustic Grand Piano (program 0) is used. A fresh
    instrument is always created internally so the caller's object is never mutated.
    """
    if instrument is None:
        track = pretty_midi.Instrument(program=0)
    else:
        track = pretty_midi.Instrument(
            program=instrument.program,
            is_drum=instrument.is_drum,
            name=instrument.name,
        )

    midi_data = pretty_midi.PrettyMIDI()
    for note in notes:
        track.notes.append(note)
    midi_data.instruments.append(track)
    midi_data.write(midi_file_path)


def write_instruments_to_midi(instrument_notes: dict, midi_file_path: str) -> None:
    """Write a dict of {instrument_name: [Note, ...]} to a MIDI file."""
    midi_data = pretty_midi.PrettyMIDI()
    for instrument_name, notes in instrument_notes.items():
        try:
            program_number = pretty_midi.instrument_name_to_program(instrument_name)
        except ValueError:
            raise ValueError(
                f"'{instrument_name}' is not a valid General MIDI instrument name. "
                "Use pretty_midi.instrument_name_to_program() to look up valid names."
            )
        instrument = pretty_midi.Instrument(program=program_number)
        for note in notes:
            instrument.notes.append(note)
        midi_data.instruments.append(instrument)
    midi_data.write(midi_file_path)


def print_midi_notes_detailed(midi_file_path):
    """Read a MIDI file and print every instrument and note to stdout."""
    midi_data = pretty_midi.PrettyMIDI(midi_file_path)
    for instrument in midi_data.instruments:
        instrument_name = pretty_midi.program_to_instrument_name(instrument.program)
        print(f"Instrument: {instrument_name} (Program: {instrument.program})")
        for note in instrument.notes:
            print(f"  Note: {note.pitch}, Start: {note.start:.2f}, End: {note.end:.2f}, Velocity: {note.velocity}")


# Musical primitives and preset data — loaded from MusicAnvil.json (see load_config).
# These module-level names are populated from the configuration file so the data
# lives in one external place; the engine and GUI keep referencing them as before.
_CONFIG = load_config()

# The twelve note names in an octave (sharps only — no flats).
notes_in_octave = _CONFIG["notes_in_octave"]

# Scale definitions: scale name -> semitone intervals from the tonic.
scale_definitions = _CONFIG["scale_definitions"]

# Chord definitions: chord type -> semitone intervals from the tonic.
chord_definitions = _CONFIG["chord_definitions"]

# Drum name -> General MIDI percussion pitch.
drum_pitches = _CONFIG["drum_pitches"]

# Genre name -> list of [velocity, pitch, start_beat, end_beat] entries (beats, not seconds).
drum_lines = _CONFIG["drum_lines"]

# Authored length of a genre pattern, in beats. Patterns are written for a bar of this
# many beats; fit_drum_line_to_bar repeats or cuts them to fill the bar of the signature
# actually in use. Genres missing from the mapping are the common 4-beat case.
DEFAULT_PATTERN_BEATS = 4
drum_pattern_beats = _CONFIG.get("drum_pattern_beats", {})

# Vocabulary a rhythmic cell is built from: candidate note lengths in beats and their
# relative likelihood (short values dominate, long ones are the exception), plus the
# default cell length in bars. See make_rhythm_cell.
rhythm_cell = _CONFIG.get("rhythm_cell", {
    "durations_in_beats": [0.25, 0.5, 0.75, 1.0, 1.5, 2.0],
    "weights": [18, 34, 6, 26, 6, 10],
    "cell_bars": 1,
})

# The fill a drummer plays into the next phrase: which drums, how loud, how many hits per
# beat, and the crash that marks the landing. See MusicAnvil.add_drum_fills.
drum_fill = _CONFIG.get("drum_fill", {})

# Relative emphasis of a position within the bar, used to turn metre into dynamics.
# "reference" is the weight that leaves a velocity untouched (see the engine's
# accent_delta); positions above it are accented, below it softened.
metric_accents = _CONFIG.get("metric_accents", {
    "downbeat": 1.0, "secondary": 0.85, "beat": 0.7, "offbeat": 0.5, "reference": 0.7,
})

# Scale name -> list of [root_offset_from_tonic, chord_type] pairs that are allowed even when
# not strictly diatonic. The engine applies these extensions alongside the normal scale filter.
chord_palette_extensions = _CONFIG["chord_palette_extensions"]


def make_rhythm_cell(rng, subs_per_beat: int, beats: int, max_length_sub: Optional[int] = None,
                     syncopation: float = 0.0, spec: Optional[dict] = None) -> list:
    """Build one rhythmic cell — the motif a section's melody is made of.

    Drawing every note length independently produces mathematically varied but
    rhythmically shapeless music; real melodies state a short cell and then repeat and
    vary it. This returns the cell as ``[(start_sub, length_sub), ...]`` filling exactly
    ``beats`` beats of the caller's grid, with lengths drawn from the weighted
    ``rhythm_cell`` vocabulary rather than uniformly.

    Two rules keep the result metrical rather than random:
    - a note of a beat or longer normally may only start on a beat, so long values land
      on strong positions instead of drifting;
    - ``syncopation`` (0-1) is the chance that a note starting on a beat is cut to half a
      beat, displacing the next onset off the beat — and, off the beat, the chance that a
      long value is kept and tied across the beat rather than shortened to it.

    Parameters:
    - rng: a ``random.Random`` — all randomness goes through it, so runs are reproducible.
    - subs_per_beat: grid steps per beat.
    - beats: cell length in beats.
    - max_length_sub: cap on a single note, in grid steps (the generator's longest note).
    - syncopation: probability of an off-beat displacement, per on-beat onset.
    - spec: override for the ``rhythm_cell`` configuration.
    """
    table = rhythm_cell if spec is None else spec
    durations = table.get("durations_in_beats") or [0.5, 1.0]
    weights = table.get("weights") or [1] * len(durations)
    weights = list(weights)[: len(durations)] or [1] * len(durations)

    total = max(1, int(round(beats * subs_per_beat)))
    cap = total if not max_length_sub else max(1, int(max_length_sub))
    choices = [max(1, int(round(d * subs_per_beat))) for d in durations]

    onsets = []
    pos = 0
    while pos < total:
        length = rng.choices(choices, weights=weights, k=1)[0]
        offset_in_beat = pos % subs_per_beat
        if length >= subs_per_beat and offset_in_beat:
            # Off the beat: normally shorten so the next onset lands on it; with
            # `syncopation`, keep the long value and tie across the beat instead.
            if not (syncopation and rng.random() < syncopation):
                length = subs_per_beat - offset_in_beat
        elif (syncopation and subs_per_beat > 1 and offset_in_beat == 0
              and rng.random() < syncopation):
            length = max(1, subs_per_beat // 2)            # displace the next onset
        length = max(1, min(length, cap, total - pos))
        onsets.append((pos, length))
        pos += length
    return onsets


# Preference order for an unstable ending: the leading tone pulls hardest towards the
# tonic, then the supertonic, then the subdominant (see ToDo 4.0).
TENDENCY_PREFERENCE = (11, 2, 5, 9, 6, 1, 10, 8, 3)


def degree_stability(scale_name: str):
    """Split a scale into stable and unstable degrees, as semitone offsets from the tonic.

    The tonic-triad degrees (1, 3, 5 — offsets 0, 3/4 and 7) are the stable ones a phrase
    can come to rest on; everything else is a tendency tone that pulls towards a
    neighbour and leaves the phrase sounding open. This is the mechanism behind the
    "question / answer" pairing of phrases, and it is a property of *which* degree, not
    of how high the note is.

    Returns ``(stable, unstable)``, both sorted lists of semitone offsets.
    """
    intervals = scale_definitions.get(scale_name.lower())
    if intervals is None:
        raise ValueError(f"Scale '{scale_name}' is not defined.")
    offsets = sorted({interval % 12 for interval in intervals})
    stable = [offset for offset in offsets if offset in (0, 3, 4, 7)]
    unstable = [offset for offset in offsets if offset not in stable]
    return stable, unstable


def preferred_tendency_degree(scale_name: str):
    """The strongest tendency tone of a scale, or None if it has none.

    Ordered by pull towards the tonic (``TENDENCY_PREFERENCE``): the leading tone first,
    then the supertonic, and so on.
    """
    _, unstable = degree_stability(scale_name)
    if not unstable:
        return None
    for offset in TENDENCY_PREFERENCE:
        if offset in unstable:
            return offset
    return unstable[0]


def diatonic_triad(scale_name: str, root_offset: int):
    """Pitch classes (relative to the tonic) of the scale's triad on ``root_offset``.

    Used to build a cadence chord — the tonic triad for a closed ending, the triad on the
    fifth for an open one. Returns None when the scale cannot spell a triad there.
    """
    intervals = scale_definitions.get(scale_name.lower())
    if intervals is None:
        raise ValueError(f"Scale '{scale_name}' is not defined.")
    pcs = {interval % 12 for interval in intervals}
    root = root_offset % 12
    if root not in pcs:
        return None
    third = next((step for step in (4, 3) if (root + step) % 12 in pcs), None)
    fifth = next((step for step in (7, 6, 8) if (root + step) % 12 in pcs), None)
    if third is None or fifth is None:
        return None
    return [root, (root + third) % 12, (root + fifth) % 12]


def metric_weight(beat_in_bar: float, beats_per_bar: int, weights: Optional[dict] = None) -> float:
    """Return the metric emphasis of a position in the bar, from ``metric_accents``.

    Metre is a hierarchy, not a flat pulse: the downbeat carries the most weight, a
    secondary strong beat comes next, plain beats follow and anything between beats is
    weakest. The secondary beat is the middle of the bar in simple metres of four or
    more (beat 3 of 4/4) and every third beat in compound metres (beats 4 and 7 of
    12/8); triple and duple metres have none.

    Parameters:
    - beat_in_bar: position within the bar, in beats (0 = downbeat). Fractional values
      are off-beat positions.
    - beats_per_bar: the time signature's numerator.
    - weights: override for the ``metric_accents`` table.
    """
    table = metric_accents if weights is None else weights
    beat = round(beat_in_bar)
    if abs(beat_in_bar - beat) > 1e-6:
        return table.get("offbeat", 0.5)
    beat %= max(1, beats_per_bar)
    if beat == 0:
        return table.get("downbeat", 1.0)
    if beats_per_bar > 3 and beats_per_bar % 3 == 0:      # compound: 6/8, 9/8, 12/8
        if beat % 3 == 0:
            return table.get("secondary", 0.85)
    elif beats_per_bar >= 4 and beats_per_bar % 2 == 0:   # simple duple/quadruple
        if beat == beats_per_bar // 2:
            return table.get("secondary", 0.85)
    return table.get("beat", 0.7)


def generate_scale(scale_name: str, tonic: str, start_octave: int = 4,
                   num_octaves: int = 3) -> list:
    """Return the note names of a scale over *num_octaves* octaves starting at *start_octave*.

    Parameters:
    - scale_name: Key in ``scale_definitions`` (case-insensitive).
    - tonic: Root note name from ``notes_in_octave`` (e.g. "C", "F#").
    - start_octave: The octave number of the lowest root note (default 4 → C4).
    - num_octaves: Number of octaves to span (default 3).
    """
    intervals = scale_definitions.get(scale_name.lower())
    if intervals is None:
        raise ValueError(f"Scale '{scale_name}' is not defined.")
    if tonic not in notes_in_octave:
        raise ValueError(f"Tonic '{tonic}' is not a valid note name.")
    if num_octaves < 1:
        raise ValueError(f"num_octaves must be at least 1, got {num_octaves}.")

    tonic_index = notes_in_octave.index(tonic)
    scale_notes = []
    for octave in range(num_octaves):
        for interval in intervals:
            semitone = tonic_index + interval + octave * 12
            note_name = notes_in_octave[semitone % 12]
            octave_number = start_octave + semitone // 12
            scale_notes.append(note_name + str(octave_number))
    return scale_notes


def generate_chord_notes(note_name: str, chord_type: str) -> list:
    """Return the note names belonging to a chord built on the given tonic."""
    intervals = chord_definitions.get(chord_type.lower())
    if intervals is None:
        raise ValueError(f"Chord type '{chord_type}' is not defined.")
    if note_name not in notes_in_octave:
        raise ValueError(f"Note '{note_name}' is not a valid note name.")

    tonic_index = notes_in_octave.index(note_name)
    return [notes_in_octave[(tonic_index + interval) % 12] for interval in intervals]


def find_compatible_chords(beat: list, chord_defs: Optional[dict] = None) -> list:
    """Return every chord from ``chord_definitions`` compatible with the notes in *beat*.

    A chord is *compatible* when every distinct pitch class present in the beat is one
    of the chord's pitch classes at the given root — i.e. all the beat's notes can be
    heard as tones of that chord.

    Parameters:
    - beat: an iterable of ``pretty_midi.Note`` objects (or raw MIDI pitch integers) —
      the notes sounding across one beat.
    - chord_defs: chord name → interval list mapping. Defaults to ``chord_definitions``.

    Returns a list of ``(root, chord_type)`` tuples, where ``root`` is a pitch class
    (0–11) and ``chord_type`` is a key of ``chord_defs``. The order is deterministic:
    by chord-definition order, then ascending root. An empty beat yields an empty list.
    """
    defs = chord_definitions if chord_defs is None else chord_defs
    pitch_classes = set()
    for item in beat:
        pitch = item.pitch if hasattr(item, "pitch") else item
        pitch_classes.add(pitch % 12)
    if not pitch_classes:
        return []

    compatible = []
    for chord_type, intervals in defs.items():
        for root in range(12):
            chord_pitch_classes = {(root + interval) % 12 for interval in intervals}
            if pitch_classes <= chord_pitch_classes:
                compatible.append((root, chord_type))
    return compatible


# Beat generation mode constants.
BEAT_MODE_FIXED_16TH = 1   # Fixed 16th-note grid: rich sub-beat variety regardless of signature
BEAT_MODE_HALF_DENOM = 2   # Half the denominator unit: sub-beat variety that respects the signature

# Human-readable labels for GUI dropdowns, keyed by display string → mode number.
BEAT_MODES = _CONFIG["beat_modes"]


def beat_sub_unit(tempo, beat_length, mode):
    """Return (sub_unit_seconds, max_multiplier) for the requested beat mode.

    This is the single definition of the mode → sub-beat grid mapping; both
    ``generate_random_beat`` here and ``MusicAnvil.generate_lead_line`` call it so the
    two grids cannot drift apart.

    Parameters:
    - tempo: Tempo in BPM.
    - beat_length: Duration in seconds of one beat, i.e. the time signature's
      denominator unit (``MusicAnvil.beat_seconds(tempo, denominator)``).
    - mode: ``BEAT_MODE_FIXED_16TH`` — base = 16th note (quarter / 4); multipliers 1-8
      give 16th … half note. ``BEAT_MODE_HALF_DENOM`` — base = half the beat;
      multipliers 1-8 give half-beat … 4 beats.
    """
    if mode == BEAT_MODE_FIXED_16TH:
        return 60.0 / tempo / 4, 8
    if mode == BEAT_MODE_HALF_DENOM:
        return beat_length / 2, 8
    raise ValueError(
        f"Unknown beat generation mode {mode!r}. "
        f"Supported: {BEAT_MODE_FIXED_16TH} (fixed 16th), {BEAT_MODE_HALF_DENOM} (half-denominator)."
    )


def _beat_sub_unit(tempo, time_signature, mode):
    """``beat_sub_unit`` keyed by a (numerator, denominator) signature instead of the
    beat length in seconds."""
    return beat_sub_unit(tempo, 60.0 / tempo * 4 / time_signature[1], mode)


def generate_random_beat(available_notes: list, tempo: float, time_signature: tuple = (4, 4),
                         beat_duration: float = 4, mode: int = BEAT_MODE_FIXED_16TH,
                         velocity: int = 100, velocity_jitter: int = 0) -> list:
    """Generate a random beat as a list of pretty_midi.Note objects.

    Notes and rests are placed sequentially (80% note / 20% rest), each lasting an
    integer multiple of the mode's base unit. Generation stops once the accumulated
    time reaches ``beat_duration``, which is interpreted in **seconds**.

    Parameters:
    - available_notes: List of MIDI note numbers (e.g. [60, 62, 64, 65, 67, 69, 71, 72]).
    - tempo: Tempo in beats per minute (BPM).
    - time_signature: (numerator, denominator); used by mode 2 to derive the base unit.
    - beat_duration: Total length of the generated beat, in seconds.
    - mode: Beat generation mode (``BEAT_MODE_FIXED_16TH`` or ``BEAT_MODE_HALF_DENOM``).
      Mode 1 uses a fixed 16th-note grid for maximum rhythmic variety.
      Mode 2 halves the denominator unit, preserving the time-signature character.
    - velocity: Base MIDI velocity for generated notes (1–127, default 100).
    - velocity_jitter: Max ±random offset applied to each note's velocity (default 0).
      Pass a positive value (e.g. 10) for natural dynamic variation.

    Returns a list of pretty_midi.Note objects.
    """
    if not available_notes:
        raise ValueError("available_notes must not be empty.")
    if tempo <= 0:
        raise ValueError(f"tempo must be a positive number of BPM, got {tempo}.")
    if beat_duration <= 0:
        raise ValueError(f"beat_duration must be a positive number of seconds, got {beat_duration}.")

    base_duration, max_mult = _beat_sub_unit(tempo, time_signature, mode)

    total_duration = 0
    beat_notes = []
    while total_duration < beat_duration:
        duration = random.randint(1, max_mult) * base_duration
        if random.random() < 0.8:  # 80% chance of a note, 20% chance of a rest
            note_number = random.choice(available_notes)
            jitter = random.randint(-velocity_jitter, velocity_jitter) if velocity_jitter > 0 else 0
            vel = max(1, min(127, velocity + jitter))
            beat_notes.append(pretty_midi.Note(velocity=vel, pitch=note_number,
                                               start=total_duration, end=total_duration + duration))
        total_duration += duration

    # Cap the final note so the beat ends no later than beat_duration.
    if beat_notes and beat_notes[-1].end > beat_duration:
        beat_notes[-1].end = beat_duration

    return beat_notes

## Beat Transformer Functions Section

def tone_shift(beat, n):
    """Return a new beat with every note shifted n semitones (positive = up, negative = down).

    Pitches are clamped to the valid MIDI range [0, 127]. Start/end times and
    velocities are preserved unchanged.
    """
    result = []
    for note in beat:
        result.append(pretty_midi.Note(
            velocity=note.velocity,
            pitch=max(0, min(127, note.pitch + n)),
            start=note.start,
            end=note.end,
        ))
    return result


def invert(beat):
    """Return a new beat with notes mirrored around the first note's pitch.

    The first note is kept unchanged. Each subsequent note is replaced by its
    reflection: new_pitch = 2 * pivot - original_pitch, where pivot is the
    pitch of the first note. Pitches are clamped to [0, 127].

    Example: E(64)-G(67)-F#(66) → E(64)-C#(61)-D(62)
    """
    if not beat:
        return []
    pivot = beat[0].pitch
    result = []
    for i, note in enumerate(beat):
        new_pitch = note.pitch if i == 0 else max(0, min(127, 2 * pivot - note.pitch))
        result.append(pretty_midi.Note(
            velocity=note.velocity,
            pitch=new_pitch,
            start=note.start,
            end=note.end,
        ))
    return result


# Transformer kinds. A *note* transformer is the original shape — ``fn(beat, **kwargs)``
# over one instrument's notes, with no idea of metre, scale or phrase. A *phrase*
# transformer is handed the whole rendered section in musical time —
# ``fn(rendered_section, **kwargs)`` — so it can shape a cadence across every role at
# once. The engine registers its phrase transformers here at import time, so the GUI
# still has a single registry to read.
TRANSFORMER_NOTE = "note"
TRANSFORMER_PHRASE = "phrase"

# Registry of all available beat transformers: name -> callable.
# Zero-parameter transformers have signature (beat,).
# Parameterised transformers have signature (beat, <extra args>).
# Use functools.partial to fix parameters when a single-argument callable is needed.
BEAT_TRANSFORMERS = {
    "tone_shift": tone_shift,
    "invert": invert,
}

# name -> {"kind": ..., "params": [descriptor, ...]}. A descriptor declares one keyword
# argument the GUI must offer: {"name", "label", "type" ("int"/"float"/"choice"),
# "default", and "min"/"max" or "choices"}. Declaring them here rather than hardcoding
# widgets means a new transformer appears in the GUI complete with its controls.
TRANSFORMER_SPECS = {
    "tone_shift": {
        "kind": TRANSFORMER_NOTE,
        "params": [{"name": "n", "label": "Shift n", "type": "int",
                    "default": 0, "min": -127, "max": 127}],
    },
    "invert": {"kind": TRANSFORMER_NOTE, "params": []},
}


def register_transformer(name, fn, kind=TRANSFORMER_NOTE, params=None):
    """Add a transformer to the registry, with its kind and parameter descriptors."""
    BEAT_TRANSFORMERS[name] = fn
    TRANSFORMER_SPECS[name] = {"kind": kind, "params": list(params or [])}
    return fn


## End of Beat Transformers Section

def get_transformer(name):
    """Return the beat-transformer registered under *name*.

    Raises ValueError with the list of available names for unknown keys.
    """
    fn = BEAT_TRANSFORMERS.get(name)
    if fn is None:
        available = ", ".join(sorted(BEAT_TRANSFORMERS))
        raise ValueError(f"Unknown transformer '{name}'. Available: {available}")
    return fn


def transformer_kind(name):
    """``TRANSFORMER_NOTE`` or ``TRANSFORMER_PHRASE`` for a registered transformer."""
    get_transformer(name)
    return TRANSFORMER_SPECS.get(name, {}).get("kind", TRANSFORMER_NOTE)


def transformer_params(name):
    """The parameter descriptors of a registered transformer (possibly empty)."""
    get_transformer(name)
    return list(TRANSFORMER_SPECS.get(name, {}).get("params", []))


def adapt_drum_line(drum_line: list, tempo: float, velocity_scaling_factor: float = 1.0,
                    denominator: int = 4) -> list:
    """Convert a beat-relative drum line to absolute seconds at the given tempo.

    Parameters:
    - drum_line: List of [velocity, pitch, start_beat, end_beat] entries.
    - tempo: Tempo in beats per minute (BPM).
    - velocity_scaling_factor: Multiplier applied to each velocity (e.g. lower it for
      faster tempos, raise it for slower ones).
    - denominator: Time-signature denominator setting the beat unit the entries are
      counted in — 4 (default) = quarter notes, 8 = eighth notes, ... A pattern is
      therefore read in the unit of the signature it is played in, so its hits stay on
      the signature's beat grid.

    Returns a new drum line of [velocity, pitch, start_time, end_time] entries in seconds.
    """
    if tempo <= 0:
        raise ValueError(f"tempo must be a positive number of BPM, got {tempo}.")
    if velocity_scaling_factor < 0:
        raise ValueError(
            f"velocity_scaling_factor must be non-negative, got {velocity_scaling_factor}."
        )
    if denominator <= 0:
        raise ValueError(f"denominator must be a positive number, got {denominator}.")
    beat_duration = 60.0 / tempo * 4.0 / denominator

    adapted_line = []
    for velocity, pitch, start_beat, end_beat in drum_line:
        start_time = start_beat * beat_duration
        end_time = end_beat * beat_duration
        adapted_velocity = max(0, min(127, int(velocity * velocity_scaling_factor)))  # Clamp to valid MIDI range
        adapted_line.append([adapted_velocity, pitch, start_time, end_time])

    return adapted_line


def pattern_beats(rhythm: str) -> float:
    """Return the authored length of a genre pattern, in beats.

    Read from ``drum_pattern_beats`` in the configuration, defaulting to
    ``DEFAULT_PATTERN_BEATS`` (4) for genres that do not declare one.
    """
    return drum_pattern_beats.get(rhythm, DEFAULT_PATTERN_BEATS)


def fit_drum_line_to_bar(drum_line: list, tempo: float, time_signature: tuple = (4, 4),
                         beats_per_pattern: float = DEFAULT_PATTERN_BEATS,
                         velocity_scaling_factor: float = 1.0) -> list:
    """Adapt a drum pattern so it spans exactly one bar of *time_signature*.

    The genre patterns in ``drum_lines`` are authored as a fixed number of beats
    (``beats_per_pattern``, 4 for most genres — see ``drum_pattern_beats``), which need
    not match the bar length of the signature they are played in. The pattern is read in
    the signature's beat unit (see ``adapt_drum_line``) and then made to fill the bar:
    it repeats from its start when the bar is longer, and is cut at the bar line when the
    bar is shorter. Hits therefore always land on the signature's beat grid, and the
    result never overruns into the next bar nor leaves a tail of silence.

    For a 4-beat pattern in 4/4 this is exactly ``adapt_drum_line`` — the common case is
    unchanged.

    Parameters:
    - drum_line: List of [velocity, pitch, start_beat, end_beat] entries.
    - tempo: Tempo in beats per minute (BPM).
    - time_signature: (numerator, denominator) of the bar to fill.
    - beats_per_pattern: Authored length of *drum_line* in beats.
    - velocity_scaling_factor: Forwarded to ``adapt_drum_line``.

    Returns a list of [velocity, pitch, start_time, end_time] entries in seconds,
    relative to the start of the bar, every one of them inside it.
    """
    if beats_per_pattern <= 0:
        raise ValueError(f"beats_per_pattern must be positive, got {beats_per_pattern}.")
    beats_per_bar, denominator = time_signature[0], time_signature[1]
    if beats_per_bar <= 0:
        raise ValueError(f"time signature numerator must be positive, got {beats_per_bar}.")

    adapted = adapt_drum_line(drum_line, tempo, velocity_scaling_factor, denominator)
    if not adapted:
        return []

    beat_duration = 60.0 / tempo * 4.0 / denominator
    pattern_seconds = beats_per_pattern * beat_duration
    bar_seconds = beats_per_bar * beat_duration

    bar_line = []
    offset = 0.0
    while offset < bar_seconds - 1e-9:
        for velocity, pitch, start_time, end_time in adapted:
            start = offset + start_time
            if start >= bar_seconds - 1e-9:
                continue  # this repetition runs past the bar line — cut it
            bar_line.append([velocity, pitch, start, min(offset + end_time, bar_seconds)])
        offset += pattern_seconds
    return bar_line
