# IPC / EMS UDS Readers

Standalone UDS `ReadDataByIdentifier` (SID `0x22`) programs, one file per DID.
Each script keeps the same ISO-TP / UDS stack as the EMS gear-position sample
and returns a `(success, value)` tuple to `main`.

## CAN IDs

| ECU | Tester (TX) | Response (RX) |
|-----|-------------|----------------|
| IPC | `0x7C9`     | `0x7C1`        |
| EMS | `0x7E0`     | `0x7E8`        |
| HLC | `0x7D3`     | `0x73A`        |

Windows default in every `__main__`: `interface="kvaser"`, `channel=0`, `bitrate=500000`.
On Linux the script switches to `socketcan` / `can0` automatically.

## Programs

| File | Function | DID | Behaviour | Returns to main |
|------|----------|-----|-----------|-----------------|
| `IPC_Read_E_SIM_Status.py` | `IPC_Read_E_SIM_Status` | `09 4D` | Read once | `(True, "AA BB …")` hex string |
| `IPC_Read_Bluetooth_Firmware_Version.py` | `IPC_Read_Bluetooth_Firmware_Version` | `B1 D1` | Read once | `(True, hex [+ ASCII])` |
| `IPC_Read_MAC_ID_Bluetooth_Chip.py` | `IPC_Read_MAC_ID_Bluetooth_Chip` | `B1 D5` | Read once | `(True, "AA:BB:CC:DD:EE:FF")` if 6 bytes, else hex |
| `IPC_Read_Mode_Selection_Status_SET.py` | `IPC_Read_Mode_Selection_Status_SET` | `E1 D0` | Poll until `0x04` | `(True, 0x04)` |
| `IPC_Read_Mode_Selection_Status_BACK.py` | `IPC_Read_Mode_Selection_Status_BACK` | `E1 D0` | Poll until `0x02` | `(True, 0x02)` |
| `IPC_Read_Mode_Selection_Status_UP.py` | `IPC_Read_Mode_Selection_Status_UP` | `E1 D0` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Mode_Selection_Status_DOWN.py` | `IPC_Read_Mode_Selection_Status_DOWN` | `E1 D0` | Poll until `0x08` | `(True, 0x08)` |
| `IPC_Read_Cruise_SET_Button_Status.py` | `IPC_Read_Cruise_SET_Button_Status` | `F1 9B` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Cruise_RESET_Button_Status.py` | `IPC_Read_Cruise_RESET_Button_Status` | `F1 9C` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Cruise_ON_OFF_Button_Status.py` | `IPC_Read_Cruise_ON_OFF_Button_Status` | `F1 9D` | Read and decode | `(True, "ON")` or `(True, "OFF")` |
| `IPC_Read_Traction_Control_Button_Status.py` | `IPC_Read_Traction_Control_Button_Status` | `09 09` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Fuel_Level_Sensor_Resistance.py` | `IPC_Read_Fuel_Level_Sensor_Resistance` | `E0 65` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Neutral_Gear_Position.py` | `IPC_Read_Neutral_Gear_Position` | `E1 27` | Poll until `0x02` | `(True, 0x02)` |
| `EMS_Read_Clutch_Switch_Status.py` | `EMS_Read_Clutch_Switch_Status` | `04 14` | Poll until `0x01` | `(True, 0x01)` |
| `EMS_Read_Clutch_Status.py` | `EMS_Read_Clutch_Status` | `10 05` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_Variant_Control.py` | `IPC_Read_Variant_Control` | `09 07` | Read and decode | `(True, "BASE")` or `(True, "KEYLESS")` |
| `EMS_Read_Engine_Temperature.py` | `EMS_Read_Engine_Temperature` | `01 02` | `(0.1 * int) - 273.14` | `(True, "24.96 deg C")` |
| `EMS_Read_Intake_Air_Temperature.py` | `EMS_Read_Intake_Air_Temperature` | `01 03` | `(0.1 * int) - 273.14` | `(True, "25.00 deg C")` |
| `EMS_Read_Map_Sensor_Voltage.py` | `EMS_Read_Map_Sensor_Voltage` | `01 12` | `0.00488281 * int` | `(True, "1.25000 V")` |
| `IPC_Read_Photo_Sensor.py` | `IPC_Read_Photo_Sensor` | `E1 1B` | raw int → decimal | `(True, "45 %")` |
| `EMS_Read_Lambda_Multiplicative_Adaptation_Upstream.py` | `EMS_Read_Lambda_Multiplicative_Adaptation_Upstream` | `01 19` | `0.00488281 * int` | `(True, 1.000976)` |
| `EMS_Read_Lambda_Additive_Adaptation_Upstream.py` | `EMS_Read_Lambda_Additive_Adaptation_Upstream` | `01 1A` | `0.046875 * int` | `(True, 0.75)` |
| `EMS_Read_Lambda_Correction_Upstream_Cylinder_2.py` | `EMS_Read_Lambda_Correction_Upstream_Cylinder_2` | `04 04` | `3.0517578125E-5 * int` | `(True, 1.0)` |
| `EMS_Read_Lambda_Average_Upstream_Cylinder_2.py` | `EMS_Read_Lambda_Average_Upstream_Cylinder_2` | `04 05` | `3.0517578125E-5 * int` | `(True, 1.0)` |
| `EMS_Read_Ambient_Pressure_Of_Engine.py` | `EMS_Read_Ambient_Pressure_Of_Engine` | `10 09` | `0.03900625 * int` | `(True, "101.026 hpa")` |
| `EMS_Read_IDLE_Throttle_APS_1.py` | `EMS_Read_IDLE_Throttle_APS_1` | `11 02` | `0.2 * int` | `(True, "800.0 mV")` |
| `EMS_Read_IDLE_Throttle_APS_2.py` | `EMS_Read_IDLE_Throttle_APS_2` | `11 03` | `0.2 * int` | `(True, "800.0 mV")` |
| `EMS_Read_FULL_Throttle_APS_1.py` | `EMS_Read_FULL_Throttle_APS_1` | `11 02` | `0.2 * int` | `(True, "4000.0 mV")` |
| `EMS_Read_FULL_Throttle_APS_2.py` | `EMS_Read_FULL_Throttle_APS_2` | `11 03` | `0.2 * int` | `(True, "4000.0 mV")` |
| `EMS_Read_BLIP_Throttle_APS_1.py` | `EMS_Read_BLIP_Throttle_APS_1` | `11 02` | `0.2 * int` | `(True, "2500.0 mV")` |
| `EMS_Read_BLIP_Throttle_APS_2.py` | `EMS_Read_BLIP_Throttle_APS_2` | `11 03` | `0.2 * int` | `(True, "2500.0 mV")` |
| `EMS_Read_Side_Stand_Sensor_Voltage.py` | `EMS_Read_Side_Stand_Sensor_Voltage` | `01 23` | Read and decode | `(True, "SIDE STANDED")` or `(True, "NOT SIDE STANDED")` |
| `EMS_Read_Kill_Switch_Status.py` | `EMS_Read_Kill_Switch_Status` | `10 24` | Read and decode | `(True, "KILL SWITCH ON")` or `(True, "KILL SWITCH OFF")` |
| `IPC_Read_Indicator_Switch_Status.py` | `IPC_Read_Indicator_Switch_Status` | `E1 C9` | Read and decode | `(True, "LEFT")` or `(True, "RIGHT")` |
| `EMS_Read_IMMO_Status.py` | `EMS_Read_IMMO_Status` | `02 12` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_DRL_Status.py` | `IPC_Read_DRL_Status` | `09 12` | Poll until `0x01` | `(True, 0x01)` |
| `IPC_Read_TPMS_Config_Status.py` | `IPC_Read_TPMS_Config_Status` | `B1 DB` | Poll until `0x01` | `(True, 0x01)` |
| `HLC_Read_Headlamp_Software_Version.py` | `HLC_Read_Headlamp_Software_Version` | `F1 95` | Read `response[3:]` | `(True, "AA BB …")` hex string |
| `IPC_Read_Hazard_Switch_Status.py` | `IPC_Read_Hazard_Switch_Status` | `E1 D3` | Poll until `0x01` (ON) | `(True, "HAZARD SWITCH ON")` |
| `IPC_Read_Bike_Finder_Button_Status.py` | `IPC_Read_Bike_Finder_Button_Status` | `09 4C` | Poll until `0x10`, to decimal | `(True, 16)` |
| `IPC_Read_Seat_Unlatch_Button_Status.py` | `IPC_Read_Seat_Unlatch_Button_Status` | `09 4C` | Poll until `0x40`, to decimal | `(True, 64)` |
| `IPC_Read_Lock_Button_Status.py` | `IPC_Read_Lock_Button_Status` | `09 4C` | Poll until `0x01`, to decimal | `(True, 1)` |
| `IPC_Read_Unlock_Button_Status.py` | `IPC_Read_Unlock_Button_Status` | `09 4C` | Poll until `0x04`, to decimal | `(True, 4)` |
| `IPC_Warning_Lights_IO_Control.py` | `IPC_Warning_Lights_IO_Control` | `2F E1 BD 03 01 00 00` | IO control, expect `0x6F` | `True` |
| `HLC_Headlamp_OFF_IO_Control.py` | `HLC_Headlamp_OFF_IO_Control` | `2F FD 00 00 00 00 00` | IO control, expect `0x6F` | `True` |
| `HLC_High_Beam_IO_Control.py` | `HLC_High_Beam_IO_Control` | `2F FD 00 04 00 00 00` | IO control, expect `0x6F` | `True` |
| `HLC_Low_Beam_IO_Control.py` | `HLC_Low_Beam_IO_Control` | `2F FD 00 01 00 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_IG_Coil_1_IO_Control.py` | `EMS_IG_Coil_1_IO_Control` | `2F A8 03 03 00 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_IG_Coil_2_IO_Control.py` | `EMS_IG_Coil_2_IO_Control` | `2F A8 16 03 01 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_Injector_Coil_1_IO_Control.py` | `EMS_Injector_Coil_1_IO_Control` | `2F A8 02 03 00 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_Injector_Coil_2_IO_Control.py` | `EMS_Injector_Coil_2_IO_Control` | `2F A8 17 03 00 01 00` | IO control, expect `0x6F` | `True` |
| `EMS_Canister_Purge_Valve_IO_Control.py` | `EMS_Canister_Purge_Valve_IO_Control` | `2F A8 08 03 00 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_Purge_Valve_IO_Control.py` | `EMS_Purge_Valve_IO_Control` | `2F A8 08 00 00 00 00` | IO control, expect `0x6F` | `True` |
| `EMS_Actuate_FAN_Relay_IO_Control.py` | `EMS_Actuate_FAN_Relay_IO_Control` | `2F A8 06 03 45 00 00` | IO control, expect `0x6F` | `True` |

Failure path for every function: `(False, None)`.

Physical signals take every data byte after SID+DID as a big-endian unsigned integer,
then apply the formula. Temperature / voltage / photo / pressure / APS return a
string that already includes the unit. Lambda signals return the converted float
only (no unit was specified).

IDLE / FULL / BLIP APS share DIDs `11 02` and `11 03`. Put the throttle in that
state, then run the matching script.

Decoded maps:

- Cruise ON/OFF (`F1 9D`): `0x01` → `"ON"`, `0x00` → `"OFF"`
- Variant Control (`09 07`): `0x00` → `"BASE"`, `0x01` → `"KEYLESS"`

The slash in `IPC_Read_Cruise_ON/OFF_Button_Status` is not valid in a Python
name, so the callable is `IPC_Read_Cruise_ON_OFF_Button_Status`.

## Run one program

```bash
pip install python-can
python IPC_Read_E_SIM_Status.py
```

Success printout:

```
STATUS  : SUCCESS
E-SIM   : 01
```

## Call from another test / main

```python
from IPC_Read_E_SIM_Status import IPC_Read_E_SIM_Status
from IPC_Read_Cruise_ON_OFF_Button_Status import IPC_Read_Cruise_ON_OFF_Button_Status
from IPC_Read_Variant_Control import IPC_Read_Variant_Control
from EMS_Read_Clutch_Switch_Status import EMS_Read_Clutch_Switch_Status
from EMS_Read_Clutch_Status import EMS_Read_Clutch_Status

ok, esim = IPC_Read_E_SIM_Status("kvaser", 0, 500000)
ok, cruise = IPC_Read_Cruise_ON_OFF_Button_Status("kvaser", 0, 500000)  # "ON" / "OFF"
ok, variant = IPC_Read_Variant_Control("kvaser", 0, 500000)              # "BASE" / "KEYLESS"
ok, clutch_sw = EMS_Read_Clutch_Switch_Status("kvaser", 0, 500000)       # DID 04 14
ok, clutch = EMS_Read_Clutch_Status("kvaser", 0, 500000)                 # DID 10 05
```

Poll scripts wait up to 5.0 s at 0.2 s intervals for the expected byte, same as
`Read_Gear_Position` in the sample.
