#!/usr/bin/env python3
# sync_gui.py – Dark Mode + nicer UI
import threading
import time
import json
from pathlib import Path
from fnmatch import fnmatch
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Deine upload.py im gleichen Ordner:
import upload  # erwartet: create_session(), upload_with_session()

SETTINGS_FILE = Path.home() / ".brb_sync_gui.json"


# ---------- Helpers ----------
def human_bytes(n: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < step:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.2f} {unit}"
        n /= step
    return f"{n:.2f} PB"


def collect_files(root: Path, include_patterns, exclude_patterns, recursive=True):
    files = []
    it = root.rglob("*") if recursive else root.glob("*")
    for p in it:
        if not p.is_file():
            continue
        name = p.name
        if include_patterns and not any(fnmatch(name, pat) for pat in include_patterns):
            continue
        if exclude_patterns and any(fnmatch(name, pat) for pat in exclude_patterns):
            continue
        if name.startswith("."):
            continue
        files.append(p)
    return sorted(files)


# ---------- Main GUI ----------
class SyncGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Brandenburg Cloud – Folder Sync")
        self.geometry("940x640")
        self.minsize(860, 560)

        self._apply_dark_theme()
        self._build_ui()

        # state
        self.running = False
        self.log_q: Queue[str] = Queue()
        self.progress_total = 0
        self.progress_done = 0
        self.worker_thread = None

        # pump log queue to textbox
        self.after(100, self._drain_log_queue)

        # settings laden
        self._load_settings()

    # ---- Theme ----
    def _apply_dark_theme(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Farben
        BG = "#111317"
        BG_ALT = "#151922"
        FG = "#E7EAF0"
        FG_SUB = "#B6BDCA"
        ACCENT = "#4F8BFF"
        ACCENT_DARK = "#3A69C3"
        BORDER = "#242A35"
        ENTRY_BG = "#0E1218"
        DISABLED = "#6C7380"

        self.configure(bg=BG)

        # Basis-Elemente
        style.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=BG_ALT, relief="solid", borderwidth=1)
        style.map("Card.TFrame", background=[("active", BG_ALT)])
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Subtle.TLabel", foreground=FG_SUB)
        style.configure("TEntry", foreground=FG, fieldbackground=ENTRY_BG, borderwidth=0)
        style.configure("TSpinbox", foreground=FG, fieldbackground=ENTRY_BG, arrowsize=14)
        style.configure("TCheckbutton", foreground=FG)
        style.configure("TLabelframe", background=BG, foreground=FG_SUB, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=BG, foreground=FG_SUB)

        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            padding=(10, 6),
            relief="flat",
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", "#324568")],
            foreground=[("disabled", "#A9B3C1")],
        )
        style.configure(
            "TButton",
            background="#1B2330",
            foreground=FG,
            padding=(10, 6),
            relief="flat",
            borderwidth=0,
        )
        style.map("TButton", background=[("active", "#202A3A")], foreground=[("disabled", DISABLED)])

        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#0B0E13",
            background=ACCENT,
            darkcolor=ACCENT,
            lightcolor=ACCENT,
            bordercolor="#0B0E13",
        )

        # Text-Widget manuell
        self._colors = {
            "bg": BG,
            "bg_alt": BG_ALT,
            "fg": FG,
            "fg_sub": FG_SUB,
            "entry_bg": ENTRY_BG,
            "border": BORDER,
        }

    # ---- UI ----
    def _build_ui(self):
        pad = {"padx": 12, "pady": 10}

        # Header
        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(header, text="Brandenburg Cloud – Folder Sync", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 4)
        )
        ttk.Label(header, text="Logge dich ein, wähle Ordner, starte Sync.", style="Subtle.TLabel").grid(
            row=1, column=0, sticky="w", padx=10, pady=(0, 10)
        )

        # Top row: Credentials + Ordner
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)

        # Credentials Card
        creds = ttk.LabelFrame(top, text="Login")
        creds.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(creds, text="Benutzer (E-Mail):").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.var_user = tk.StringVar()
        entry_user = ttk.Entry(creds, textvariable=self.var_user, width=36)
        entry_user.grid(row=0, column=1, sticky="we", padx=(0, 10), pady=(10, 4))

        ttk.Label(creds, text="Passwort:").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.var_pass = tk.StringVar()
        self._pass_entry = ttk.Entry(creds, textvariable=self.var_pass, show="•", width=36)
        self._pass_entry.grid(row=1, column=1, sticky="we", padx=(0, 10), pady=4)

        self._show_pw = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            creds, text="Passwort anzeigen", variable=self._show_pw, command=self._toggle_pw
        ).grid(row=2, column=1, sticky="w", padx=(0, 10), pady=(0, 10))

        self.btn_test = ttk.Button(creds, text="Test Login", command=self._test_login, style="TButton")
        self.btn_test.grid(row=2, column=0, sticky="w", padx=10, pady=(0, 10))

        creds.grid_columnconfigure(1, weight=1)

        # Folder Card
        folder = ttk.LabelFrame(top, text="Ordner")
        folder.pack(side="left", fill="both", expand=True, padx=(6, 0))

        self.var_dir = tk.StringVar()
        ttk.Label(folder, text="Pfad:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        entry_dir = ttk.Entry(folder, textvariable=self.var_dir)
        entry_dir.grid(row=0, column=1, sticky="we", padx=(0, 10), pady=(10, 4))
        ttk.Button(folder, text="Browse…", command=self._browse_dir, style="TButton").grid(
            row=0, column=2, sticky="w", padx=(0, 10), pady=(10, 4)
        )
        ttk.Button(folder, text="Ordner öffnen", command=self._open_dir, style="TButton").grid(
            row=1, column=2, sticky="w", padx=(0, 10), pady=(0, 10)
        )
        self.lbl_count = ttk.Label(folder, text="0 Dateien (0 B)", style="Subtle.TLabel")
        self.lbl_count.grid(row=1, column=1, sticky="w", padx=(0, 10), pady=(0, 10))

        folder.grid_columnconfigure(1, weight=1)

        # Options
        box_opts = ttk.LabelFrame(self, text="Optionen")
        box_opts.pack(fill="x", **pad)

        ttk.Label(box_opts, text="Include (CSV):").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.var_inc = tk.StringVar(value="*")
        ttk.Entry(box_opts, textvariable=self.var_inc).grid(row=0, column=1, sticky="we", padx=(0, 10), pady=(10, 4))

        ttk.Label(box_opts, text="Exclude (CSV):").grid(row=1, column=0, sticky="w", padx=10, pady=4)
        self.var_exc = tk.StringVar(value="*.tmp,*.ds_store")
        ttk.Entry(box_opts, textvariable=self.var_exc).grid(row=1, column=1, sticky="we", padx=(0, 10), pady=4)

        self.var_recursive = tk.BooleanVar(value=True)
        ttk.Checkbutton(box_opts, text="Rekursiv", variable=self.var_recursive).grid(
            row=0, column=2, sticky="w", padx=10, pady=(10, 4)
        )

        self.var_dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(box_opts, text="Dry-Run (nur anzeigen)", variable=self.var_dry).grid(
            row=1, column=2, sticky="w", padx=10, pady=4
        )

        ttk.Label(box_opts, text="Parallel (1–5):").grid(row=0, column=3, sticky="e", padx=(10, 4))
        self.var_workers = tk.IntVar(value=2)
        ttk.Spinbox(box_opts, from_=1, to=5, textvariable=self.var_workers, width=6).grid(
            row=0, column=4, sticky="w", padx=(0, 10), pady=(10, 4)
        )

        # Spacer
        box_opts.grid_columnconfigure(1, weight=1)

        # Progress Card
        prog_card = ttk.Frame(self, style="Card.TFrame")
        prog_card.pack(fill="x", padx=12, pady=(0, 6))
        self.prog = ttk.Progressbar(prog_card, mode="determinate")
        self.prog.grid(row=0, column=0, sticky="we", padx=10, pady=10)
        self.lbl_status = ttk.Label(prog_card, text="Bereit.", style="Subtle.TLabel")
        self.lbl_status.grid(row=0, column=1, sticky="e", padx=10, pady=10)
        prog_card.grid_columnconfigure(0, weight=1)

        # Buttons
        box_btns = ttk.Frame(self)
        box_btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(box_btns, text="Start", command=self._start, style="Accent.TButton")
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(box_btns, text="Stop", command=self._stop, state="disabled", style="TButton")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(box_btns, text="Clear Log", command=self._clear_log, style="TButton").pack(side="right")
        ttk.Button(box_btns, text="Copy Log", command=self._copy_log, style="TButton").pack(side="right", padx=6)

        # Log
        log_box = ttk.LabelFrame(self, text="Log")
        log_box.pack(fill="both", expand=True, **pad)

        self.txt = tk.Text(
            log_box,
            wrap="word",
            height=18,
            bg=self._colors["bg_alt"],
            fg=self._colors["fg"],
            insertbackground=self._colors["fg"],  # Cursor-Farbe
            relief="flat",
            highlightthickness=1,
            highlightbackground=self._colors["border"],
            padx=10,
            pady=10,
        )
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_box, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)

        # Live-Update file count when path changes
        self.var_dir.trace_add("write", lambda *args: self._update_count_label())

    # ---- Small actions ----
    def _toggle_pw(self):
        self._pass_entry.configure(show="" if self._show_pw.get() else "•")

    def _browse_dir(self):
        path = filedialog.askdirectory(title="Ordner wählen")
        if path:
            self.var_dir.set(path)

    def _open_dir(self):
        p = self.var_dir.get().strip()
        if not p:
            return
        path = Path(p)
        if not path.exists():
            messagebox.showerror("Fehler", "Ordner existiert nicht.")
            return
        try:
            if Path().anchor:  # Windows
                import os
                os.startfile(str(path))
            else:
                import subprocess, platform
                if platform.system() == "Darwin":
                    subprocess.run(["open", str(path)])
                else:
                    subprocess.run(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Fehler", f"Konnte Ordner nicht öffnen:\n{e}")

    def _copy_log(self):
        try:
            txt = self.txt.get("1.0", "end-1c")
            self.clipboard_clear()
            self.clipboard_append(txt)
        except Exception:
            pass

    def _clear_log(self):
        self.txt.delete("1.0", "end")

    def _update_count_label(self):
        directory = self.var_dir.get().strip()
        if not directory:
            self.lbl_count.configure(text="0 Dateien (0 B)")
            return
        root = Path(directory).expanduser()
        if not root.exists():
            self.lbl_count.configure(text="0 Dateien (0 B)")
            return
        include = [s.strip() for s in self.var_inc.get().split(",") if s.strip()]
        exclude = [s.strip() for s in self.var_exc.get().split(",") if s.strip()]
        recursive = self.var_recursive.get()
        files = collect_files(root, include, exclude, recursive=recursive)
        total = sum(p.stat().st_size for p in files) if files else 0
        self.lbl_count.configure(text=f"{len(files)} Dateien ({human_bytes(total)})")

    # ---- Log queue ----
    def _log(self, msg: str):
        self.log_q.put(msg)

    def _drain_log_queue(self):
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.txt.insert("end", msg + "\n")
                self.txt.see("end")
        except Empty:
            pass
        finally:
            self.after(100, self._drain_log_queue)

    # ---- Run control ----
    def _set_running(self, running: bool):
        self.running = running
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

    def _test_login(self):
        user = self.var_user.get().strip()
        pw = self.var_pass.get()
        if not user or not pw:
            messagebox.showerror("Fehler", "Bitte Benutzer und Passwort angeben.")
            return
        self._log("→ Test-Login…")
        try:
            s = upload.create_session(user, pw)
            self._log("✓ Login erfolgreich.")
            messagebox.showinfo("OK", "Login erfolgreich.")
            s.close()
        except Exception as e:
            self._log(f"✗ Login fehlgeschlagen → {e}")
            messagebox.showerror("Login fehlgeschlagen", str(e))

    def _start(self):
        if self.running:
            return
        user = self.var_user.get().strip()
        pw = self.var_pass.get()
        directory = self.var_dir.get().strip()

        if not user or not pw:
            messagebox.showerror("Fehler", "Bitte Benutzer und Passwort angeben.")
            return
        if not directory:
            messagebox.showerror("Fehler", "Bitte Ordner auswählen.")
            return

        include = [s.strip() for s in self.var_inc.get().split(",") if s.strip()]
        exclude = [s.strip() for s in self.var_exc.get().split(",") if s.strip()]
        recursive = self.var_recursive.get()
        workers = max(1, min(int(self.var_workers.get()), 5))
        dry = self.var_dry.get()

        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            messagebox.showerror("Fehler", f"Ordner nicht gefunden:\n{root}")
            return

        files = collect_files(root, include, exclude, recursive=recursive)
        if not files:
            messagebox.showinfo("Info", "Keine passenden Dateien gefunden.")
            return

        self.progress_total = len(files)
        self.progress_done = 0
        self.prog.configure(mode="determinate", maximum=self.progress_total, value=0)
        self.lbl_status.configure(text=f"{self.progress_done}/{self.progress_total} Dateien")

        self._set_running(True)
        self.txt.delete("1.0", "end")
        self._log(f"Gefundene Dateien: {len(files)}")
        total_bytes = sum(p.stat().st_size for p in files)
        self._log(f"Gesamtgröße: {human_bytes(total_bytes)}")
        for p in files[:12]:
            self._log(f"  • {p.relative_to(root)}")
        if len(files) > 12:
            self._log("  …")

        # Settings speichern
        self._save_settings()

        self.worker_thread = threading.Thread(
            target=self._worker, args=(user, pw, files, dry, workers), daemon=True
        )
        self.worker_thread.start()

    def _stop(self):
        if self.running:
            self._log("Stop angefordert…")
            self._set_running(False)

    def _bump_progress(self):
        # smooth-ish
        self.progress_done += 1
        self.prog.configure(value=self.progress_done)
        self.lbl_status.configure(text=f"{self.progress_done}/{self.progress_total} Dateien")

    def _worker(self, user, pw, files, dry, workers):
        t0 = time.time()
        ok = 0
        fail = 0

        try:
            self._log("→ Login…")
            session = upload.create_session(user, pw)
            self._log("✓ Login ok.")

            if dry:
                self._log("Dry-Run aktiv: Es wird nichts hochgeladen.")
                for p in files:
                    if not self.running:
                        break
                    self._log(f"[DRY] {p.name}")
                    self._bump_progress()
                return

            lock = threading.Lock()

            def do_one(p: Path):
                nonlocal ok, fail
                if not self.running:
                    return
                try:
                    res = upload.upload_with_session(session, str(p))
                    with lock:
                        ok += 1
                        self._log(f"✓ {p.name} ({res['mime']}, {human_bytes(res['size'])})")
                except Exception as e:
                    with lock:
                        fail += 1
                        self._log(f"✗ {p.name} → {e}")
                finally:
                    self._bump_progress()

            if workers == 1:
                for p in files:
                    if not self.running:
                        break
                    do_one(p)
            else:
                # Simple Thread-Pool
                it = iter(files)

                def feeder():
                    for p in it:
                        if not self.running:
                            break
                        do_one(p)

                threads = [threading.Thread(target=feeder, daemon=True) for _ in range(workers)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

        finally:
            dt = time.time() - t0
            self._log(f"\nFertig: {ok} ok, {fail} fail, in {dt:.1f}s")
            self._set_running(False)

    # ---- Settings ----
    def _save_settings(self):
        data = {
            "user": self.var_user.get().strip(),
            "dir": self.var_dir.get().strip(),
            "include": self.var_inc.get(),
            "exclude": self.var_exc.get(),
            "recursive": self.var_recursive.get(),
            "workers": int(self.var_workers.get()),
            "dry": self.var_dry.get(),
        }
        try:
            SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_settings(self):
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                self.var_user.set(data.get("user", ""))
                self.var_dir.set(data.get("dir", ""))
                self.var_inc.set(data.get("include", "*"))
                self.var_exc.set(data.get("exclude", "*.tmp,*.ds_store"))
                self.var_recursive.set(bool(data.get("recursive", True)))
                self.var_workers.set(int(data.get("workers", 2)))
                self.var_dry.set(bool(data.get("dry", False)))
                self._update_count_label()
        except Exception:
            pass


if __name__ == "__main__":
    app = SyncGUI()
    # DPI scaling (Windows)
    try:
        from ctypes import windll  # noqa: F401
        app.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    app.mainloop()
