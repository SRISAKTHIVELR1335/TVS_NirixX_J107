# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import can
import time
from can import Message
import pandas as pd
import os
import sys

# =========================
# CONFIG
# =========================
TESTER_ID = 0x7E1
ECU_RESPONSE_ID = 0x7E9

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # PyInstaller temp folder
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

EXCEL_DTC_PATH = resource_path(os.path.join("dtc_error_code", "ABS_DTC.xlsx"))

# =========================
# EXCEL DTC MAPPING (WITH DTC_Required SUPPORT)
# =========================
def safe_str(value, fallback="Unknown Description"):
    if value is None:
        return fallback
    if isinstance(value, float) and pd.isna(value):
        return fallback
    try:
        result = str(value).strip()
        return result if result else fallback
    except Exception:
        return fallback


def load_dtc_map_from_excel(excel_path):
    if not os.path.exists(excel_path):
        print(f"[ERROR] Excel file not found: {excel_path}")
        return {}

    try:
        df = pd.read_excel(excel_path)
        print(f"[DEBUG] Excel columns found: {list(df.columns)}")

        # Normalize column names
        df.columns = df.columns.str.strip()

        # Check for required columns
        required_columns = ['DTC Code', 'Description', 'DTC_Required']
        for col in required_columns:
            if col not in df.columns:
                print(f"[ERROR] Missing required column: '{col}'")
                print(f"[ERROR] Available columns: {list(df.columns)}")
                return {}

        # Normalize values â€” convert before iterating to avoid per-row NaN issues
        df['DTC Code']     = df['DTC Code'].astype(str).str.strip().str.upper()
        df['Description']  = df['Description'].apply(
            lambda v: safe_str(v, fallback="No Description")
        )
        df['DTC_Required'] = df['DTC_Required'].apply(normalize_boolean_value)

        # Build dictionary with duplicate handling
        dtc_map        = {}
        duplicate_count = 0

        for _, row in df.iterrows():
            code          = row['DTC Code']
            desc          = row['Description']   # Now always a clean string
            dtc_required  = row['DTC_Required']

            # Skip completely empty / NaN DTC codes
            if code in ('', 'NAN', 'NONE'):
                print(f"[WARNING] Skipping row with invalid DTC Code: '{code}'")
                continue

            if code in dtc_map:
                # Safe concatenation â€” both sides are guaranteed strings
                existing_desc = dtc_map[code]['description']
                dtc_map[code]['description'] = f"{existing_desc} | {desc}"
                duplicate_count += 1
            else:
                dtc_map[code] = {
                    "description": desc,
                    "dtc_required": dtc_required
                }

        # Preview first 5 entries
        for i, (code, info) in enumerate(dtc_map.items()):
            if i >= 5:
                break
            preview = info['description'][:40]
            print(f"  {code} â†’ {preview}... | Required: {info['dtc_required']}")

        print(f"[INFO] Loaded {len(dtc_map)} unique DTC codes from Excel")
        if duplicate_count > 0:
            print(f"[INFO] Combined {duplicate_count} duplicate entries")

        # Summary
        required_count     = sum(1 for v in dtc_map.values() if v['dtc_required'] is True)
        not_required_count = sum(1 for v in dtc_map.values() if v['dtc_required'] is False)
        print(f"[INFO] DTC_Required=True  (PASS if occurs): {required_count}")
        print(f"[INFO] DTC_Required=False (FAIL if occurs): {not_required_count}")

        return dtc_map

    except Exception as e:
        print(f"[ERROR] Failed to read Excel: {e}")
        import traceback
        traceback.print_exc()
        return {}


def normalize_boolean_value(value):
    """Convert various truthy/falsy representations to bool."""
    if isinstance(value, float) and pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        value_lower = value.strip().lower()
        if value_lower in ('true', 'pass', 'yes', '1', 'p', 'y', 't'):
            return True
        if value_lower in ('false', 'fail', 'no', '0', 'f', 'n'):
            return False

    print(f"[WARNING] Unknown DTC_Required value: '{value}', defaulting to False")
    return False


# =========================
# Logging
# =========================
def log_message(direction, msg):
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    print(f"{direction} {msg.arbitration_id:04X}: {formatted_data}")


# =========================
# CAN HELPERS
# =========================
def _send_can_frame(bus, arbitration_id, data):
    padded = list(data)
    while len(padded) < 8:
        padded.append(0x00)

    msg = Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded[:8]),
        is_extended_id=False
    )
    log_message("TX", msg)
    bus.send(msg)


