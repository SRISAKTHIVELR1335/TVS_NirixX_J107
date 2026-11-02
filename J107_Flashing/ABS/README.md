# J107 Flashing / ABS — UDS programs

Standalone programs that talk to the ABS ECU on CAN IDs **`0x7E1` / `0x7E9`**.
Each one opens the bus, runs its step, and returns to `main`:

```python
status, value = ABS_Clear_DTC(interface, channel, bitrate)
```

* success -> `(True, value)` — usually `"PASSED"`
* failure -> `(False, error_message)`

`ABS_Read_VIN` and `ABS_Write_VIN` take `api_url` and `vin_number` and return
three values, `(status, api_value, ecu_value)`, on every path.

## Programs

| file | request |
|---|---|
| `ABS_Clear_DTC` | `0x14 0xFF 0xFF 0xFF` |
| `ABS_Extended_Session` | `0x10 0x03` |
| `ABS_Tester_Present` | `0x3E 0x00`, repeated for 2 s |
| `ABS_Security_Access` | `0x10 0x01` → `0x10 0x03` → `0x27 0x01` → `0x27 0x02 <key>` |
| `ABS_Read_DTC` | `0x10 0x03` → `0x19 0x02 0x8F` |
| `ABS_Read_VIN` | `0x22 0xF1 0x90`, compared against the API VIN |
| `ABS_Write_VIN` | `0x2E 0xF1 0x90` + ASCII VIN, NUL-padded |

The security-access key algorithm is the ABS one
(`(((seed + 0xAEFB) - 0x1111) << 4) + 0x00A0`, masked to 16 bits).

## Shared helper block

Identical to `J107_Flashing/EMS`, `J107_IMU`, `J107_RVS` and `J107_Static`:
`log_print`, `_send_can_frame`, `_receive_single_can_frame`,
`receive_isotp_response`, `send_isotp_request`, `send_tester_present`,
`send_uds_request`, `_communication_error_message`. No imports between files.

`send_uds_request` returns `(response, error_message)`; on NRC `0x78` it
re-arms a 3 s window and sends Tester Present every second.

`error_message` is a UDS error string (`NRC Received: 0xXX`,
`ECU_RESPONSE_TIMEOUT`, `UNEXPECTED_RESPONSE_SID: 0xXX`) or one of the two
operator-facing blocks:

```text
- Verify failed:
- PCAN USB is not connected
- Check PCAN driver installation
- Verify PCAN channel selection
```

```text
- Verify failed:
- No communication from ECU
- Check vehicle ignition status
- Check CAN wiring
- Verify baud rate
```

## Running on Linux

Pass `interface="socketcan"` and a channel name (`can0`). The program brings
the link down, re-applies the bitrate, brings it up, and takes it down again in
`finally`.
