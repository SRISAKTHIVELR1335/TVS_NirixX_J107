# IMU / ABS EOL programs

Standalone programs from the IMU sample. Each file opens the CAN bus, runs
one UDS step, and returns to `main` a two-value tuple:

```python
status, value = Some_Test(interface, channel, bitrate)
```

* success -> `(True, value)`     where `value` is the read value, or `"PASSED"` /
  `True` for write / control steps
* failure -> `(False, error_message)`

`error_message` is either a UDS error string (`NRC Received: 0xXX`,
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

Every file carries the same self-contained CAN/UDS helper block
(`log_print`, `_send_can_frame`, `_receive_single_can_frame`,
`receive_isotp_response`, `send_isotp_request`, `send_tester_present`,
`send_uds_request`, `_communication_error_message`), so each script runs
standalone with no imports from its siblings. `__main__` always prints a
Result block.

`TVS_Nirix_J107.py` loads these dynamically with
`getattr(module, <file name>)`, so the callable inside each file must keep the
same name as the file.

## CAN IDs

| ECU | Tester (TX) | Response (RX) |
|-----|-------------|----------------|
| ABS | `0x7E1`     | `0x7E9`        |
| IPC | `0x7C9`     | `0x7C1`        |

Default `__main__`: `interface="pcan"`, `channel="PCAN_USBBUS1"`, `bitrate=500000`.
On Linux the script switches to `socketcan` / `can0`.

## Flow

| # | Function | Request / DID | Return |
|---|----------|---------------|--------|
| 1 | `ABS_Default_Session` | `10 01` | `(True, 0x01)` |
| 2 | `ABS_Extended_Session` | `10 03` | `(True, 0x03)` |
| 3 | `ABS_Clear_DTC` | `14 FF FF FF` | `(True, True)` |
| 4 | `ABS_Security_Access` | `27 01` then `27 02` + key | `(True, True)` |
| 5 | `ABS_Write_EOL_Mode` | `2E F1 F1 01` | `(True, 0x01)` |
| 6 | `ABS_Read_IMU_EOL_Mode` | `22 F1 F1`, expected `0x01` | `(True, 0x01)` |
| 7 | `ABS_IMU_EOL_Routine` | `31 01 B0 06 01` | `(True, True)` |
| 8 | `ABS_Read_Pitch_Angle` | `22 F1 0A` signed int16 | `(True, angle)` |
| 9 | `ABS_Read_Lean_Angle` | `22 F1 08` signed int16 | `(True, angle)` |
| 10 | `ABS_Write_Pitch_Angle` | `2E F1 F5 00 0D` | `(True, True)` |
| 11 | `ABS_Write_Lean_Angle` | `2E F1 F2 FF EE` | `(True, True)` |
| 12 | `ABS_Write_IMU_EOL_Mode` | `2E F1 F1 01` | `(True, 0x01)` |
| 13 | `IPC_Read_Bike_Finder_Button_Status` | `22 09 4C` expect `0x10` | `(True, 16)` |
| 14 | `IPC_Read_Seat_Unlatch_Button_Status` | `22 09 4C` expect `0x40` | `(True, 64)` |
| 15 | `IPC_Read_Lock_Button_Status` | `22 09 4C` expect `0x01` | `(True, 1)` |
| 16 | `IPC_Read_Unlock_Button_Status` | `22 09 4C` expect `0x04` | `(True, 4)` |
| 17 | `ABS_Read_IMU_EOL_Mode(..., expected_value=0x01)` | `22 F1 F1` | `(True, 0x01)` |
| 18 | `ABS_IMU_EOL_Routine` | `31 01 B0 06 01` | `(True, True)` |
| 19 | `ABS_Read_IMU_EOL_Mode(..., expected_value=0x00)` | `22 F1 F1` | `(True, 0x00)` |
| 20 | `ABS_Read_Pitch_Angle` | `22 F1 0A` | `(True, angle)` |
| 21 | `ABS_Read_Lean_Angle` | `22 F1 08` | `(True, angle)` |
| 22 | `IPC_Write_Test_Stamp` | *skipped — need DID* | |
| 23 | `IPC_Read_Test_Stamp` | *skipped — need DID* | |

`ABS_Read_IMU_EOL_Mode` takes `expected_value` (default `0x01`). After the
second routine call it with `expected_value=0x00`. Mode `0x02` is treated as
an IMU mounting / malfunction fault.

Security key (same as the sample):

```text
key = ((((seed_hb << 8) | seed_lb) + 0xAEFB - 0x1111) << 4) + 0x00A0
key &= 0xFFFF
```

## Call from another main

```python
from ABS_Default_Session import ABS_Default_Session
from ABS_Extended_Session import ABS_Extended_Session
from ABS_Clear_DTC import ABS_Clear_DTC
from ABS_Security_Access import ABS_Security_Access
from ABS_Write_EOL_Mode import ABS_Write_EOL_Mode
from ABS_Read_IMU_EOL_Mode import ABS_Read_IMU_EOL_Mode
from ABS_IMU_EOL_Routine import ABS_IMU_EOL_Routine
from ABS_Read_Pitch_Angle import ABS_Read_Pitch_Angle
from ABS_Read_Lean_Angle import ABS_Read_Lean_Angle

status = ABS_Default_Session("kvaser", 0, 500000)
status = ABS_Extended_Session("kvaser", 0, 500000)
status = ABS_Security_Access("kvaser", 0, 500000)
status, mode = ABS_Read_IMU_EOL_Mode("kvaser", 0, 500000, expected_value=0x01)
status, mode = ABS_Read_IMU_EOL_Mode("kvaser", 0, 500000, expected_value=0x00)
status, pitch = ABS_Read_Pitch_Angle("kvaser", 0, 500000)
status, lean  = ABS_Read_Lean_Angle("kvaser", 0, 500000)
```
