# -*- coding: utf-8 -*-
"""
Created on Tue Sep 2 15:34:08 2025

@author: Sri.Sakthivel
"""

import can
from can import Message
import time
import os
import platform

# =========================
# ABS Configuration
# =========================
TESTER_ID = 0x7E1
ECU_RESPONSE_ID = 0x7E9

log_counter = 1


# =========================
# LOGGING
# =========================
def log_message(direction, msg):
    global log_counter
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    time_stamp = time.time() * 1000
    print(f"{log_counter:>3}  {time_stamp:.3f} DT {msg.arbitration_id:04X} {direction} 8  {formatted_data}")
    log_counter += 1


# =========================
# CAN HELPERS
# =========================
def _send_can_frame(bus, arbitration_id, data):
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)
    msg = Message(arbitration_id=arbitration_id, data=bytearray(padded_data[:8]), is_fd=False, is_extended_id=False)
    log_message("TX", msg)
    bus.send(msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining = timeout - (time.time() - start_time)
        if remaining <= 0:
            break
        msg = bus.recv(timeout=remaining)
        if msg and msg.arbitration_id == response_id:
            log_message("RX", msg)
            return msg
    return None


# =========================
# ISO-TP RECEIVE
# =========================
def receive_isotp_response(bus, response_id, timeout=3.0):
    start_time = time.time()
    full_response_data = []
    expect_consecutive_frames = False
    seq_number_expected = 1
    total_uds_length = 0

    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not msg:
            continue

        pci_type = (msg.data[0] & 0xF0) >> 4

        # ---- Single Frame ----
        if pci_type == 0x0:
            uds_length = msg.data[0] & 0x0F
            return list(msg.data[1:1 + uds_length])

        # ---- First Frame ----
        elif pci_type == 0x1:
            total_uds_length = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            print(f"  [ISO-TP] Total UDS length expected: {total_uds_length} bytes")
            full_response_data = list(msg.data[2:])
            expect_consecutive_frames = True
            seq_number_expected = 1

            # Send Flow Control (CTS)
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.005)
            _send_can_frame(bus, TESTER_ID, fc_frame)

        # ---- Consecutive Frame ----
        elif expect_consecutive_frames and pci_type == 0x2:
            seq_number = msg.data[0] & 0x0F
            if seq_number != seq_number_expected:
                print(f"  [ISO-TP] Sequence mismatch: Expected {seq_number_expected}, Got {seq_number}")
                return None

            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16

            if len(full_response_data) >= total_uds_length:
                return full_response_data[:total_uds_length]

    return None


# =========================
# ISO-TP SEND
# =========================
def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)

    # Single Frame
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # First Frame
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # Wait for Flow Control
    fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=1.5)
    if not fc_msg:
        print("  [ISO-TP] No Flow Control received from ECU.")
        return False

    pci_type = (fc_msg.data[0] & 0xF0) >> 4
    if pci_type != 0x3:
        print("  [ISO-TP] Invalid Flow Control frame.")
        return False

    flow_status = fc_msg.data[0] & 0x0F
    if flow_status != 0:  # Not CTS
        print(f"  [ISO-TP] Flow Control status not CTS: {flow_status}")
        return False

    # Calculate Separation Time (STmin) according to ISO 15765-2
    st_min = fc_msg.data[2]
    if st_min <= 0x7F:
        st_min_sec = st_min / 1000.0
    elif 0xF1 <= st_min <= 0xF9:
        st_min_sec = (st_min - 0xF0) * 0.0001
    else:
        st_min_sec = 0.001

    # Send Consecutive Frames
    remaining_data = data[6:]
    seq = 1

    while remaining_data:
        time.sleep(st_min_sec)
        cf_pci = 0x20 | (seq % 16)
        cf_data_len = min(7, len(remaining_data))
        cf_data = [cf_pci] + remaining_data[:cf_data_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining_data = remaining_data[cf_data_len:]
        seq += 1

    return True


# =========================
# UDS CORE
# =========================
def send_uds_request(bus, sid, sub_payload, expected_positive_sid):
    uds_payload = [sid] + sub_payload
    retry_delay = 2.0

    if not send_isotp_request(bus, TESTER_ID, uds_payload):
        print("Failed to send ISO-TP request.")
        return None

    response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)

    # NRC Handling
    if response and response[0] == 0x7F:
        if len(response) >= 3 and response[2] == 0x78:
            print("  [NRC 0x78] Response Pending - waiting...")
            time.sleep(retry_delay)
            return receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=5.0)

        if len(response) >= 3:
            print(f"  [UDS] Negative Response: NRC 0x{response[2]:02X}")
        return None

    if response and response[0] == expected_positive_sid:
        return response

    return None


