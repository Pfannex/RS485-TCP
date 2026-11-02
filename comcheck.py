"""Kommunikationscheck: PC -> Ethernet -> ET69C02 -> RS485 -> Toshiba VF-S15.

Beispiel:
    py comcheck.py
    py comcheck.py --host 192.168.1.69 --port 8887 --unit 1
    py comcheck.py --mode rtu          # falls das Gateway transparent arbeitet

Läuft automatisch nach jeder Code-Änderung durch Claude (.claude/settings.json).
"""

import argparse
import socket
import sys
import time

from rs485tcp.modbus_client import ModbusClient, ModbusError, ModbusException, check_port
from rs485tcp.vfs15 import MONITOR, format_value


def main():
    ap = argparse.ArgumentParser(description="Kommunikationscheck ET69C02 + Toshiba VF-S15")
    ap.add_argument("--host", default="192.168.1.69")
    ap.add_argument("--port", type=int, default=8887)
    ap.add_argument("--unit", type=int, default=1, help="Modbus-Adresse des FU (f802)")
    ap.add_argument("--mode", choices=["tcp", "rtu"], default="tcp",
                    help="tcp = Modbus TCP (Gateway wandelt), rtu = RTU-Frames über TCP")
    ap.add_argument("--timeout", type=float, default=2.0)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    print(f"Ziel: {args.host}:{args.port}  Unit {args.unit}  Modus {args.mode}\n")

    # 1) Gateway im Netz?
    print("[1] Gateway erreichbar ...", end=" ")
    if not check_port(args.host, args.port, args.timeout):
        print("NEIN")
        web = check_port(args.host, 80, args.timeout)
        print(f"    Port {args.port} zu. Web-Interface (80): {'offen' if web else 'zu'}")
        print("    -> IP/Port im Gateway prüfen (Local port).")
        return 1
    print("OK")

    # 2) Antwortet der Umrichter über RS485?
    print("[2] Umrichter antwortet ...", end=" ")
    client = ModbusClient(args.host, args.port, args.unit, args.mode, args.timeout)
    try:
        client.connect()
        client.read_holding(0xFD00)
        print("OK\n")
    except ModbusException as e:
        print("NEIN")
        print(f"    {e}")
        if e.code in (0x0A, 0x0B):
            print("    -> Gateway erreicht den FU nicht: Verkabelung A/B, Baudrate/Parität,")
            print("       f829=1 (Modbus RTU) und f802 (Adresse) prüfen, FU neu starten.")
        return 2
    except (socket.timeout, TimeoutError):
        print("NEIN (Timeout)")
        print("    -> Keine Antwort. Typische Ursachen:")
        print("       - A+/B- vertauscht oder GND fehlt")
        print("       - Gateway-Baudrate/Parität passt nicht zu f800/f801 (Werk: 19200, Even)")
        print("       - FU noch auf Toshiba-Protokoll (f829=0) oder Adresse f802=0")
        print("       - Parameter geändert, aber FU nicht aus-/eingeschaltet")
        print("       - Gateway im falschen Modus: --mode rtu probieren")
        return 2
    except (ModbusError, OSError) as e:
        print("FEHLER")
        print(f"    {e}")
        return 2

    # 3) Werte lesen (einzeln: Blockabfragen überspringen beim VF-S15 Adresslücken)
    print("[3] Werte:")
    errors = 0
    for address, (name, _scale, _unit) in MONITOR.items():
        try:
            raw = client.read_holding(address)[0]
            print(f"    {address:04X}  {name:<22} {format_value(address, raw)}")
        except (ModbusError, OSError) as e:
            errors += 1
            print(f"    {address:04X}  {name:<22} Fehler: {e}")
        time.sleep(0.05)
    client.close()

    print(f"\nKommunikation {'OK' if errors == 0 else f'mit {errors} Fehler(n)'}.")
    return 0 if errors == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
