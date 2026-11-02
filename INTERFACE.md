# Schnittstellenbeschreibung: Toshiba VF-S15 über Gateway ET69C02

Dieses Dokument beschreibt vollständig, wie ein Client (z. B. Home Assistant, ein Skript
oder eine SPS) den Frequenzumrichter über das Gateway liest. Es setzt nichts voraus, was
nicht in diesem Repository steht. Stand: 2026-11-02, alle Angaben am realen Gerät getestet.

```
Client ──Modbus TCP──> ET69C02 (192.168.1.69:8887) ──Modbus RTU, RS485 19200 8N1──> VF-S15 (Slave 1)
```

---

## 1. Verbindung – das Wichtigste auf einen Blick

| Eigenschaft | Wert |
|---|---|
| Protokoll zum Gateway | **Modbus TCP** (Standard-MBAP-Header). Das Gateway setzt auf Modbus RTU um. |
| Host | **192.168.1.69** (per DHCP; Reservierung im Router für MAC `DC:32:62:B0:27:60` nötig) |
| Port | **8887** (nicht 502) |
| Unit-ID / Slave-Adresse | **1** |
| Funktionscode | **0x03 Read Holding Registers** (nur Lesen) |
| Register pro Anfrage | **1 empfohlen**, max. 8 (Anzahl ≥ 9 → Exception 0x03). Achtung Blockabfrage, siehe unten. |
| Registeradressierung | 0-basiert, **Adresse = Toshiba-Kommunikationsnummer als Hex**, kein Offset (z. B. Ausgangsfrequenz = `0xFD00` = 64768) |
| Datenformat | 16 Bit, Big Endian. Vorzeichenlos, außer wo unten „int16“ steht. |
| Antwortzeit | ca. 30 ms pro Register (über Netzwerk + RS485) |
| Nicht vorhandene Adresse | Antwort mit Modbus-Exception **0x02** (Illegal data address), kein Timeout |
| Umrichter aus / keine Antwort | Gateway antwortet **nicht** (keine Exception 0x0B) → Client-Timeout. Empfohlener Timeout: 1–3 s |
| Zugriff | **Nur lesen.** Schreiben ist nicht eingerichtet und nicht freigegeben (siehe Abschnitt 6). |

### ⚠ Blockabfragen überspringen Lücken

Bei Anzahl > 1 liefert der VF-S15 die **nächsten existierenden** Register, nicht zwingend
Adresse+1, Adresse+2 … Beispiel (getestet): Start 0x0009, Anzahl 2 → `[300, 100]` =
`acc` (0x0009) und `dec` (0x0010), weil 0x000A nicht existiert. Die Zuordnung ist damit nur
in lückenlosen Bereichen eindeutig (z. B. 0xFD00–0xFD07). **Empfehlung: jedes Register
einzeln lesen (Anzahl = 1).**

### ⚠ Nur EIN Client gleichzeitig

Das Gateway nimmt mehrere TCP-Verbindungen an, **schickt aber jede Antwort an alle
verbundenen Clients**. Getestet: Client 2 erhielt die Antwort auf die Anfrage von Client 1
(mit dessen Transaction-ID); die Clients bekommen dadurch falsche Antworten und Timeouts.

- Es darf immer nur **ein** Modbus-Client verbunden sein.
- Die Monitor-App dieses Repos (`app.py`, `comcheck.py`) vorher trennen bzw. nicht starten,
  während Home Assistant das Gateway nutzt.
- Wer mehrere Clients braucht, muss einen Modbus-Proxy davorsetzen, der Anfragen
  serialisiert, und nur den Proxy mit dem Gateway verbinden.

### Abfrageabstand

Anfragen nacheinander senden (auf die Antwort warten, dann die nächste). Ein zusätzlicher
Abstand von ~30 ms zwischen Anfragen schadet nicht. Bei 20 Werten und 30 ms je Register ist
ein Zyklus von 1–2 s problemlos möglich.

---

## 2. Beispiel-Frames (echt aufgezeichnet)

Modbus TCP, Werte in Hex. Aufbau Anfrage: `TID(2) PID(2)=0000 LEN(2)=0006 UNIT(1) FC(1)=03 ADR(2) ANZ(2)=0001`.

| Zweck | Anfrage (Client → Gateway) | Antwort (Gateway → Client) | Bedeutung |
|---|---|---|---|
| Status 1 lesen | `00 01 00 00 00 06 01 03 FD 01 00 01` | `00 01 00 00 00 05 01 03 02 40 00` | Wert 0x4000 = „Bereit“ |
| f800 lesen | `00 02 00 00 00 06 01 03 08 00 00 01` | `00 02 00 00 00 05 01 03 02 00 04` | 4 = 19200 Baud |
| ungültige Adresse | `00 03 00 00 00 06 01 03 00 02 00 01` | `00 03 00 00 00 03 01 83 02` | Exception 0x02 |

RTU-Frame auf dem RS485-Bus zum Vergleich (Status 1): `01 03 FD 01 00 01 E4 66`
bzw. Ausgangsfrequenz `01 03 FD 00 00 01 B5 A6`.

