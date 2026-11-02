"""Register und Dekodierung für den Toshiba VF-S15 (Handbuch E6581913).

Die Modbus-Registeradresse entspricht der Toshiba-Kommunikationsnummer (hex).
"""

# Adresse: (Name, Skalierung, Einheit)
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


def format_value(address, raw):
    name, scale, unit = MONITOR[address]
    if address == 0xFD01:
        active = [text for bit, text in STATUS1_BITS.items() if raw & (1 << bit)]
        return f"0x{raw:04X}  [{', '.join(active) or 'Stopp, keine Meldung'}]"
    if scale is None:
        return f"0x{raw:04X} ({raw})"
    value = raw * scale
    return f"{value:.2f} {unit}" if scale < 1 else f"{value:g} {unit}"
