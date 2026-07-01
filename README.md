# MusicAnvil

MusicAnvil was inspired by the book my Italian musician Marco "Mark the Hammer" Arata. 
The book explains the basics of music theory in a fun and practical way: Mark the Hammer's thesis is that anybody can create a song in one hour by just applying a few practical rules, because creating something is the first step towards a more serious and organic study of music theory.
This software tries to distill what's in the book and can be used directly, via a GUI, to generate music, or as a library to create (MIDI) music procedurally.

---

MusicAnvil is a Python library for procedurally generating MIDI music. It provides building blocks — scales, chords, drum patterns, and randomised beat generation — that can be assembled into multi-instrument MIDI files. A `tkinter` GUI is also included for interactive use without writing code.

And it needs no Artificial Intelligence to do so...


## Requirements

- Python 3.12
- `pretty_midi`

```
pip install pretty_midi
```

## GUI

Launch the graphical interface:

```
python musicanvil/MusicAnvil_GUI.py
```

The GUI lets you configure:

| Field | Description |
|---|---|
| Tempo | BPM (default 120) |
| Signature | Time signature (4/4, 3/4, 6/8, …) |
| Rhythm | Drum genre preset (Rock, Jazz, Metal, Bossa Nova, …) |
| Scale | Scale type (major, blues, pentatonic, …) |
| Tonic Note | Root note of the scale |
| Instruments | Multi-select list of instruments to include |
| Lead Instrument | Instrument that carries the melody |
| FileName | Output `.mid` file name |
| Duration | Length of the generated piece (MM:SS) |

## Library Usage

Import the core module:

```python
from musicanvil import ma_utils
```

### Scales

```python
# Returns note name strings over 3 octaves (e.g. ["C4", "D4", "E4", ...])
notes = ma_utils.generate_scale("major", "C")
notes = ma_utils.generate_scale("blues", "A")
```

Available scales: `major`, `natural_minor`, `harmonic_minor`, `melodic_minor`, `blues`, `pentatonic_major`, `pentatonic_minor`.

### Chords

```python
# Returns note names for the chord (e.g. ["C", "E", "G"])
chord = ma_utils.generate_chord_notes("C", "major")
chord = ma_utils.generate_chord_notes("A", "minor7")
```

Available chord types: `major`, `minor`, `diminished`, `augmented`, `major7`, `minor7`, `dominant7`.

### Random Beat Generation

```python
import pretty_midi

available_notes = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 to B4
notes = ma_utils.generate_random_beat(
    available_notes,
    tempo=120,
    time_signature=(4, 4),
    beat_duration=4   # seconds
)
```

Returns a list of `pretty_midi.Note` objects. Notes and rests are placed randomly (80% / 20% probability), each lasting an integer multiple of the base beat unit.

### Drum Lines

Predefined patterns are stored in `ma_utils.drum_lines`. Available genres: `Rock`, `Bossa Nova`, `Waltz`, `Rock and Roll`, `Country`, `Blues`, `Jazz`, `Metal`, `Epic Metal`, `Punk Rock`.

Drum entries are in beat-relative format `[velocity, pitch, start_beat, end_beat]`. Convert to seconds with `adapt_drum_line` before writing to MIDI:

```python
tempo = 120
adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines["Rock"], tempo)
```

You can also scale velocities across the pattern:

```python
adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines["Jazz"], tempo, velocity_scaling_factor=0.8)
```

### Writing MIDI Files

Single instrument:

```python
import pretty_midi

notes = ma_utils.generate_random_beat([60, 62, 64, 67, 69], tempo=120, beat_duration=4)
ma_utils.write_notes_to_midi(notes, "output.mid")

# Custom instrument (program number from GM standard)
guitar = pretty_midi.Instrument(program=25)
ma_utils.write_notes_to_midi(notes, "output.mid", instrument=guitar)
```

Multiple instruments:

```python
instrument_notes = {
    "Acoustic Grand Piano": piano_notes,
    "Acoustic Bass": bass_notes,
}
ma_utils.write_instruments_to_midi(instrument_notes, "output.mid")
```

### Inspecting a MIDI File

```python
ma_utils.print_midi_notes_detailed("output.mid")
# Instrument: Acoustic Grand Piano (Program: 0)
#   Note: 60, Start: 0.00, End: 0.50, Velocity: 100
#   ...
```

## Reference

### Drum MIDI Pitches

| Name | MIDI Pitch |
|---|---|
| Bass Drum | 35 |
| Snare Drum | 38 |
| Closed Hi-Hat | 42 |
| Open Hi-Hat | 46 |
| Crash Cymbal | 49 |
| Ride Cymbal | 51 |
| Tom 1 (High) | 50 |
| Tom 2 (Mid) | 47 |
| Tom 3 (Low) | 48 |
| Tambourine | 57 |

### Note Numbering

```
Note name:   C   C#   D   D#   E   F   F#   G   G#   A   A#   B
Note index:  0    1   2    3   4   5    6   7    8   9   10  11
MIDI pitch:  C4 = 60, C5 = 72, C3 = 48
```

Notes use sharps only (`C#`, not `Db`). Percussion always uses MIDI channel 10.

## Disclaimer

MusicAnvil generates music randomly based on configuration parameters provided by the user (scale, rhythm, tempo, instruments). The output is non-deterministic and the software has no mechanism to check whether any generated sequence resembles existing copyrighted material. **The authors of MusicAnvil accept no responsibility for any copyright infringement that may arise from the use, distribution, or publication of MIDI files produced by this software.** Users are solely responsible for verifying that any generated content complies with applicable copyright law before using it publicly or commercially.

## License

MusicAnvil is released under the **GNU General Public License v3.0 (GPL-3.0)**.

The sole runtime dependency, [`pretty_midi`](https://github.com/craffel/pretty-midi), is distributed under the **MIT License**, which is fully compatible with GPL-3.0. MIT is a permissive license that imposes no restrictions that conflict with the GPL, so MusicAnvil can be distributed as a GPL-3.0 work without issue.
