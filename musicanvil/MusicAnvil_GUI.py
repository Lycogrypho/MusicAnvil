import tkinter as tk
from tkinter import messagebox, ttk

import pretty_midi

from musicanvil import ma_utils

_INSTRUMENT_PROGRAMS = {
    "Piano":  0,   # Acoustic Grand Piano
    "Guitar": 25,  # Acoustic Guitar (steel)
    "Bass":   32,  # Acoustic Bass
    "Violin": 40,  # Violin
}

instruments = list(_INSTRUMENT_PROGRAMS.keys()) + ["Drums"]


class MusicGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Music Generator")

        # Tempo
        tk.Label(root, text="Tempo:").grid(row=0, column=0, padx=10, pady=10)
        self.tempo_var = tk.IntVar(value=120)
        tk.Entry(root, textvariable=self.tempo_var).grid(row=0, column=1, padx=10, pady=10)

        # Signature
        tk.Label(root, text="Signature:").grid(row=1, column=0, padx=10, pady=10)
        self.signature_var = tk.StringVar(value="4/4")
        signature_options = ["4/4", "2/2", "2/4", "3/4", "6/8"]
        ttk.Combobox(root, textvariable=self.signature_var, values=signature_options).grid(row=1, column=1, padx=10, pady=10)

        # Rhythm
        tk.Label(root, text="Rhythm:").grid(row=2, column=0, padx=10, pady=10)
        self.rhythm_var = tk.StringVar(value=list(ma_utils.drum_lines.keys())[0])
        ttk.Combobox(root, textvariable=self.rhythm_var, values=list(ma_utils.drum_lines.keys())).grid(row=2, column=1, padx=10, pady=10)

        # Scale
        tk.Label(root, text="Scale:").grid(row=3, column=0, padx=10, pady=10)
        self.scale_var = tk.StringVar(value=list(ma_utils.scale_definitions.keys())[0])
        ttk.Combobox(root, textvariable=self.scale_var, values=list(ma_utils.scale_definitions.keys())).grid(row=3, column=1, padx=10, pady=10)

        # Tonic Note
        tk.Label(root, text="Tonic Note:").grid(row=4, column=0, padx=10, pady=10)
        self.tonic_var = tk.StringVar(value=ma_utils.notes_in_octave[0])
        ttk.Combobox(root, textvariable=self.tonic_var, values=ma_utils.notes_in_octave).grid(row=4, column=1, padx=10, pady=10)

        # Instruments
        tk.Label(root, text="Instruments:").grid(row=5, column=0, padx=10, pady=10)
        self.instruments_listbox = tk.Listbox(root, selectmode=tk.MULTIPLE, exportselection=False)
        for instrument in instruments:
            self.instruments_listbox.insert(tk.END, instrument)
        self.instruments_listbox.grid(row=5, column=1, padx=10, pady=10)

        # Lead Instrument
        tk.Label(root, text="Lead Instrument:").grid(row=6, column=0, padx=10, pady=10)
        self.lead_instrument_var = tk.StringVar(value=instruments[0])
        ttk.Combobox(root, textvariable=self.lead_instrument_var, values=instruments).grid(row=6, column=1, padx=10, pady=10)

        # FileName
        tk.Label(root, text="FileName:").grid(row=7, column=0, padx=10, pady=10)
        self.filename_var = tk.StringVar(value="output")
        tk.Entry(root, textvariable=self.filename_var).grid(row=7, column=1, padx=10, pady=10)

        # Duration
        tk.Label(root, text="Duration (MM:SS):").grid(row=8, column=0, padx=10, pady=10)
        self.duration_var = tk.StringVar(value="00:30")
        tk.Entry(root, textvariable=self.duration_var).grid(row=8, column=1, padx=10, pady=10)

        # Generate button
        tk.Button(root, text="Generate", command=self._generate).grid(
            row=9, column=0, columnspan=2, pady=20
        )

    def _parse_duration(self):
        """Parse MM:SS string → total seconds (int)."""
        raw = self.duration_var.get().strip()
        parts = raw.split(":")
        if len(parts) != 2:
            raise ValueError(f"Duration must be MM:SS, got '{raw}'")
        return int(parts[0]) * 60 + int(parts[1])

    def _parse_signature(self):
        """Parse 'N/D' string → (numerator, denominator) tuple."""
        raw = self.signature_var.get().strip()
        parts = raw.split("/")
        if len(parts) != 2:
            raise ValueError(f"Signature must be N/D, got '{raw}'")
        return int(parts[0]), int(parts[1])

    def _generate(self):
        try:
            tempo = self.tempo_var.get()
            if tempo <= 0:
                raise ValueError("Tempo must be a positive number.")
            time_signature = self._parse_signature()
            beat_duration = self._parse_duration()
            if beat_duration <= 0:
                raise ValueError("Duration must be greater than 00:00.")
            scale = self.scale_var.get()
            tonic = self.tonic_var.get()
            rhythm = self.rhythm_var.get()
            filename = self.filename_var.get().strip() or "output"
            if not filename.endswith(".mid"):
                filename += ".mid"

            # Build available MIDI pitches from the chosen scale
            note_names = ma_utils.generate_scale(scale, tonic)
            available_pitches = [pretty_midi.note_name_to_number(n) for n in note_names]

            midi_data = pretty_midi.PrettyMIDI(initial_tempo=tempo)

            selected_indices = self.instruments_listbox.curselection()
            selected_instruments = [instruments[i] for i in selected_indices] or [instruments[0]]

            for name in selected_instruments:
                if name == "Drums":
                    drum_inst = pretty_midi.Instrument(program=0, is_drum=True, name="Drums")
                    adapted = ma_utils.adapt_drum_line(ma_utils.drum_lines[rhythm], tempo)
                    # Pattern length = end time of the last entry in one repetition
                    pattern_len = max(entry[3] for entry in adapted)
                    t = 0.0
                    while t < beat_duration:
                        for velocity, pitch, start, end in adapted:
                            note_start = t + start
                            note_end = t + end
                            if note_start >= beat_duration:
                                continue
                            drum_inst.notes.append(pretty_midi.Note(
                                velocity=velocity,
                                pitch=pitch,
                                start=note_start,
                                end=min(note_end, beat_duration),
                            ))
                        t += pattern_len
                    midi_data.instruments.append(drum_inst)
                else:
                    program = _INSTRUMENT_PROGRAMS[name]
                    inst = pretty_midi.Instrument(program=program, name=name)
                    for note in ma_utils.generate_random_beat(available_pitches, tempo, time_signature, beat_duration):
                        inst.notes.append(note)
                    midi_data.instruments.append(inst)

            midi_data.write(filename)
            messagebox.showinfo("Done", f"MIDI saved to {filename}")

        except Exception as exc:
            messagebox.showerror("Error", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = MusicGeneratorApp(root)
    root.mainloop()
