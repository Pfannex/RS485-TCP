"""RS485-TCP Monitor: Statusanzeige Gateway (ET69C02) und Umrichter (Toshiba VF-S15).

Start:
    py app.py        (ohne Konsole: start_app.cmd)
"""

import bisect
import csv
import json
import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from rs485tcp.modbus_client import ModbusClient, ModbusError, ModbusException
from rs485tcp.vfs15 import (MONITOR, MONITOR_ALL, STATUS1_BITS, describe, format_param,
                            format_value, load_params, scan_addresses)

GREY, GREEN, RED, ORANGE = "#9e9e9e", "#2e7d32", "#c62828", "#ef6c00"
TICK_S = 2.0                 # Lebenszeichen-Abfrage des Umrichters
TICK_REGISTER = 0xFD01       # Status 1
HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(HERE, "exports")
POLL_FILE = os.path.join(HERE, "poll_list.json")
CHECK_ON, CHECK_OFF = "☑", "☐"


class Lamp(tk.Canvas):
    def __init__(self, master, size=18):
        super().__init__(master, width=size, height=size, highlightthickness=0)
        self._dot = self.create_oval(2, 2, size - 2, size - 2, fill=GREY, outline="")

    def set(self, color):
        self.itemconfigure(self._dot, fill=color)