---

## 3. Monitorwerte (Messwerte)

Umrechnung: **Wert = Rohwert × Skalierung**.

| Wert | Adresse hex | Adresse dez | Typ | Skalierung | Einheit | Hinweis |
|---|---|---|---|---|---|---|
| Ausgangsfrequenz | 0xFD00 | 64768 | uint16 | 0,01 | Hz | |
| Status 1 | 0xFD01 | 64769 | uint16 | Bitfeld | – | siehe Abschnitt 4 |
| Frequenz-Sollwert | 0xFD02 | 64770 | uint16 | 0,01 | Hz | |
| Ausgangsstrom | 0xFD03 | 64771 | uint16 | 0,01 | % Nennstrom | × 9,5 A / 100 → A (Nennstrom aus 0xFE70) |
| Zwischenkreisspannung | 0xFD04 | 64772 | uint16 | 0,01 | % | Bezugsgröße im Handbuch nicht angegeben |
| Ausgangsspannung | 0xFD05 | 64773 | uint16 | 0,01 | % | Annahme: Bezug Nennspannung 400 V (0xFE71) |
| Eingangsklemmen | 0xFD06 | 64774 | uint16 | Bitfeld | – | |
| Ausgangsklemmen | 0xFD07 | 64775 | uint16 | Bitfeld | – | |
| Drehmoment | 0xFD18 | 64792 | **int16** | 0,01 | % | |
| Drehmomentstrom | 0xFD20 | 64800 | **int16** | 0,01 | % | |
| Motorlast | 0xFD26 | 64806 | uint16 | 1 | % | |
| Umrichterlast | 0xFD27 | 64807 | uint16 | 1 | % | |
| Eingangsleistung | 0xFD29 | 64809 | uint16 | 0,01 | kW | |
| Ausgangsleistung | 0xFD30 | 64816 | uint16 | 0,01 | kW | |
| Motordrehzahl | 0xFD90 | 64912 | uint16 | 1 | min⁻¹ | |
| Störungscode aktuell | 0xFC90 | 64656 | uint16 | – | – | 0 = keine Störung |
| Betriebsstunden | 0xFE14 | 65044 | uint16 | 1 | h | stetig steigend |
| Einschaltzeit kumuliert | 0xFE80 | 65152 | uint16 | 10 | h | stetig steigend |
| Energie Eingang | 0xFE76 | 65142 | uint16 | 1 | kWh | Einheit hängt von f749 ab, aktuell f749 = 1 → 1 kWh |
| Energie Ausgang | 0xFE77 | 65143 | uint16 | 1 | kWh | wie oben |
| Nennstrom Umrichter | 0xFE70 | 65136 | uint16 | 0,1 | A | gelesen: 95 → 9,5 A |
| Nennspannung Umrichter | 0xFE71 | 65137 | uint16 | 0,1 | V | gelesen: 4000 → 400,0 V |

Zu jedem `FDxx`-Wert gibt es ein `FExx`-Register mit dem Wert **zum Zeitpunkt der letzten
Störung** (z. B. 0xFE00 = Ausgangsfrequenz beim Trip). Weitere Monitorregister mit Namen
und Einheiten: `MONITOR_ALL` in [rs485tcp/vfs15.py](rs485tcp/vfs15.py).

---

## 4. Status 1 (0xFD01) – Bitbelegung

| Bit | Maske | Bedeutung bei 1 |
|---|---|---|
| 0 | 0x0001 | FL-Relais (Störungsausgang) aktiv |
| 1 | 0x0002 | **Störung (Trip)** |
| 2 | 0x0004 | **Alarm** |
| 3 | 0x0008 | Unterspannung |
| 7 | 0x0080 | DC-Bremsung aktiv |
| 8 | 0x0100 | Jog-Betrieb |
| 9 | 0x0200 | Drehrichtung rückwärts |
| 10 | 0x0400 | **Läuft** |
| 11 | 0x0800 | ST aus (Freilauf) |
| 12 | 0x1000 | Not-Halt |
| 13 | 0x2000 | Bereit und Startbefehl (ST/RUN) liegt an |
| 14 | 0x4000 | **Bereit** (initialisiert, keine Störung, kein Alarm) |
| 15 | – | undefiniert, nicht auswerten |

Typische Werte: `0x4000` = bereit, steht · `0x6400` = bereit, Startbefehl, läuft vorwärts.
**Erreichbarkeit:** Status 1 regelmäßig lesen (z. B. alle 2 s). Kommt keine Antwort, ist
der Umrichter aus oder die RS485-Strecke unterbrochen; ist die TCP-Verbindung weg, ist das
Gateway nicht erreichbar.

---

## 5. Parameter (Einstellwerte)

Alle 433 Parameter aus dem Handbuch (Kap. 11) liegen maschinenlesbar in
[rs485tcp/vfs15_params.json](rs485tcp/vfs15_params.json). Ein Eintrag:

