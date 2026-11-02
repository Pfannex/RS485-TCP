"""RS485-TCP Monitor: Statusanzeige Gateway (ET69C02) und Umrichter (Toshiba VF-S15).

Start:
    py app.py
"""

import bisect
import csv
import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk

from rs485tcp.modbus_client import ModbusClient, ModbusError, ModbusException, check_port
from rs485tcp.vfs15 import MONITOR, MONITOR_ALL, describe, format_value, scan_addresses

GREY, GREEN, RED, ORANGE = "#9e9e9e", "#2e7d32", "#c62828", "#ef6c00"
HEARTBEAT_S = 3.0
EXPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports")


class Lamp(tk.Canvas):
    def __init__(self, master, size=18):
        super().__init__(master, width=size, height=size, highlightthickness=0)
        self._dot = self.create_oval(2, 2, size - 2, size - 2, fill=GREY, outline="")

    def set(self, color):
        self.itemconfigure(self._dot, fill=color)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RS485-TCP Monitor – ET69C02 / Toshiba VF-S15")
        self.minsize(760, 620)

        self.host = tk.StringVar(value="192.168.1.69")
        self.port = tk.IntVar(value=8887)
        self.unit = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="tcp")
        self.interval = tk.DoubleVar(value=2.0)
        self.polling = tk.BooleanVar(value=False)
        self.poll_all = tk.BooleanVar(value=False)

        self.results = queue.Queue()
        self.busy = False
        self.poll_job = None
        self.gw_online = None
        self.abort = threading.Event()
        self.ctx = {}        # zuletzt gelesene Rohwerte (für A/V-Umrechnung)
        self.all_rows = {}   # Adresse -> (Bereich, Name, Wert, Roh)
        self.shown = []      # sortierte Adressen, die in der Tabelle stehen

        self._build()
        self.after(100, self._drain)
        self.after(200, self._heartbeat)

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

        status = ttk.LabelFrame(self, text="Status")
        status.pack(fill="x", **pad)
        self.gw_lamp, self.gw_text = Lamp(status), ttk.Label(status, text="unbekannt")
        self.fu_lamp, self.fu_text = Lamp(status), ttk.Label(status, text="unbekannt")
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
        ttk.Checkbutton(ctl, text="alle Monitore mitlesen", variable=self.poll_all).pack(side="left", **pad)
        self.last = ttk.Label(ctl, text="")
        self.last.pack(side="right", **pad)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)

        # Reiter 1: Übersicht
        tab1 = ttk.Frame(nb)
        nb.add(tab1, text="Übersicht")
        self.tree = ttk.Treeview(tab1, columns=("addr", "name", "value"), show="headings", height=9)
        for col, text, width in (("addr", "Register", 80), ("name", "Name", 200), ("value", "Wert", 380)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        for address, (name, _s, _u) in MONITOR.items():
            self.tree.insert("", "end", iid=str(address), values=(f"0x{address:04X}", name, "–"))
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)

        # Reiter 2: Alle Register
        tab2 = ttk.Frame(nb)
        nb.add(tab2, text="Alle Register")
        bar = ttk.Frame(tab2)
        bar.pack(fill="x", padx=4, pady=4)
        self.btn_mon = ttk.Button(bar, text="Alle Monitore lesen", command=self.read_monitors)
        self.btn_mon.pack(side="left", padx=3)
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
        self.progress = ttk.Progressbar(tab2, mode="determinate")
        self.progress.pack(fill="x", padx=4)
        self.progress_text = ttk.Label(tab2, text="Noch nicht gelesen.")
        self.progress_text.pack(anchor="w", padx=4)

        cols = (("addr", "Register", 70), ("area", "Bereich", 80), ("name", "Name / Kürzel", 260),
                ("value", "Wert", 220), ("dec", "Roh dez", 70), ("hex", "Roh hex", 70))
        frame = ttk.Frame(tab2)
        frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.all_tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings")
        for col, text, width in cols:
            self.all_tree.heading(col, text=text)
            self.all_tree.column(col, width=width, anchor="w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.all_tree.yview)
        self.all_tree.configure(yscrollcommand=sb.set)
        self.all_tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", **pad)
        self.log = tk.Text(logf, height=6, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _params(self):
        try:
            return self.host.get().strip(), self.port.get(), self.unit.get(), self.mode.get()
        except tk.TclError:
            self._log("Ungültige Eingabe bei Port/Unit")
            return None

    def _start(self, target, *args):
        params = self._params()
        if self.busy or params is None:
            return False
        self.busy = True
        self.abort.clear()
        for b in (self.btn_query, self.btn_mon, self.btn_scan):
            b.configure(state="disabled")
        threading.Thread(target=target, args=params + args, daemon=True).start()
        return True

    # --- Gateway-Heartbeat ------------------------------------------------

    def _heartbeat(self):
        """Prüft das Gateway zyklisch, unabhängig von Umrichter-Abfragen."""
        if not self.busy:
            try:
                host, port = self.host.get().strip(), self.port.get()
            except tk.TclError:
                host = None
            if host:
                threading.Thread(target=self._heartbeat_worker, args=(host, port), daemon=True).start()
        self.after(int(HEARTBEAT_S * 1000), self._heartbeat)

    def _heartbeat_worker(self, host, port):
        modbus = check_port(host, port, 1.5)
        web = check_port(host, 80, 1.5)
        if modbus:
            self.results.put(("gateway", True, f"online – Modbus-Port {port} offen"))
        elif web:
            self.results.put(("gateway", False, f"online, aber Port {port} zu (Local port prüfen)"))
        else:
            self.results.put(("gateway", False, f"offline – {host} nicht erreichbar"))

    # --- Abfragen (Hintergrund-Threads) ------------------------------------

    def query(self):
        addresses = list(MONITOR)
        if self.poll_all.get():
            addresses += [a for a in MONITOR_ALL if a not in MONITOR]
        self._start(self._read_worker, addresses, "Abfrage")

    def read_monitors(self):
        self._start(self._read_worker, list(MONITOR_ALL), "Monitore")

    def full_scan(self):
        if self._start(self._read_worker, scan_addresses(), "Vollscan"):
            self.all_rows.clear()
            self._refill_all()

    def _read_worker(self, host, port, unit, mode, addresses, label):
        """Liest die Adressen nacheinander. Nicht vorhandene liefern Exception 0x02."""
        t0 = time.monotonic()
        if not check_port(host, port):
            web = check_port(host, 80, 1.0)
            self.results.put(("gateway", False, f"Port {port} zu (Web-Interface {'offen' if web else 'zu'})"))
            self.results.put(("fu", None, "keine Verbindung zum Gateway"))
            self.results.put(("done", label, None))
            return
        self.results.put(("gateway", True, f"online – Modbus-Port {port} offen"))

        values, missing, total = {}, 0, len(addresses)
        client = ModbusClient(host, port, unit, mode, timeout=1.0)
        try:
            client.connect()
            for i, address in enumerate(addresses, 1):
                if self.abort.is_set():
                    self.results.put(("fu", True, f"{label} abgebrochen nach {i - 1}/{total}"))
                    break
                try:
                    raw = client.read_holding(address)[0]
                    values[address] = raw
                    self.results.put(("row", address, raw))
                except ModbusException as e:
                    if e.code != 0x02:
                        raise
                    missing += 1
                if i % 20 == 0 or i == total:
                    self.results.put(("progress", (i, total), label))
            else:
                ms = (time.monotonic() - t0) * 1000
                self.results.put(("fu", True, f"antwortet – {label}: {len(values)} Register gelesen, "
                                              f"{missing} nicht vorhanden ({ms / 1000:.1f} s)"))
        except ModbusException as e:
            self.results.put(("fu", False, str(e)))
        except (socket.timeout, TimeoutError):
            self.results.put(("fu", False, "keine Antwort (Timeout)" if not values
                              else f"Timeout nach {len(values)} Registern"))
        except (ModbusError, OSError) as e:
            self.results.put(("fu", False, f"Fehler: {e}"))
        finally:
            client.close()
        self.results.put(("done", label, None))

    # --- Ergebnisse in die GUI ----------------------------------------------

    def _drain(self):
        changed_rows = set()
        while not self.results.empty():
            kind, a, b = self.results.get()
            if kind == "gateway":
                self.gw_lamp.set(GREEN if a else RED)
                self.gw_text.configure(text=b)
                if a != self.gw_online:
                    self._log(f"Gateway: {b}")
                    self.gw_online = a
            elif kind == "fu":
                self.fu_lamp.set(GREY if a is None else GREEN if a else RED)
                self.fu_text.configure(text=b)
                self._log(f"Umrichter: {b}")
            elif kind == "row":
                self.ctx[a] = b
                if a in MONITOR:
                    self.tree.set(str(a), "value", format_value(a, b, self.ctx))
                area, name = describe(a)
                self.all_rows[a] = (area, name, format_value(a, b, self.ctx), b)
                changed_rows.add(a)
            elif kind == "progress":
                done, total = a
                self.progress.configure(maximum=total, value=done)
                self.progress_text.configure(text=f"{b}: {done}/{total} Adressen, "
                                                  f"{len(self.all_rows)} Register in der Tabelle")
            elif kind == "done":
                self.busy = False
                for btn in (self.btn_query, self.btn_mon, self.btn_scan):
                    btn.configure(state="normal")
                self.last.configure(text=f"Letzte Abfrage: {time.strftime('%H:%M:%S')}")
                self._schedule()
        if changed_rows:
            self._refill_all(changed_rows)
        self.after(100, self._drain)

    def _refill_all(self, addresses=None):
        """Tabelle aktualisieren: nur die übergebenen Adressen, sonst komplett neu."""
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

    def export_csv(self):
        if not self.all_rows:
            self._log("Nichts zu exportieren – erst Monitore lesen oder Vollscan")
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
            self._log("Polling gestoppt")

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


if __name__ == "__main__":
    App().mainloop()
