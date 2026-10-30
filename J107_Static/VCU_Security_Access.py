# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel
"""

import can
from Crypto.Cipher import AES
import time
from can import Message
import platform
import os

# =========================
# Configuration
# =========================
TESTER_ID = 0x7B3
ECU_RESPONSE_ID = 0x71A
PRV_KEY = bytes.fromhex('4A9241B3B1D9F34CFF21ABEC8321EB92')
FIXED_CODE = bytes.fromhex('82E9FC4BB79EFF2A')

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

        if pci_type == 0x0:  # Single Frame
            uds_length = msg.data[0] & 0x0F
            return list(msg.data[1:1 + uds_length])

        elif pci_type == 0x1:  # First Frame
            total_uds_length = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            print(f"Total UDS length expected: {total_uds_length}")
            full_response_data = list(msg.data[2:])
            expect_consecutive_frames = True
            seq_number_expected = 1

            # Send Flow Control (CTS)
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.005)
            _send_can_frame(bus, TESTER_ID, fc_frame)

        elif expect_consecutive_frames and pci_type == 0x2:  # Consecutive Frame
            seq_number = msg.data[0] & 0x0F
            if seq_number != seq_number_expected:
                print(f"ISO-TP Sequence mismatch. Expected: {seq_number_expected}, Got: {seq_number}")
                return None

            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16

            if len(full_response_data) >= total_uds_length:
                return full_response_data[:total_uds_length]

    return None


# =========================
# ISO-TP SEND (FIXED STmin)
# =========================
def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # Send First Frame
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # Wait for Flow Control
    fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=2.0)
    if not fc_msg:
        print("No flow control received.")
        return False

    pci_type = (fc_msg.data[0] & 0xF0) >> 4
    if pci_type != 0x3:
        print("Invalid flow control frame.")
        return False

    flow_status = fc_msg.data[0] & 0x0F
    if flow_status != 0:  # Not CTS
        print(f"Flow control status not CTS: {flow_status}")
        return False

    # Calculate Separation Time (STmin) according to ISO 15765-2
    st_min = fc_msg.data[2]
    if st_min <= 0x7F:
        st_min_sec = st_min / 1000.0
    elif 0xF1 <= st_min <= 0xF9:
        st_min_sec = (st_min - 0xF0) * 0.0001 
    else:
        st_min_sec = 0.001                    # Default 1ms

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

    if response and response[0] == 0x7F:
        if len(response) >= 3 and response[2] == 0x78:
            print("[NRC 0x78] Response Pending - waiting...")
            time.sleep(retry_delay)
            return receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=5.0)

        if len(response) >= 3:
            print(f"Negative Response: NRC 0x{response[2]:02X}")
        return None

    if response and response[0] == expected_positive_sid:
        return response

    return None


# =========================
# DIAGNOSTIC SESSIONS & SECURITY
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


def request_seed(bus):
    response = send_uds_request(bus, 0x27, [0x01], 0x67)
    if response and len(response) >= 2 and response[1] == 0x01:
        seed = bytes(response[2:])
        if seed:
            print(f"Raw Seed Received: {seed.hex()}")
            return seed
        print("Invalid seed length.")
    print("Seed Request Failed.")
    return None


def encrypt_seed(seed, prv_key, fixed_code):
    if not seed:
        return None, None

    # Pad seed to 8 bytes if needed
    if len(seed) < 8:
        padded_seed = seed + b'\x00' * (8 - len(seed))
    elif len(seed) == 8:
        padded_seed = seed
    else:
        print("Seed length exceeds 8 bytes.")
        return None, None

    plaintext = padded_seed + fixed_code
    print(f"Plaintext (Seed + FixedCode): {plaintext.hex()}")

    cipher = AES.new(prv_key, AES.MODE_ECB)
    encrypted_full = cipher.encrypt(plaintext)
    print(f"AES Key: {encrypted_full.hex()}")

    key_to_send = encrypted_full[4:12]
    print(f"Sliced Key to Send: {key_to_send.hex()}")
    print("AES Encryption Passed.\n")
    return encrypted_full, key_to_send


def send_key(bus, encrypted_key_to_send):
    if not encrypted_key_to_send or len(encrypted_key_to_send) != 8:
        print("Invalid key length for sending.")
        return False

    uds_payload = [0x27, 0x02] + list(encrypted_key_to_send)

    if not send_isotp_request(bus, TESTER_ID, uds_payload):
        print("Failed to send ISO-TP Send Key request.")
        return False

    response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)

    if response and response[0] == 0x7F:
        if len(response) >= 3 and response[2] == 0x78:
            response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)
        else:
            print(f"Negative Response on Key: NRC 0x{response[2]:02X}")
            return False

    if response and len(response) >= 2 and response[0] == 0x67 and response[1] == 0x02:
        print("Security Access Passed (Unlocked).\n")
        return True

    print("Security Access Failed: Invalid or No Response.")
    return False


# =========================
# MAIN FUNCTION
# =========================
def VCU_Security_Access(interface, channel, bitrate):
    bus = None
    OS = platform.system()

    try:
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
                print(error_message)
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
        _, key_to_send = encrypt_seed(seed, PRV_KEY, FIXED_CODE)
        if not key_to_send:
            return False, "Failed to encrypt seed and generate key."

        # Step 5: Send Key
        if not send_key(bus, key_to_send):
            return False, "Failed to send key / Security Access Denied."

        return True, "PASSED"

    except can.CanError as e:
        error_msg = str(e).lower()
        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."
        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = "ERROR: No communication from ECU. Check ECU power, wiring and baud rate."
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
            print("CAN bus shutdown completed.")


if __name__ == "__main__":
    VCU_Security_Access(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000)