"""RS485-TCP Monitor: Statusanzeige Gateway (ET69C02) und Umrichter (Toshiba VF-S15).

Start:
    py app.py
"""

import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

from rs485tcp.modbus_client import ModbusClient, ModbusError, ModbusException, check_port
from rs485tcp.vfs15 import MONITOR, format_value

GREY, GREEN, RED, ORANGE = "#9e9e9e", "#2e7d32", "#c62828", "#ef6c00"


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
        self.minsize(640, 520)

        self.host = tk.StringVar(value="192.168.1.69")
        self.port = tk.IntVar(value=8887)
        self.unit = tk.IntVar(value=1)
        self.mode = tk.StringVar(value="tcp")
        self.interval = tk.DoubleVar(value=2.0)
        self.polling = tk.BooleanVar(value=False)

        self.results = queue.Queue()
        self.busy = False
        self.poll_job = None

        self._build()
        self.after(100, self._drain)

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
        self.last = ttk.Label(ctl, text="")
        self.last.pack(side="right", **pad)

        vals = ttk.LabelFrame(self, text="Werte")
        vals.pack(fill="both", expand=True, **pad)
        self.tree = ttk.Treeview(vals, columns=("addr", "name", "value"), show="headings", height=9)
        for col, text, width in (("addr", "Register", 80), ("name", "Name", 200), ("value", "Wert", 300)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="w")
        for address, (name, _s, _u) in MONITOR.items():
            self.tree.insert("", "end", iid=str(address), values=(f"0x{address:04X}", name, "–"))
        self.tree.pack(fill="both", expand=True, padx=4, pady=4)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", **pad)
        self.log = tk.Text(logf, height=7, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    # --- Abfrage ----------------------------------------------------------

    def query(self):
        if self.busy:
            return
        try:
            params = (self.host.get().strip(), self.port.get(), self.unit.get(), self.mode.get())
        except tk.TclError:
            self._log("Ungültige Eingabe bei Port/Unit")
            return
        self.busy = True
        self.btn_query.configure(state="disabled")
        threading.Thread(target=self._worker, args=params, daemon=True).start()

    def _worker(self, host, port, unit, mode):
        """Läuft im Hintergrund; Ergebnisse gehen über die Queue an die GUI."""
        t0 = time.monotonic()
        if not check_port(host, port):
            web = check_port(host, 80, 1.0)
            self.results.put(("gateway", False, f"Port {port} zu (Web-Interface {'offen' if web else 'zu'})"))
            self.results.put(("fu", None, "keine Verbindung zum Gateway"))
            self.results.put(("done", None, None))
            return
        self.results.put(("gateway", True, f"{host}:{port} erreichbar"))

        values = {}
        client = ModbusClient(host, port, unit, mode, timeout=1.5)
        try:
            client.connect()
            for address in MONITOR:
                values[address] = client.read_holding(address)[0]
                time.sleep(0.03)
            ms = (time.monotonic() - t0) * 1000
            self.results.put(("fu", True, f"antwortet (Unit {unit}, {len(values)} Register, {ms:.0f} ms)"))
        except ModbusException as e:
            self.results.put(("fu", False, str(e)))
        except (socket.timeout, TimeoutError):
            self.results.put(("fu", False, "keine Antwort (Timeout)" if not values
                              else f"Timeout nach {len(values)} Registern"))
        except (ModbusError, OSError) as e:
            self.results.put(("fu", False, f"Fehler: {e}"))
        finally:
            client.close()
        self.results.put(("values", values, None))
        self.results.put(("done", None, None))

    def _drain(self):
        while not self.results.empty():
            kind, a, b = self.results.get()
            if kind == "gateway":
                self.gw_lamp.set(GREEN if a else RED)
                self.gw_text.configure(text=b)
                if not a:
                    self._log(f"Gateway: {b}")
            elif kind == "fu":
                self.fu_lamp.set(GREY if a is None else GREEN if a else RED)
                self.fu_text.configure(text=b)
                self._log(f"Umrichter: {b}")
            elif kind == "values":
                for address in MONITOR:
                    text = format_value(address, a[address]) if address in a else "–"
                    self.tree.set(str(address), "value", text)
            elif kind == "done":
                self.busy = False
                self.btn_query.configure(state="normal")
                self.last.configure(text=f"Letzte Abfrage: {time.strftime('%H:%M:%S')}")
                self._schedule()
        self.after(100, self._drain)

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
