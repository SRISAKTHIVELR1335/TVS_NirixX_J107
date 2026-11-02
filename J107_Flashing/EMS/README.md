# J107 Flashing / EMS — UDS write programs

Standalone flashing programs. Each file opens the CAN bus, enters the write
path, verifies the ECU answer, and returns to `main`:

```python
status, value = ABS_Write_SKU(interface, channel, bitrate, api_url, vin)
```

* success -> `(True, value)` — the value written
* failure -> `(False, error_message)`

`EMS_Write_SKU` is the one three-value entry, because it also hands back the
read-back:

```python
match, api_sku, ecu_sku = EMS_Write_SKU(interface, channel, bitrate, api_url, vin)
```

On failure it returns `(False, api_sku, error_message)`; if the API lookup
itself fails before any SKU is known it returns `(False, api_error, None)`.

`error_message` is a UDS error string (`NRC Received: 0xXX`,
`ECU_RESPONSE_TIMEOUT`, `UNEXPECTED_RESPONSE_SID: 0xXX`,
`ISOTP_FLOW_CONTROL_TIMEOUT`) or one of the two operator-facing blocks:

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

Every file carries the same self-contained helper block (`log_print`,
`_send_can_frame`, `_receive_single_can_frame`, `receive_isotp_response`,
`send_isotp_request`, `send_tester_present`, `send_uds_request`,
`_communication_error_message`), so each script runs standalone with no
imports from its siblings. `log_print` emits a PCAN-style trace line:

```text
  1  0.000123 DT 7E0 TX 8  02 10 03 00 00 00 00 00
```

## CAN IDs

| program | tester | ECU response |
|---|---|---|
| `EMS_Write_SKU`, `EMS_Write_VIN` | `0x7E0` | `0x7E8` |
| `ABS_Write_SKU` | `0x7E1` | `0x7E9` |
| `IPC_Write_MAC_ID`, `IPC_Write_Secret_Key` | `0x7C9` | `0x7C1` |

## UDS payloads

| program | request | payload |
|---|---|---|
| `EMS_Write_SKU` | `0x2E 0xF1 0x91` | ASCII SKU, written as received (no padding) |
| `ABS_Write_SKU` | `0x2E 0xF1 0x91` | ASCII SKU padded to 16 bytes with `0x2D` |
| `EMS_Write_VIN` | `0x2E 0xF1 0x90` | ASCII VIN, NUL-padded |
| `IPC_Write_MAC_ID` | `0x2E 0xF1 0x8C` | 6 raw MAC bytes |
| `IPC_Write_Secret_Key` | `0x2E 0xF1 0x39` | 16 raw key bytes |

Expected positive response is `0x6E` with the DID echoed.

The diagnostic-session step (`0x10 0x03` / `0x10 0x01`) is left commented out
inside these files: the workbook runs the session as its own step, so the write
runs in whatever session `TVS_Nirix_J107.py` established.

## Running on Linux

Pass `interface="socketcan"` and a channel name (`can0`). The program brings
the link down, re-applies the bitrate, brings it up, and takes it down again in
`finally`.
