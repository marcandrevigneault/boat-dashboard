# JBD Bluetooth BMS

Batteries "Batterie A" and "Batterie B": 12 V LiFePO4, 4 cells, 280 Ah, JBD-family BMS
(also sold as Xiaoxiang, Overkill, many OEM brands). Identified by BLE service `0xFF00`.

## Protocol
- Write requests to characteristic `0xFF02`; replies arrive as notifications on `0xFF01`,
  split into ~20-byte packets that must be reassembled.
- Request:  `DD A5 <reg> 00 <checksum:2> 77`
- Response: `DD <reg> <status> <len> <payload…> <checksum:2> 77`
  - checksum = `0x10000 − (len + sum(payload))`, big-endian. Status `0x00` = OK.
- Register `0x03` basic info: voltage (10 mV), current (signed, 10 mA, + = charging),
  remaining/nominal capacity (10 mAh), cycles, protection bitfield, SOC %, FET bits
  (bit0 charge, bit1 discharge), cell count, NTC temperatures (0.1 K).
- Register `0x04`: cell voltages, 2 bytes each, in mV.

## Runtime behaviour (`boatdash/jbd.py`)
- One `JBDClient` task per battery; holds a persistent BLE connection and polls both registers
  every `poll_interval` (2 s).
- On any error: mark disconnected, record the error, retry with exponential backoff 2 → 60 s.
- Connections are started 1.5 s apart — BlueZ fails when several connect simultaneously.
- Each read is bounded by a 5 s timeout; buffers are reset per frame (no unbounded growth).

## Testing
`tests/test_jbd.py` builds frames byte-for-byte (values taken from a real reading of Batterie A)
and simulates chunked notifications. No hardware needed.
