# J107 Flashing / EMS — UDS programs

Every program in this folder is standalone: it opens the CAN bus, runs one UDS
step (or a small sequence such as session → seed/key → write), and returns to
`main`.

```python
status, value = EMS_Read_VIN(interface, channel, bitrate, api_url, vin)
```

* success -> `(True, value)`
* failure -> `(False, error_message)`

API-backed readers return three values, `(status, api_value, ecu_value)`, on
every path. `EMS_Write_SKU` is also a three-value entry:

```python
match, api_sku, ecu_sku = EMS_Write_SKU(interface, channel, bitrate, api_url, vin)
```

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

## Shared helper block

Each file carries the same self-contained helpers, so there are no imports
between siblings: `log_print`, `_send_can_frame`,
`_receive_single_can_frame`, `receive_isotp_response`, `send_isotp_request`,
`send_tester_present`, `send_uds_request`, `_communication_error_message`.

`send_uds_request` returns `(response, error_message)` and handles NRC `0x78`
by re-arming a 3 s window while sending Tester Present every second.

`log_print` emits a PCAN-style trace line:

```text
  1  0.000123 DT 7E0 TX 8  02 10 03 00 00 00 00 00
```

## CAN IDs

| program prefix | tester | ECU response |
|---|---|---|
| `EMS_*`, `Bosch_EMS_*` | `0x7E0` | `0x7E8` |
| `ABS_*`, `Bosch_ABS_*` | `0x7E1` | `0x7E9` |
| `IPC_*` | `0x7C9` | `0x7C1` |
| `VCU_*` | `0x7B3` | `0x71A` |

## Programming steps in this folder

| program | request |
|---|---|
| `EMS_Write_SKU` | `0x2E 0xF1 0x91` + ASCII SKU (unpadded) |
| `ABS_Write_SKU` | `0x2E 0xF1 0x91` + ASCII SKU padded to 16 with `0x2D` |
| `EMS_Write_VIN` | `0x2E 0xF1 0x90` + ASCII VIN |
| `IPC_Write_MAC_ID` | `0x2E 0xF1 0x8C` + 6 MAC bytes |
| `IPC_Write_Secret_Key` | `0x2E 0xF1 0x39` + 16 key bytes |
| `ABS_Write_IMU_Feature_Control` | `0x2E 0x30 0x06 0x01` |
| `EMS_IMMO_Enable` | `0x2E 0x02 0x12 0x01` |
| `EMS_Quick_Shift_Enable` | `0x2E 0x01 0x24 0x01` |
| `IPC_Write_Test_Stamp` | `0x2E 0x10 0xFF 0x00 0x01 0x20` |

Expected positive response is `0x6E` with the DID echoed.

The flashing copies of `ABS/EMS/IPC/VCU_Security_Access` enter the default and
extended session before requesting the seed; the diagnostic-session step used
to be a separate workbook step, so the write programs keep their session call
commented out.

## Running on Linux

Pass `interface="socketcan"` and a channel name (`can0`). The program brings
the link down, re-applies the bitrate, brings it up, and takes it down again in
`finally`.
