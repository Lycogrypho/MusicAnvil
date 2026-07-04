import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

try:
    from musicanvil import MusicAnvil, ma_utils
except ImportError:  # script-directory launch
    import MusicAnvil
    import ma_utils


# OopCompanion:suppressRename

MELODIC_INSTRUMENTS = list(MusicAnvil.INSTRUMENT_PROGRAMS.keys())
NONE_CHOICE = "(none)"
SIGNATURE_OPTIONS = ["4/4", "2/2", "2/4", "3/4", "6/8"]
OCTAVE_OPTIONS = ["2", "3", "4", "5", "6"]
TRANSFORMER_OPTIONS = [NONE_CHOICE] + sorted(ma_utils.BEAT_TRANSFORMERS)


def _entry_label(entry):
    """Format a StructureEntry (or plain section name string) for the structure listbox."""
    if isinstance(entry, str):
        return entry
    if entry.transformer is None:
        return entry.section
    if entry.transformer == "tone_shift":
        n = entry.transformer_kwargs.get("n", 0)
        return f"{entry.section} [{n:+d}]"
    return f"{entry.section} [{entry.transformer}]"


def fmt_mmss(seconds):
    """Format a duration in seconds as MM:SS."""
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


class RoleEditor:
    """Main + supports pickers for the three melodic roles, one column per role."""

    def __init__(self, parent, defaults=None):
        defaults = defaults or {}
        self.main_vars: dict[str, tk.StringVar] = {}
        self.support_boxes: dict[str, tk.Listbox] = {}
        for column, role in enumerate(MusicAnvil.ROLES):
            frame = tk.LabelFrame(parent, text=role)
            frame.grid(row=0, column=column, padx=5, pady=5, sticky="n")
            tk.Label(frame, text="Main:").grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value=defaults.get(role, NONE_CHOICE))
            if role == MusicAnvil.ROLE_LEAD:
                values = MELODIC_INSTRUMENTS
            else:
                values = [NONE_CHOICE] + MELODIC_INSTRUMENTS
            ttk.Combobox(frame, textvariable=var, values=values,
                         state="readonly", width=12).grid(row=0, column=1, padx=2, pady=2)
            tk.Label(frame, text="Supports:").grid(row=1, column=0, sticky="nw")
            box = tk.Listbox(frame, selectmode=tk.MULTIPLE, height=5, width=14, exportselection=False)
            for instrument in MELODIC_INSTRUMENTS:
                box.insert(tk.END, instrument)
            box.grid(row=1, column=1, padx=2, pady=2)
            self.main_vars[role] = var
            self.support_boxes[role] = box

    def get_roles(self):
        roles = {}
        for role in MusicAnvil.ROLES:
            main = self.main_vars[role].get()
            main = None if main in ("", NONE_CHOICE) else main
            supports: list[str] = [MELODIC_INSTRUMENTS[i] for i in self.support_boxes[role].curselection()]
            supports = [s for s in supports if s != main]
            roles[role] = MusicAnvil.RoleAssignment(main=main, supports=supports)
        return roles

    def set_roles(self, roles):
        for role in MusicAnvil.ROLES:
            assignment = roles.get(role) or MusicAnvil.RoleAssignment()
            self.main_vars[role].set(assignment.main or NONE_CHOICE)
            box = self.support_boxes[role]
            box.selection_clear(0, tk.END)
            for i, instrument in enumerate(MELODIC_INSTRUMENTS):
                if instrument in assignment.supports:
                    box.selection_set(i)


class MusicGeneratorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MusicAnvil — Piece Builder")

        self.sections = {}   # name -> MusicAnvil.SectionSpec
        self.structure = []  # ordered section names

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)
        self.piece_tab = tk.Frame(notebook)
        self.sections_tab = tk.Frame(notebook)
        notebook.add(self.piece_tab, text="Piece")
        notebook.add(self.sections_tab, text="Sections")

        self._build_piece_tab()
        self._build_sections_tab()

    # ------------------------------------------------------------- Piece tab

    def _build_piece_tab(self):
        defaults = tk.LabelFrame(self.piece_tab, text="Piece Defaults")
        defaults.grid(row=0, column=0, padx=10, pady=10, sticky="nw")

        tk.Label(defaults, text="Tempo (BPM):").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.tempo_var = tk.StringVar(value="120")
        tk.Entry(defaults, textvariable=self.tempo_var, width=8).grid(row=0, column=1, padx=5, pady=3)

        tk.Label(defaults, text="Signature:").grid(row=1, column=0, sticky="w", padx=5, pady=3)
        self.signature_var = tk.StringVar(value="4/4")
        ttk.Combobox(defaults, textvariable=self.signature_var, values=SIGNATURE_OPTIONS,
                     state="readonly", width=6).grid(row=1, column=1, padx=5, pady=3)

        tk.Label(defaults, text="Genre (drums):").grid(row=2, column=0, sticky="w", padx=5, pady=3)
        self.rhythm_var = tk.StringVar(value=list(ma_utils.drum_lines.keys())[0])
        ttk.Combobox(defaults, textvariable=self.rhythm_var, values=list(ma_utils.drum_lines.keys()),
                     state="readonly", width=14).grid(row=2, column=1, padx=5, pady=3)

        tk.Label(defaults, text="Scale:").grid(row=3, column=0, sticky="w", padx=5, pady=3)
        self.scale_var = tk.StringVar(value=list(ma_utils.scale_definitions.keys())[0])
        ttk.Combobox(defaults, textvariable=self.scale_var, values=list(ma_utils.scale_definitions.keys()),
                     state="readonly", width=14).grid(row=3, column=1, padx=5, pady=3)

        tk.Label(defaults, text="Tonic Note:").grid(row=4, column=0, sticky="w", padx=5, pady=3)
        tonic_frame = tk.Frame(defaults)
        tonic_frame.grid(row=4, column=1, padx=5, pady=3, sticky="w")
        self.tonic_var = tk.StringVar(value=ma_utils.notes_in_octave[0])
        ttk.Combobox(tonic_frame, textvariable=self.tonic_var, values=ma_utils.notes_in_octave,
                     state="readonly", width=4).pack(side="left")
        self.tonic_octave_var = tk.StringVar(value="4")
        ttk.Combobox(tonic_frame, textvariable=self.tonic_octave_var, values=OCTAVE_OPTIONS,
                     state="readonly", width=3).pack(side="left", padx=(4, 0))

        tk.Label(defaults, text="FileName:").grid(row=5, column=0, sticky="w", padx=5, pady=3)
        self.filename_var = tk.StringVar(value="output")
        tk.Entry(defaults, textvariable=self.filename_var, width=16).grid(row=5, column=1, padx=5, pady=3)

        roles_frame = tk.LabelFrame(self.piece_tab, text="Default Roles")
        roles_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nw")
        self.piece_roles = RoleEditor(roles_frame, defaults={
            MusicAnvil.ROLE_LEAD: "Piano",
            MusicAnvil.ROLE_ACCOMPANIMENT: "Guitar",
            MusicAnvil.ROLE_BASS: "Bass",
        })

        structure = tk.LabelFrame(self.piece_tab, text="Piece Structure")
        structure.grid(row=0, column=1, rowspan=2, padx=10, pady=10, sticky="n")

        self.structure_listbox = tk.Listbox(structure, height=14, width=26, exportselection=False)
        self.structure_listbox.grid(row=0, column=0, columnspan=3, padx=5, pady=5)

        self.add_section_var = tk.StringVar()
        self.add_section_combo = ttk.Combobox(structure, textvariable=self.add_section_var,
                                              values=[], state="readonly", width=16)
        self.add_section_combo.grid(row=1, column=0, columnspan=2, padx=5, pady=3)
        tk.Button(structure, text="Add", command=self._add_to_structure).grid(row=1, column=2, padx=5, pady=3)

        # Transformer row
        transform_frame = tk.Frame(structure)
        transform_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=2, sticky="w")
        tk.Label(transform_frame, text="Transformer:").grid(row=0, column=0, sticky="w")
        self.transform_var = tk.StringVar(value=NONE_CHOICE)
        ttk.Combobox(transform_frame, textvariable=self.transform_var,
                     values=TRANSFORMER_OPTIONS, state="readonly", width=11).grid(row=0, column=1, padx=(3, 8))
        tk.Label(transform_frame, text="Shift n:").grid(row=0, column=2, sticky="w")
        self.shift_var = tk.StringVar(value="0")
        self.shift_spinbox = tk.Spinbox(transform_frame, from_=-127, to=127,
                                        textvariable=self.shift_var, width=4, state="disabled")
        self.shift_spinbox.grid(row=0, column=3, padx=(3, 0))
        self.transform_var.trace_add("write", self._on_transform_changed)

        tk.Button(structure, text="Remove", command=self._remove_from_structure).grid(row=3, column=0, padx=5, pady=3)
        tk.Button(structure, text="Move Up", command=lambda: self._move_in_structure(-1)).grid(row=3, column=1, padx=5, pady=3)
        tk.Button(structure, text="Move Down", command=lambda: self._move_in_structure(1)).grid(row=3, column=2, padx=5, pady=3)

        self.total_label = tk.Label(structure, text="Total duration: 00:00")
        self.total_label.grid(row=4, column=0, columnspan=3, pady=5)

        tk.Button(structure, text="Generate", command=self._generate).grid(row=5, column=0, columnspan=3, pady=10)

    def _on_transform_changed(self, *_):
        state = "normal" if self.transform_var.get() == "tone_shift" else "disabled"
        self.shift_spinbox.config(state=state)

    def _add_to_structure(self):
        name = self.add_section_var.get()
        if not name:
            messagebox.showerror("Error", "Create a section in the Sections tab first, then pick it here.")
            return
        transformer = self.transform_var.get()
        transformer = None if transformer == NONE_CHOICE else transformer
        kwargs = {}
        if transformer == "tone_shift":
            try:
                kwargs["n"] = int(self.shift_var.get())
            except ValueError:
                messagebox.showerror("Error", "Shift n must be a whole number.")
                return
        entry = MusicAnvil.StructureEntry(section=name, transformer=transformer, transformer_kwargs=kwargs)
        self.structure.append(entry)
        self.structure_listbox.insert(tk.END, _entry_label(entry))
        self._update_total()

    def _remove_from_structure(self):
        selection = self.structure_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.structure_listbox.delete(index)
        del self.structure[index]
        self._update_total()

    def _move_in_structure(self, delta):
        selection = self.structure_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        target = index + delta
        if not (0 <= target < len(self.structure)):
            return
        self.structure[index], self.structure[target] = self.structure[target], self.structure[index]
        self.structure_listbox.delete(index)
        self.structure_listbox.insert(target, _entry_label(self.structure[target]))
        self.structure_listbox.selection_set(target)
        self._update_total()

    def _update_total(self):
        try:
            piece = self._current_piece_spec()
            total = MusicAnvil.piece_seconds(piece) if piece.structure else 0.0
            self.total_label.config(text=f"Total duration: {fmt_mmss(total)}")
        except Exception:
            self.total_label.config(text="Total duration: --:--")

    # ---------------------------------------------------------- Sections tab

    def _build_sections_tab(self):
        library = tk.LabelFrame(self.sections_tab, text="Section Library")
        library.grid(row=0, column=0, padx=10, pady=10, sticky="n")

        self.library_listbox = tk.Listbox(library, height=14, width=20, exportselection=False)
        self.library_listbox.grid(row=0, column=0, columnspan=2, padx=5, pady=5)
        self.library_listbox.bind("<<ListboxSelect>>", self._load_section)

        tk.Button(library, text="New Section", command=self._new_section).grid(row=1, column=0, padx=5, pady=3)
        tk.Button(library, text="Delete", command=self._delete_section).grid(row=1, column=1, padx=5, pady=3)

        editor = tk.LabelFrame(self.sections_tab, text="Section Editor")
        editor.grid(row=0, column=1, padx=10, pady=10, sticky="n")

        tk.Label(editor, text="Bars:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.bars_var = tk.StringVar(value="4")
        tk.Spinbox(editor, from_=1, to=128, textvariable=self.bars_var, width=6).grid(row=0, column=1, sticky="w", padx=5, pady=3)

        # Override rows: checkbox enables the field, otherwise the piece default is used.
        self.sec_override = {}

        def override_row(row, key, label, widget_values, width):
            check_var = tk.BooleanVar(value=False)
            tk.Checkbutton(editor, text=label, variable=check_var).grid(row=row, column=0, sticky="w", padx=5, pady=3)
            value_var = tk.StringVar()
            if widget_values is None:
                tk.Entry(editor, textvariable=value_var, width=width).grid(row=row, column=1, sticky="w", padx=5, pady=3)
            else:
                ttk.Combobox(editor, textvariable=value_var, values=widget_values,
                             state="readonly", width=width).grid(row=row, column=1, sticky="w", padx=5, pady=3)
            self.sec_override[key] = (check_var, value_var)

        override_row(1, "tempo", "Override Tempo (BPM)", None, 8)
        override_row(2, "signature", "Override Signature", SIGNATURE_OPTIONS, 6)
        override_row(3, "rhythm", "Override Genre (drums)", list(ma_utils.drum_lines.keys()), 14)
        override_row(4, "scale", "Override Scale", list(ma_utils.scale_definitions.keys()), 14)
        override_row(5, "tonic", "Override Tonic Note", ma_utils.notes_in_octave, 6)
        override_row(6, "tonic_octave", "Override Tonic Octave", OCTAVE_OPTIONS, 4)

        self.sec_roles_override_var = tk.BooleanVar(value=False)
        tk.Checkbutton(editor, text="Override Roles", variable=self.sec_roles_override_var).grid(
            row=7, column=0, sticky="w", padx=5, pady=3)
        roles_holder = tk.Frame(editor)
        roles_holder.grid(row=8, column=0, columnspan=2, padx=5, pady=3)
        self.sec_roles = RoleEditor(roles_holder)

        self.sec_duration_label = tk.Label(editor, text="Duration: --:--")
        self.sec_duration_label.grid(row=9, column=0, columnspan=2, pady=5)

        tk.Button(editor, text="Apply", command=self._apply_section).grid(row=10, column=0, columnspan=2, pady=10)

    def _selected_library_name(self) -> str | None:
        selection = self.library_listbox.curselection()
        if not selection:
            return None
        return self.library_listbox.get(selection[0])

    def _new_section(self):
        name = simpledialog.askstring("New Section", "Section name (e.g. intro, verse A, chorus):",
                                      parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.sections:
            messagebox.showerror("Error", f"A section named '{name}' already exists.")
            return
        self.sections[name] = MusicAnvil.SectionSpec(name=name)
        self.library_listbox.insert(tk.END, name)
        self._refresh_section_choices()

    def _delete_section(self):
        name = self._selected_library_name()
        if name is None:
            return
        if not messagebox.askyesno("Delete Section", f"Delete section '{name}'? "
                                   "It will also be removed from the piece structure."):
            return
        selection = self.library_listbox.curselection()
        self.library_listbox.delete(selection[0])
        del self.sections[name]
        # Remove every occurrence from the structure (walk backwards to keep indices valid).
        for index in range(len(self.structure) - 1, -1, -1):
            if self.structure[index] == name:
                del self.structure[index]
                self.structure_listbox.delete(index)
        self._refresh_section_choices()
        self._update_total()

    def _load_section(self, _event=None):
        name = self._selected_library_name()
        if name is None:
            return
        spec = self.sections[name]
        self.bars_var.set(str(spec.bars))
        loaders = {
            "tempo": None if spec.tempo is None else str(spec.tempo),
            "signature": None if spec.signature is None else f"{spec.signature[0]}/{spec.signature[1]}",
            "rhythm": spec.rhythm,
            "scale": spec.scale,
            "tonic": spec.tonic,
            "tonic_octave": None if spec.tonic_octave is None else str(spec.tonic_octave),
        }
        for key, value in loaders.items():
            check_var, value_var = self.sec_override[key]
            check_var.set(value is not None)
            value_var.set(value if value is not None else "")
        self.sec_roles_override_var.set(bool(spec.roles))
        self.sec_roles.set_roles(spec.roles if spec.roles else {})
        self._update_section_duration(spec)

    def _apply_section(self):
        name = self._selected_library_name()
        if name is None:
            messagebox.showerror("Error", "Select a section in the library first.")
            return
        try:
            spec = MusicAnvil.SectionSpec(name=str(name), bars=int(self.bars_var.get()))
            if spec.bars <= 0:
                raise ValueError("Bars must be a positive number.")
            check_var, value_var = self.sec_override["tempo"]
            if check_var.get():
                spec.tempo = int(value_var.get())
                if spec.tempo <= 0:
                    raise ValueError("Tempo must be a positive number.")
            check_var, value_var = self.sec_override["signature"]
            if check_var.get():
                spec.signature = MusicAnvil.parse_signature(value_var.get())
            for key in ("rhythm", "scale", "tonic"):
                check_var, value_var = self.sec_override[key]
                if check_var.get():
                    value = value_var.get()
                    if not value:
                        raise ValueError(f"Pick a value for the overridden {key}.")
                    setattr(spec, key, value)
            check_var, value_var = self.sec_override["tonic_octave"]
            if check_var.get():
                spec.tonic_octave = int(value_var.get())
            if self.sec_roles_override_var.get():
                spec.roles = self.sec_roles.get_roles()
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.sections[name] = spec
        self._update_section_duration(spec)
        self._refresh_section_choices()
        self._update_total()

    def _update_section_duration(self, spec):
        try:
            piece = self._current_piece_spec()
            resolved = MusicAnvil.resolve_section(spec, piece)
            seconds = MusicAnvil.section_seconds(resolved.bars, resolved.tempo, resolved.signature)
            self.sec_duration_label.config(text=f"Duration: {fmt_mmss(seconds)}")
        except Exception:
            self.sec_duration_label.config(text="Duration: --:--")

    def _refresh_section_choices(self):
        self.add_section_combo.config(values=list(self.sections.keys()))

    # ------------------------------------------------------------ Generation

    def _current_piece_spec(self):
        tempo = int(self.tempo_var.get())
        if tempo <= 0:
            raise ValueError("Tempo must be a positive number.")
        piece = MusicAnvil.PieceSpec(
            tempo=tempo,
            signature=MusicAnvil.parse_signature(self.signature_var.get()),
            rhythm=self.rhythm_var.get(),
            scale=self.scale_var.get(),
            tonic=self.tonic_var.get(),
            tonic_octave=int(self.tonic_octave_var.get()),
            roles=self.piece_roles.get_roles(),
            sections=dict(self.sections),
            structure=list(self.structure),
        )
        if piece.roles[MusicAnvil.ROLE_LEAD].main is None:
            raise ValueError("A main Lead instrument is required.")
        return piece

    def _generate(self):
        try:
            piece = self._current_piece_spec()
            if not piece.structure:
                raise ValueError("The piece structure is empty — add at least one section.")
            filename = self.filename_var.get().strip() or "output"
            if not filename.endswith(".mid"):
                filename += ".mid"
            midi_data = MusicAnvil.render_piece(piece)
            midi_data.write(filename)
            total = MusicAnvil.piece_seconds(piece)
            messagebox.showinfo("Done", f"MIDI saved to {filename} ({fmt_mmss(total)})")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = MusicGeneratorApp(root)
    root.mainloop()
