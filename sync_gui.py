#!/usr/bin/env python3
# sync_gui.py
import threading
import time
from pathlib import Path
from fnmatch import fnmatch
from queue import Queue, Empty

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# WICHTIG: Deine upload.py liegt im gleichen Ordner
import upload  # erwartet: create_session(), upload_with_session()

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

class SyncGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Brandenburg Cloud – Folder Sync")
        self.geometry("820x560")
        self.minsize(760, 520)

        self._build_ui()

        # state
        self.running = False
        self.log_q: Queue[str] = Queue()
        self.progress_total = 0
        self.progress_done = 0
        self.worker_thread = None

        # pump log queue to textbox
        self.after(100, self._drain_log_queue)

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", **pad)

        # Credentials
        box_creds = ttk.LabelFrame(frm_top, text="Login")
        box_creds.pack(side="left", fill="both", expand=True, **pad)

        ttk.Label(box_creds, text="Benutzer (E-Mail):").grid(row=0, column=0, sticky="w")
        self.var_user = tk.StringVar()
        ttk.Entry(box_creds, textvariable=self.var_user, width=36).grid(row=0, column=1, sticky="we", padx=6)

        ttk.Label(box_creds, text="Passwort:").grid(row=1, column=0, sticky="w")
        self.var_pass = tk.StringVar()
        ttk.Entry(box_creds, textvariable=self.var_pass, show="•", width=36).grid(row=1, column=1, sticky="we", padx=6)

        for i in range(2):
            box_creds.grid_columnconfigure(i, weight=1)

        # Folder
        box_folder = ttk.LabelFrame(frm_top, text="Ordner")
        box_folder.pack(side="left", fill="both", expand=True, **pad)

        self.var_dir = tk.StringVar()
        ttk.Entry(box_folder, textvariable=self.var_dir).grid(row=0, column=0, sticky="we", padx=6)
        ttk.Button(box_folder, text="Browse…", command=self._browse_dir).grid(row=0, column=1, sticky="w")
        for i in (0,):
            box_folder.grid_columnconfigure(i, weight=1)

        # Options
        box_opts = ttk.LabelFrame(self, text="Optionen")
        box_opts.pack(fill="x", **pad)

        ttk.Label(box_opts, text="Include (CSV):").grid(row=0, column=0, sticky="w")
        self.var_inc = tk.StringVar(value="*")
        ttk.Entry(box_opts, textvariable=self.var_inc).grid(row=0, column=1, sticky="we", padx=6)

        ttk.Label(box_opts, text="Exclude (CSV):").grid(row=1, column=0, sticky="w")
        self.var_exc = tk.StringVar(value="*.tmp,*.ds_store")
        ttk.Entry(box_opts, textvariable=self.var_exc).grid(row=1, column=1, sticky="we", padx=6)

        self.var_recursive = tk.BooleanVar(value=True)
        ttk.Checkbutton(box_opts, text="Rekursiv", variable=self.var_recursive).grid(row=0, column=2, sticky="w", padx=10)

        self.var_dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(box_opts, text="Dry-Run (nur anzeigen)", variable=self.var_dry).grid(row=1, column=2, sticky="w", padx=10)

        ttk.Label(box_opts, text="Parallel (1–5):").grid(row=0, column=3, sticky="e")
        self.var_workers = tk.IntVar(value=2)
        ttk.Spinbox(box_opts, from_=1, to=5, textvariable=self.var_workers, width=5).grid(row=0, column=4, sticky="w")

        for c in (1,):
            box_opts.grid_columnconfigure(c, weight=1)

        # Progress
        box_prog = ttk.Frame(self)
        box_prog.pack(fill="x", **pad)
        self.prog = ttk.Progressbar(box_prog, mode="determinate")
        self.prog.pack(fill="x", padx=4)

        self.lbl_status = ttk.Label(box_prog, text="Bereit.")
        self.lbl_status.pack(anchor="w", padx=4, pady=2)

        # Buttons
        box_btns = ttk.Frame(self)
        box_btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(box_btns, text="Start", command=self._start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(box_btns, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)

        # Log
        box_log = ttk.LabelFrame(self, text="Log")
        box_log.pack(fill="both", expand=True, **pad)

        self.txt = tk.Text(box_log, wrap="word", height=18)
        self.txt.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(box_log, command=self.txt.yview)
        sb.pack(side="right", fill="y")
        self.txt.configure(yscrollcommand=sb.set)

    def _browse_dir(self):
        path = filedialog.askdirectory(title="Ordner wählen")
        if path:
            self.var_dir.set(path)

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
            self.after(120, self._drain_log_queue)

    def _set_running(self, running: bool):
        self.running = running
        state = "disabled" if running else "normal"
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")

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
        for p in files[:10]:
            self._log(f"  - {p.relative_to(root)}")
        if len(files) > 10:
            self._log("  ...")

        self.worker_thread = threading.Thread(
            target=self._worker, args=(user, pw, files, dry, workers), daemon=True
        )
        self.worker_thread.start()

    def _stop(self):
        if self.running:
            self._log("Stop angefordert…")
            # Soft-stop: wir setzen Flag, Worker checkt es
            self._set_running(False)

    def _bump_progress(self):
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

            # Worker-Funktion
            lock = threading.Lock()

            def do_one(p: Path):
                nonlocal ok, fail
                if not self.running:
                    return
                try:
                    res = upload.upload_with_session(session, str(p))
                    with lock:
                        ok += 1
                        self._log(f"✓ {p.name} ({res['mime']}, {res['size']} B)")
                except Exception as e:
                    with lock:
                        fail += 1
                        self._log(f"✗ {p.name} → {e}")
                finally:
                    self._bump_progress()

            # Parallel oder seriell
            if workers == 1:
                for p in files:
                    if not self.running:
                        break
                    do_one(p)
            else:
                threads = []
                # simple pool
                it = iter(files)
                pending = True
                def feeder():
                    for p in it:
                        if not self.running:
                            break
                        do_one(p)

                for _ in range(workers):
                    t = threading.Thread(target=feeder, daemon=True)
                    threads.append(t)
                    t.start()
                for t in threads:
                    t.join()

        finally:
            dt = time.time() - t0
            self._log(f"\nFertig: {ok} ok, {fail} fail, in {dt:.1f}s")
            self._set_running(False)

if __name__ == "__main__":
    app = SyncGUI()
    # kleines Dark-ish Theme
    try:
        from ctypes import windll  # noqa
        app.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    ttk.Style().theme_use("clam")
    app.mainloop()
