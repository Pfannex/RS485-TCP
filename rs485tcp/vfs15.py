"""Register und Dekodierung für den Toshiba VF-S15.

Quellen: E6581913 (RS485-Kommunikation, Kap. 8 + Monitor-Tabelle S. 70/71),
VF-S15 Handbuch DE (Parameterkürzel ↔ Kommunikationsnummer).
Die Modbus-Registeradresse entspricht der Toshiba-Kommunikationsnummer (hex).
"""

# Übersicht: Adresse -> (Name, Skalierung, Einheit)
MONITOR = {
    0xFD00: ("Ausgangsfrequenz", 0.01, "Hz"),
    0xFD01: ("Status 1", None, ""),
    0xFD02: ("Frequenz-Sollwert", 0.01, "Hz"),
    0xFD03: ("Ausgangsstrom", 0.01, "% Nennstrom"),
    0xFD04: ("Zwischenkreisspannung", 0.01, "%"),
    0xFD05: ("Ausgangsspannung", 0.01, "%"),
    0xFD26: ("Motorlast", 1, "%"),
    0xFC90: ("Störungscode", None, ""),
    0xFE14: ("Betriebsstunden", 1, "h"),
}

# Alle Monitor-Register aus E6581913. FDxx = aktueller Wert, FExx = Wert beim letzten Trip.
_MONITOR_PAIRS = {
    0x00: ("Ausgangsfrequenz", 0.01, "Hz"),
    0x01: ("Status 1", None, ""),
    0x02: ("Frequenz-Sollwert", 0.01, "Hz"),
    0x03: ("Ausgangsstrom", 0.01, "% Nennstrom"),
    0x04: ("Zwischenkreisspannung", 0.01, "%"),
    0x05: ("Ausgangsspannung", 0.01, "%"),
    0x06: ("Eingangsklemmen", None, "bits"),
    0x07: ("Ausgangsklemmen", None, "bits"),
    0x15: ("Kompensierte Frequenz", 0.01, "Hz"),
    0x16: ("Geschätzte Drehzahl", 0.01, "Hz"),
    0x18: ("Drehmoment", 0.01, "%"),
    0x20: ("Drehmomentstrom", 0.01, "%"),
    0x22: ("PID-Istwert", 0.01, "Hz"),
    0x23: ("Motor-Überlast (OL2)", 0.01, "%"),
    0x24: ("Umrichter-Überlast (OL1)", 0.01, "%"),
    0x25: ("Bremswiderstand Last kumuliert", 1, "%"),
    0x26: ("Motorlast", 1, "%"),
    0x27: ("Umrichterlast", 1, "%"),
    0x28: ("Bremswiderstand Last", 1, "%"),
    0x29: ("Eingangsleistung", 0.01, "kW"),
    0x30: ("Ausgangsleistung", 0.01, "kW"),
    0x42: ("Status 2", None, ""),
    0x49: ("Status 3", None, ""),
    0x90: ("Motordrehzahl", 1, "min⁻¹"),
}

MONITOR_ALL = {
    0xFB05: ("Leistungscode Umrichter", None, ""),
    0xFB07: ("Serientyp", None, ""),
    0xFC00: ("Tastendaten (wirksam)", None, ""),
    0xFC01: ("Tastendaten Bedienfeld", None, ""),
    0xFC90: ("Störungscode aktuell", None, ""),
    0xFC91: ("Alarm 1", None, ""),
    0xFC92: ("Alarm 2", None, ""),
}
for _low, (_name, _scale, _unit) in _MONITOR_PAIRS.items():
    MONITOR_ALL[0xFD00 | _low] = (_name, _scale, _unit)
for _low, (_name, _scale, _unit) in _MONITOR_PAIRS.items():
    if _low != 0x90:
        MONITOR_ALL[0xFE00 | _low] = (f"{_name} (bei Trip)", _scale, _unit)
MONITOR_ALL[0xFE90] = ("Motordrehzahl (bei Trip)", 1, "min⁻¹")
MONITOR_ALL.update({
    0xFD10: ("Störung 5", None, ""),
    0xFD11: ("Störung 6", None, ""),
    0xFD12: ("Störung 7", None, ""),
    0xFD13: ("Störung 8 (älteste)", None, ""),
    0xFE08: ("CPU-Version 1 (Applikation)", None, ""),
    0xFE10: ("Störung 1 (letzte)", None, ""),
    0xFE11: ("Störung 2", None, ""),
    0xFE12: ("Störung 3", None, ""),
    0xFE13: ("Störung 4", None, ""),
    0xFE14: ("Betriebsstunden", 1, "h"),
    0xFD32: ("Anzahl Starts", 1, "× 1000"),
    0xFD33: ("Anzahl Starts vorwärts", 1, "× 1000"),
    0xFD34: ("Anzahl Starts rückwärts", 1, "× 1000"),
    0xFE35: ("Klemme VIA", 0.01, "%"),
    0xFE36: ("Klemme VIB", 0.01, "%"),
    0xFE37: ("Klemme VIC", 0.01, "%"),
    0xFE40: ("FM-Ausgang", 0.01, "%"),
    0xFD40: ("Pulsausgang", 1, "pps"),
    0xFD41: ("Lüfter-Betriebszeit", 10, "h"),
    0xFE56: ("Pulseingang", 1, "pps"),
    0xFE70: ("Nennstrom", 0.1, "A"),
    0xFE71: ("Nennspannung", 0.1, "V"),
    0xFE73: ("CPU-Version 2 (Motor)", None, ""),
    0xFE76: ("Energie Eingang (Skal. f749)", 1, ""),
    0xFE77: ("Energie Ausgang (Skal. f749)", 1, ""),
    0xFE79: ("Teiletausch-Alarm", None, ""),
    0xFE80: ("Einschaltzeit kumuliert", 10, "h"),
    0x0999: ("Einheit Hoch-/Runterlaufzeit", None, ""),
    # Befehlsregister (lesbar, Schreiben steuert den FU!)
    0xFA00: ("Befehl 1 (FA00)", None, ""),
    0xFA01: ("Frequenzbefehl (FA01)", 0.01, "Hz"),
    0xFA20: ("Befehl 2 (FA20)", None, ""),
    0xFA26: ("Befehl 3 (FA26)", None, ""),
})

