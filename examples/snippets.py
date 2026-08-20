"""Standalone pretty_midi snippet — how to define a simple drum line by hand.

Not part of the ``musicanvil`` package: it uses pretty_midi directly, with no
MusicAnvil import, and exists purely as a worked example. Running it writes
``drum_pattern.mid`` next to this file.

    python examples/snippets.py
"""

import os

import pretty_midi

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drum_pattern.mid")


def build_drum_pattern():
    """Return a PrettyMIDI object holding a single three-hit drum bar."""
    midi_data = pretty_midi.PrettyMIDI()

    # Create a drum instrument (is_drum=True puts it on MIDI channel 10)
    drum_instrument = pretty_midi.Instrument(program=0, is_drum=True)

    # MIDI note numbers for drums
    bass_drum = 35  # Acoustic Bass Drum
    snare_drum = 38  # Acoustic Snare
    closed_hi_hat = 42  # Closed Hi-Hat

    # Add the drum hits to the instrument (times are in seconds)
    drum_instrument.notes.append(pretty_midi.Note(velocity=100, pitch=bass_drum, start=0, end=1))
    drum_instrument.notes.append(pretty_midi.Note(velocity=100, pitch=snare_drum, start=0, end=1))
    drum_instrument.notes.append(pretty_midi.Note(velocity=80, pitch=closed_hi_hat, start=0, end=0.5))

    midi_data.instruments.append(drum_instrument)
    return midi_data


if __name__ == "__main__":
    build_drum_pattern().write(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")
