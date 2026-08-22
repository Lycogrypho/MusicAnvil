import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

try:
    from musicanvil import MusicAnvil, ma_utils
except ImportError:  # script-directory launch
    import MusicAnvil
    import ma_utils


# OopCompanion:suppressRename

# GUI presets and defaults come from the external MusicAnvil.json (see ma_utils.load_config).
_CFG = ma_utils.load_config()
_GUI = _CFG["gui"]
_PIECE_DEFAULTS = _CFG["piece_defaults"]

MELODIC_INSTRUMENTS = list(MusicAnvil.INSTRUMENT_PROGRAMS.keys())
NONE_CHOICE = "(none)"
SIGNATURE_OPTIONS = _GUI["signature_options"]
OCTAVE_OPTIONS = _GUI["octave_options"]
TRANSFORMER_OPTIONS = [NONE_CHOICE] + sorted(ma_utils.BEAT_TRANSFORMERS)
BEAT_MODE_OPTIONS = list(ma_utils.BEAT_MODES.keys())
DRUM_INSTRUMENTS = list(ma_utils.drum_pitches.keys())
DEFAULT_SECTION_NAMES = _GUI["default_section_names"]

# (key, label, default, is_int) — default values are read from piece_defaults in the config.
ARTIC_PARAMS = [
    ("lead_rest_prob",       "Lead Rest Prob (0–1):",  str(_PIECE_DEFAULTS["lead_rest_prob"]),       False),
    ("lead_sustain",         "Lead Sustain (0–2):",    str(_PIECE_DEFAULTS["lead_sustain"]),         False),
    ("lead_velocity_jitter", "Lead Vel. Jitter:",      str(_PIECE_DEFAULTS["lead_velocity_jitter"]), True),
    ("lead_step_bias",       "Lead Step Bias (0–1):",  str(_PIECE_DEFAULTS["lead_step_bias"]),       False),
    ("bass_gate",            "Bass Gate (0–1):",       str(_PIECE_DEFAULTS["bass_gate"]),            False),
    ("chord_gate",           "Chord Gate (0–1):",      str(_PIECE_DEFAULTS["chord_gate"]),           False),
    ("chord_octave_shift",   "Chord Octave Shift:",    str(_PIECE_DEFAULTS["chord_octave_shift"]),   True),
    # Phrasing and dynamics (ToDo 4.1-4.6)
    ("phrase_bars",          "Phrase Bars (0=auto):",  str(_PIECE_DEFAULTS["phrase_bars"]),          True),
    ("metric_accent",        "Metric Accent:",         str(_PIECE_DEFAULTS["metric_accent"]),        True),
    ("intensity",            "Intensity (0–2):",       str(_PIECE_DEFAULTS["intensity"]),            False),
    ("final_lengthening",    "Final Lengthening:",     str(_PIECE_DEFAULTS["final_lengthening"]),    False),
    ("lead_syncopation",     "Lead Syncopation (0–1):", str(_PIECE_DEFAULTS["lead_syncopation"]),    False),
    ("cadence_beats",        "Cadence Beats:",         str(_PIECE_DEFAULTS["cadence_beats"]),        True),
]

# Piece-level switches (checkboxes rather than entries).
TOGGLE_PARAMS = [
    ("auto_cadence", "Open/closed phrase endings", bool(_PIECE_DEFAULTS["auto_cadence"])),
    ("drum_fills",   "Drum fills at phrase ends",  bool(_PIECE_DEFAULTS["drum_fills"])),
    ("expression",   "Expression (CC swells, bends)", bool(_PIECE_DEFAULTS["expression"])),
]


def _entry_label(entry):
    """'Verse', 'Verse [invert]', 'Verse [+5]', 'Verse [tension bars=1]' — built from the
    transformer's declared parameters, so a new transformer needs no code here."""
    if isinstance(entry, str):
        return entry
    if entry.transformer is None:
        return entry.section
    if entry.transformer == "tone_shift":
        n = entry.transformer_kwargs.get("n", 0)
        return f"{entry.section} [{n:+d}]"
    shown = " ".join(f"{key}={value}" for key, value in entry.transformer_kwargs.items())
    return f"{entry.section} [{entry.transformer}{' ' + shown if shown else ''}]"


def fmt_mmss(seconds):
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


# --------------------------------------------------------------- Project I/O
#
# A project file is JSON capturing the full PieceSpec (piece defaults, roles, the
# whole section library, and the ordered structure) plus the GUI output filename,
# so a saved song can be reopened and edited exactly as it was.

PROJECT_FORMAT = "musicanvil-project"
PROJECT_VERSION = 2

# Scalar (non-signature, non-roles) fields shared by PieceSpec and SectionSpec.
# Version 2 added the phrasing/dynamics fields (ToDo 4.2-4.4). Older project files
# simply lack those keys and fall back to the piece defaults when loaded.
_MUSICAL_FIELDS = (
    "phrase_bars", "metric_accent", "intensity", "final_lengthening", "lead_syncopation",
    "auto_cadence", "cadence_beats", "drum_fills", "expression",
)
_SECTION_SCALAR_FIELDS = (
    "bars", "tempo", "rhythm", "scale", "tonic", "tonic_octave", "beat_mode",
    "drums_enabled", "lead_rest_prob", "lead_sustain", "lead_velocity_jitter",
    "lead_step_bias", "bass_gate", "chord_gate", "chord_octave_shift",
) + _MUSICAL_FIELDS
_PIECE_SCALAR_FIELDS = (
    "tempo", "rhythm", "scale", "tonic", "tonic_octave", "beat_mode",
    "drums_enabled", "lead_rest_prob", "lead_sustain", "lead_velocity_jitter",
    "lead_step_bias", "bass_gate", "chord_gate", "chord_octave_shift",
) + _MUSICAL_FIELDS


