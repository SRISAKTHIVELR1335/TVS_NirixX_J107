# RVS (J107_RVS) programs

Standalone programs from the RVS sample. Each file opens the CAN bus, runs one
UDS step, and returns to `main` either **two** or **three** values.

## Two values — plain UDS step

```python
status, value = Some_Test(interface, channel, bitrate)
```

* success -> `(True, value)` where `value` is the read value, or `"PASSED"`
  for write / control steps
* failure -> `(False, error_message)`

## Three values — API fetch, MATCH / NOT MATCHED read

```python
status, api_value, ecu_value = Some_Read(interface, channel, bitrate, api_url, vin_number)
```

* API value fetched first; the ECU value is then read over CAN and compared
* match -> `(True, api_value, ecu_value)`
* mismatch -> `(False, api_value, ecu_value)`
* failure -> `(False, api_value_or_None, error_message)`

The API value is always slot 2 and the ECU value / error always slot 3, so an
API failure returns `(False, None, api_error)`.

## Error messages

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

Every CAN file carries the same self-contained helper block (`log_print`,
`_send_can_frame`, `_receive_single_can_frame`, `receive_isotp_response`,
`send_isotp_request`, `send_tester_present`, `send_uds_request`,
`_communication_error_message`), so each script runs standalone with no imports
from its siblings. `__main__` always prints a Result block.

`TVS_Nirix_J107.py` loads these dynamically with
`getattr(module, <file name>)`, so the callable inside each file must keep the
same name as the file.

## CAN IDs

| ECU | Tester (TX) | Response (RX) |
|-----|-------------|----------------|
| EMS | `0x7E0`     | `0x7E8`        |
| ABS | `0x7E1`     | `0x7E9`        |
| VCU | `0x7B3`     | `0x71A`        |
| IPC | `0x7C9`     | `0x7C1`        |

Default `__main__`: `interface="pcan"`, `channel="PCAN_USBBUS1"`,
`bitrate=500000`. On Linux the script switches to `socketcan` / `can0`.

## Flow (three-value steps marked ->3)

| # | Function | Request / DID | Notes |
|---|----------|---------------|-------|
| 7/8/9/10 | `*_Tester_Present` | `3E 00`, 2 s loop | 4 ECUs |
| 11 | `IPC_Default_Session` | `10 01` | |
| 12 | `EMS_Read_Test_Stamp` | `22 10 FF` | 2-byte hex string |
| 13 | `IPC_Read_Software_Version` | `22 F1 81`, bytes 20..23 | ->3, `IPC_CVN_READ` |
| 14 | `IPC_Read_Bootloader_Version` | `22 F1 81`, bytes 20..23 | ->3, `IPC_CALID_READ` |
| 15/16/20/32/43 | `*_Extended_Session` | `10 03` | 4 ECUs |
| 17/18/19 | `VCU_/EMS_/IPC_Security_Access` | `27 01` then `27 02` | 3 key algorithms |
| 21 | `IPC_ICCID2_Number` | `22 F2 0C`, 20 ASCII | ->3, txbytes[35:55] |
| 22 | `IPC_IMEI_Number` | `22 F1 43`, 15 ASCII | ->3, txbytes[:15] |
| 23 | `IPC_ICCID1_Number` | `22 F2 0B`, 20 ASCII | ->3, txbytes[15:35] |
| 25 | `EMS_Read_Running_Mode` | `22 10 FF` expect `0x01` | polls 5 s |
| 26–30 | `EMS_ABS_Read_Ride_Mode_*` | ABS `22 2F FF` + EMS `22 11 10` | both ECUs |
| 31/33/34 | `EMS_/ABS_/IPC_Read_VIN` | `22 F1 90` | ->3, `data.vin` |
| 35–38 | `*_Clear_DTC` | `14 FF FF FF` | 4 ECUs |
| 39–42 | `IPC_Read_*_Button_Status` | `22 09 4C` | `0x10` / `0x40` / `0x01` / `0x04` |
| 44 | `EMS_Read_CVN` | `22 F1 F1` | ->3, `PCM_CVN_READ` |
| 45–48 | `*_Read_DTC` | `19 02 8F` | `(bool, [dtc, ...])` |
| — | `*_Write_EOL_Mode` / `EMS_Write_Running_Mode` | `2E …` | write steps |
| — | `IPC_Write_Production_Mode` / `IPC_Write_Test_Stamp` | `2E 09 53` / `2E 10 FF` | write steps |

## Security Access — one algorithm per ECU

| ECU | Key derivation |
|-----|----------------|
| ABS | `key = ((((seed_hb << 8) \| seed_lb) + 0xAEFB - 0x1111) << 4) + 0x00A0`, `& 0xFFFF` |
| EMS | `RIPEMD160(SYMMETRIC_KEY ‖ seed)[:8]` — seed must be 8 bytes |
| VCU | `AES-128-ECB(PRV_KEY, seed_padded_8 ‖ FIXED_CODE)[4:12]` |
| IPC | `VIC_Cluster.dll` `CalculateKey(seed_hex)`; XOR `0xDEADBEEF` fallback when the DLL is absent |

## Files not restructured

These contain no CAN/UDS code and keep their original form:

* `ABS_Flashing_Flag_Check.py`, `EMS_Flashing_Flag_Check.py`,
  `VCU_Flashing_Flag_Check.py` — HTTP flag checks
* `Static_Flag_Check.py`, `DAQ_Flag_Check.py` — HTTP flag checks
* `ICCID1_Status_Check.py` — Tata Communications SIM-status API

## Call from another main

```python
from EMS_Tester_Present import EMS_Tester_Present
from EMS_Read_VIN import EMS_Read_VIN

status, message = EMS_Tester_Present("pcan", "PCAN_USBBUS1", 500000)
status, api_vin, ecu_vin = EMS_Read_VIN(
    "pcan", "PCAN_USBBUS1", 500000,
    "http://10.121.2.174:3002/vehicles/flashFile/ejo",
    "SH2NB133XSP000000",
)
```
