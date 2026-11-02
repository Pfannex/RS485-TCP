# Einstellungen & Anleitung: RS485-TCP (ET69C02 ↔ Toshiba VF-S15)

Signalweg: **PC / Home Assistant → Ethernet → ET69C02 (Modbus TCP ↔ RTU) → RS485 → Toshiba VF-S15**

---

## 1. Netzwerk

| Gerät | Wert |
|---|---|
| ET69C02 IP | **192.168.1.69** (DHCP vom Router) → im Router fest reservieren |
| ET69C02 MAC | `DC:32:62:B0:27:60` |
| Web-Interface | http://192.168.1.69 (Port 80), Login `admin` / Passwort ändern |
| Modbus-TCP-Port | **8887** (Gateway „Local port“) |
| Werks-IP (ohne DHCP-Server) | 192.168.3.7, Gateway 192.168.3.1 |

**Gateway ohne Router finden:** Laptop-LAN auf `192.168.3.20 / 255.255.255.0`
(kein Gateway, kein DNS) und http://192.168.3.7 öffnen. Unbekannte IP:
Mitschnitt mit Wireshark auf dem LAN-Port, Board neu starten → ARP-Probe zeigt die IP.

**Laptop:** Am LAN-Port kein Standardgateway eintragen, wenn WLAN im selben Netz
(192.168.1.x) hängt. Sonst zwei Gateways → Internet bricht ab.

---

## 2. ET69C02 – Web-Interface

| Bereich | Feld | Wert |
|---|---|---|
| Network | DHCP | enable |
| Network | Work mode | TCP server |
| Network | Local port | 8887 |
| Serial | Baud rate | **19200** |
| Serial | Data bit | **8** |
| Serial | Parity | **EVEN** |
| Serial | Stop bit | **1** |
| Serial | Flow | NONE |
| MODBUS | MODBUS TCP to RTU | **Open** |
| MODBUS | Modbus mode | Simple |
| MODBUS | address filter | 0 |
| MODBUS | Modbus timeout | 1000 ms |

Nach Änderungen: **submit**, dann **Reboot**.

Gerätedaten: Modell ET01, Version 9013-8-17, SN S5203122C.

---

## 3. Spannungsversorgung ET69C02

- Spezifikation: **6,5–25 V DC**, nominal 12 V, 20–25 mA.
- Aktuell: 12-V-Netzteil (Hohlstecker).
- Option: 24 V vom FU-Klemmenblock **P24 → VIN, CC → GND**.
  - P24 liefert 24 V DC, max. **100 mA (Summe P24 + +24)** laut E6581611.
  - Vorher P24–CC messen: muss **< 25 V** sein. Sonst Step-down auf 12 V davor.
  - Sicherung 100–200 mA in VIN empfohlen (P24 versorgt auch die FU-Steuereingänge).
  - **Nie** Pin 7 (P24) der RS485-RJ45-Buchse benutzen.

---

## 4. Verdrahtung RS485

RS485-Buchse am VF-S15 = **RJ45** (Patchkabel abschneiden, nur 3 Adern nutzen).

| RJ45-Pin am FU | Signal | ET69C02-Klemme | Farbe T568B* |
|---|---|---|---|
| **4** | RXD+/TXD+ | **A+** | blau |
| **5** | RXD−/TXD− | **B−** | weiß-blau |
| **8** | SG (Signalmasse) | **GND** | braun |
| 7 | P24 (24 V) | **nicht anschließen!** | weiß-braun |
| 1, 2, 3, 6 | – | nicht anschließen | |

\* Pin 4 (blau), 5 (weiß/blau), 7 (weiß/braun) und 8 (braun) sind bei **T568A und T568B
identisch**: Die Farben gelten also unabhängig vom Crimp-Standard. Trotzdem vor dem
Anklemmen mit Durchgangsprüfer gegenprüfen. Weiß/braun (Pin 7 = 24 V) einzeln isolieren.

**Pin-Zählung RJ45-Stecker:** Kontakte zu dir (Verriegelung hinten), Kabel nach unten
→ **Pin 1 links, Pin 8 rechts**. Das blaue Paar liegt in der Mitte (4/5), braun ganz außen (8).

- Bei kurzer Leitung (Schaltschrank) kein Abschlusswiderstand nötig. Bei langer
  Leitung 120 Ω zwischen A+ und B− am Leitungsende.