def _roles_to_dict(roles):
    return {role: {"main": ra.main, "supports": list(ra.supports)}
            for role, ra in roles.items()}


def _roles_from_dict(data):
    return {role: MusicAnvil.RoleAssignment(main=value.get("main"),
                                            supports=list(value.get("supports") or []))
            for role, value in (data or {}).items()}


def _section_to_dict(spec):
    data = {"name": spec.name}
    for field in _SECTION_SCALAR_FIELDS:
        data[field] = getattr(spec, field)
    data["signature"] = list(spec.signature) if spec.signature is not None else None
    data["roles"] = _roles_to_dict(spec.roles) if spec.roles else {}
    return data


def _section_from_dict(data):
    spec = MusicAnvil.SectionSpec(name=data["name"])
    for field in _SECTION_SCALAR_FIELDS:
        if field in data:
            setattr(spec, field, data[field])
    signature = data.get("signature")
    spec.signature = tuple(signature) if signature is not None else None
    spec.roles = _roles_from_dict(data.get("roles"))
    return spec


def _structure_entry_to_dict(entry):
    if isinstance(entry, str):
        return {"section": entry, "transformer": None, "transformer_kwargs": {}}
    return {"section": entry.section,
            "transformer": entry.transformer,
            "transformer_kwargs": dict(entry.transformer_kwargs)}


def _structure_entry_from_dict(data):
    return MusicAnvil.StructureEntry(
        section=data["section"],
        transformer=data.get("transformer"),
        transformer_kwargs=dict(data.get("transformer_kwargs") or {}),
    )


def piece_to_project_dict(piece, filename=""):
    """Serialise a PieceSpec (+ GUI filename) to a JSON-ready project dict."""
    piece_data = {field: getattr(piece, field) for field in _PIECE_SCALAR_FIELDS}
    piece_data["signature"] = list(piece.signature)
    piece_data["roles"] = _roles_to_dict(piece.roles)
    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "filename": filename,
        "piece": piece_data,
        "sections": [_section_to_dict(s) for s in piece.sections.values()],
        "structure": [_structure_entry_to_dict(e) for e in piece.structure],
    }


def project_dict_to_piece(data):
    """Rebuild a (PieceSpec, filename) pair from a project dict.

    Raises ValueError if the dict is not a recognised MusicAnvil project.
    """
    if not isinstance(data, dict) or data.get("format") != PROJECT_FORMAT:
        raise ValueError("This file is not a MusicAnvil project.")
    piece_data = data.get("piece", {})
    piece = MusicAnvil.PieceSpec()
    for field in _PIECE_SCALAR_FIELDS:
        if field in piece_data:
            setattr(piece, field, piece_data[field])
    signature = piece_data.get("signature")
    if signature is not None:
        piece.signature = tuple(signature)
    piece.roles = _roles_from_dict(piece_data.get("roles"))
    piece.sections = {}
    for section_data in data.get("sections", []):
        spec = _section_from_dict(section_data)
        piece.sections[spec.name] = spec
    piece.structure = [_structure_entry_from_dict(e) for e in data.get("structure", [])]
    return piece, data.get("filename", "")


def _scrolled_listbox(parent, height, width, selectmode=tk.BROWSE, **kwargs):
    """Return (frame, listbox) with a built-in vertical scrollbar."""
    frame = tk.Frame(parent)
    sb = tk.Scrollbar(frame, orient=tk.VERTICAL)
    lb = tk.Listbox(frame, height=height, width=width, selectmode=selectmode,
                    exportselection=False, yscrollcommand=sb.set, **kwargs)
    sb.config(command=lb.yview)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    return frame, lb


class DrumEditor:
    """Rhythm dropdown + drum instrument enable/disable listbox."""

    def __init__(self, parent, on_change=None, list_height=6):
        self._on_change = on_change
        frame = tk.LabelFrame(parent, text="Drums")
        frame.grid(row=0, column=0, padx=5, pady=5, sticky="n")

        tk.Label(frame, text="Rhythm:").grid(row=0, column=0, sticky="w", padx=4, pady=2)
        self.rhythm_var = tk.StringVar(value=list(ma_utils.drum_lines.keys())[0])
        cb = ttk.Combobox(frame, textvariable=self.rhythm_var,
                          values=list(ma_utils.drum_lines.keys()), state="readonly", width=13)
        cb.grid(row=0, column=1, padx=4, pady=2)
        cb.bind("<<ComboboxSelected>>", self._fire)

        tk.Label(frame, text="Active:").grid(row=1, column=0, sticky="nw", padx=4, pady=2)
        lf, self.drum_lb = _scrolled_listbox(frame, height=list_height, width=15, selectmode=tk.MULTIPLE)
        lf.grid(row=1, column=1, padx=4, pady=2)
        for name in DRUM_INSTRUMENTS:
            self.drum_lb.insert(tk.END, name)
        self.drum_lb.selection_set(0, tk.END)
        self.drum_lb.bind("<<ListboxSelect>>", self._fire)

    def _fire(self, *_):
        if self._on_change:
            self._on_change()

    def get_rhythm(self):
        return self.rhythm_var.get()

    def get_drums_enabled(self):
        sel = list(self.drum_lb.curselection())
        if len(sel) == len(DRUM_INSTRUMENTS):
            return None
        return [DRUM_INSTRUMENTS[i] for i in sel]

    def set_rhythm(self, value):
        self.rhythm_var.set(value)

    def set_drums_enabled(self, drums_enabled):
        self.drum_lb.selection_clear(0, tk.END)
        if drums_enabled is None:
            self.drum_lb.selection_set(0, tk.END)
        else:
            for i, name in enumerate(DRUM_INSTRUMENTS):
                if name in drums_enabled:
                    self.drum_lb.selection_set(i)


