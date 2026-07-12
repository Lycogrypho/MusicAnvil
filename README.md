# MusicAnvil

MusicAnvil was inspired by the book by Italian musician Marco "Mark the Hammer" Arata.
The book explains the basics of music theory in a fun and practical way: Mark the Hammer's thesis is that anybody can create a song in one hour by just applying a few practical rules, because creating something is the first step towards a more serious and organic study of music theory.
This software tries to distill what's in the book and can be used directly, via a GUI, to generate music, or as a library to create (MIDI) music procedurally.

---

MusicAnvil is a Python library for procedurally generating MIDI music. It provides building blocks — scales, chords, drum patterns, and randomised beat generation — that can be assembled into multi-instrument MIDI files. A `tkinter` GUI is also included for interactive use without writing code.

And it needs no Artificial Intelligence to do so...


## Requirements

- Python 3.13
- `pretty_midi` and its transitive dependencies

Use an **isolated** virtual environment so the project does not pick up (and inherit the
vulnerabilities of) unrelated packages from a system/Anaconda base install. A plain
`venv` is isolated by default (`include-system-site-packages = false`):

```
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
```

Install from the project root (exact versions pinned in `requirements-lock.txt`):

```
pip install -r requirements.txt           # minimum — only pretty_midi pinned
pip install -r requirements-lock.txt      # reproducible — all runtime deps pinned
pip install -r requirements-dev.txt       # test/audit tooling (pytest, pip-audit)
```

## Architecture