class Link:
    """Eine TCP-Verbindung zum Gateway, von allen Threads gemeinsam genutzt (Lock)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.client = None
        self.settings = None

    @property
    def connected(self):
        return self.client is not None

    def open(self, host, port, unit, mode):
        with self.lock:
            self._close()
            self.settings = (host, port, unit, mode)
            self._connect()

    def close(self):
        with self.lock:
            self.settings = None
            self._close()

    def read(self, address):
        """Ein Register lesen. Nach Timeout wird neu verbunden (verspätete Antworten verwerfen)."""
        with self.lock:
            if self.settings is None:
                raise ModbusError("nicht verbunden")
            if self.client is None:
                self._connect()
            try:
                return self.client.read_holding(address)[0]
            except ModbusException:
                raise
            except (socket.timeout, TimeoutError):
                self._close()
                raise
            except (ModbusError, OSError):
                self._close()
                raise

    def _connect(self):
        host, port, unit, mode = self.settings
        client = ModbusClient(host, port, unit, mode, timeout=1.0)
        client.connect()
        self.client = client

    def _close(self):
        if self.client:
            self.client.close()
            self.client = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RS485-TCP Monitor – ET69C02 / Toshiba VF-S15")
        self.minsize(860, 680)

        self.host = tk.StringVar(value="192.168.1.69")
        self.port = tk.IntVar(value=8887)
        self.unit = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="tcp")
        self.interval = tk.DoubleVar(value=2.0)
        self.polling = tk.BooleanVar(value=False)

        self.link = Link()
        self.results = queue.Queue()
        self.busy = False
        self.job = None
        self.poll_job = None
        self.abort = threading.Event()
        self.stop_tick = threading.Event()
        self.ctx = {}        # zuletzt gelesene Rohwerte
        self.all_rows = {}   # Alle Register: Adresse -> (Bereich, Name, Wert, Roh)
        self.shown = []
        self.params = load_params()
        self.param_by_addr = {p["address"]: p for p in self.params}
        self.poll_set = self._load_poll_set()

        self._build()
        self.after(100, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI ---------------------------------------------------------------

    def _build(self):
        pad = {"padx": 6, "pady": 4}

        cfg = ttk.LabelFrame(self, text="Verbindung")
        cfg.pack(fill="x", **pad)
        ttk.Label(cfg, text="IP").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(cfg, textvariable=self.host, width=15).grid(row=0, column=1, **pad)
        ttk.Label(cfg, text="Port").grid(row=0, column=2, sticky="w", **pad)
        ttk.Entry(cfg, textvariable=self.port, width=6).grid(row=0, column=3, **pad)
        ttk.Label(cfg, text="Unit").grid(row=0, column=4, sticky="w", **pad)
        ttk.Spinbox(cfg, from_=1, to=247, textvariable=self.unit, width=5).grid(row=0, column=5, **pad)
        ttk.Label(cfg, text="Modus").grid(row=0, column=6, sticky="w", **pad)
        ttk.Combobox(cfg, textvariable=self.mode, values=("tcp", "rtu"), width=5,
                     state="readonly").grid(row=0, column=7, **pad)
        self.btn_connect = ttk.Button(cfg, text="Verbinden", command=self.toggle_connect)
        self.btn_connect.grid(row=0, column=8, **pad)

        status = ttk.LabelFrame(self, text="Status")
        status.pack(fill="x", **pad)
        self.gw_lamp, self.gw_text = Lamp(status), ttk.Label(status, text="getrennt")
        self.fu_lamp, self.fu_text = Lamp(status), ttk.Label(status, text="getrennt")
        ttk.Label(status, text="Gateway").grid(row=0, column=0, sticky="w", **pad)
        self.gw_lamp.grid(row=0, column=1, **pad)
        self.gw_text.grid(row=0, column=2, sticky="w", **pad)
        ttk.Label(status, text="Umrichter").grid(row=1, column=0, sticky="w", **pad)
        self.fu_lamp.grid(row=1, column=1, **pad)
        self.fu_text.grid(row=1, column=2, sticky="w", **pad)
        status.columnconfigure(2, weight=1)

        ctl = ttk.Frame(self)
        ctl.pack(fill="x", **pad)
        self.btn_query = ttk.Button(ctl, text="Jetzt abfragen", command=self.query)
        self.btn_query.pack(side="left", **pad)
        ttk.Checkbutton(ctl, text="Polling", variable=self.polling,
                        command=self._toggle_polling).pack(side="left", **pad)
        ttk.Label(ctl, text="Intervall (s)").pack(side="left")
        ttk.Spinbox(ctl, from_=0.5, to=60, increment=0.5, textvariable=self.interval,
                    width=5).pack(side="left", **pad)
        self.poll_info = ttk.Label(ctl, text="")
        self.poll_info.pack(side="left", **pad)
        self.last = ttk.Label(ctl, text="")
        self.last.pack(side="right", **pad)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)
        self._build_overview(nb)
        self._build_params(nb)
        self._build_all(nb)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", **pad)
        self.log = tk.Text(logf, height=5, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)
        self._update_poll_info()

    def _build_overview(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Übersicht")
        self.tree = ttk.Treeview(tab, columns=("addr", "name", "value"), show="headings", height=9)
        for col, text, width in (("addr", "Register", 80), ("name", "Name", 220), ("value", "Wert", 420)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        for address, (name, _s, _u) in MONITOR.items():
            self.tree.insert("", "end", iid=str(address), values=(f"0x{address:04X}", name, "–"))
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_params(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Parameter")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=4, pady=4)
        self.btn_params = ttk.Button(bar, text="Alle lesen", command=self.read_params)
        self.btn_params.pack(side="left", padx=3)
        self.btn_selected = ttk.Button(bar, text="Markierte lesen", command=self.read_selected)
        self.btn_selected.pack(side="left", padx=3)
        ttk.Button(bar, text="Abbrechen", command=self.abort.set).pack(side="left", padx=3)
        ttk.Button(bar, text="Alles aufklappen", command=lambda: self._expand(True)).pack(side="left", padx=3)
        ttk.Button(bar, text="Alles zuklappen", command=lambda: self._expand(False)).pack(side="left", padx=3)
        ttk.Button(bar, text="Polling-Liste leeren", command=self._clear_poll).pack(side="left", padx=3)
        ttk.Label(bar, text="Klick auf ☐ = ins Polling aufnehmen").pack(side="right", padx=3)

        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True, padx=4)
        cols = (("hex", "Adr. HEX", 70), ("dec", "Adr. DEZ", 70), ("value", "Wert", 260),
                ("unit", "Einheit", 70), ("poll", "Polling", 60))
        self.ptree = ttk.Treeview(frame, columns=[c[0] for c in cols])
        self.ptree.heading("#0", text="Klartext / Beschreibung")
        self.ptree.column("#0", width=380, anchor="w")
        for col, text, width in cols:
            self.ptree.heading(col, text=text)
            self.ptree.column(col, width=width, anchor="center" if col == "poll" else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.ptree.yview)
        self.ptree.configure(yscrollcommand=sb.set)
        self.ptree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.ptree.bind("<Button-1>", self._on_ptree_click)
        self.ptree.bind("<<TreeviewSelect>>", self._on_ptree_select)
        self.detail = ttk.Label(tab, text="", wraplength=820, justify="left")
        self.detail.pack(fill="x", padx=6, pady=4)

        # Monitorwerte als eigene Gruppe, dann die Handbuch-Gruppen in Reihenfolge
        g = self.ptree.insert("", "end", iid="g_mon", text="Monitorwerte (nur lesen)", open=False)
        for address, (name, _s, unit) in sorted(MONITOR_ALL.items()):
            self.ptree.insert(g, "end", iid=f"a{address}", text=name,
                              values=(f"0x{address:04X}", address, "–", "", self._mark(address)))
        groups = {}
        for p in self.params:
            if p["group"] not in groups:
                groups[p["group"]] = self.ptree.insert("", "end", iid=f"g{len(groups)}",
                                                       text=p["group"] or "Sonstige", open=False)
            if self.ptree.exists(f"a{p['address']}"):
                continue
            label = f"{p['title']} – {p['name']}" if p["name"] else p["title"]
            self.ptree.insert(groups[p["group"]], "end", iid=f"a{p['address']}", text=label,
                              values=(f"0x{p['address']:04X}", p["address"], "–", p["unit"],
                                      self._mark(p["address"])))

    def _build_all(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Alle Register (Scan)")
        bar = ttk.Frame(tab)
        bar.pack(fill="x", padx=4, pady=4)
        self.btn_scan = ttk.Button(bar, text="Vollscan (alle Adressen)", command=self.full_scan)
        self.btn_scan.pack(side="left", padx=3)
        ttk.Button(bar, text="Abbrechen", command=self.abort.set).pack(side="left", padx=3)
        ttk.Button(bar, text="CSV exportieren", command=self.export_csv).pack(side="left", padx=3)
        ttk.Label(bar, text="Filter").pack(side="left", padx=(12, 3))
        self.filter = tk.StringVar(value="alle")
        cb = ttk.Combobox(bar, textvariable=self.filter, values=("alle", "Monitor", "Parameter", "Befehl"),
                          width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda _e: self._refill_all())
        self.progress = ttk.Progressbar(tab, mode="determinate")
        self.progress.pack(fill="x", padx=4)
        self.progress_text = ttk.Label(tab, text="Noch nicht gelesen.")
        self.progress_text.pack(anchor="w", padx=4)

        cols = (("addr", "Register", 70), ("area", "Bereich", 80), ("name", "Name / Kürzel", 260),
                ("value", "Wert", 220), ("dec", "Roh dez", 70), ("hex", "Roh hex", 70))
        frame = ttk.Frame(tab)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.all_tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings")
        for col, text, width in cols:
            self.all_tree.heading(col, text=text)
            self.all_tree.column(col, width=width, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.all_tree.yview)
        self.all_tree.configure(yscrollcommand=sb.set)
        self.all_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # --- Verbindung & Lebenszeichen -----------------------------------------

    def toggle_connect(self):
        if self.link.settings is not None:
            self.stop_tick.set()
            self.polling.set(False)
            self._toggle_polling()
            self.link.close()
            self.btn_connect.configure(text="Verbinden")
            for lamp, label in ((self.gw_lamp, self.gw_text), (self.fu_lamp, self.fu_text)):
                lamp.set(GREY)
                label.configure(text="getrennt")
            self._log("Verbindung getrennt")
            return
        try:
            settings = (self.host.get().strip(), self.port.get(), self.unit.get(), self.mode.get())
        except tk.TclError:
            self._log("Ungültige Eingabe bei Port/Unit")
            return
        self.btn_connect.configure(text="Trennen")
        self.stop_tick.clear()
        threading.Thread(target=self._tick_worker, args=(settings,), daemon=True).start()

    def _tick_worker(self, settings):
        """Verbindet und liest alle TICK_S Sekunden Status 1, solange verbunden."""
        host, port = settings[0], settings[1]
        try:
            self.link.open(*settings)
            self.results.put(("gateway", True, f"verbunden mit {host}:{port}"))
        except OSError as e:
            self.results.put(("gateway", False, f"Verbindung fehlgeschlagen: {e}"))
        while not self.stop_tick.is_set():
            try:
                t0 = time.monotonic()
                raw = self.link.read(TICK_REGISTER)
                ms = (time.monotonic() - t0) * 1000
                self.results.put(("gateway", True, f"verbunden mit {host}:{port}"))
                self.results.put(("tick", raw, ms))
            except ModbusException as e:
                self.results.put(("fu", False, str(e)))
            except (socket.timeout, TimeoutError):
                self.results.put(("fu", False, "keine Antwort (Timeout)"))
            except (ModbusError, OSError) as e:
                if self.link.settings is None:
                    break
                self.results.put(("gateway", False, f"nicht erreichbar: {e}"))
                self.results.put(("fu", None, "kein Gateway"))
            self.stop_tick.wait(TICK_S)

    # --- Lesen (Hintergrund-Threads) ---------------------------------------

    def _start(self, addresses, label, show_progress=False):
        if self.busy:
            return False
        if self.link.settings is None:
            self._log("Erst verbinden")
            self.polling.set(False)
            return False
        self.busy = True
        self.job = label
        self.abort.clear()
        for b in (self.btn_query, self.btn_params, self.btn_selected, self.btn_scan):
            b.configure(state="disabled")
        threading.Thread(target=self._read_worker, args=(addresses, label, show_progress),
                         daemon=True).start()
        return True

    def query(self):
        addresses = list(MONITOR) + sorted(a for a in self.poll_set if a not in MONITOR)
        self._start(addresses, "Abfrage")

    def read_params(self):
        self._start([p["address"] for p in self.params] + sorted(MONITOR_ALL), "Parameter", True)

    def read_selected(self):
        addresses = sorted(int(i[1:]) for i in self.ptree.selection() if i.startswith("a"))
        for i in self.ptree.selection():
            if i.startswith("g"):
                addresses += [int(c[1:]) for c in self.ptree.get_children(i)]
        if addresses:
            self._start(sorted(set(addresses)), "Markierte", True)

    def full_scan(self):
        if self._start(scan_addresses(), "Vollscan", True):
            self.all_rows.clear()
            self._refill_all()

    def _read_worker(self, addresses, label, show_progress):
        t0 = time.monotonic()
        values, missing, total = 0, 0, len(addresses)
        try:
            for i, address in enumerate(addresses, 1):
                if self.abort.is_set():
                    self.results.put(("fu", True, f"{label} abgebrochen nach {i - 1}/{total}"))
                    break
                try:
                    self.results.put(("row", address, self.link.read(address)))
                    values += 1
                except ModbusException as e:
                    if e.code != 0x02:
                        raise
                    missing += 1
                if show_progress and (i % 20 == 0 or i == total):
                    self.results.put(("progress", (i, total), label))
            else:
                if label != "Abfrage":
                    s = time.monotonic() - t0
                    self.results.put(("fu", True, f"{label}: {values} gelesen, "
                                                  f"{missing} nicht vorhanden ({s:.1f} s)"))
        except ModbusException as e:
            self.results.put(("fu", False, str(e)))
        except (socket.timeout, TimeoutError):
            self.results.put(("fu", False, f"keine Antwort (Timeout) nach {values} Registern"))
        except (ModbusError, OSError) as e:
            self.results.put(("fu", False, f"Fehler: {e}"))
        self.results.put(("done", label, None))

    # --- Ergebnisse in die GUI ----------------------------------------------

    def _drain(self):
        changed = set()
        while not self.results.empty():
            kind, a, b = self.results.get()
            if kind == "gateway":
                self.gw_lamp.set(GREEN if a else RED)
                if self.gw_text.cget("text") != b:
                    self.gw_text.configure(text=b)
                    self._log(f"Gateway: {b}")
            elif kind == "tick":
                active = [t for bit, t in STATUS1_BITS.items() if a & (1 << bit)]
                trip = a & 0b110
                self.fu_lamp.set(ORANGE if trip else GREEN)
                self._set_fu(f"online – {', '.join(active) or 'Stopp'} ({b:.0f} ms)", log=False)
                self.ctx[TICK_REGISTER] = a
            elif kind == "fu":
                self.fu_lamp.set(GREY if a is None else GREEN if a else RED)
                self._set_fu(b)
            elif kind == "row":
                self._store(a, b)
                changed.add(a)
            elif kind == "progress":
                done, total = a
                self.progress.configure(maximum=total, value=done)
                self.progress_text.configure(text=f"{b}: {done}/{total} Adressen")
            elif kind == "done":
                self.busy = False
                self.job = None
                for btn in (self.btn_query, self.btn_params, self.btn_selected, self.btn_scan):
                    btn.configure(state="normal")
                self.last.configure(text=f"Letzte Abfrage: {time.strftime('%H:%M:%S')}")
                self._schedule()
        scan_changed = {a for a in changed if a in self.all_rows}
        if scan_changed:
            self._refill_all(scan_changed)
        self.after(100, self._drain)

    def _set_fu(self, text, log=True):
        old = self.fu_text.cget("text")
        self.fu_text.configure(text=text)
        if log and old != text:
            self._log(f"Umrichter: {text}")
        elif not log and not old.startswith("online"):
            self._log("Umrichter: online")

    def _store(self, address, raw):
        self.ctx[address] = raw
        if address in MONITOR:
            self.tree.set(str(address), "value", format_value(address, raw, self.ctx))
        iid = f"a{address}"
        if self.ptree.exists(iid):
            p = self.param_by_addr.get(address)
            text = format_param(p, raw) if p else format_value(address, raw, self.ctx)
            self.ptree.set(iid, "value", text)
        if self.job == "Vollscan" or address in self.all_rows:
            area, name = describe(address)
            self.all_rows[address] = (area, name, format_value(address, raw, self.ctx), raw)

    def _refill_all(self, addresses=None):
        """Scan-Tabelle aktualisieren: nur die übergebenen Adressen, sonst komplett neu."""
        wanted = self.filter.get()
        if addresses is None:
            self.all_tree.delete(*self.all_tree.get_children())
            self.shown = []
            addresses = self.all_rows
        for address in sorted(addresses):
            area, name, value, raw = self.all_rows[address]
            if wanted not in ("alle", area):
                continue
            row = (f"0x{address:04X}", area, name, value, raw, f"0x{raw:04X}")
            if self.all_tree.exists(str(address)):
                self.all_tree.item(str(address), values=row)
            else:
                index = bisect.bisect(self.shown, address)
                self.shown.insert(index, address)
                self.all_tree.insert("", index, iid=str(address), values=row)

    # --- Parameterbaum: Checkboxen & Details --------------------------------

    def _mark(self, address):
        return CHECK_ON if address in self.poll_set else CHECK_OFF

    def _on_ptree_click(self, event):
        if self.ptree.identify_column(event.x) != "#5":   # Spalte "Polling"
            return
        iid = self.ptree.identify_row(event.y)
        if not iid:
            return
        targets = self.ptree.get_children(iid) if iid.startswith("g") else [iid]
        addrs = [int(t[1:]) for t in targets]
        turn_on = not all(a in self.poll_set for a in addrs)
        for t, a in zip(targets, addrs):
            (self.poll_set.add if turn_on else self.poll_set.discard)(a)
            self.ptree.set(t, "poll", self._mark(a))
        self._save_poll_set()
        return "break"

    def _on_ptree_select(self, _event):
        sel = self.ptree.selection()
        if not sel or not sel[0].startswith("a"):
            self.detail.configure(text="")
            return
        address = int(sel[0][1:])
        p = self.param_by_addr.get(address)
        if p:
            text = (f"{p['title']}  (0x{address:04X} / {address}) – {p['name']}\n"
                    f"Einstellbereich: {p['range'] or '–'}   |   Werkseinstellung: {p['default'] or '–'}   |   "
                    f"Auflösung Panel/Komm.: {p['resolution'] or '–'}   |   Handbuch DE S. {p['page']}")
        else:
            name, _scale, unit = MONITOR_ALL[address]
            text = f"Monitor 0x{address:04X} / {address} – {name} {unit}"
        if address in self.ctx:
            text += f"   |   Rohwert {self.ctx[address]} (0x{self.ctx[address]:04X})"
        self.detail.configure(text=text)

    def _expand(self, state):
        for g in self.ptree.get_children(""):
            self.ptree.item(g, open=state)

    def _clear_poll(self):
        for a in list(self.poll_set):
            if self.ptree.exists(f"a{a}"):
                self.ptree.set(f"a{a}", "poll", CHECK_OFF)
        self.poll_set.clear()
        self._save_poll_set()

    def _load_poll_set(self):
        try:
            with open(POLL_FILE, encoding="utf-8") as f:
                return set(json.load(f).get("addresses", []))
        except (OSError, ValueError):
            return set()

    def _save_poll_set(self):
        with open(POLL_FILE, "w", encoding="utf-8") as f:
            json.dump({"addresses": sorted(self.poll_set)}, f, indent=1)
        self._update_poll_info()

    def _update_poll_info(self):
        self.poll_info.configure(text=f"Polling-Liste: Übersicht + {len(self.poll_set)} markierte")

    # --- Export -------------------------------------------------------------

    def export_csv(self):
        if not self.all_rows:
            self._log("Nichts zu exportieren – erst Vollscan")
            return
        os.makedirs(EXPORT_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            initialdir=EXPORT_DIR, initialfile=f"vfs15_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Register", "Bereich", "Name/Kürzel", "Wert", "Roh dez", "Roh hex"])
            for address in sorted(self.all_rows):
                area, name, value, raw = self.all_rows[address]
                w.writerow([f"0x{address:04X}", area, name, value, raw, f"0x{raw:04X}"])
        self._log(f"Exportiert: {path} ({len(self.all_rows)} Register)")

    # --- Polling ----------------------------------------------------------

    def _toggle_polling(self):
        if self.polling.get():
            self._log("Polling gestartet")
            self.query()
        else:
            if self.poll_job:
                self.after_cancel(self.poll_job)
                self.poll_job = None

    def _schedule(self):
        if self.polling.get() and self.poll_job is None:
            try:
                delay = max(0.5, float(self.interval.get()))
            except (tk.TclError, ValueError):
                delay = 2.0
            self.poll_job = self.after(int(delay * 1000), self._poll_tick)

    def _poll_tick(self):
        self.poll_job = None
        if self.polling.get():
            self.query()

    def _on_close(self):
        self.stop_tick.set()
        self.abort.set()
        self.link.close()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