class RoleEditor:
    """Main + supports pickers for the three melodic roles, one column per role."""

    def __init__(self, parent, defaults=None, on_change=None, list_height=5):
        defaults = defaults or {}
        self._on_change = on_change
        self.main_vars: dict[str, tk.StringVar] = {}
        self.main_combos: dict[str, ttk.Combobox] = {}
        self.support_boxes: dict[str, tk.Listbox] = {}
        for column, role in enumerate(MusicAnvil.ROLES):
            frame = tk.LabelFrame(parent, text=role)
            frame.grid(row=0, column=column, padx=5, pady=5, sticky="n")
            tk.Label(frame, text="Main:").grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value=defaults.get(role, NONE_CHOICE))
            values = MELODIC_INSTRUMENTS if role == MusicAnvil.ROLE_LEAD else [NONE_CHOICE] + MELODIC_INSTRUMENTS
            cb = ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=12)
            cb.grid(row=0, column=1, padx=2, pady=2)
            cb.bind("<<ComboboxSelected>>", self._fire)
            tk.Label(frame, text="Supports:").grid(row=1, column=0, sticky="nw")
            lf, box = _scrolled_listbox(frame, height=list_height, width=14, selectmode=tk.MULTIPLE)
            lf.grid(row=1, column=1, padx=2, pady=2)
            for instrument in MELODIC_INSTRUMENTS:
                box.insert(tk.END, instrument)
            box.bind("<<ListboxSelect>>", self._fire)
            self.main_vars[role] = var
            self.main_combos[role] = cb
            self.support_boxes[role] = box

    def _fire(self, *_):
        if self._on_change:
            self._on_change()

    def get_roles(self):
        roles = {}
        for role in MusicAnvil.ROLES:
            main = self.main_vars[role].get()
            main = None if main in ("", NONE_CHOICE) else main
            supports = [MELODIC_INSTRUMENTS[i] for i in self.support_boxes[role].curselection()]
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

        self.sections: dict[str, MusicAnvil.SectionSpec] = {}
        self.structure: list[MusicAnvil.StructureEntry] = []
        self._autosave_enabled = False
        self._project_path = None

        self._build_menu()

        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=5, pady=5)
        self.piece_tab = tk.Frame(notebook)
        self.sections_tab = tk.Frame(notebook)
        self.structure_tab = tk.Frame(notebook)
        notebook.add(self.piece_tab, text="Main")
        notebook.add(self.sections_tab, text="Sections")
        notebook.add(self.structure_tab, text="Piece Structure")

        self._build_piece_tab()
        self._build_sections_tab()
        self._build_structure_tab()
        self._create_default_sections()
        self._autosave_enabled = True

    # ----------------------------------------------------------------- Menu bar

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="New Project", command=self._new_project,
                              accelerator="Ctrl+N")
        file_menu.add_command(label="Open Project…", command=self._open_project,
                              accelerator="Ctrl+O")
        file_menu.add_separator()
        file_menu.add_command(label="Save Project", command=self._save_project,
                              accelerator="Ctrl+S")
        file_menu.add_command(label="Save Project As…", command=self._save_project_as,
                              accelerator="Ctrl+Shift+S")
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

        self.root.bind("<Control-n>", lambda _e: self._new_project())
        self.root.bind("<Control-o>", lambda _e: self._open_project())
        self.root.bind("<Control-s>", lambda _e: self._save_project())
        self.root.bind("<Control-S>", lambda _e: self._save_project_as())

    # ------------------------------------------------------------- Project I/O

    def _set_project_path(self, path):
        self._project_path = path
        suffix = f" — {os.path.basename(path)}" if path else ""
        self.root.title(f"MusicAnvil — Piece Builder{suffix}")

    def _new_project(self):
        if not messagebox.askyesno("New Project",
                                   "Discard the current project and start fresh?"):
            return
        piece = MusicAnvil.PieceSpec(
            roles={role: MusicAnvil.RoleAssignment(main=_GUI["default_roles"].get(role))
                   for role in MusicAnvil.ROLES},
            sections={name: MusicAnvil.SectionSpec(name=name)
                      for name in DEFAULT_SECTION_NAMES},
            structure=[],
        )
        self._apply_piece_spec(piece, filename=_GUI["default_filename"])
        self._set_project_path(None)

    def _open_project(self):
        path = filedialog.askopenfilename(
            title="Open Project",
            filetypes=[("MusicAnvil Project", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            piece, filename = project_dict_to_piece(data)
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("Open Failed", f"Could not load project:\n{exc}")
            return
        self._apply_piece_spec(piece, filename)
        self._set_project_path(path)

    def _save_project(self):
        if self._project_path:
            self._write_project(self._project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        path = filedialog.asksaveasfilename(
            title="Save Project",
            defaultextension=".json",
            filetypes=[("MusicAnvil Project", "*.json"), ("All files", "*.*")],
            initialfile=(self.filename_var.get().strip() or "project"),
        )
        if not path:
            return
        self._write_project(path)

    def _write_project(self, path):
        try:
            piece = self._current_piece_spec(require_lead=False)
            data = piece_to_project_dict(piece, filename=self.filename_var.get().strip())
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
            self._set_project_path(path)
        except Exception as exc:  # invalid tempo/signature, disk errors, …
            messagebox.showerror("Save Failed", str(exc))

    def _apply_piece_spec(self, piece, filename=""):
        """Push a PieceSpec (and filename) into every widget on every tab."""
        self._autosave_enabled = False
        try:
            self.tempo_var.set(str(piece.tempo))
            self.signature_var.set(f"{piece.signature[0]}/{piece.signature[1]}")
            self.scale_var.set(piece.scale)
            self.tonic_var.set(piece.tonic)
            self.tonic_octave_var.set(str(piece.tonic_octave))
            self.beat_mode_var.set(self._beat_mode_label(piece.beat_mode))
            if filename:
                self.filename_var.set(filename)

            for key in self.artic_vars:
                self.artic_vars[key].set(str(getattr(piece, key)))
            for key in self.toggle_vars:
                self.toggle_vars[key].set(bool(getattr(piece, key)))

            self.piece_drum_editor.set_rhythm(piece.rhythm)
            self.piece_drum_editor.set_drums_enabled(piece.drums_enabled)
            self.piece_roles.set_roles(piece.roles)

            self.sections = dict(piece.sections)
            self.library_listbox.delete(0, tk.END)
            for name in self.sections:
                self.library_listbox.insert(tk.END, name)

            self.structure = list(piece.structure)
            self.structure_listbox.delete(0, tk.END)
            for entry in self.structure:
                self.structure_listbox.insert(tk.END, _entry_label(entry))

            self._refresh_section_choices()
        finally:
            self._autosave_enabled = True

        # Reload the section editor from the first section (if any) so it no
        # longer shows the previous project's values.
        if self.sections:
            self.library_listbox.selection_clear(0, tk.END)
            self.library_listbox.selection_set(0)
            self._load_section()
        self._update_total()

    @staticmethod
    def _beat_mode_label(mode):
        for label, number in ma_utils.BEAT_MODES.items():
            if number == mode:
                return label
        return BEAT_MODE_OPTIONS[0]

    # ----------------------------------------------------------------- Main tab

    def _build_piece_tab(self):
        # ---- Piece Defaults (left column) ----
        defaults = tk.LabelFrame(self.piece_tab, text="Piece Defaults")
        defaults.grid(row=0, column=0, padx=10, pady=10, sticky="nw")
        defaults.columnconfigure(0, minsize=110)

        tk.Label(defaults, text="Tempo (BPM):", anchor="w").grid(row=0, column=0, sticky="ew", padx=5, pady=3)
        self.tempo_var = tk.StringVar(value=str(_PIECE_DEFAULTS["tempo"]))
        tk.Entry(defaults, textvariable=self.tempo_var, width=8).grid(row=0, column=1, sticky="w", padx=5, pady=3)

        tk.Label(defaults, text="Signature:", anchor="w").grid(row=1, column=0, sticky="ew", padx=5, pady=3)
        signature_default = "{}/{}".format(*_PIECE_DEFAULTS["signature"])
        self.signature_var = tk.StringVar(value=signature_default)
        ttk.Combobox(defaults, textvariable=self.signature_var, values=SIGNATURE_OPTIONS,
                     state="readonly", width=6).grid(row=1, column=1, sticky="w", padx=5, pady=3)

        tk.Label(defaults, text="Scale:", anchor="w").grid(row=2, column=0, sticky="ew", padx=5, pady=3)
        self.scale_var = tk.StringVar(value=_PIECE_DEFAULTS["scale"])
        ttk.Combobox(defaults, textvariable=self.scale_var, values=list(ma_utils.scale_definitions.keys()),
                     state="readonly", width=14).grid(row=2, column=1, sticky="w", padx=5, pady=3)

        tk.Label(defaults, text="Tonic Note:", anchor="w").grid(row=3, column=0, sticky="ew", padx=5, pady=3)
        tonic_frame = tk.Frame(defaults)
        tonic_frame.grid(row=3, column=1, padx=5, pady=3, sticky="w")
        self.tonic_var = tk.StringVar(value=_PIECE_DEFAULTS["tonic"])
        ttk.Combobox(tonic_frame, textvariable=self.tonic_var, values=ma_utils.notes_in_octave,
                     state="readonly", width=4).pack(side="left")
        self.tonic_octave_var = tk.StringVar(value=str(_PIECE_DEFAULTS["tonic_octave"]))
        ttk.Combobox(tonic_frame, textvariable=self.tonic_octave_var, values=OCTAVE_OPTIONS,
                     state="readonly", width=3).pack(side="left", padx=(4, 0))

        tk.Label(defaults, text="Beat Mode:", anchor="w").grid(row=4, column=0, sticky="ew", padx=5, pady=3)
        self.beat_mode_var = tk.StringVar(value=BEAT_MODE_OPTIONS[0])
        ttk.Combobox(defaults, textvariable=self.beat_mode_var, values=BEAT_MODE_OPTIONS,
                     state="readonly", width=18).grid(row=4, column=1, sticky="w", padx=5, pady=3)

        tk.Label(defaults, text="FileName:", anchor="w").grid(row=5, column=0, sticky="ew", padx=5, pady=3)
        self.filename_var = tk.StringVar(value=_GUI["default_filename"])
        tk.Entry(defaults, textvariable=self.filename_var, width=16).grid(row=5, column=1, sticky="w", padx=5, pady=3)

        # ---- Articulation Defaults (right of Piece Defaults) ----
        artic = tk.LabelFrame(self.piece_tab, text="Articulation Defaults")
        artic.grid(row=0, column=1, padx=10, pady=10, sticky="nw")
        artic.columnconfigure(0, minsize=160)

        self.artic_vars: dict[str, tk.StringVar] = {}
        for r, (key, label, default, _is_int) in enumerate(ARTIC_PARAMS):
            tk.Label(artic, text=label, anchor="w").grid(row=r, column=0, sticky="ew", padx=5, pady=3)
            var = tk.StringVar(value=default)
            tk.Entry(artic, textvariable=var, width=8).grid(row=r, column=1, sticky="w", padx=5, pady=3)
            self.artic_vars[key] = var

        self.toggle_vars = {}
        for offset, (key, label, default) in enumerate(TOGGLE_PARAMS):
            var = tk.BooleanVar(value=default)
            tk.Checkbutton(artic, text=label, variable=var, anchor="w").grid(
                row=len(ARTIC_PARAMS) + offset, column=0, columnspan=2,
                sticky="w", padx=5, pady=2)
            self.toggle_vars[key] = var

        # ---- Default Roles (below, spanning both columns) ----
        roles_frame = tk.LabelFrame(self.piece_tab, text="Default Roles")
        roles_frame.grid(row=1, column=0, columnspan=2, padx=10, pady=10, sticky="nw")

        drum_sub = tk.Frame(roles_frame)
        drum_sub.grid(row=0, column=0, sticky="n")
        self.piece_drum_editor = DrumEditor(drum_sub, list_height=10)

        melodic_sub = tk.Frame(roles_frame)
        melodic_sub.grid(row=0, column=1, sticky="n")
        self.piece_roles = RoleEditor(melodic_sub, defaults=_GUI["default_roles"], list_height=10)

    # --------------------------------------------------------------- Sections tab

    def _build_sections_tab(self):
        library = tk.LabelFrame(self.sections_tab, text="Section Library")
        library.grid(row=0, column=0, padx=10, pady=10, sticky="n")

        lf, self.library_listbox = _scrolled_listbox(library, height=14, width=20)
        lf.grid(row=0, column=0, columnspan=2, padx=5, pady=5)
        self.library_listbox.bind("<<ListboxSelect>>", self._load_section)

        tk.Button(library, text="New Section", command=self._new_section).grid(row=1, column=0, padx=5, pady=3)
        tk.Button(library, text="Delete", command=self._delete_section).grid(row=1, column=1, padx=5, pady=3)

        editor = tk.LabelFrame(self.sections_tab, text="Section Editor")
        editor.grid(row=0, column=1, padx=10, pady=10, sticky="n")

        tk.Label(editor, text="Bars:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.bars_var = tk.StringVar(value="4")
        tk.Spinbox(editor, from_=1, to=128, textvariable=self.bars_var,
                   width=6).grid(row=0, column=1, sticky="w", padx=5, pady=3)

        self.sec_override: dict[str, tuple[tk.BooleanVar, tk.StringVar]] = {}

        def override_row(row, key, label, widget_values, width):
            check_var = tk.BooleanVar(value=False)
            tk.Checkbutton(editor, text=label, variable=check_var).grid(
                row=row, column=0, sticky="w", padx=5, pady=2)
            value_var = tk.StringVar()
            if widget_values is None:
                tk.Entry(editor, textvariable=value_var, width=width).grid(
                    row=row, column=1, sticky="w", padx=5, pady=2)
            else:
                ttk.Combobox(editor, textvariable=value_var, values=widget_values,
                             state="readonly", width=width).grid(
                    row=row, column=1, sticky="w", padx=5, pady=2)
            self.sec_override[key] = (check_var, value_var)

        # Musical overrides
        override_row(1,  "tempo",       "Override Tempo (BPM)",   None,                               8)
        override_row(2,  "signature",   "Override Signature",     SIGNATURE_OPTIONS,                  6)
        override_row(3,  "rhythm",      "Override Rhythm",        list(ma_utils.drum_lines.keys()),  14)
        override_row(4,  "scale",       "Override Scale",         list(ma_utils.scale_definitions.keys()), 14)
        override_row(5,  "tonic",       "Override Tonic Note",    ma_utils.notes_in_octave,           6)
        override_row(6,  "tonic_octave","Override Tonic Octave",  OCTAVE_OPTIONS,                     4)
        override_row(7,  "beat_mode",   "Override Beat Mode",     BEAT_MODE_OPTIONS,                 18)

        # Articulation overrides
        override_row(8,  "lead_rest_prob",       "Override Rest Prob",     None,  8)
        override_row(9,  "lead_sustain",         "Override Lead Sustain",  None,  8)
        override_row(10, "lead_velocity_jitter", "Override Vel. Jitter",   None,  6)
        override_row(11, "lead_step_bias",       "Override Step Bias",     None,  8)
        override_row(12, "bass_gate",            "Override Bass Gate",          None,  8)
        override_row(13, "chord_gate",           "Override Chord Gate",         None,  8)
        override_row(14, "chord_octave_shift",   "Override Chord Oct. Shift",   None,  4)

        # Phrasing / dynamics overrides (ToDo 4.1-4.6)
        override_row(15, "phrase_bars",       "Override Phrase Bars",     None,  4)
        override_row(16, "metric_accent",     "Override Metric Accent",   None,  4)
        override_row(17, "intensity",         "Override Intensity",       None,  6)
        override_row(18, "final_lengthening", "Override Final Length.",   None,  6)
        override_row(19, "lead_syncopation",  "Override Syncopation",     None,  6)
        override_row(20, "cadence_beats",     "Override Cadence Beats",   None,  4)

        # Drums enabled override (listbox — separate from override_row)
        self._sec_drums_override_var = tk.BooleanVar(value=False)
        tk.Checkbutton(editor, text="Override Drums Enabled",
                       variable=self._sec_drums_override_var).grid(
            row=21, column=0, sticky="w", padx=5, pady=2)
        dlf, self._sec_drums_lb = _scrolled_listbox(editor, height=4, width=15, selectmode=tk.MULTIPLE)
        dlf.grid(row=21, column=1, padx=5, pady=2, sticky="w")
        for name in DRUM_INSTRUMENTS:
            self._sec_drums_lb.insert(tk.END, name)
        self._sec_drums_lb.selection_set(0, tk.END)

        # Roles override
        self.sec_roles_override_var = tk.BooleanVar(value=False)
        tk.Checkbutton(editor, text="Override Roles",
                       variable=self.sec_roles_override_var).grid(
            row=16, column=0, sticky="w", padx=5, pady=2)
        roles_holder = tk.Frame(editor)
        roles_holder.grid(row=17, column=0, columnspan=2, padx=5, pady=3)
        self.sec_roles = RoleEditor(roles_holder, on_change=self._auto_save_section)

        self.sec_duration_label = tk.Label(editor, text="Duration: --:--")
        self.sec_duration_label.grid(row=18, column=0, columnspan=2, pady=5)

        # Wire auto-save to every field
        self.bars_var.trace_add("write", self._auto_save_section)
        for check_var, value_var in self.sec_override.values():
            check_var.trace_add("write", self._auto_save_section)
            value_var.trace_add("write", self._auto_save_section)
        self.sec_roles_override_var.trace_add("write", self._auto_save_section)
        self._sec_drums_override_var.trace_add("write", self._auto_save_section)
        self._sec_drums_lb.bind("<<ListboxSelect>>", self._auto_save_section)

    # ------------------------------------------------------------- Structure tab

    def _build_structure_tab(self):
        structure = tk.LabelFrame(self.structure_tab, text="Piece Structure")
        structure.grid(row=0, column=0, padx=10, pady=10, sticky="n")

        lf, self.structure_listbox = _scrolled_listbox(structure, height=14, width=26)
        lf.grid(row=0, column=0, columnspan=3, padx=5, pady=5)

        self.add_section_var = tk.StringVar()
        self.add_section_combo = ttk.Combobox(structure, textvariable=self.add_section_var,
                                              values=[], state="readonly", width=16)
        self.add_section_combo.grid(row=1, column=0, columnspan=2, padx=5, pady=3)
        tk.Button(structure, text="Add", command=self._add_to_structure).grid(row=1, column=2, padx=5, pady=3)

        transform_frame = tk.Frame(structure)
        transform_frame.grid(row=2, column=0, columnspan=3, padx=5, pady=2, sticky="w")
        tk.Label(transform_frame, text="Transformer:").grid(row=0, column=0, sticky="w")
        self.transform_var = tk.StringVar(value=NONE_CHOICE)
        ttk.Combobox(transform_frame, textvariable=self.transform_var,
                     values=TRANSFORMER_OPTIONS, state="readonly", width=11).grid(row=0, column=1, padx=(3, 8))
        # Parameter controls are built from ma_utils.transformer_params(), so every
        # transformer brings its own widgets instead of the GUI hardcoding them.
        self.transform_param_frame = tk.Frame(transform_frame)
        self.transform_param_frame.grid(row=0, column=2, sticky="w")
        self.transform_param_vars = {}
        self.transform_var.trace_add("write", self._on_transform_changed)
        self._build_transformer_params()

        tk.Button(structure, text="Remove", command=self._remove_from_structure).grid(row=3, column=0, padx=5, pady=3)
        tk.Button(structure, text="Move Up", command=lambda: self._move_in_structure(-1)).grid(row=3, column=1, padx=5, pady=3)
        tk.Button(structure, text="Move Down", command=lambda: self._move_in_structure(1)).grid(row=3, column=2, padx=5, pady=3)

        self.total_label = tk.Label(structure, text="Total duration: 00:00")
        self.total_label.grid(row=4, column=0, columnspan=3, pady=5)

        tk.Button(structure, text="Generate", command=self._generate).grid(row=5, column=0, columnspan=3, pady=10)

    def _build_transformer_params(self):
        """Rebuild the parameter widgets for the selected transformer."""
        for child in self.transform_param_frame.winfo_children():
            child.destroy()
        self.transform_param_vars = {}
        name = self.transform_var.get()
        if name not in ma_utils.BEAT_TRANSFORMERS:   # "(none)", or nothing chosen yet
            return
        for column, param in enumerate(ma_utils.transformer_params(name)):
            label = param.get("label", param["name"])
            tk.Label(self.transform_param_frame, text=f"{label}:").grid(
                row=0, column=column * 2, sticky="w", padx=(6, 0))
            var = tk.StringVar(value=str(param.get("default", "")))
            self.transform_param_vars[param["name"]] = (var, param)
            if param.get("type") == "choice":
                ttk.Combobox(self.transform_param_frame, textvariable=var,
                             values=list(param.get("choices") or []), state="readonly",
                             width=10).grid(row=0, column=column * 2 + 1, padx=(3, 0))
            else:
                tk.Spinbox(self.transform_param_frame,
                           from_=param.get("min", 0), to=param.get("max", 100),
                           increment=1 if param.get("type") == "int" else 0.1,
                           textvariable=var, width=5).grid(row=0, column=column * 2 + 1,
                                                           padx=(3, 0))

    def _transformer_kwargs(self):
        """Read the parameter widgets into a kwargs dict, converting to the declared type."""
        kwargs = {}
        for name, (var, param) in self.transform_param_vars.items():
            raw = var.get()
            kind = param.get("type", "str")
            try:
                if kind == "int":
                    kwargs[name] = int(float(raw))
                elif kind == "float":
                    kwargs[name] = float(raw)
                else:
                    kwargs[name] = raw
            except (TypeError, ValueError):
                raise ValueError(f"{param.get('label', name)} must be a number, got '{raw}'.")
        return kwargs

    def _on_transform_changed(self, *_):
        self._build_transformer_params()

    def _add_to_structure(self):
        name = self.add_section_var.get()
        if not name:
            messagebox.showerror("Error", "Create a section in the Sections tab first, then pick it here.")
            return
        transformer = self.transform_var.get()
        transformer = None if transformer == NONE_CHOICE else transformer
        kwargs = {}
        if transformer is not None:
            try:
                kwargs = self._transformer_kwargs()
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
        entry = MusicAnvil.StructureEntry(section=name, transformer=transformer, transformer_kwargs=kwargs)
        self.structure.append(entry)
        self.structure_listbox.insert(tk.END, _entry_label(entry))
        idx = self.structure_listbox.size() - 1
        self.structure_listbox.selection_clear(0, tk.END)
        self.structure_listbox.selection_set(idx)
        self.structure_listbox.see(idx)
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

    # --------------------------------------------------------- Section CRUD

    def _create_default_sections(self):
        for name in DEFAULT_SECTION_NAMES:
            self.sections[name] = MusicAnvil.SectionSpec(name=name)
            self.library_listbox.insert(tk.END, name)
        self._refresh_section_choices()

    def _selected_library_name(self) -> str | None:
        sel = self.library_listbox.curselection()
        return self.library_listbox.get(sel[0]) if sel else None

    def _new_section(self):
        name = simpledialog.askstring("New Section", "Section name:", parent=self.root)
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
        idx = self.library_listbox.size() - 1
        self.library_listbox.selection_clear(0, tk.END)
        self.library_listbox.selection_set(idx)
        self.library_listbox.see(idx)
        self._load_section()
        self._refresh_section_choices()

    def _delete_section(self):
        name = self._selected_library_name()
        if name is None:
            return
        if not messagebox.askyesno("Delete Section",
                                   f"Delete section '{name}'? It will also be removed from the structure."):
            return
        sel = self.library_listbox.curselection()
        self.library_listbox.delete(sel[0])
        del self.sections[name]
        for index in range(len(self.structure) - 1, -1, -1):
            if self.structure[index].section == name:
                del self.structure[index]
                self.structure_listbox.delete(index)
        self._refresh_section_choices()
        self._update_total()

    def _load_section(self, _event=None):
        name = self._selected_library_name()
        if name is None:
            return
        self._autosave_enabled = False
        spec = self.sections[name]
        self.bars_var.set(str(spec.bars))

        beat_mode_label = next(
            (lbl for lbl, num in ma_utils.BEAT_MODES.items() if num == spec.beat_mode), None
        )
        musical_loaders = {
            "tempo":        None if spec.tempo is None else str(spec.tempo),
            "signature":    None if spec.signature is None else f"{spec.signature[0]}/{spec.signature[1]}",
            "rhythm":       spec.rhythm,
            "scale":        spec.scale,
            "tonic":        spec.tonic,
            "tonic_octave": None if spec.tonic_octave is None else str(spec.tonic_octave),
            "beat_mode":    beat_mode_label,
        }
        for key, value in musical_loaders.items():
            check_var, value_var = self.sec_override[key]
            check_var.set(value is not None)
            value_var.set(value if value is not None else "")

        # Articulation overrides
        artic_loaders = {
            "lead_rest_prob":       spec.lead_rest_prob,
            "lead_sustain":         spec.lead_sustain,
            "lead_velocity_jitter": spec.lead_velocity_jitter,
            "lead_step_bias":       spec.lead_step_bias,
            "bass_gate":            spec.bass_gate,
            "chord_gate":           spec.chord_gate,
            "chord_octave_shift":   spec.chord_octave_shift,
        }
        for key, value in artic_loaders.items():
            check_var, value_var = self.sec_override[key]
            check_var.set(value is not None)
            value_var.set("" if value is None else str(value))

        # Drums enabled override
        has_drums_override = spec.drums_enabled is not None
        self._sec_drums_override_var.set(has_drums_override)
        self._sec_drums_lb.selection_clear(0, tk.END)
        if not has_drums_override:
            self._sec_drums_lb.selection_set(0, tk.END)
        else:
            for i, drum_name in enumerate(DRUM_INSTRUMENTS):
                if drum_name in spec.drums_enabled:
                    self._sec_drums_lb.selection_set(i)

        # Roles override
        self.sec_roles_override_var.set(bool(spec.roles))
        self.sec_roles.set_roles(spec.roles if spec.roles else {})
        self._update_section_duration(spec)
        self._autosave_enabled = True

    # -------------------------------------------------------- Auto-save logic

    def _auto_save_section(self, *_):
        if not self._autosave_enabled:
            return
        name = self._selected_library_name()
        if name is None:
            return
        try:
            spec = self._build_section_spec(name)
            self.sections[name] = spec
            self._update_section_duration(spec)
            self._refresh_section_choices()
            self._update_total()
        except (ValueError, KeyError):
            self.sec_duration_label.config(text="Duration: --:--")

    def _build_section_spec(self, name):
        spec = MusicAnvil.SectionSpec(name=str(name), bars=int(self.bars_var.get()))
        if spec.bars <= 0:
            raise ValueError("Bars must be positive.")

        # Musical overrides
        check_var, value_var = self.sec_override["tempo"]
        if check_var.get():
            spec.tempo = int(value_var.get())
            if spec.tempo <= 0:
                raise ValueError("Tempo must be positive.")
        check_var, value_var = self.sec_override["signature"]
        if check_var.get():
            spec.signature = MusicAnvil.parse_signature(value_var.get())
        for key in ("rhythm", "scale", "tonic"):
            check_var, value_var = self.sec_override[key]
            if check_var.get():
                value = value_var.get()
                if not value:
                    raise ValueError(f"Pick a value for overridden {key}.")
                setattr(spec, key, value)
        check_var, value_var = self.sec_override["tonic_octave"]
        if check_var.get():
            spec.tonic_octave = int(value_var.get())
        check_var, value_var = self.sec_override["beat_mode"]
        if check_var.get():
            spec.beat_mode = ma_utils.BEAT_MODES[value_var.get()]

        # Articulation overrides
        for key, _label, _default, is_int in ARTIC_PARAMS:
            check_var, value_var = self.sec_override[key]
            if check_var.get():
                raw = value_var.get()
                setattr(spec, key, int(raw) if is_int else float(raw))

        # Drums enabled override
        if self._sec_drums_override_var.get():
            sel = list(self._sec_drums_lb.curselection())
            spec.drums_enabled = [DRUM_INSTRUMENTS[i] for i in sel]

        # Roles override
        if self.sec_roles_override_var.get():
            spec.roles = self.sec_roles.get_roles()
        return spec

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

    # ---------------------------------------------------------------- Generation

    def _parse_artic(self) -> dict:
        result = {}
        for key, _label, _default, is_int in ARTIC_PARAMS:
            raw = self.artic_vars[key].get()
            result[key] = int(raw) if is_int else float(raw)
        for key, _label, _default in TOGGLE_PARAMS:
            result[key] = bool(self.toggle_vars[key].get())
        return result

    def _current_piece_spec(self, require_lead=True):
        try:
            tempo = int(self.tempo_var.get())
        except ValueError:
            raise ValueError("Tempo must be a whole number of BPM.")
        if tempo <= 0:
            raise ValueError("Tempo must be a positive number.")
        artic = self._parse_artic()
        piece = MusicAnvil.PieceSpec(
            tempo=tempo,
            signature=MusicAnvil.parse_signature(self.signature_var.get()),
            rhythm=self.piece_drum_editor.get_rhythm(),
            scale=self.scale_var.get(),
            tonic=self.tonic_var.get(),
            tonic_octave=int(self.tonic_octave_var.get()),
            beat_mode=ma_utils.BEAT_MODES[self.beat_mode_var.get()],
            drums_enabled=self.piece_drum_editor.get_drums_enabled(),
            lead_rest_prob=artic["lead_rest_prob"],
            lead_sustain=artic["lead_sustain"],
            lead_velocity_jitter=artic["lead_velocity_jitter"],
            lead_step_bias=artic["lead_step_bias"],
            bass_gate=artic["bass_gate"],
            chord_gate=artic["chord_gate"],
            chord_octave_shift=artic["chord_octave_shift"],
            roles=self.piece_roles.get_roles(),
            sections=dict(self.sections),
            structure=list(self.structure),
        )
        if require_lead and piece.roles[MusicAnvil.ROLE_LEAD].main is None:
            raise ValueError("A main Lead instrument is required.")
        return piece

    def _generate(self):
        try:
            piece = self._current_piece_spec()
            if not piece.structure:
                raise ValueError("The piece structure is empty — add at least one section.")
            default_name = self.filename_var.get().strip() or _GUI["default_filename"]
            if not default_name.endswith(".mid"):
                default_name += ".mid"
            path = filedialog.asksaveasfilename(
                title="Save MIDI File",
                defaultextension=".mid",
                filetypes=[("MIDI files", "*.mid"), ("All files", "*.*")],
                initialfile=default_name,
            )
            if not path:
                return
            midi_data = MusicAnvil.render_piece(piece)
            midi_data.write(path)
            total = MusicAnvil.piece_seconds(piece)
            messagebox.showinfo("Done", f"MIDI saved to {path} ({fmt_mmss(total)})")
        except Exception as exc:
            messagebox.showerror("Error", str(exc))


if __name__ == "__main__":
    root = tk.Tk()
    app = MusicGeneratorApp(root)
    root.mainloop()
