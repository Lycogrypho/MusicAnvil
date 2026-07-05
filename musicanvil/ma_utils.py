import random

import pretty_midi


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


def write_notes_to_midi(notes, midi_file_path, instrument=None):
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


def write_instruments_to_midi(instrument_notes, midi_file_path):
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


# The twelve note names in an octave (sharps only — no flats).
notes_in_octave = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
]

# Scale definitions: scale name -> semitone intervals from the tonic.
scale_definitions = {
    "major": [0, 2, 4, 5, 7, 9, 11],              # Major scale intervals
    "natural_minor": [0, 2, 3, 5, 7, 8, 10],      # Natural minor scale intervals
    "harmonic_minor": [0, 2, 3, 5, 7, 8, 11],     # Harmonic minor scale intervals
    "melodic_minor": [0, 2, 3, 5, 7, 9, 11],      # Melodic minor scale intervals (ascending)
    "dorian": [0, 2, 3, 5, 7, 9, 10],             # Dorian mode intervals
    "phrygian": [0, 1, 3, 5, 7, 8, 10],           # Phrygian mode intervals
    "lydian": [0, 2, 4, 6, 7, 9, 11],             # Lydian mode intervals
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],         # Mixolydian mode intervals
    "locrian": [0, 1, 3, 5, 6, 8, 10],            # Locrian mode intervals
    "blues": [0, 3, 5, 6, 7, 10],                 # Blues scale intervals
    "pentatonic_major": [0, 2, 4, 7, 9],          # Major pentatonic scale intervals
    "pentatonic_minor": [0, 3, 5, 7, 10],         # Minor pentatonic scale intervals
    "chromatic": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],  # Chromatic scale intervals
}

# Chord definitions: chord type -> semitone intervals from the tonic.
chord_definitions = {
    "major": [0, 4, 7],          # Major chord intervals (root, major third, perfect fifth)
    "minor": [0, 3, 7],          # Minor chord intervals (root, minor third, perfect fifth)
    "diminished": [0, 3, 6],     # Diminished chord intervals (root, minor third, diminished fifth)
    "augmented": [0, 4, 8],      # Augmented chord intervals (root, major third, augmented fifth)
    "major7": [0, 4, 7, 11],     # Major 7th chord intervals
    "minor7": [0, 3, 7, 10],     # Minor 7th chord intervals
    "dominant7": [0, 4, 7, 10],  # Dominant 7th chord intervals
}

# Drum name -> General MIDI percussion pitch.
drum_pitches = {
    "Bass Drum": 35,        # Acoustic Bass Drum
    "Snare Drum": 38,       # Acoustic Snare
    "Closed Hi-Hat": 42,    # Closed Hi-Hat
    "Open Hi-Hat": 46,      # Open Hi-Hat
    "Crash Cymbal": 49,     # Crash Cymbal 1
    "Ride Cymbal": 51,      # Ride Cymbal 1
    "Tom 1": 50,            # High Tom
    "Tom 2": 47,            # Mid Tom
    "Tom 3": 48,            # Low Tom
    "Tambourine": 57,       # Tambourine
}