def _receive_can(bus, response_id, timeout=1.0):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining_timeout = timeout - (time.time() - start_time)
        if remaining_timeout <= 0:
            break
        msg = bus.recv(timeout=remaining_timeout)
        if msg and msg.arbitration_id == response_id:
            log_message("RX", msg)
            return msg
    return None


# =========================
# ISO-TP Receive
# =========================
def receive_isotp_response(bus, response_id, timeout=3.0):
    start        = time.time()
    full_data    = []
    expected_len = 0
    seq_expected = 1
    expecting_cf = False

    while time.time() - start < timeout:
        msg = _receive_can(bus, response_id, timeout=1.0)
        if not msg:
            continue

        pci        = msg.data[0]
        frame_type = (pci & 0xF0) >> 4

        if frame_type == 0x0:                        # Single Frame
            length = pci & 0x0F
            return list(msg.data[1:1 + length])

        elif frame_type == 0x1:
            expected_len = ((pci & 0x0F) << 8) | msg.data[1]
            full_data    = list(msg.data[2:])
            expecting_cf = True
            fc = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            _send_can_frame(bus, TESTER_ID, fc)

        elif frame_type == 0x2 and expecting_cf:
            seq = pci & 0x0F
            if seq != seq_expected:
                print(f"[ERROR] ISO-TP sequence error: expected {seq_expected}, got {seq}")
                return None
            full_data.extend(msg.data[1:])
            seq_expected = (seq_expected + 1) % 16
            if len(full_data) >= expected_len:
                return full_data[:expected_len]

    return None


# =========================
# ISO-TP Send
# =========================
def send_isotp_request(bus, arbitration_id, payload):
    length = len(payload)

    if length <= 7:
        sf = [length] + payload
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # First Frame
    ff = [0x10 | ((length >> 8) & 0x0F), length & 0xFF] + payload[:6]
    _send_can_frame(bus, arbitration_id, ff)

    # Wait for Flow Control
    start      = time.time()
    stmin_sec  = 0.001

    while time.time() - start < 2.0:
        fc = _receive_can(bus, ECU_RESPONSE_ID, timeout=0.5)
        if not fc:
            continue
        if (fc.data[0] >> 4) == 0x3:
            stmin = fc.data[2]
            if stmin <= 0x7F:
                stmin_sec = stmin / 1000
            elif 0xF1 <= stmin <= 0xF9:
                stmin_sec = (stmin - 0xF0) / 10000
            else:
                stmin_sec = 0.001
            break
    else:
        print("[ERROR] No Flow Control received")
        return False

    # Consecutive Frames
    remaining = payload[6:]
    seq       = 1
    while remaining:
        time.sleep(stmin_sec)
        cf        = [0x20 | (seq & 0x0F)] + remaining[:7]
        _send_can_frame(bus, arbitration_id, cf)
        remaining = remaining[7:]
        seq       = (seq + 1) % 16

    return True


# =========================
# Tester Present (SID 0x3E)
# =========================
def send_tester_present(bus):
    uds_payload   = [0x3E, 0x80]
    isotp_sf_data = [len(uds_payload)] + uds_payload
    _send_can_frame(bus, TESTER_ID, isotp_sf_data)


# =========================
# UDS Core
# =========================
def send_uds_request(bus, sid, sub_payload, expected_positive_sid):
    uds_payload = [sid] + sub_payload
    max_retries = 0
    retry_delay = 3.0
    tp_interval = 1.0

    if len(uds_payload) <= 7:
        isotp_sf_data = [len(uds_payload)] + uds_payload
        _send_can_frame(bus, TESTER_ID, isotp_sf_data)
    else:
        if not send_isotp_request(bus, TESTER_ID, uds_payload):
            print("Failed to send ISO-TP request.")
            return None

    for attempt in range(max_retries + 1):
        response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)

        if response and response[0] == 0x7F:
            if len(response) >= 3 and response[2] == 0x78:
                print("[NRC]-0x78-Response Pending")
                wait_start   = time.time()
                last_tp_time = time.time()

                while time.time() - wait_start < retry_delay:
                    pending_response = receive_isotp_response(
                        bus, ECU_RESPONSE_ID, timeout=0.5)
                    if pending_response:
                        if pending_response[0] == expected_positive_sid:
                            return pending_response
                        if pending_response[0] == 0x7F and len(pending_response) >= 3:
                            nrc = pending_response[2]
                            if nrc == 0x78:
                                print("[NRC] 0x78 Received again - Still Pending")
                            else:
                                print(f"Negative Response during wait: NRC 0x{nrc:02X}")
                                return None
                    if time.time() - last_tp_time >= tp_interval:
                        send_tester_present(bus)
                        last_tp_time = time.time()

                print("No positive response after NRC 0x78.")
                return None

            if len(response) >= 3:
                print(f"Negative Response: NRC 0x{response[2]:02X}")
            return None

        if response and response[0] == expected_positive_sid:
            return response

        print("No valid response received.")
        return None

    print("No response received.")
    return None


