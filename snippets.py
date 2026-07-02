#how to define a simple drum line

import pretty_midi

# Create a PrettyMIDI object
midi_data = pretty_midi.PrettyMIDI()

# Create a drum instrument (using channel 10)
drum_instrument = pretty_midi.Instrument(program=0, is_drum=True)  # is_drum=True indicates a drum instrument

# Define the notes for the drum pattern
# MIDI note numbers for drums
bass_drum = 35  # Acoustic Bass Drum
snare_drum = 38  # Acoustic Snare
closed_hi_hat = 42  # Closed Hi-Hat

# Add the drum hits to the instrument
# Note On at time 0, Note Off at time 480 (1 second duration)
drum_instrument.notes.append(pretty_midi.Note(velocity=100, pitch=bass_drum, start=0, end=1))
drum_instrument.notes.append(pretty_midi.Note(velocity=100, pitch=snare_drum, start=0, end=1))
drum_instrument.notes.append(pretty_midi.Note(velocity=80, pitch=closed_hi_hat, start=0, end=0.5))

# Add the drum instrument to the PrettyMIDI object
midi_data.instruments.append(drum_instrument)

# Write the MIDI data to a file
midi_data.write('drum_pattern.mid')