# Basisparameter: Kürzel am Panel (Kommunikationsnummern laut Handbuch DE)
PARAM_TITLES = {
    0x0000: "au1", 0x0001: "au2", 0x0003: "cmod", 0x0004: "fmod", 0x0005: "fmsl",
    0x0006: "fm", 0x0008: "fr", 0x0009: "acc", 0x0010: "dec", 0x0012: "fh",
    0x0013: "ul", 0x0014: "ll", 0x0016: "vb", 0x0017: "olm", 0x0018: "sr1",
    0x0019: "sr2", 0x0020: "sr3", 0x0021: "sr4", 0x0022: "sr5", 0x0023: "sr6",
    0x0024: "sr7", 0x0025: "fpid", 0x0030: "sr0", 0x0050: "psel", 0x0090: "aua",
    0x0093: "auf", 0x0094: "aul", 0x0099: "set", 0x0409: "vl", 0x0600: "thr",
}

PARAM_NOTES = {
    0x0003: "0 Klemmen, 1 Panel, 2 RS485",
    0x0004: "Frequenzquelle",
    0x0800: "Baudrate (3=9600, 4=19200, 5=38400)",
    0x0801: "Parität (0=keine, 1=gerade, 2=ungerade)",
    0x0802: "Umrichter-Nr. (Slave-ID)",
    0x0803: "Komm.-Timeout",
    0x0806: "Master/Slave Inter-Drive",
    0x0829: "Protokoll (0=Toshiba, 1=Modbus RTU)",
}

STATUS1_BITS = {
    0: "FL (Störungsrelais)",
    1: "Störung (Trip)",
    2: "Alarm",
    3: "Unterspannung",
    7: "DC-Bremse",
    8: "Jog",
    9: "Rückwärts",
    10: "Läuft",
    11: "ST aus (Freilauf)",
    12: "Not-Halt",
    13: "Bereit + Startbefehl (ST/RUN an)",
    14: "Bereit",
}


def param_title(address):
    """Panel-Kürzel eines Parameters (0x0000–0x0999)."""
    if address in PARAM_TITLES:
        return PARAM_TITLES[address]
    if 0x0100 <= address <= 0x0999:
        return f"f{address:03X}"
    return ""


def scan_addresses():
    """Alle Adressen mit Dezimalziffern-Kommunikationsnummer: Parameter + Monitor/Befehle."""
    def digits(prefix):
        return [(prefix << 8) | int(f"{n:02d}", 16) for n in range(100)]
    addrs = [int(f"{n:04d}", 16) for n in range(1000)]          # 0000–0999
    for prefix in (0xFA, 0xFB, 0xFC, 0xFD, 0xFE):               # FA00–FE99
        addrs += digits(prefix)
    return addrs


def describe(address):
    """(Bereich, Name) für die Tabelle."""
    area = "Befehl" if address >> 8 == 0xFA else "Monitor"
    if address in MONITOR_ALL:
        return area, MONITOR_ALL[address][0]
    if address <= 0x0999:
        title = param_title(address)
        note = PARAM_NOTES.get(address, "")
        return "Parameter", f"{title}  {note}".strip()
    return area, "(nicht dokumentiert)"


def format_value(address, raw, ctx=None):
    """Wert formatiert. ctx: bereits gelesene Werte (für A/V-Umrechnung über Nennwerte)."""
    ctx = ctx or {}
    if address not in MONITOR_ALL and address not in MONITOR:
        return str(raw)
    name, scale, unit = MONITOR_ALL.get(address) or MONITOR[address]
    if address in (0xFD01, 0xFE01):
        active = [text for bit, text in STATUS1_BITS.items() if raw & (1 << bit)]
        return f"0x{raw:04X}  [{', '.join(active) or 'Stopp, keine Meldung'}]"
    if unit == "bits":
        return f"0b{raw:08b}"
    if scale is None:
        return f"0x{raw:04X} ({raw})"
    value = raw * scale
    decimals = 2 if scale < 0.1 else 1 if scale < 1 else 0
    text = f"{value:.{decimals}f} {unit}"
    if address in (0xFD03, 0xFE03) and 0xFE70 in ctx:
        text += f"  ({value / 100 * ctx[0xFE70] * 0.1:.2f} A)"
    if address in (0xFD05, 0xFE05) and 0xFE71 in ctx:
        text += f"  ({value / 100 * ctx[0xFE71] * 0.1:.1f} V)"
    return text.strip()
