# MusicAnvil

MusicAnvil was inspired by the book "write a hit in 90 mins" by Italian musician Marco "Mark the Hammer" Arata.
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

Or install the package itself — `pyproject.toml` declares the same runtime pin, the
`dev` extra, and `MusicAnvil.json` as package data (without which an installed copy
could not load any preset):

```
pip install .            # runtime only
pip install .[dev]       # plus pytest and pip-audit
```

Every push and pull request runs the test suite and a `pip-audit` vulnerability scan
against an environment built from the pinned requirement files
(`.github/workflows/ci.yml`); the same job also runs weekly so newly disclosed CVEs
surface without a commit.

## Architecture

| Module | Role |
|---|---|
| `musicanvil.MusicAnvil` | Composition engine — `PieceSpec`, `SectionSpec`, `render_piece`, etc. |
| `musicanvil.ma_utils` | Utility library — scales, chords, drum patterns, MIDI helpers |
| `musicanvil.MusicAnvil_GUI` | `tkinter` interface to the composition engine |
| `musicanvil/MusicAnvil.json` | External configuration — all preset data and defaults (see [Configuration](#configuration)) |
| `examples/` | Standalone `pretty_midi` snippets; not part of the package |

A PlantUML view of the same structure — modules, dataclasses and the call flow — is in
[`struct.puml`](struct.puml).

Inside the engine, music is generated in **musical time**: notes live on an integer grid
of sub-beat units as `NoteEvent`s that carry their phrase, metric weight and scale degree,
and are converted to seconds exactly once, at the end. That is what lets the shaping
passes know where a note sits in the bar and which phrase it closes:

```
ResolvedSection
  → plan_phrases()   → [Phrase]                     (antecedent / consequent)
  → make_cell()      → RhythmCell                   (the section's motif)
  → generate_*()     → [NoteEvent] on the grid
  → shaping: harmonic acceleration → metric accents → phrase-final lengthening
             → phrase cadences → drum fills → expression → keyswitches
  → materialise()    → {instrument: [pretty_midi.Note]}
```

All public symbols from both `MusicAnvil` and `ma_utils` are re-exported at the package level, so you can write either:

```python
from musicanvil import PieceSpec, generate_scale          # flat import
from musicanvil import MusicAnvil, ma_utils               # module import
```

## Configuration

All preset data and defaults live in a single external file, `musicanvil/MusicAnvil.json`, so they can be tweaked without touching code. It holds:

- **Musical data** — `notes_in_octave`, `scale_definitions`, `chord_definitions`, `drum_pitches`, `drum_lines`, `drum_pattern_beats`, `drum_fill`, `beat_modes`
- **Phrasing and dynamics** — `rhythm_cell` (the note-length vocabulary a motif is drawn from) and `metric_accents` (how much emphasis each position in the bar carries)
- **Expression** — `expression` (ambience sends per role, swell/decay ranges, vibrato and bend settings, palm-mute gate, the optional fret-noise and portamento switches), `power_chord_programs` (the distorted programs voiced with fifths) and `keyswitches` (per-instrument articulation map for sampled libraries, empty by default)
- **Instrument mapping** — `instrument_programs` (name → General MIDI program) and `velocities` (lead / bass / chord / support)
- **`piece_defaults`** — the default values for every `PieceSpec` / `SectionSpec` field (tempo, signature, scale, tonic, the articulation, phrasing and dynamics parameters, section bars, …)
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
Every parameter explains itself: hover over a field for a balloon, and the same text appears
in the info line at the bottom of the Main tab.

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

Fine-tune how notes are shaped in the generated output. Every parameter here — and the phrasing and dynamics fields below it — can also be overridden per section in the Sections tab.

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

Every parameter on this tab can be overridden per section in the Sections tab — including
the three switches, which appear there as yes/no dropdowns.

### Sections tab

Manages the section library and the section editor. Six default sections are pre-created: **Intro**, **Verse**, **Chorus**, **Solo**, **Bridge**, **Outro**. New sections can be added or deleted at any time.

Clicking a section in the library loads it into the editor immediately. Every change auto-saves — there is no Apply button.

Each section can override any piece default independently:

- Tempo, Signature, Rhythm, Scale, Tonic Note, Tonic Octave, Beat Mode
- All six Articulation parameters (Rest Prob, Sustain, Vel. Jitter, Step Bias, Bass Gate, Chord Gate)
- Which drum voices are active (per-section drum filtering)
- Lead, Accompaniment, and Bass role assignments

Fields left unchecked inherit the piece default.

The section editor also shows a live **Techniques** line: what the engine will actually do
to this section given the instruments and switches chosen — power chords and palm mutes for
a distorted program, what expression is writing, which roles get pitch bends, whether
cadences and drum fills are on. Playing technique follows from the instrument you pick, not
from a separate setting, and this is where that becomes visible.

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

When a section's resolved tempo differs from the piece default, `render_piece` inserts a MIDI tempo-change event at the section boundary so that sequencers and notation editors display correct bar and beat positions across the whole file. Time signatures are written the same way: one event at time 0 and one at every later boundary where the resolved signature changes, so a piece in 3/4 (or with a 6/8 bridge) opens against the right bar grid instead of a default 4/4 one.

Two caveats on those meta events:

- pretty_midi has no public API for adding a tempo change to an object under construction, so the engine uses private members of the pinned `pretty_midi==0.2.11`. If a future version renames them, rendering does **not** fail: the tempo map is skipped, a `RuntimeWarning` explains why, and the notes — whose timing already reflects the per-section tempo — are still written. `tests/test_composer.py::TestTempoInternalsGuard` fails on such a bump so the breakage is caught at test time.
- MIDI stores a time-signature denominator as a power-of-two exponent, so a signature like `6/12` cannot be represented. Such a signature still renders (the maths works), but no time-signature event is emitted for it and a `RuntimeWarning` says so. The GUI only offers real signatures.

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

Both the engine's melody generator and `generate_random_beat` take their grid from a
single helper, `ma_utils.beat_sub_unit(tempo, beat_length, mode)`, which returns
`(sub_unit_seconds, max_multiplier)` — so the two can never drift apart.

### Phrasing, dynamics and cadences

A section is divided into **phrases** (`phrase_bars`, 0 = derive from the section length:
half the section, capped at four bars). Phrases alternate *antecedent* (open) and
*consequent* (closed), and the engine shapes them:

| Field | Default | What it does |
|---|---|---|
| `phrase_bars` | 0 (auto) | Phrase length in bars |
| `lead_syncopation` | 0.25 | Chance of an off-beat displacement in the melodic motif |
| `metric_accent` | 12 | How much louder the downbeat is than a plain beat (0 = off) |
| `intensity` | 1.0 | Velocity multiplier for the whole section (Intro < Verse < Chorus) |
| `final_lengthening` | 1.5 | How much the last note of a phrase is stretched (1.0 = off) |
| `auto_cadence` | true | Give each phrase an open or closed ending |
| `cadence_beats` | 1 | How many beats at a phrase end are reshaped |
| `drum_fills` | true | Fill into each phrase boundary, crash on the landing |
| `expression` | true | Control changes, pitch bends and playing technique (below) |

What each pass does:

- **Rhythmic motif** — instead of drawing every note length independently (which is
  varied on paper and shapeless in the ear), each section states a one-bar cell built from
  the weighted `rhythm_cell` vocabulary, repeats it, and then plays its *fragmented* form
  — the first half stated twice — through the second half of the section. A note of a beat
  or more starts on a beat, unless syncopation ties it across one.
- **Metric accents** — velocity follows the metre: downbeat strongest, then the secondary
  strong beat (middle of the bar in simple metres of four or more, every third beat in
  compound metres such as 6/8), then plain beats, then off-beat positions.
  `lead_velocity_jitter` stays on top as humanisation.
- **Phrase-final lengthening** — the last note of each phrase is stretched and allowed to
  ring to its full length instead of being clipped for a note that never comes.
- **Cadences** — an antecedent phrase is left open (the melody rises to the strongest
  tendency tone of the scale — the leading tone in major — over the triad of the fifth,
  with the bass on its root and a velocity swell); a consequent closes on the tonic, with
  a descending line, the tonic triad and a taper. Chords held across several beats are
  re-struck once per beat in the bar that closes a phrase.
- **Drums** — a tom/snare fill plays through the last beat of each phrase and a crash
  opens the next one.

The accompaniment also holds a chord for as long as the melody stays inside it, instead of
re-striking it on every beat, and the bass lands on the strong beats while holding some
notes across two.

### Expression: controllers, bends and technique

With `expression` on (the default) the engine writes performance data, not just notes:

- **Ambience sends** — one CC 91 (reverb) and CC 93 (chorus) per instrument, from the
  per-role table in the `expression` config block.
- **Phrase dynamics** — a CC 11 ramp across each phrase: a swell into an open ending, a
  decay into a closed one. Unlike velocity, this also shapes notes that are still ringing.
- **Pitch bends** — the closing note of an open phrase is approached from below, and a
  note a step from its predecessor landing on a strong beat is slid into. Every gesture
  returns the wheel to centre; a bend left hanging would detune the rest of the channel.
  Because pitch bend is per channel, only the monophonic roles (lead, bass) are bent.
- **Vibrato** — notes held longer than `vibrato_beats` get CC 1, which is smoother than a
  stepped bend ramp and costs one event instead of a dozen.
- **Power chords** — an accompaniment whose program is in `power_chord_programs`
  (`Overdriven Guitar`, `Distortion Guitar`, `Guitar Harmonics`) is voiced root-and-fifth
  and its cadence chords drop the third: distortion plus a major third is mud.
- **Palm mutes** — on those same distorted parts, strikes off the strong beats are choked
  to a short gate, which is the chug under a riff.
- **Off by default:** `fret_noise` (a soft `Guitar Fret Noise` layer before each phrase)
  and `portamento` (CC 5/65 around stepwise legato pairs, which would otherwise slur twice
  over the pitch-bend slides).

```python
piece.expression = False        # notes only, no controllers or bends
```

**Keyswitches.** For a sampled library (Ample, Shreddage, MODO Bass, Trilian) rather than a
GM synth, articulations are chosen with notes below the playing range. Fill in
`keyswitches` in the config — `{"Electric Bass": {"muted": 24, "sustain": 26, "normal": 25}}`
— and the engine emits one whenever the articulation changes (muted, sustained or ordinary,
read from the gate and length the shaping passes produced). It is empty by default, so
nothing is written unless a library is actually being targeted.

### Articulation parameters

Every articulation parameter can be set on `PieceSpec` (piece-wide) and overridden individually on any `SectionSpec`:

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

**Beats and time signatures.** A pattern's beat numbers are counted in the time
signature's denominator unit — quarter notes by default, eighth notes with
`denominator=8`, and so on — so a pattern always lands on the grid of the signature it
is played in:

```python
adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines["Rock"], tempo=120, denominator=8)
```

Each genre also declares the bar length it was written for, in `drum_pattern_beats`
(4 beats for every genre except `Waltz`, which is 3). Because that authored length need
not match the bar in use, `fit_drum_line_to_bar` adapts the pattern to exactly one bar
of a given signature — repeating it when the bar is longer, cutting it at the bar line
when it is shorter — so the drums never overrun into the next bar nor leave a silent
tail. This is what `render_section` calls, so any section signature works:

```python
bar = ma_utils.fit_drum_line_to_bar(
    ma_utils.drum_lines["Rock"], tempo=120, time_signature=(6, 8),
    beats_per_pattern=ma_utils.pattern_beats("Rock"),
)   # a 4-beat pattern repeated to cover all six eighths of the bar
```

### Phrase transformers: `tension` and `release`

The transformers above rewrite pitches note by note. A **phrase transformer** instead
receives the whole rendered section in musical time — its phrases, its per-role events and
its drum track — so it can shape a cadence across every instrument at once. Two are built
in, and they are what "build tension here, release it there" means in practice:

```python
piece.structure = [
    "Verse",
    MusicAnvil.StructureEntry(section="Verse", transformer="tension"),   # leave it hanging
    MusicAnvil.StructureEntry(section="Chorus", transformer="release",   # and resolve
                              transformer_kwargs={"bars": 2}),
]
```

`tension` ends the passage on an unstable degree above the line, over the triad of the
fifth, with the bass on its root and velocities swelling; `release` descends to the tonic
over the tonic triad with a taper. Both hold the closing note. `bars` (default 1) sets how
much of the ending is reshaped. Because the approach notes are re-ordered rather than
invented, the result can never leave the scale.

Every transformer declares its kind and its parameters in `ma_utils.TRANSFORMER_SPECS`, so
the GUI builds the right controls for it automatically:

```python
ma_utils.transformer_kind("release")     # "phrase"
ma_utils.transformer_params("tone_shift")  # [{"name": "n", "type": "int", ...}]

ma_utils.register_transformer("my_ending", my_fn,
                              kind=ma_utils.TRANSFORMER_PHRASE,
                              params=[{"name": "bars", "label": "Bars", "type": "int",
                                       "default": 1, "min": 1, "max": 8}])
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

**All 128 General MIDI programs are selectable**, under their standard names
(`Acoustic Grand Piano`, `Overdriven Guitar`, `Distortion Guitar`, `Slap Bass 1`,
`Fretless Bass`, `Church Organ`, …).

The list opens with the curated short names from `instrument_programs` in the
configuration, which is what the GUI offers first:

`Piano`, `Organ`, `Guitar`, `Electric Guitar`, `Bass`, `Electric Bass`, `Violin`,
`Strings`, `Trumpet`, `Sax`, `Flute`.

Each of those is an alias for a GM program (`Bass` = GM 32 Acoustic Bass, `Electric Bass`
= GM 33 Electric Bass (finger)), and the rest of the General MIDI set is merged in after
them by `MusicAnvil.INSTRUMENT_PROGRAMS`. Add or rename an entry in the config to change
what a short name means, or to introduce a new one — a curated name always wins over the
GM name for the same program.

#### Guitar and bass timbres

A MIDI file carries instructions, not audio, so distortion is a property of the *sound*
selected, not something stored in the file. General MIDI already provides the distorted
timbres — `Overdriven Guitar` (29), `Distortion Guitar` (30), `Guitar Harmonics` (31),
`Guitar Fret Noise` (120) — and for bass `Electric Bass (pick)` (34), `Fretless Bass`
(35), `Slap Bass 1/2` (36/37) and the synth basses (38/39); selecting one is all it takes.

Beyond the choice of program, a GM-compliant player also responds to control changes:
CC 91 reverb send, CC 93 chorus send, CC 1 modulation, CC 11 expression, CC 7 volume,
CC 10 pan, CC 64 sustain (GM2/GS/XG add CC 92 tremolo and CC 95 phaser). There is **no**
standard controller for "distortion amount" — that lives in the preset. MusicAnvil emits the useful ones itself — see
[Expression](#expression-controllers-bends-and-technique) — carried by `pretty_midi`
through `Instrument.control_changes` and `Instrument.pitch_bends`.

For a real amp/cabinet character, palm mutes or slides with finger noise, play the
generated `.mid` through a sampled library or amp simulator (SF2/SFZ soundfont, or a VST),
or render a clean guitar patch and apply a distortion plugin afterwards.

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

Run the test suite (606 tests):

```
.venv\Scripts\python -m pytest tests/ -v
```

Tests cover the composition engine (`test_composer.py`), the musical-time layer (`test_musical_time.py`), the utility library (`test_ma_utils.py`), GUI imports, structure operations and project files (`test_gui.py`), the pinned environment (`test_dependencies.py`), and the repository layout and packaging metadata (`test_packaging.py`). The same suite plus `pip-audit` runs in CI on every push and pull request.

---

## Disclaimer

MusicAnvil generates music randomly based on configuration parameters provided by the user (scale, rhythm, tempo, instruments). The output is non-deterministic and the software has no mechanism to check whether any generated sequence resembles existing copyrighted material. **The authors of MusicAnvil accept no responsibility for any copyright infringement that may arise from the use, distribution, or publication of MIDI files produced by this software.** Users are solely responsible for verifying that any generated content complies with applicable copyright law before using it publicly or commercially.

## License

MusicAnvil is released under the **GNU General Public License v3.0 (GPL-3.0)**.

The sole runtime dependency, [`pretty_midi`](https://github.com/craffel/pretty-midi), is distributed under the **MIT License**, which is fully compatible with GPL-3.0. MIT is a permissive license that imposes no restrictions that conflict with the GPL, so MusicAnvil can be distributed as a GPL-3.0 work without issue.
