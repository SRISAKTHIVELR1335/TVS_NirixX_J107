# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel
"""

import can
import time
import os
import platform
from can import Message

# ---------------------------------------------------------------------------
# CAN IDs & Diagnostic Constants
# ---------------------------------------------------------------------------
ABS_REQUEST_ID   = 0x7E1
ABS_RESPONSE_ID  = 0x7E9

EMS_REQUEST_ID   = 0x7E0
EMS_RESPONSE_ID  = 0x7E8

# Expected Values
ABS_EXPECTED_VALUE = 0x01
EMS_EXPECTED_VALUE = 0x02

log_counter = 1


# ---------------------------------------------------------------------------
# Logging Helper
# ---------------------------------------------------------------------------
def log_print(arb_id, direction, data):
    global log_counter
    timestamp = time.time() * 1000
    data_str  = ' '.join(f"{b:02X}" for b in data)
    print(
        f"{log_counter:>3}  {timestamp:.3f} DT "
        f"{arb_id:04X} {direction} 8  {data_str}"
    )
    log_counter += 1


# ---------------------------------------------------------------------------
# CAN Frame Sender
# ---------------------------------------------------------------------------
def send_frame(bus, arb_id, data):
    padded = list(data) + [0x00] * (8 - len(data))
    msg = Message(arbitration_id=arb_id, data=bytearray(padded[:8]), is_extended_id=False)
    bus.send(msg)
    log_print(msg.arbitration_id, "TX", msg.data)


# ---------------------------------------------------------------------------
# Flow Control Frame Sender
# ---------------------------------------------------------------------------
def send_flow_control(bus, tester_id, block_size=0x00, st_min=0x00):
    fc_frame = [0x30, block_size, st_min, 0x00, 0x00, 0x00, 0x00, 0x00]
    send_frame(bus, tester_id, fc_frame)
    print(f"  [ISO-TP] Flow Control sent -> Tester ID 0x{tester_id:03X}")


# ---------------------------------------------------------------------------
# ISO-TP Response Receiver (Single & Multi-frame)
# ---------------------------------------------------------------------------
def receive_response(bus, response_id, tester_id, timeout=0.2):
    start           = time.time()
    uds_payload     = []
    expected_length = 0
    expected_sn     = 1
    in_multi_frame  = False

    while (time.time() - start) < timeout:
        remaining = timeout - (time.time() - start)
        if remaining <= 0:
            break

        msg = bus.recv(timeout=min(remaining, 0.05))
        if msg is None or msg.arbitration_id != response_id:
            continue

        log_print(msg.arbitration_id, "RX", msg.data)
        data     = list(msg.data)
        pci_type = (data[0] & 0xF0) >> 4

        # ── Single Frame ──────────────────────────────────────────────────
        if pci_type == 0x0:
            uds_len = data[0] & 0x0F
            if uds_len == 0 or uds_len > 7:
                return None

            uds_payload = data[1: 1 + uds_len]

            # NRC 0x78 (Response Pending) -> Continue listening
            if (len(uds_payload) >= 3 and uds_payload[0] == 0x7F and uds_payload[2] == 0x78):
                uds_payload = []
                in_multi_frame = False
                continue

            return uds_payload

        # ── First Frame ───────────────────────────────────────────────────
        elif pci_type == 0x1:
            expected_length = ((data[0] & 0x0F) << 8) | data[1]
            uds_payload     = data[2:]          # First 6 bytes of UDS data
            expected_sn     = 1
            in_multi_frame  = True

            send_flow_control(bus, tester_id)

        # ── Consecutive Frame ─────────────────────────────────────────────
        elif pci_type == 0x2:
            if not in_multi_frame:
                continue

            sn = data[0] & 0x0F
            if sn != expected_sn:
                return None

            uds_payload += data[1:]
            expected_sn  = (expected_sn + 1) & 0x0F

            if len(uds_payload) >= expected_length:
                return uds_payload[:expected_length]

    if in_multi_frame and len(uds_payload) >= expected_length:
        return uds_payload[:expected_length]

    return None


# ---------------------------------------------------------------------------
# UDS Response Validator
# ---------------------------------------------------------------------------
def validate_response(uds_data, did_high, did_low, expected_value, ecu_name):
    if not uds_data:
        return False

    # ── Negative Response ─────────────────────────────────────────────────
    if uds_data[0] == 0x7F:
        if len(uds_data) >= 3:
            nrc = uds_data[2]
            if nrc == 0x78:
                return None  # Response pending
            print(f"  [{ecu_name}] Negative Response | Service: 0x{uds_data[1]:02X} | NRC: 0x{nrc:02X}")
        return False

    # ── Positive Response (0x62) ──────────────────────────────────────────
    if (len(uds_data) >= 4 and uds_data[0] == 0x62 and uds_data[1] == did_high and uds_data[2] == did_low):
        actual_value = uds_data[3]
        if actual_value == expected_value:
            print(f"  [{ecu_name}] Matched: 0x{actual_value:02X}")
            return True
        else:
            print(f"  [{ecu_name}] Mismatched: Actual 0x{actual_value:02X}, Expected 0x{expected_value:02X}")
            return False

    return False


# =============================================================================
# Main Test Function
# =============================================================================
def EMS_ABS_Read_Ride_Mode_3_Tour(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000, timeout_sec=10.0):
    bus = None
    OS  = platform.system()

    try:
        # ── OS-Specific CAN Setup ────────────────────────────────────────
        if OS == "Linux":
            interface = "socketcan"
            channel   = "can0"
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")

            bus = can.interface.Bus(interface=interface,channel=channel)
        elif OS == "Windows":
            try:
                bus = can.interface.Bus(interface=interface,channel=channel,bitrate=bitrate)
            except can.CanInitializationError:
                error_message = "ERROR: PCAN is not connected or not initialized."
                print(error_message)
                return False, error_message

        # Filter only the response IDs
        bus.set_filters([
            {"can_id": ABS_RESPONSE_ID, "can_mask": 0x7FF, "extended": False},
            {"can_id": EMS_RESPONSE_ID, "can_mask": 0x7FF, "extended": False},
        ])

        abs_request = [0x03, 0x22, 0x2F, 0xFF, 0x00, 0x00, 0x00, 0x00]
        ems_request = [0x03, 0x22, 0x11, 0x10, 0x00, 0x00, 0x00, 0x00]

        # Tracking flags
        ems_matched = False
        abs_matched = False
        ems_value   = None
        abs_value   = None

        start_time = time.time()
        while (time.time() - start_time) < timeout_sec:
            # ── 1. ABS Request & Response (Sent every cycle) ─────────────
            send_frame(bus, ABS_REQUEST_ID, abs_request)
            abs_uds = receive_response(bus, response_id=ABS_RESPONSE_ID, tester_id=ABS_REQUEST_ID, timeout=0.15)
            if validate_response(abs_uds, 0x2F, 0xFF, ABS_EXPECTED_VALUE, "ABS"):
                abs_matched = True
                abs_value   = abs_uds[3]

            # ── 2. EMS Request & Response (Sent every cycle) ─────────────
            send_frame(bus, EMS_REQUEST_ID, ems_request)
            ems_uds = receive_response(bus, response_id=EMS_RESPONSE_ID, tester_id=EMS_REQUEST_ID, timeout=0.15)
            if validate_response(ems_uds, 0x11, 0x10, EMS_EXPECTED_VALUE, "EMS"):
                ems_matched = True
                ems_value   = ems_uds[3]

            # ── 3. Check Condition ───────────────────────────────────────
            if ems_matched and abs_matched:
                print(f"\nEMS & ABS Read Ride Mode Passed - {time.time() - start_time:.2f}s "
                      f"(EMS=0x{ems_value:02X}, ABS=0x{abs_value:02X})")
                return True, "PASSED"

            time.sleep(0.05)

        # ── 4. Timeout Expired ───────────────────────────────────────────
        print(f"\n[FAILED] Test Timed Out ({timeout_sec}s).")
        print(f"Status -> ABS Matched: {abs_matched}, EMS Matched: {ems_matched}")
        return False, "TIMEOUT: Did not receive expected response from both ECUs"

    except KeyboardInterrupt:
        error_message = "ERROR: Operation interrupted by user."
        print(error_message)
        return False, error_message

    except can.CanError as e:
        error_msg = str(e).lower()
        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."
        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = ("ERROR: No communication from ECU.\n"
                             "Check ECU power, CAN wiring and baud rate.")
        else:
            error_message = f"CAN Error: {e}"

        print(error_message)
        return False, error_message

    except Exception as e:
        error_message = f"Unexpected Error: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN Channel Closed.")

        if OS == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"  {channel} Down Complete")


# =============
# Entry Point
# =============
if __name__ == "__main__":
    result, status = EMS_ABS_Read_Ride_Mode_3_Tour(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        timeout_sec=10.0
    )