# =========================
# SESSIONS & SECURITY ACCESS
# =========================
def default_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x01], 0x50)
    if response and len(response) >= 2 and response[1] == 0x01:
        print("Default Diagnostic Session Passed.\n")
        return True
    print("Default Diagnostic Session Failed.")
    return False


def extended_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x03], 0x50)
    if response and len(response) >= 2 and response[1] == 0x03:
        print("Extended Diagnostic Session Passed.\n")
        return True
    print("Extended Diagnostic Session Failed.")
    return False


def calculate_key(seed_hb, seed_lb):
    """
    ABS Specific Key Generation Algorithm
    """
    genkey = (seed_hb << 8) | seed_lb
    key = (((genkey + 0xAEFB) - 0x1111) << 4) + 0x00A0
    key = key & 0xFFFF
    return (key >> 8, key & 0xFF)


def request_seed(bus):
    response = send_uds_request(bus, 0x27, [0x01], 0x67)
    if response and len(response) >= 4 and response[1] == 0x01:
        seed_hb, seed_lb = response[2], response[3]
        print(f"Raw Seed Received: HB=0x{seed_hb:02X}, LB=0x{seed_lb:02X}")
        return seed_hb, seed_lb
    print("Seed Request Failed.")
    return None


def send_key(bus, key_hb, key_lb):
    response = send_uds_request(bus, 0x27, [0x02, key_hb, key_lb], 0x67)
    if response and len(response) >= 2 and response[1] == 0x02:
        print("Security Access Passed (Unlocked).\n")
        return True
    print("Security Access Failed.")
    return False


# =========================
# MAIN FUNCTION
# =========================
def ABS_Security_Access(interface, channel, bitrate):
    bus = None
    OS = platform.system()

    try:
        # OS-Specific CAN initialization
        if OS == "Linux":
            interface = "socketcan"
            channel = "can0"
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")
            bus = can.interface.Bus(interface=interface, channel=channel)

        elif OS.upper() == "WINDOWS":
            try:
                bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate, fd=False)
            except can.CanInitializationError:
                error_message = "ERROR: PCAN is not connected or not initialized."
                return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Step 1: Default Session
        if not default_diagnostic_session(bus):
            return False, "Failed to enter default diagnostic session."

        # Step 2: Extended Session
        if not extended_diagnostic_session(bus):
            return False, "Failed to enter extended diagnostic session."

        # Step 3: Request Seed
        seed = request_seed(bus)
        if not seed:
            return False, "Failed to retrieve seed from ECU."

        # Step 4: Calculate Key
        seed_hb, seed_lb = seed
        key_hb, key_lb = calculate_key(seed_hb, seed_lb)
        print(f"Calculated Key: HB=0x{key_hb:02X}, LB=0x{key_lb:02X}")

        # Step 5: Send Key
        if not send_key(bus, key_hb, key_lb):
            return False, "Failed to send key / Security Access Denied."

        return True, "PASSED"

    except can.CanError as e:
        error_msg = str(e).lower()
        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."
        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = "ERROR: No communication from ECU. Check ECU power, CAN wiring and baud rate."
        else:
            error_message = f"CAN Error: {e}"
        return False, error_message

    except KeyboardInterrupt:
        return False, "ERROR: Operation interrupted by user."

    except Exception as e:
        return False, f"Unexpected Error: {e}"

    finally:
        if bus:
            time.sleep(0.1)
            bus.shutdown()
            print("CAN bus shutdown completed.")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    status, result = ABS_Security_Access(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    print("\n" + "=" * 40)
    print(f"STATUS : {'SUCCESS' if status else 'FAILURE'}")
    print(f"RESULT : {result}")
    print("=" * 40)