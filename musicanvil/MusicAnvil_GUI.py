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
# Widgets are sized from the longest name they must show, so no instrument is clipped
# (the General MIDI set includes names like "Electric Guitar (muted)").
INSTRUMENT_WIDTH = max(len(name) for name in MELODIC_INSTRUMENTS) + 2
RHYTHM_WIDTH = max(len(name) for name in ma_utils.drum_lines) + 2
SCALE_WIDTH = max(len(name) for name in ma_utils.scale_definitions) + 2
DRUM_WIDTH = max(len(name) for name in ma_utils.drum_pitches) + 2

# key -> one-sentence explanation, shown as a balloon and in the info line at the bottom
# of the Main tab. Lives in the configuration so the wording can be edited without code.
PARAMETER_HELP = _CFG.get("parameter_help", {})
INFO_HINT = "Hover over a field for an explanation of what it does."


def help_for(key):
    """The explanation of a parameter, or an empty string when none is written yet."""
    return PARAMETER_HELP.get(key, "")
NONE_CHOICE = "(none)"
BOOL_CHOICES = ("yes", "no")
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


def _modifier_label(name, kwargs):
    """'invert', '+5', 'tension bars=2' — built from the declared parameters."""
    if name == "tone_shift":
        return f"{kwargs.get('n', 0):+d}"
    shown = " ".join(f"{key}={value}" for key, value in (kwargs or {}).items())
    return f"{name} {shown}".strip()


def describe_techniques(piece, spec):
    """Explain, in words, what the engine will do to this section.

    Playing technique is not a switch buried in a menu: it follows from the instruments
    chosen for the section and from the Expression setting. This spells that out so the
    Sections tab can show it, rather than leaving the user to guess why one part chugs
    and another rings.
    """
    try:
        resolved = MusicAnvil.resolve_section(spec, piece)
    except Exception:
        return "Techniques: (unavailable until the section is valid)"

    lines = []
    for role in MusicAnvil.ROLES:
        assignment = resolved.roles.get(role)
        instrument = getattr(assignment, "main", None)
        if not instrument:
            continue
        if MusicAnvil.is_power_chord_instrument(instrument):
            lines.append(f"{instrument} ({role}): distorted program — power chords "
                         f"(root+fifth) and palm-muted off-beats")
        elif role == MusicAnvil.ROLE_ACCOMPANIMENT:
            lines.append(f"{instrument} ({role}): full chords, held while the melody fits")

    if resolved.expression:
        lines.append("Expression on: reverb/chorus sends, a swell or decay across each "
                     "phrase, vibrato on long notes")
        lines.append("Pitch bends and slides: lead and bass only (a bend moves the whole "
                     "MIDI channel, so chords are left alone)")
    else:
        lines.append("Expression off: notes only, no controllers or bends")

    if resolved.auto_cadence:
        lines.append(f"Cadences on: each phrase ends open then closed, over its last "
                     f"{resolved.cadence_beats} beat(s)")
    if resolved.drum_fills:
        lines.append("Drum fills at every phrase boundary")
    return "Techniques: " + "; ".join(lines) if lines else "Techniques: none"


def _as_structure_entry(entry):
    """Normalise a structure slot to a StructureEntry (plain strings are accepted)."""
    if isinstance(entry, str):
        return MusicAnvil.StructureEntry(section=entry)
    return entry


def _copy_structure_entry(entry):
    """An independent copy of a structure slot, modifiers included."""
    source = _as_structure_entry(entry)
    return MusicAnvil.StructureEntry(section=source.section,
                                     modifiers=source.all_modifiers())


def _entry_label(entry):
    """'Verse', 'Verse [invert]', 'Verse [+5]', 'Verse [tension bars=1 | +5]' — built from
    each modifier's declared parameters, so a new transformer needs no code here."""
    if isinstance(entry, str):
        return entry
    modifiers = entry.all_modifiers()
    if not modifiers:
        return entry.section
    shown = " | ".join(_modifier_label(name, kwargs) for name, kwargs in modifiers)
    return f"{entry.section} [{shown}]"


def fmt_mmss(seconds):
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes:02d}:{secs:02d}"