# =========================
# SESSION
# =========================
def extended_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x03], 0x50)
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session")
        return True
    print("[FAIL] Extended Diagnostic Session")
    return False


# =========================
# SAE J2012 DECODER (REFERENCE)
# =========================
def decode_j2012_dtc(b1: int, b2: int) -> str:
    systems    = {0: 'P', 1: 'C', 2: 'B', 3: 'U'}
    system_bits = (b1 >> 6) & 0x03
    system     = systems[system_bits]
    digit1     = (b1 >> 4) & 0x03
    digit2     = b1 & 0x0F
    digit3     = (b2 >> 4) & 0x0F
    digit4     = b2 & 0x0F
    return f"{system}{digit1}{digit2:X}{digit3:X}{digit4:X}"


def ABS_Read_DTC(interface, channel, bitrate):
    bus = None
    try:
        bus = can.interface.Bus(interface=interface,channel=channel,bitrate=bitrate,fd=False)
        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Load Excel DTC Map
        DTC_MAP = load_dtc_map_from_excel(EXCEL_DTC_PATH)

        # Extended Diagnostic Session
        if not extended_diagnostic_session(bus):
            return False, [{"code": "N/A", "description": "Extended Session Failed"}]

        # Read DTCs (UDS 0x19 0x02)
        response = send_uds_request(bus, 0x19, [0x02, 0x8F], 0x59)

        if not response or len(response) < 3:
            return False, [{"code": "N/A", "description": "No DTC Response"}]

        if response[0] != 0x59:
            return False, [{"code": "N/A", "description": "Invalid UDS Response"}]

        # Skip SID (0x59), SubFunction (0x02), StatusAvailabilityMask
        payload = response[3:]

        if not payload:
            print("[INFO] No DTCs detected")
            return True, []

        # 4 bytes per DTC: [B1][B2][FTB][STATUS]
        if len(payload) % 4 != 0:
            return False, [{
                "code": "N/A",
                "description": "Invalid DTC Payload Length"
            }]

        detected_dtcs = []
        overall_pass  = True
        dtc_count     = len(payload) // 4

        for i in range(dtc_count):
            b1       = payload[i * 4]
            b2       = payload[i * 4 + 1]
            hex_code = f"0X{b1:02X}{b2:02X}"

            dtc_info = DTC_MAP.get(hex_code, None)

            if dtc_info:
                description  = dtc_info["description"]
                dtc_required = dtc_info["dtc_required"]
            else:
                description  = "Unknown DTC (not in Excel)"
                dtc_required = False
                print(f"[WARNING] DTC {hex_code} not found in Excel mapping")

            if not dtc_required:
                overall_pass = False

            print(f"[RAW] b1={b1:02X} b2={b2:02X} â†’ HEX={hex_code}")
            print(f"[DTC] {hex_code}: {description} | DTC_Required={dtc_required}")

            detected_dtcs.append({
                "code": hex_code,
                "description": description
            })

        return overall_pass, detected_dtcs

    except can.CanError as e:
        return False, [{"code": "N/A", "description": f"CAN Error: {e}"}]

    except Exception as e:
        return False, [{"code": "N/A", "description": f"Error: {e}"}]

    finally:
        if bus:
            bus.shutdown()
            print("CAN bus shutdown.")


# ================= ENTRY =================
if __name__ == "__main__":
    success, dtcs = ABS_Read_DTC(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    print(f"\nSUCCESS: {success}")
    print(f"DTC COUNT: {len(dtcs)}")

    if not dtcs:
        print("No DTCs detected")
    else:
        print("DETECTED DTCs:")
        for dtc in dtcs:
            print(f"  Code       : {dtc['code']}")
            print(f"  Description: {dtc['description']}")