```json
{
  "comm": "0009",          // Kommunikationsnummer = Registeradresse in Hex (0x0009)
  "title": "acc",          // Kürzel am Bedienfeld
  "name": "Hochlaufzeit 1",
  "unit": "s",
  "resolution": "0,1/0,1", // Auflösung Bedienfeld / serielle Kommunikation
  "scale": 0.1,            // Skalierung für Modbus: Wert = Rohwert × scale
  "range": "0,0-3.600 (360,0) *8",
  "options": {},           // bei Auswahlparametern: {"0": "Klemmleiste", "1": ...}
  "signed": false,         // true -> Rohwert als int16 interpretieren
  "default": "10,0",
  "group": "Basisparameter",
  "page": 280              // Seite im deutschen Handbuch
}
```

Umrechnung: `signed` → als int16 lesen; gibt es `options`, ist der Rohwert ein Schlüssel
(Klartext = `options[str(roh)]`); sonst `roh × scale` (ohne `scale`: Rohwert direkt).
Einzelne Namen können durch das PDF-Tabellenlayout verschoben sein (z. B. `thr`/`olm`).

Aktuell gelesene Einstellungen dieser Anlage:

| Parameter | Adresse | Wert | Bedeutung |
|---|---|---|---|
| `cmod` | 0x0003 | 0 | Start/Stopp über Klemmleiste (P24–F ist fest gebrückt → läuft bei Netz ein) |
| `fmod` | 0x0004 | 1 | Frequenzsollwert über Analogeingang VIA |
| `acc` | 0x0009 | 300 | Hochlaufzeit 30,0 s |
| `dec` | 0x0010 | 100 | Runterlaufzeit 10,0 s |
| `ul` | 0x0012 | 6000 | Obere Grenzfrequenz 60,00 Hz |
| `f800` | 0x0800 | 4 | 19200 Baud |
| `f801` | 0x0801 | 0 | keine Parität |
| `f802` | 0x0802 | 1 | Slave-Adresse 1 |
| `f829` | 0x0829 | 1 | Modbus RTU |
| `f749` | 0x0749 | 1 | Energiezähler-Einheit 1 kWh |

---

## 6. Schreiben / Steuern – nicht freigegeben

Steuern wäre über `0xFA00` (Befehl) und `0xFA01` (Frequenzsollwert, 0,01 Hz) möglich
(Funktion 0x06). Das ist **nicht eingerichtet**: Der Umrichter wird über Klemmen gestartet
und über VIA gesollt (`cmod` = 0, `fmod` = 1). Schreiben würde erfordern, `cmod`/`fmod` zu
ändern oder in FA00 die Kommunikationspriorität zu setzen, und kann den Motor anlaufen
lassen. Ohne ausdrückliche Freigabe des Anlagenbetreibers **keine Schreibzugriffe**.

---

## 7. Serielle Seite und Verkabelung (zur Information)

| | Wert |
|---|---|
| RS485 | 2-Draht, 19200 Baud, 8 Datenbits, **keine Parität**, 1 Stoppbit (8N1) |
| Gateway seriell | 19200 / 8 / NONE / 1, „MODBUS TCP to RTU = Open“, „Modbus mode = Simple“ |
| Umrichter | `f829` = 1, `f802` = 1, `f800` = 4, `f801` = 0 |
| Verdrahtung | RJ45 am FU: Pin 4 → A+, Pin 5 → B−, Pin 8 → GND; Pin 7 (24 V) frei |

Details, Fehlersuche und Änderungsprotokoll: [settings.md](settings.md).

---

## 8. Vorlage Home Assistant

[homeassistant/vfs15_modbus.yaml](homeassistant/vfs15_modbus.yaml) ist eine **Vorlage**
(Modbus-Hub + Sensoren aus Abschnitt 3 + Status-Bits als Template-Binärsensoren). Sie ist
nicht in einer HA-Instanz getestet; Host/Port/Namen/Intervalle nach Bedarf anpassen.

## 9. Verbindung prüfen

Mit Python 3 aus diesem Repo (keine Abhängigkeiten), **ohne dass ein anderer Client verbunden ist**:

```
py comcheck.py --host 192.168.1.69 --port 8887 --unit 1
```

Erwartet: „Gateway erreichbar … OK“, „Umrichter antwortet … OK“ und eine Werteliste.
Minimaler Client-Code (Lesen eines Registers): [rs485tcp/modbus_client.py](rs485tcp/modbus_client.py).

---

## 10. Fehlerbilder

| Beobachtung | Ursache |
|---|---|
| TCP-Verbindung auf 8887 schlägt fehl | Gateway aus / andere IP (DHCP) → im Router nach MAC `DC:32:62:B0:27:60` suchen |
| Verbindung steht, aber jede Anfrage Timeout | Umrichter aus, RS485 unterbrochen, oder serielle Einstellungen geändert |
| Sporadisch falsche Werte / Transaction-ID passt nicht / Timeouts | **zweiter Client verbunden** (Abschnitt 1) |
| Exception 0x02 | Adresse existiert nicht |
| Exception 0x03 | mehr als 8 Register in einer Anfrage |
| Werte „verrutscht“ bei Blockabfrage | Lücke im Adressbereich übersprungen (Abschnitt 1) – einzeln lesen |