# --------------------------------------------------------------- Project I/O
#
# A project file is JSON capturing the full PieceSpec (piece defaults, roles, the
# whole section library, and the ordered structure) plus the GUI output filename,
# so a saved song can be reopened and edited exactly as it was.

PROJECT_FORMAT = "musicanvil-project"
PROJECT_VERSION = 3

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
    """Serialise one structure slot.

    Version 3 records the full ``modifiers`` stack; ``transformer`` /
    ``transformer_kwargs`` are still written for the first modifier so an older
    MusicAnvil can open the file and at least play it with that one.
    """
    if isinstance(entry, str):
        return {"section": entry, "transformer": None, "transformer_kwargs": {},
                "modifiers": []}
    modifiers = entry.all_modifiers()
    first_name, first_kwargs = modifiers[0] if modifiers else (None, {})
    return {"section": entry.section,
            "transformer": first_name,
            "transformer_kwargs": dict(first_kwargs),
            "modifiers": [{"name": name, "kwargs": dict(kwargs)}
                          for name, kwargs in modifiers]}


def _structure_entry_from_dict(data):
    modifiers = data.get("modifiers")
    if modifiers is None:      # a version 1/2 file: the single-transformer shorthand
        return MusicAnvil.StructureEntry(
            section=data["section"],
            transformer=data.get("transformer"),
            transformer_kwargs=dict(data.get("transformer_kwargs") or {}),
        )
    return MusicAnvil.StructureEntry(
        section=data["section"],
        modifiers=[(item["name"], dict(item.get("kwargs") or {})) for item in modifiers],
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


class Tooltip:
    """A balloon that appears next to a widget while the pointer rests on it.

    Also reports the same text to ``on_show`` so the Main tab can mirror it in its info
    line — hovering explains a parameter without covering the one next to it.
    """

    DELAY_MS = 400

    def __init__(self, widget, text, on_show=None):
        self.widget = widget
        self.text = text
        self.on_show = on_show
        self.window = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        if self.on_show:
            self.on_show(self.text)
        self._cancel()
        self.after_id = self.widget.after(self.DELAY_MS, self._show)

    def _cancel(self):
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except Exception:
                pass
            self.after_id = None

    def _show(self):
        if self.window is not None or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except Exception:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.wm_geometry(f"+{x}+{y}")
        tk.Label(self.window, text=self.text, justify="left", wraplength=380,
                 background="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=4).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.window is not None:
            self.window.destroy()
            self.window = None


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
                          values=list(ma_utils.drum_lines.keys()), state="readonly",
                          width=RHYTHM_WIDTH)
        cb.grid(row=0, column=1, padx=4, pady=2)
        cb.bind("<<ComboboxSelected>>", self._fire)

        tk.Label(frame, text="Active:").grid(row=1, column=0, sticky="nw", padx=4, pady=2)
        lf, self.drum_lb = _scrolled_listbox(frame, height=list_height, width=DRUM_WIDTH,
                                            selectmode=tk.MULTIPLE)
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
            cb = ttk.Combobox(frame, textvariable=var, values=values, state="readonly",
                              width=INSTRUMENT_WIDTH)
            cb.grid(row=0, column=1, padx=2, pady=2)
            cb.bind("<<ComboboxSelected>>", self._fire)
            tk.Label(frame, text="Supports:").grid(row=1, column=0, sticky="nw")
            lf, box = _scrolled_listbox(frame, height=list_height, width=INSTRUMENT_WIDTH,
                                        selectmode=tk.MULTIPLE)
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

    def _describe(self, text):
        """Mirror a balloon's text in the Main tab's info line."""
        if getattr(self, "info_label", None) is not None:
            self.info_label.config(text=text or "")

    def _with_help(self, widget, key, label_widget=None):
        """Attach the parameter's explanation to a widget (and to its label)."""
        text = help_for(key)
        if not text:
            return widget
        Tooltip(widget, text, on_show=self._describe)
        if label_widget is not None:
            Tooltip(label_widget, text, on_show=self._describe)
        return widget

    def _build_piece_tab(self):
        # ---- Piece Defaults (left column) ----
        defaults = tk.LabelFrame(self.piece_tab, text="Piece Defaults")
        defaults.grid(row=0, column=0, padx=10, pady=10, sticky="nw")
        defaults.columnconfigure(0, minsize=110)

        tempo_label = tk.Label(defaults, text="Tempo (BPM):", anchor="w")
        tempo_label.grid(row=0, column=0, sticky="ew", padx=5, pady=3)
        self.tempo_var = tk.StringVar(value=str(_PIECE_DEFAULTS["tempo"]))
        tempo_entry = tk.Entry(defaults, textvariable=self.tempo_var, width=8)
        tempo_entry.grid(row=0, column=1, sticky="w", padx=5, pady=3)
        self._with_help(tempo_entry, "tempo", tempo_label)

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
            name = tk.Label(artic, text=label, anchor="w")
            name.grid(row=r, column=0, sticky="ew", padx=5, pady=3)
            var = tk.StringVar(value=default)
            entry = tk.Entry(artic, textvariable=var, width=8)
            entry.grid(row=r, column=1, sticky="w", padx=5, pady=3)
            self.artic_vars[key] = var
            self._with_help(entry, key, name)

        self.toggle_vars = {}
        for offset, (key, label, default) in enumerate(TOGGLE_PARAMS):
            var = tk.BooleanVar(value=default)
            box = tk.Checkbutton(artic, text=label, variable=var, anchor="w")
            box.grid(row=len(ARTIC_PARAMS) + offset, column=0, columnspan=2,
                     sticky="w", padx=5, pady=2)
            self.toggle_vars[key] = var
            self._with_help(box, key)

        # ---- Info line: explains whatever the pointer is over ----
        self.info_label = tk.Label(self.piece_tab, text=INFO_HINT, anchor="w",
                                   justify="left", wraplength=620, relief="groove",
                                   padx=6, pady=4)
        self.info_label.grid(row=2, column=0, columnspan=2, padx=10, pady=(0, 10),
                             sticky="ew")

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
            """One 'override this' checkbox plus its value widget.

            ``widget_values`` is None for a free entry, a list for a dropdown, or
            BOOL_CHOICES for a piece-level switch — so every parameter of the Main tab
            can be overridden here in the same way.
            """
            check_var = tk.BooleanVar(value=False)
            box = tk.Checkbutton(editor, text=label, variable=check_var)
            box.grid(row=row, column=0, sticky="w", padx=5, pady=2)
            value_var = tk.StringVar()
            if widget_values is None:
                widget = tk.Entry(editor, textvariable=value_var, width=width)
            else:
                widget = ttk.Combobox(editor, textvariable=value_var, values=widget_values,
                                      state="readonly", width=width)
            widget.grid(row=row, column=1, sticky="w", padx=5, pady=2)
            self.sec_override[key] = (check_var, value_var)
            self._with_help(widget, key, box)

        # Musical overrides
        override_row(1,  "tempo",       "Override Tempo (BPM)",   None,                               8)
        override_row(2,  "signature",   "Override Signature",     SIGNATURE_OPTIONS,                  6)
        override_row(3,  "rhythm",      "Override Rhythm",        list(ma_utils.drum_lines.keys()),
                     RHYTHM_WIDTH)
        override_row(4,  "scale",       "Override Scale",         list(ma_utils.scale_definitions.keys()),
                     SCALE_WIDTH)
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

        # Switches: the same three the Main tab offers, so every piece parameter can be
        # overridden per section (ToDo 6.1).
        for offset, (key, label, _default) in enumerate(TOGGLE_PARAMS):
            override_row(21 + offset, key, f"Override {label}", BOOL_CHOICES, 6)

        # Drums enabled override (listbox — separate from override_row)
        self._sec_drums_override_var = tk.BooleanVar(value=False)
        self.technique_label = tk.Label(editor, text="Techniques: —", anchor="w",
                                        justify="left", wraplength=430, fg="#333333")
        self.technique_label.grid(row=20 + len(TOGGLE_PARAMS), column=0, columnspan=2,
                                  sticky="w", padx=5, pady=(6, 2))
        Tooltip(self.technique_label,
                "What the engine will actually do to this section, given the instruments "
                "and switches above. Distortion, power chords and palm mutes follow from "
                "the instrument you pick, not from a separate setting.",
                on_show=self._describe)

        drums_row = 22 + len(TOGGLE_PARAMS)
        tk.Checkbutton(editor, text="Override Drums Enabled",
                       variable=self._sec_drums_override_var).grid(
            row=drums_row, column=0, sticky="w", padx=5, pady=2)
        dlf, self._sec_drums_lb = _scrolled_listbox(editor, height=4, width=15, selectmode=tk.MULTIPLE)
        dlf.grid(row=drums_row, column=1, padx=5, pady=2, sticky="w")
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

        # EXTENDED so several occurrences can be duplicated, removed or modified at once.
        lf, self.structure_listbox = _scrolled_listbox(structure, height=14, width=34,
                                                       selectmode=tk.EXTENDED)
        lf.grid(row=0, column=0, columnspan=3, padx=5, pady=5)

        self.add_section_var = tk.StringVar()
        self.add_section_combo = ttk.Combobox(structure, textvariable=self.add_section_var,
                                              values=[], state="readonly", width=20)
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

        # A modifier is added to this stack, and the whole stack goes on the next
        # occurrence added — or onto the occurrences already selected. Stacking is what
        # lets one section both build tension and change key.
        stack_frame = tk.Frame(structure)
        stack_frame.grid(row=3, column=0, columnspan=3, padx=5, pady=2, sticky="w")
        tk.Button(stack_frame, text="Stack modifier",
                  command=self._stack_modifier).grid(row=0, column=0, padx=(0, 4))
        tk.Button(stack_frame, text="Clear stack",
                  command=self._clear_modifier_stack).grid(row=0, column=1, padx=4)
        tk.Button(stack_frame, text="Apply stack to selected",
                  command=self._apply_stack_to_selected).grid(row=0, column=2, padx=4)
        self.modifier_stack = []
        self.stack_label = tk.Label(structure, text=self._stack_text(), anchor="w",
                                    justify="left", wraplength=320, fg="#333333")
        self.stack_label.grid(row=4, column=0, columnspan=3, padx=5, sticky="w")

        tk.Button(structure, text="Remove", command=self._remove_from_structure).grid(row=5, column=0, padx=5, pady=3)
        tk.Button(structure, text="Duplicate", command=self._duplicate_in_structure).grid(row=5, column=1, padx=5, pady=3)
        tk.Button(structure, text="Move Up", command=lambda: self._move_in_structure(-1)).grid(row=6, column=0, padx=5, pady=3)
        tk.Button(structure, text="Move Down", command=lambda: self._move_in_structure(1)).grid(row=6, column=1, padx=5, pady=3)

        self.total_label = tk.Label(structure, text="Total duration: 00:00")
        self.total_label.grid(row=7, column=0, columnspan=3, pady=5)

        tk.Button(structure, text="Generate", command=self._generate).grid(row=8, column=0, columnspan=3, pady=10)

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

    def _stack_text(self):
        if not getattr(self, "modifier_stack", None):
            return "Modifier stack: (empty) — pick a modifier above and press Stack modifier."
        shown = " | ".join(_modifier_label(name, kwargs) for name, kwargs in self.modifier_stack)
        return f"Modifier stack: {shown}"

    def _refresh_stack_label(self):
        self.stack_label.config(text=self._stack_text())

    def _current_modifier(self):
        """The modifier currently selected in the combo, or None."""
        name = self.transform_var.get()
        if name not in ma_utils.BEAT_TRANSFORMERS:
            return None
        return name, self._transformer_kwargs()

    def _stack_modifier(self):
        """Append the selected modifier to the stack applied to the next occurrence."""
        try:
            modifier = self._current_modifier()
        except ValueError as exc:
            messagebox.showerror("Error", str(exc))
            return
        if modifier is None:
            messagebox.showerror("Error", "Pick a modifier first.")
            return
        self.modifier_stack.append(modifier)
        self._refresh_stack_label()

    def _clear_modifier_stack(self):
        self.modifier_stack = []
        self._refresh_stack_label()

    def _apply_stack_to_selected(self):
        """Add the stacked modifiers to every selected occurrence."""
        selection = list(self.structure_listbox.curselection())
        if not selection:
            messagebox.showerror("Error", "Select one or more occurrences first.")
            return
        stack = list(self.modifier_stack)
        if not stack:
            try:
                modifier = self._current_modifier()
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            if modifier is None:
                messagebox.showerror("Error", "Stack a modifier, or pick one, first.")
                return
            stack = [modifier]
        for index in selection:
            entry = _as_structure_entry(self.structure[index])
            for name, kwargs in stack:
                entry = entry.with_modifier(name, **kwargs)
            self.structure[index] = entry
            self.structure_listbox.delete(index)
            self.structure_listbox.insert(index, _entry_label(entry))
        for index in selection:
            self.structure_listbox.selection_set(index)
        self._update_total()

    def _duplicate_in_structure(self):
        """Copy every selected occurrence, inserting the copies after the selection."""
        selection = list(self.structure_listbox.curselection())
        if not selection:
            return
        copies = [_copy_structure_entry(self.structure[index]) for index in selection]
        target = selection[-1] + 1
        for offset, entry in enumerate(copies):
            self.structure.insert(target + offset, entry)
            self.structure_listbox.insert(target + offset, _entry_label(entry))
        self.structure_listbox.selection_clear(0, tk.END)
        for offset in range(len(copies)):
            self.structure_listbox.selection_set(target + offset)
        self._update_total()

    def _add_to_structure(self):
        name = self.add_section_var.get()
        if not name:
            messagebox.showerror("Error", "Create a section in the Sections tab first, then pick it here.")
            return
        modifiers = list(getattr(self, "modifier_stack", []))
        if not modifiers:
            try:
                current = self._current_modifier()
            except ValueError as exc:
                messagebox.showerror("Error", str(exc))
                return
            if current is not None:
                modifiers = [current]
        entry = MusicAnvil.StructureEntry(section=name, modifiers=modifiers)
        self.structure.append(entry)
        self.structure_listbox.insert(tk.END, _entry_label(entry))
        idx = self.structure_listbox.size() - 1
        self.structure_listbox.selection_clear(0, tk.END)
        self.structure_listbox.selection_set(idx)
        self.structure_listbox.see(idx)
        self._update_total()

    def _remove_from_structure(self):
        """Remove every selected occurrence (highest index first, so the rest stay put)."""
        selection = sorted(self.structure_listbox.curselection(), reverse=True)
        if not selection:
            return
        for index in selection:
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

        # Switch overrides
        for key, _label, _default in TOGGLE_PARAMS:
            value = getattr(spec, key, None)
            check_var, value_var = self.sec_override[key]
            check_var.set(value is not None)
            value_var.set("" if value is None
                          else (BOOL_CHOICES[0] if value else BOOL_CHOICES[1]))

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
        self._update_technique_summary(spec)
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
            self._update_technique_summary(spec)
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

        # Switch overrides ("yes"/"no" -> True/False)
        for key, _label, _default in TOGGLE_PARAMS:
            check_var, value_var = self.sec_override[key]
            if check_var.get():
                raw = value_var.get()
                if raw not in BOOL_CHOICES:
                    raise ValueError(f"Pick {' or '.join(BOOL_CHOICES)} for overridden {key}.")
                setattr(spec, key, raw == BOOL_CHOICES[0])

        # Drums enabled override
        if self._sec_drums_override_var.get():
            sel = list(self._sec_drums_lb.curselection())
            spec.drums_enabled = [DRUM_INSTRUMENTS[i] for i in sel]

        # Roles override
        if self.sec_roles_override_var.get():
            spec.roles = self.sec_roles.get_roles()
        return spec

    def _update_technique_summary(self, spec):
        """Refresh the plain-language summary of this section's techniques."""
        if getattr(self, "technique_label", None) is None:
            return
        try:
            piece = self._current_piece_spec(require_lead=False)
            self.technique_label.config(text=describe_techniques(piece, spec))
        except Exception:
            self.technique_label.config(text="Techniques: (unavailable until the piece is valid)")

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
