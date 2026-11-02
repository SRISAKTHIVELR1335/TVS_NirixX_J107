# J107 Flashing / VCU — UDS programs

Standalone programs that talk to the VCU on CAN IDs **`0x7B3` / `0x71A`**.
Each one opens the bus, runs its step, and returns to `main`:

```python
status, value = VCU_Read_DTC(interface, channel, bitrate)
```

* success -> `(True, value)` — `"PASSED"` or the decoded value
* failure -> `(False, error_message)`

`VCU_Read_VIN`, `VCU_Read_SKU` and `VCU_Read_CVN` take `api_url` and
`vin_number` and return three values, `(status, api_value, ecu_value)`, on
every path.

## Programs

| file | request |
|---|---|
| `VCU_Clear_DTC` | `0x14 0xFF 0xFF 0xFF` |
| `VCU_Extended_Session` | `0x10 0x03` |
| `VCU_Tester_Present` | `0x3E 0x00`, repeated for 2 s |
| `VCU_Security_Access` | `0x10 0x01` → `0x10 0x03` → `0x27 0x01` → `0x27 0x02 <key>` |
| `VCU_Read_DTC` | `0x10 0x03` → `0x19 0x02 0x8F`, decoded through `dtc_error_code/VCU_DTC.xlsx` |
| `VCU_Read_VIN` | `0x22 0xF1 0x90`, compared against the API VIN |
| `VCU_Read_SKU` | `0x22 0xF1 0x91`, compared against the API SKU |
| `VCU_Read_CVN` | `0x22 0xF1 0xF1`, compared against the API CVN |

The CVN is reported as an upper-case hex string (`4E363139…`), which is the
form the API `txbytes` carries. The VCU key is AES-128 ECB over the 8-byte seed
plus a fixed code, sliced `[4:12]`.

## Shared helper block

Identical to `J107_Flashing/EMS`, `J107_Flashing/ABS`, `J107_IMU`, `J107_RVS`
and `J107_Static`: `log_print`, `_send_can_frame`,
`_receive_single_can_frame`, `receive_isotp_response`, `send_isotp_request`,
`send_tester_present`, `send_uds_request`, `_communication_error_message`. No
imports between files.

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