- Keine Antwort → zuerst A+/B− tauschen.

Quelle: E6581913, Anhang 5 „Connecting for RS485 communication“.

---

## 5. Toshiba VF-S15 – Modbus RTU aktivieren

Gerät: Toshiba TOSVERT **VF-S15**, 3 × 380–500 V, 3,7/4,0 kW (5 HP), vermutlich VFS15-4037PL.

### Parameter

| Parameter | Bedeutung | Werk | **Soll** | Wirksam |
|---|---|---|---|---|
| **f829** | Kommunikationsprotokoll | 0 = Toshiba | **1 = Modbus RTU** | nach Aus/Ein |
| **f802** | Umrichter-Nummer (Slave-ID) | 0 (= Broadcast, keine Antwort!) | **1** | sofort |
| f800 | Baudrate | 4 = 19200 | **4** (unverändert) | nach Aus/Ein |
| f801 | Parität | 1 = Even | **1** (unverändert) | nach Aus/Ein |
| f803 | Kommunikations-Timeout | 0.0 = aus | **0.0** (aus lassen) | – |

f803 nicht aktivieren: Bei Verbindungsverlust würde der FU sonst Alarm/Trip auslösen.
Für reines Auslesen bleiben `cmod` / `fmod` unverändert (Steuerung weiter über Klemmen/Panel).

### Bedienung am Panel

1. **FU stoppen** (Motor steht). Manche Parameter lassen sich im Betrieb nicht ändern.
2. **Standard-Einstellmodus** sicherstellen: Ist die EASY-LED an, **EASY** drücken,
   bis `std` erscheint (EASY-LED aus). Im Easy-Modus sind f8xx nicht sichtbar.
3. **MODE** drücken, bis die Parameterliste erscheint (erster Eintrag `auh`).
4. Einstellrad drehen bis zur Gruppe **`f8--`** → Mitte des Rads drücken.
5. Rad drehen bis **`f829`** → Mitte drücken (aktueller Wert wird angezeigt).
6. Rad auf **`1`** drehen → Mitte drücken zum **Speichern** (Anzeige wechselt `f829` / `1`).
7. Rad drehen bis **`f802`** → Mitte drücken → auf **`1`** → Mitte drücken.
8. Kontrolle: `f800` = 4, `f801` = 1.
9. Mehrmals **MODE** → zurück zur Frequenzanzeige.
10. **FU komplett ausschalten**, warten bis Anzeige aus ist, wieder einschalten.

Handbücher (Ordner `docs/`):
- Deutsch, Langversion: *Programmierung der erweiterten Parameter* PDF-Seite 76,
  Parameter f829 PDF-Seite 232.
- E6581611 (EN): Abschnitt 4.2 „How to set parameters“, Parametertabelle F-137.
- E6581913 (EN, Kommunikation): Kap. 4 Modbus RTU, Kap. 7 Parameter, Kap. 8 Register.

### Start über Binäreingang (Steuerklemmen)

| Klemme | Funktion (Werk) |
|---|---|
| **F** | Vorwärts-Start: geschlossen = Lauf, offen = Stopp mit Rampe |
| R | Rückwärts-Start |
| RES | Störung quittieren |
| S1–S3 | Festfrequenzen |
| CC | 0 V Bezug |
| P24 | interne 24 V (max. 100 mA inkl. +24) |

- Beschaltung je nach Schiebeschalter **SW1**: SINK → Kontakt **F–CC**,
  SOURCE → Kontakt **P24–F**, PLC (Werk) → externe 24 V über Klemme PLC.
- Voraussetzung: **`cmod` = 0** (Klemmenleiste). Werk laut Tabelle: `cmod` = 1 (Panel, RUN-Taste).
- ST (Standby) ist ab Werk immer aktiv (`f110` = 6), keine extra Freigabe nötig.
- Frequenzquelle separat über `fmod`.
- **Ist-Zustand der Anlage (2026-11-02):** **P24–F fest gebrückt** → Dauer-Startbefehl.
  - Daraus folgt SW1 = SOURCE (noch optisch prüfen) und vermutlich `cmod` = 0.
  - FU läuft, sobald Netz anliegt; Stopp nur über Netz aus, Trip oder STOP-Taste.
  - **Wiederanlauf automatisch** nach Netzwiederkehr / Störungsquittierung.
  - Frequenzquelle (`fmod`) noch unbekannt (Anzeige 48,8 Hz) → per Modbus auslesen
    (Register 0x0003 = cmod, 0x0004 = fmod).
  - Später HA-Steuerung: Brücke durch Relaiskontakt ersetzen **oder** Start/Stopp per
    Modbus (`cmod` = 2 bzw. FA00 Bit 15).