| Module | Role |
|---|---|
| `musicanvil.MusicAnvil` | Composition engine — `PieceSpec`, `SectionSpec`, `render_piece`, etc. |
| `musicanvil.ma_utils` | Utility library — scales, chords, drum patterns, MIDI helpers |
| `musicanvil.MusicAnvil_GUI` | `tkinter` interface to the composition engine |
| `musicanvil/MusicAnvil.json` | External configuration — all preset data and defaults (see [Configuration](#configuration)) |

All public symbols from both `MusicAnvil` and `ma_utils` are re-exported at the package level, so you can write either:

```python
from musicanvil import PieceSpec, generate_scale          # flat import
from musicanvil import MusicAnvil, ma_utils               # module import
```

## Configuration

All preset data and defaults live in a single external file, `musicanvil/MusicAnvil.json`, so they can be tweaked without touching code. It holds:

- **Musical data** — `notes_in_octave`, `scale_definitions`, `chord_definitions`, `drum_pitches`, `drum_lines`, `beat_modes`
- **Instrument mapping** — `instrument_programs` (name → General MIDI program) and `velocities` (lead / bass / chord / support)
- **`piece_defaults`** — the default values for every `PieceSpec` / `SectionSpec` field (tempo, signature, scale, tonic, the six articulation parameters, section bars, …)
- **`gui`** — dropdown option lists, default section names, default role assignments, and the default output filename

`ma_utils` reads and caches the file at import time; the module-level dicts in `ma_utils` and the constants and dataclass defaults in `MusicAnvil` are all populated from it. To add a scale, a drum genre, or change a default, edit the JSON — no code change is needed.

```python
from musicanvil import ma_utils

config = ma_utils.load_config()                       # full dict (cached)
config = ma_utils.load_config(force_reload=True)      # re-read after editing the file
tempo  = ma_utils.get_param("piece_defaults", "tempo")   # nested lookup → 120
```

---

## GUI

Launch the graphical interface:

```
python musicanvil/MusicAnvil_GUI.py
```

The GUI is organised into three tabs, with a **File** menu for saving and loading projects.

### File menu

Save and reload a whole song as a `.json` **project file** — the piece defaults, articulation settings, default roles, the entire section library (with every per-section override), and the ordered structure are all captured.

| Command | Shortcut | Action |
|---|---|---|
| New Project | Ctrl+N | Reset to the shipped defaults and the six default sections |
| Open Project… | Ctrl+O | Load a project file, repopulating every tab |
| Save Project | Ctrl+S | Save to the current project file (prompts if none yet) |
| Save Project As… | Ctrl+Shift+S | Save to a new project file |
| Exit | | Close the application |

Project files are plain JSON (`format: "musicanvil-project"`) and are separate from `MusicAnvil.json`, which holds app-wide presets rather than a specific song. The serialisers are also available programmatically as `MusicAnvil_GUI.piece_to_project_dict(piece, filename)` and `project_dict_to_piece(data)`.

### Main tab

Configures piece-wide defaults, split across two panels.

**Piece Defaults**

| Field | Description |
|---|---|
| Tempo | BPM (default 120) |
| Signature | Time signature (4/4, 3/4, 6/8, …) |
| Scale | Scale type (major, blues, Dorian, …) |
| Tonic Note | Root note + octave of the scale (e.g. C4) |
| Beat Mode | Sub-beat grid used for lead melody generation (see below) |
| FileName | Output `.mid` file name |

**Articulation Defaults**

Fine-tune how notes are shaped in the generated output. All six parameters can also be overridden per section in the Sections tab.

| Field | Default | Effect |
|---|---|---|
| Lead Rest Prob | 0.08 | Probability (0–1) that any melody grid slot is a rest |
| Lead Sustain | 0.95 | Gate factor: note ends at `duration × sustain`, preventing note-off/note-on collisions |
| Lead Vel. Jitter | 12 | Max ±velocity offset applied randomly to each melody note |
| Lead Step Bias | 0.70 | Probability of stepping ±2 scale degrees from the previous pitch rather than jumping randomly |
| Bass Gate | 0.90 | Bass note duration as a fraction of one beat |
| Chord Gate | 0.85 | Chord note duration as a fraction of one beat |

**Default Roles**

- **Drums**: rhythm pattern dropdown (Rock, Jazz, Bossa Nova, …) and a multi-select list of which drum voices are active.
- **Lead / Accompaniment / Bass**: main instrument dropdown and a multi-select list of support instruments for each role. Support instruments double their role's main line at a lower velocity, filtered by position (lead supports play even beats only, accompaniment supports play the first half of each bar, bass supports play bar-downbeats only).

### Sections tab

Manages the section library and the section editor. Six default sections are pre-created: **Intro**, **Verse**, **Chorus**, **Solo**, **Bridge**, **Outro**. New sections can be added or deleted at any time.

Clicking a section in the library loads it into the editor immediately. Every change auto-saves — there is no Apply button.

Each section can override any piece default independently:

- Tempo, Signature, Rhythm, Scale, Tonic Note, Tonic Octave, Beat Mode
- All six Articulation parameters (Rest Prob, Sustain, Vel. Jitter, Step Bias, Bass Gate, Chord Gate)
- Which drum voices are active (per-section drum filtering)
- Lead, Accompaniment, and Bass role assignments

Fields left unchecked inherit the piece default.

### Piece Structure tab

Builds the ordered list of section occurrences that makes up the full piece.

- Pick a section from the dropdown and click **Add** to append it to the structure.
- Optionally attach a **transformer** to the occurrence before adding:
  - `tone_shift` — shifts all melodic pitches by ±n semitones (set the Shift n spinner).
  - `invert` — reflects pitches around the first note, producing a mirror-image melody.
- **Remove**, **Move Up**, **Move Down** to reorganise.
- The **Total duration** label updates live as the structure changes.
- **Generate** renders the piece; a save-file dialog lets you choose where the `.mid` file is written. Closing the dialog cancels without writing.

The same library section played multiple times is rendered once and reused identically at every occurrence (consistent repetition). The same section with different transformers applied produces distinct music each time.

---

## Composition Engine

Import the engine and describe a piece:

```python
from musicanvil import MusicAnvil

piece = MusicAnvil.PieceSpec(
    tempo=120,
    signature=(4, 4),
    rhythm="Rock",
    scale="major",
    tonic="C",
    tonic_octave=4,        # C4 = middle C
    beat_mode=MusicAnvil.ma_utils.BEAT_MODE_FIXED_16TH,
    # Articulation (all optional — these are the defaults)
    lead_rest_prob=0.08,
    lead_sustain=0.95,
    lead_velocity_jitter=12,
    lead_step_bias=0.70,
    bass_gate=0.90,
    chord_gate=0.85,
    roles={
        MusicAnvil.ROLE_LEAD:          MusicAnvil.RoleAssignment(main="Piano"),
        MusicAnvil.ROLE_ACCOMPANIMENT: MusicAnvil.RoleAssignment(main="Guitar"),
        MusicAnvil.ROLE_BASS:          MusicAnvil.RoleAssignment(main="Bass"),
    },
    sections={
        "intro":  MusicAnvil.SectionSpec(name="intro",  bars=4),
        "verse":  MusicAnvil.SectionSpec(name="verse",  bars=8),
        "chorus": MusicAnvil.SectionSpec(name="chorus", bars=8, tempo=130,
                                         lead_rest_prob=0.05, chord_gate=0.80),
    },
    structure=["intro", "verse", "chorus", "verse", "chorus"],
)

midi_data = MusicAnvil.render_piece(piece)
midi_data.write("song.mid")
```

When a section's resolved tempo differs from the piece default, `render_piece` inserts a MIDI tempo-change event at the section boundary so that sequencers and notation editors display correct bar and beat positions across the whole file.

### Section overrides

Any `SectionSpec` field set to a non-`None` value overrides the corresponding piece default for that section only. Fields left as `None` (the default) inherit from `PieceSpec`.

```python
MusicAnvil.SectionSpec(
    name="bridge",
    bars=4,
    tempo=90,                # slower tempo for this section
    scale="natural_minor",   # switch to minor
    tonic_octave=3,          # lower register
    lead_step_bias=0.40,     # more melodic leaps
    bass_gate=0.70,          # punchier bass
    drums_enabled=["Bass Drum", "Snare Drum"],  # stripped-down drums
)
```

### Structure transformers

Use `StructureEntry` to attach a transformer to a section occurrence:

```python
from musicanvil import MusicAnvil

structure = [
    MusicAnvil.StructureEntry(section="verse"),                          # plain
    MusicAnvil.StructureEntry(section="verse",
                              transformer="tone_shift",
                              transformer_kwargs={"n": 5}),              # up a fourth
    MusicAnvil.StructureEntry(section="chorus", transformer="invert"),   # mirror melody
]
```

Plain strings are also accepted wherever a `StructureEntry` is expected, so `structure=["intro", "verse"]` continues to work.

Available transformers (also accessible via `ma_utils.BEAT_TRANSFORMERS`):

| Name | Effect |
|---|---|
| `tone_shift` | Shifts every melodic pitch by `n` semitones. `n` may be negative. Clamped to 0–127. |
| `invert` | Reflects all pitches around the first note (mirror inversion). |

Drum tracks are never modified by a transformer.

### Tonic octave

`tonic_octave` controls which register the scale starts from. The default is 4 (middle C = C4). The scale spans three octaves from that starting point by default; pass `num_octaves` to `generate_scale` to control the range explicitly.

```python
piece.tonic_octave = 3   # darker, lower register
piece.tonic_octave = 5   # brighter, higher register
```

### Beat modes

`beat_mode` controls the sub-beat grid used when generating the lead melody:

| Constant | Value | Grid unit | Character |
|---|---|---|---|
| `BEAT_MODE_FIXED_16TH` | 1 | True 16th note at the current tempo | Maximum rhythmic variety |
| `BEAT_MODE_HALF_DENOM` | 2 | Half the denominator beat unit | Variety that tracks the time signature |

```python
from musicanvil import ma_utils

piece = MusicAnvil.PieceSpec(beat_mode=ma_utils.BEAT_MODE_HALF_DENOM, ...)
```

### Articulation parameters

All six articulation parameters can be set on `PieceSpec` (piece-wide) and overridden individually on any `SectionSpec`:

| Parameter | Type | Default | Notes |
|---|---|---|---|
| `lead_rest_prob` | float 0–1 | 0.08 | Fraction of melody grid slots that are rests |
| `lead_sustain` | float 0–2 | 0.95 | Gate factor on each note's duration; values > 1 create legato overlap |
| `lead_velocity_jitter` | int ≥ 0 | 12 | Max ±random offset on `VELOCITY_LEAD` per note |
| `lead_step_bias` | float 0–1 | 0.70 | Probability of stepwise motion (±2 scale degrees) |
| `bass_gate` | float 0–1 | 0.90 | Bass note duration as fraction of one beat |
| `chord_gate` | float 0–1 | 0.85 | Chord note duration as fraction of one beat |

### Per-section drum filtering

Set `drums_enabled` on a section (or piece) to restrict which drum voices play. `None` means all voices in the pattern are active.

```python
# Only kick and snare for the intro
MusicAnvil.SectionSpec(name="intro", bars=4,
                       drums_enabled=["Bass Drum", "Snare Drum"])

# All drums (default)
MusicAnvil.SectionSpec(name="chorus", bars=8, drums_enabled=None)
```

Available voice names match the keys of `ma_utils.drum_pitches`.

---

## Utility Library

Import `ma_utils` for low-level primitives:

```python
from musicanvil import ma_utils
```

### Scales

```python
# Returns note name strings (e.g. ["C4", "D4", "E4", ...])
notes = ma_utils.generate_scale("major", "C")                       # 3 octaves, starting C4
notes = ma_utils.generate_scale("blues", "A")
notes = ma_utils.generate_scale("dorian", "D", start_octave=3)      # start at D3
notes = ma_utils.generate_scale("major", "C", num_octaves=1)        # single octave (7 notes)
notes = ma_utils.generate_scale("major", "C", num_octaves=4)        # four octaves
```

`start_octave` sets the lowest root note (default 4 → C4). `num_octaves` controls how many octaves are spanned (default 3); raises `ValueError` for values below 1.

Available scales: `major`, `natural_minor`, `harmonic_minor`, `melodic_minor`, `blues`, `pentatonic_major`, `pentatonic_minor`, `dorian`, `phrygian`, `lydian`, `mixolydian`, `aeolian`, `locrian`, `chromatic`.

### Chords

```python
# Returns note names for the chord (e.g. ["C", "E", "G"])
chord = ma_utils.generate_chord_notes("C", "major")
chord = ma_utils.generate_chord_notes("A", "minor7")
```

Available chord types:

- **Triads** — `major`, `minor`, `diminished`, `augmented`
- **Suspended** — `sus2`, `sus4`
- **Sixths** — `major6`, `minor6`
- **Sevenths** — `major7`, `minor7`, `dominant7`, `minor_major7`, `half_diminished7`, `diminished7`, `augmented7`
- **Dyads** — `fifth` (power chord), `major_third`, `minor_third` (the diatonic thirds)

#### Matching chords to a set of notes

`find_compatible_chords` returns every chord from `chord_definitions` whose tones contain all the pitch classes present in a beat (a list of `pretty_midi.Note` objects or raw MIDI pitch numbers). This is what the engine's accompaniment generator uses to pick a chord that fits the melody:

```python
# Which chords contain both C and E?  → [(0, "major"), (9, "minor"), (0, "augmented"), ...]
ma_utils.find_compatible_chords([60, 64])
```

Each result is a `(root, chord_type)` pair where `root` is a pitch class (0–11).

### Random Beat Generation

```python
import pretty_midi

available_notes = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 to B4
notes = ma_utils.generate_random_beat(
    available_notes,
    tempo=120,
    time_signature=(4, 4),
    beat_duration=4,           # seconds
    mode=ma_utils.BEAT_MODE_FIXED_16TH,
    velocity=100,              # base MIDI velocity (default 100)
    velocity_jitter=10,        # ± random offset per note for natural dynamics (default 0)
)
```

Returns a list of `pretty_midi.Note` objects. The `mode` parameter selects the sub-beat grid (see Beat modes above). Notes and rests are placed on the grid (80 % note / 20 % rest), each lasting a random integer multiple of the grid unit. `velocity_jitter` adds a random ±offset to each note's velocity, clamped to [1, 127]; leave it at 0 for a flat dynamic.

### Drum Lines

Predefined patterns are stored in `ma_utils.drum_lines`. Available genres:
`Rock`, `Bossa Nova`, `Waltz`, `Rock and Roll`, `Country`, `Blues`, `Jazz`, `Metal`, `Epic Metal`, `Punk Rock`.

Drum entries are in beat-relative format `[velocity, pitch, start_beat, end_beat]`. Convert to seconds with `adapt_drum_line` before writing to MIDI:

```python
adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines["Rock"], tempo=120)
```

Velocity scaling:

```python
adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines["Jazz"], tempo=120,
                                   velocity_scaling_factor=0.8)
```

### Beat Transformers

Transformers are functions that shift the pitches of a list of `pretty_midi.Note` objects:

```python
from musicanvil import ma_utils

shifted = ma_utils.tone_shift(notes, n=7)    # up a perfect fifth
mirrored = ma_utils.invert(notes)            # mirror inversion
```

The full registry is `ma_utils.BEAT_TRANSFORMERS` (a dict of name → callable). Retrieve by name with `ma_utils.get_transformer(name)`.

### Writing MIDI Files

Single instrument:

```python
notes = ma_utils.generate_random_beat([60, 62, 64, 67, 69], tempo=120, beat_duration=4)
ma_utils.write_notes_to_midi(notes, "output.mid")

# Custom GM instrument
import pretty_midi
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

---

## Reference

The values below are the shipped defaults, all defined in `musicanvil/MusicAnvil.json` (see [Configuration](#configuration)) and editable there.

### Available Melodic Instruments

`Piano`, `Organ`, `Guitar`, `Electric Guitar`, `Bass`, `Violin`, `Strings`, `Trumpet`, `Sax`, `Flute`.

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

---

## Tests

Run the test suite (213 tests):

```
.venv\Scripts\python -m pytest tests/ -v
```

Tests cover the composition engine (`test_composer.py`), utility library (`test_ma_utils.py`), and GUI imports and structure operations (`test_gui.py`).

---

## Disclaimer

MusicAnvil generates music randomly based on configuration parameters provided by the user (scale, rhythm, tempo, instruments). The output is non-deterministic and the software has no mechanism to check whether any generated sequence resembles existing copyrighted material. **The authors of MusicAnvil accept no responsibility for any copyright infringement that may arise from the use, distribution, or publication of MIDI files produced by this software.** Users are solely responsible for verifying that any generated content complies with applicable copyright law before using it publicly or commercially.

## License

MusicAnvil is released under the **GNU General Public License v3.0 (GPL-3.0)**.

The sole runtime dependency, [`pretty_midi`](https://github.com/craffel/pretty-midi), is distributed under the **MIT License**, which is fully compatible with GPL-3.0. MIT is a permissive license that imposes no restrictions that conflict with the GPL, so MusicAnvil can be distributed as a GPL-3.0 work without issue.
