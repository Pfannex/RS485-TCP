# RS485-TCP

Python tools to talk to a **Toshiba VF-S15** frequency inverter via Modbus RTU over an
**eletechsup ET69C02** Ethernet ↔ RS485 gateway.

```
PC / Home Assistant ──Ethernet──> ET69C02 (Modbus TCP ↔ RTU) ──RS485──> Toshiba VF-S15
```

No external dependencies, Python 3.8+.

## Communication check

```
py comcheck.py                                   # defaults: 192.168.1.69:8887, unit 1
py comcheck.py --host 192.168.1.69 --port 8887 --unit 1
py comcheck.py --mode rtu                        # gateway in transparent mode (RTU frames over TCP)
```

The check runs in three steps: is the gateway reachable, does the inverter answer, then it
reads the main monitor registers (frequency, status, current, voltages, trip code, operating hours).

## Setup

Wiring, gateway configuration and inverter parameters (`f829 = 1`, `f802 = 1`, 19200 8E1)
are documented in [settings.md](settings.md) (German).

## Manuals

Not included in the repository (copyright Toshiba). Download:

- [VF-S15 RS485 Communication Function Manual (E6581913)](https://www.toshiba.com/tic/datafiles/manuals/S15_RS485_Communication_Manual.pdf)
- VF-S15 Instruction Manual (E6581611): available from Toshiba / distributors
