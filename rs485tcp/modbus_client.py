"""Minimaler Modbus-Client (nur Standardbibliothek).

Unterstützt zwei Transportarten zum ET69C02-Gateway:
  - "tcp":     Modbus TCP (MBAP-Header). Gateway-Einstellung "MODBUS TCP to RTU = Open".
  - "rtu":     Modbus RTU über TCP (rohe RTU-Frames mit CRC, transparenter Modus).
"""

import socket
import struct

EXCEPTION_CODES = {
    0x01: "Illegal function",
    0x02: "Illegal data address",
    0x03: "Illegal data value",
    0x04: "Slave device failure",
    0x06: "Slave device busy",
    0x0A: "Gateway path unavailable",
    0x0B: "Gateway target device failed to respond",
}


class ModbusError(Exception):
    pass


class ModbusException(ModbusError):
    """Das Gerät hat mit einer Modbus-Exception geantwortet."""

    def __init__(self, function, code):
        self.function = function
        self.code = code
        text = EXCEPTION_CODES.get(code, "unbekannt")
        super().__init__(f"Exception 0x{code:02X} ({text}) auf Funktion 0x{function:02X}")


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


class ModbusClient:
    def __init__(self, host, port=502, unit=1, mode="tcp", timeout=2.0):
        if mode not in ("tcp", "rtu"):
            raise ValueError("mode muss 'tcp' oder 'rtu' sein")
        self.host = host
        self.port = port
        self.unit = unit
        self.mode = mode
        self.timeout = timeout
        self._sock = None
        self._tid = 0

    def connect(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)

    def close(self):
        if self._sock:
            self._sock.close()
            self._sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    # --- Funktionen -------------------------------------------------------

    def read_holding(self, address, count=1):
        """Funktion 0x03. Der VF-S15 erlaubt nur count=1."""
        pdu = struct.pack(">BHH", 0x03, address, count)
        resp = self._transact(pdu)
        if len(resp) < 2 or resp[1] != 2 * count:
            raise ModbusError(f"Unerwartete Antwortlänge: {resp.hex(' ')}")
        return list(struct.unpack(f">{count}H", resp[2:2 + 2 * count]))

    def write_single(self, address, value):
        """Funktion 0x06."""
        pdu = struct.pack(">BHH", 0x06, address, value)
        self._transact(pdu)

    # --- Transport --------------------------------------------------------

    def _transact(self, pdu):
        if self._sock is None:
            self.connect()
        if self.mode == "tcp":
            resp = self._transact_tcp(pdu)
        else:
            resp = self._transact_rtu(pdu)
        if resp[0] & 0x80:
            raise ModbusException(resp[0] & 0x7F, resp[1])
        if resp[0] != pdu[0]:
            raise ModbusError(f"Falscher Funktionscode in Antwort: {resp.hex(' ')}")
        return resp

    def _transact_tcp(self, pdu):
        self._tid = (self._tid + 1) & 0xFFFF
        frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu
        self._sock.sendall(frame)
        header = self._recv_exact(7)
        tid, _pid, length, unit = struct.unpack(">HHHB", header)
        body = self._recv_exact(length - 1)
        if tid != self._tid:
            raise ModbusError(f"Transaction-ID passt nicht ({tid} != {self._tid})")
        if unit != self.unit:
            raise ModbusError(f"Antwort von Unit {unit}, erwartet {self.unit}")
        return body

    def _transact_rtu(self, pdu):
        adu = bytes([self.unit]) + pdu
        self._sock.sendall(adu + struct.pack("<H", crc16(adu)))
        head = self._recv_exact(2)
        if head[1] & 0x80:
            rest = self._recv_exact(3)  # Exception-Code + CRC
        elif head[1] == 0x03:
            n = self._recv_exact(1)
            rest = n + self._recv_exact(n[0] + 2)
        else:
            rest = self._recv_exact(6)  # 0x06 / 0x10: Adresse + Wert + CRC
        frame = head + rest
        if crc16(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
            raise ModbusError(f"CRC-Fehler: {frame.hex(' ')}")
        if frame[0] != self.unit:
            raise ModbusError(f"Antwort von Unit {frame[0]}, erwartet {self.unit}")
        return frame[1:-2]

    def _recv_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ModbusError("Verbindung vom Gateway geschlossen")
            buf += chunk
        return buf
