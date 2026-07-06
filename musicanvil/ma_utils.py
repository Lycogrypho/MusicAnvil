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

# Scale name -> list of [root_offset_from_tonic, chord_type] pairs that are allowed even when
# not strictly diatonic. The engine applies these extensions alongside the normal scale filter.
chord_palette_extensions = _CONFIG["chord_palette_extensions"]


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


def _beat_sub_unit(tempo, time_signature, mode):
    """Return (sub_unit_seconds, max_multiplier) for the requested beat mode.

    Mode 1: base = 16th note (quarter / 4). Multipliers 1-8 give 16th … half note.
    Mode 2: base = half the denominator unit.  Multipliers 1-8 give 8th … double-whole.
    """
    quarter = 60.0 / tempo
    denom_unit = quarter * 4 / time_signature[1]
    if mode == BEAT_MODE_FIXED_16TH:
        return quarter / 4, 8
    if mode == BEAT_MODE_HALF_DENOM:
        return denom_unit / 2, 8
    raise ValueError(
        f"Unknown beat generation mode {mode!r}. "
        f"Supported: {BEAT_MODE_FIXED_16TH} (fixed 16th), {BEAT_MODE_HALF_DENOM} (half-denominator)."
    )


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


# Registry of all available beat transformers: name -> callable.
# Zero-parameter transformers have signature (beat,).
# Parameterised transformers have signature (beat, <extra args>).
# Use functools.partial to fix parameters when a single-argument callable is needed.
BEAT_TRANSFORMERS = {
    "tone_shift": tone_shift,
    "invert": invert,
}

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


def adapt_drum_line(drum_line: list, tempo: float, velocity_scaling_factor: float = 1.0) -> list:
    """Convert a beat-relative drum line to absolute seconds at the given tempo.

    Parameters:
    - drum_line: List of [velocity, pitch, start_beat, end_beat] entries.
    - tempo: Tempo in beats per minute (BPM).
    - velocity_scaling_factor: Multiplier applied to each velocity (e.g. lower it for
      faster tempos, raise it for slower ones).

    Returns a new drum line of [velocity, pitch, start_time, end_time] entries in seconds.
    """
    if tempo <= 0:
        raise ValueError(f"tempo must be a positive number of BPM, got {tempo}.")
    if velocity_scaling_factor < 0:
        raise ValueError(
            f"velocity_scaling_factor must be non-negative, got {velocity_scaling_factor}."
        )
    quarter_note_duration = 60.0 / tempo

    adapted_line = []
    for velocity, pitch, start_beat, end_beat in drum_line:
        start_time = start_beat * quarter_note_duration
        end_time = end_beat * quarter_note_duration
        adapted_velocity = max(0, min(127, int(velocity * velocity_scaling_factor)))  # Clamp to valid MIDI range
        adapted_line.append([adapted_velocity, pitch, start_time, end_time])

    return adapted_line