Quelle: E6581611 Abschnitt 2.3.2 „Control circuit terminals“, 5.x `cmod`/`fmod`.

---

## 6. Modbus-Register VF-S15

Funktion **03** (Read Holding), **immer nur 1 Register pro Anfrage** (VF-S15-Einschränkung).
Registeradresse = Toshiba-Kommunikationsnummer (hex).

| Adresse | Dez | Wert | Einheit |
|---|---|---|---|
| 0xFD00 | 64768 | Ausgangsfrequenz | 0,01 Hz |
| 0xFD01 | 64769 | Status 1 (Bit 10 läuft, 9 rückwärts, 1 Trip, 2 Alarm) | Bits |
| 0xFD02 | 64770 | Frequenz-Sollwert | 0,01 Hz |
| 0xFD03 | 64771 | Ausgangsstrom | 0,01 % Nennstrom |
| 0xFD04 | 64772 | Zwischenkreisspannung | 0,01 % |
| 0xFD05 | 64773 | Ausgangsspannung | 0,01 % |
| 0xFD26 | 64806 | Motorlast | 1 % |
| 0xFC90 | 64656 | Störungscode aktuell | – |
| 0xFE14 | 65044 | Betriebsstunden | 1 h |

Steuern (später): 0xFA00 Befehl, 0xFA01 Frequenzsollwert (0,01 Hz). Setzt Freigabe über
Kommunikation voraus (`cmod`/`fmod` oder FA00 Bit 14/15).

Testframe (RTU, Unit 1, FD00 lesen): `01 03 FD 00 00 01 B5 A6`

---

## 7. Monitor-App & Kommunikationscheck

**GUI:** `py app.py` (oder Doppelklick, ohne Konsole: `pyw app.py`)
- Status-Lampen Gateway / Umrichter (grün = OK, rot = Fehler, grau = unbekannt)
- Gateway wird automatisch alle 3 s geprüft (Modbus-Port + Web-Port 80)
- „Jetzt abfragen“ oder Polling mit einstellbarem Intervall
- IP, Port, Unit, Modus (tcp/rtu) im Fenster änderbar; Werte-Tabelle und Log

**Kommandozeile:**

```
py comcheck.py                       # 192.168.1.69:8887, Unit 1, Modbus TCP
py comcheck.py --mode rtu            # falls Gateway transparent (RTU über TCP)
```

**Automatisch:** Nach jeder Änderung an einer `.py`-Datei durch Claude Code startet ein
Hook (`.claude/settings.json` → `.claude/hooks/run_comcheck.py`) den Check und meldet das
Ergebnis an Claude zurück. Deaktivieren/prüfen über `/hooks`.

## Änderungsprotokoll

| Datum | Änderung |
|---|---|
| 2026-11-02 | ET69C02 gefunden (Werks-IP 192.168.3.7), DHCP → 192.168.1.69 |
| 2026-11-02 | Gateway seriell auf 19200 8E1 umgestellt (passend zu FU-Werkseinstellung) |
| 2026-11-02 | Kabel RJ45 → A+/B−/GND in Arbeit; FU-Parameter f829/f802 noch umzustellen |
| 2026-11-02 | Erster Test mit FU an: **keine Antwort** (Modbus TCP + RTU, Unit 1–10, Toshiba-ASCII) bei 19200 8E1 → Verdacht Verdrahtung/Baudrate |

## Fehlersuche: FU antwortet nicht

1. Gateway-LEDs beim Polling: TX blinkt + RX dunkel → FU antwortet nicht; TX dunkel → Gateway sendet nicht.
2. A+ / B− tauschen (häufigste Ursache, ungefährlich).
3. Pins durchmessen: RJ45 Pin 4 → A+, Pin 5 → B−, Pin 8 → GND; richtige Buchse am FU.
4. Am Panel prüfen: f800 = 4, f801 = 1 (passend zum Gateway).
5. f829 = 1, f802 = 1 gesetzt **und** FU danach aus/ein geschaltet.
6. Antwortet der FU auf Toshiba-ASCII `(RFD00)\r`, stimmt die Physik und nur f829 fehlt.