# Genre name -> list of [velocity, pitch, start_beat, end_beat] entries (beats, not seconds).
drum_lines = {
    "Rock": [
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 2],     # Snare Drum on beat 2
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [100, drum_pitches["Bass Drum"], 2, 3],      # Bass Drum on beat 3
        [100, drum_pitches["Snare Drum"], 3, 4],     # Snare Drum on beat 4
    ],
    "Bossa Nova": [
        [80, drum_pitches["Bass Drum"], 0, 1],       # Bass Drum on beat 1
        [80, drum_pitches["Snare Drum"], 0.5, 1.5],  # Snare Drum on the "and" of 1
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [80, drum_pitches["Bass Drum"], 1.5, 2.5],   # Bass Drum on the "and" of 2
        [80, drum_pitches["Snare Drum"], 2, 3],      # Snare Drum on beat 2
    ],
    "Waltz": [
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 1.5],   # Snare Drum on beat 2
        [100, drum_pitches["Bass Drum"], 1.5, 2.5],  # Bass Drum on beat 3
        [80, drum_pitches["Closed Hi-Hat"], 0, 2],   # Hi-Hat on beats 1 and 2
    ],
    "Rock and Roll": [
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 2],     # Snare Drum on beat 2
        [100, drum_pitches["Bass Drum"], 2, 3],      # Bass Drum on beat 3
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [80, drum_pitches["Closed Hi-Hat"], 2, 3],   # Hi-Hat on beat 3
    ],
    "Country": [     # Country: steady bass drum on the downbeats and a snare on the "and" of the beats, with closed hi-hats keeping time.
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 1.5],   # Snare Drum on the "and" of 1
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [100, drum_pitches["Bass Drum"], 2, 3],      # Bass Drum on beat 3
        [100, drum_pitches["Snare Drum"], 3, 3.5],   # Snare Drum on the "and" of 3
    ],
    "Blues": [      # Blues: similar to country but emphasizing the backbeat with the snare and a consistent hi-hat pattern.
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 1.5],   # Snare Drum on the "and" of 1
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [100, drum_pitches["Bass Drum"], 2, 3],      # Bass Drum on beat 3
        [100, drum_pitches["Snare Drum"], 3, 4],     # Snare Drum on beat 4
        [80, drum_pitches["Closed Hi-Hat"], 2, 3],   # Hi-Hat on beat 3
    ],
    "Jazz": [      # Jazz: ride cymbal for a swing feel, with the bass drum and snare providing a syncopated groove.
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 1.5],   # Snare Drum on the "and" of 1
        [80, drum_pitches["Closed Hi-Hat"], 0, 1],   # Hi-Hat on beat 1
        [80, drum_pitches["Closed Hi-Hat"], 1, 2],   # Hi-Hat on beat 2
        [100, drum_pitches["Bass Drum"], 2, 3],      # Bass Drum on beat 3
        [100, drum_pitches["Snare Drum"], 3, 4],     # Snare Drum on beat 4
        [80, drum_pitches["Ride Cymbal"], 0, 1],     # Ride Cymbal on beat 1
        [80, drum_pitches["Ride Cymbal"], 1, 2],     # Ride Cymbal on beat 2
    ],
    "Metal": [     # Metal: driving bass drum and snare pattern, with closed hi-hats maintaining a consistent pulse.
        [120, drum_pitches["Bass Drum"], 0, 0.5],    # Bass Drum on beat 1
        [120, drum_pitches["Snare Drum"], 0.5, 1],   # Snare Drum on beat 1
        [120, drum_pitches["Bass Drum"], 1, 1.5],    # Bass Drum on beat 2
        [120, drum_pitches["Snare Drum"], 1.5, 2],   # Snare Drum on beat 2
        [120, drum_pitches["Bass Drum"], 2, 2.5],    # Bass Drum on beat 3
        [120, drum_pitches["Snare Drum"], 2.5, 3],   # Snare Drum on beat 3
        [120, drum_pitches["Closed Hi-Hat"], 0, 3],  # Hi-Hat on all beats
    ],
    "Epic Metal": [  # Epic Metal: crash cymbals mark significant moments; a mix of bass and snare hits with a flowing ride cymbal.
        [100, drum_pitches["Bass Drum"], 0, 1],      # Bass Drum on beat 1
        [100, drum_pitches["Snare Drum"], 1, 1.5],   # Snare Drum on the "and" of 1
        [100, drum_pitches["Bass Drum"], 1.5, 2.5],  # Bass Drum on the "and" of 2
        [100, drum_pitches["Snare Drum"], 2.5, 3],   # Snare Drum on beat 3
        [100, drum_pitches["Crash Cymbal"], 0, 0.5], # Crash Cymbal on beat 1
        [80, drum_pitches["Ride Cymbal"], 0, 3],     # Ride Cymbal on all beats
        [100, drum_pitches["Bass Drum"], 3, 4],      # Bass Drum on beat 4
    ],
    "Punk Rock": [
        [120, drum_pitches["Bass Drum"], 0, 0.5],    # Bass Drum on beat 1
        [120, drum_pitches["Snare Drum"], 0.5, 1],   # Snare Drum on beat 1
        [120, drum_pitches["Bass Drum"], 1, 1.5],    # Bass Drum on beat 2
        [120, drum_pitches["Snare Drum"], 1.5, 2],   # Snare Drum on beat 2
        [120, drum_pitches["Bass Drum"], 2, 2.5],    # Bass Drum on beat 3
        [120, drum_pitches["Snare Drum"], 2.5, 3],   # Snare Drum on beat 3
        [120, drum_pitches["Closed Hi-Hat"], 0, 3],  # Hi-Hat on all beats
    ],
}


def generate_scale(scale_name, tonic, start_octave=4):
    """Return the note names of a scale over three octaves starting at *start_octave*.

    Parameters:
    - scale_name: Key in ``scale_definitions`` (case-insensitive).
    - tonic: Root note name from ``notes_in_octave`` (e.g. "C", "F#").
    - start_octave: The octave number of the lowest root note (default 4 → C4).
    """
    intervals = scale_definitions.get(scale_name.lower())
    if intervals is None:
        raise ValueError(f"Scale '{scale_name}' is not defined.")
    if tonic not in notes_in_octave:
        raise ValueError(f"Tonic '{tonic}' is not a valid note name.")

    tonic_index = notes_in_octave.index(tonic)
    scale_notes = []
    for octave in range(3):
        for interval in intervals:
            semitone = tonic_index + interval + octave * 12
            note_name = notes_in_octave[semitone % 12]
            octave_number = start_octave + semitone // 12
            scale_notes.append(note_name + str(octave_number))
    return scale_notes


def generate_chord_notes(note_name, chord_type):
    """Return the note names belonging to a chord built on the given tonic."""
    intervals = chord_definitions.get(chord_type.lower())
    if intervals is None:
        raise ValueError(f"Chord type '{chord_type}' is not defined.")
    if note_name not in notes_in_octave:
        raise ValueError(f"Note '{note_name}' is not a valid note name.")

    tonic_index = notes_in_octave.index(note_name)
    return [notes_in_octave[(tonic_index + interval) % 12] for interval in intervals]


# Beat generation mode constants.
BEAT_MODE_FIXED_16TH = 1   # Fixed 16th-note grid: rich sub-beat variety regardless of signature
BEAT_MODE_HALF_DENOM = 2   # Half the denominator unit: sub-beat variety that respects the signature

# Human-readable labels for GUI dropdowns, keyed by display string → mode number.
BEAT_MODES = {
    "1 — Fixed 16th-note": BEAT_MODE_FIXED_16TH,
    "2 — Half-beat":       BEAT_MODE_HALF_DENOM,
}


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


def generate_random_beat(available_notes, tempo, time_signature=(4, 4), beat_duration=4, mode=BEAT_MODE_FIXED_16TH):
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
            beat_notes.append(pretty_midi.Note(velocity=100, pitch=note_number,
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


def adapt_drum_line(drum_line, tempo, velocity_scaling_factor=1.0):
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
