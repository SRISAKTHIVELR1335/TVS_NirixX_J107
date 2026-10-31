# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import os
import can
import time
import platform
from Crypto.Cipher import AES
from can import Message

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7B3
ECU_RESPONSE_ID  = 0x71A



log_counter      = 1
START_TIME       = time.perf_counter()

# =========================
# LOGGING
# =========================
def log_print(arb_id, direction, data):
    global log_counter
    elapsed_time = time.perf_counter() - START_TIME
    data_str = ' '.join(f"{b:02X}" for b in data)
    print(f"{log_counter:>3}  {elapsed_time:010.6f} DT {arb_id:04X} {direction} 8  {data_str}")
    log_counter += 1


# =========================
# CAN Helpers
# =========================
def _send_can_frame(bus, arbitration_id, data):
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)

    msg = can.Message(arbitration_id=arbitration_id,data=bytearray(padded_data[:8]),is_fd=False,is_extended_id=False)

    bus.send(msg)
    log_print(msg.arbitration_id, "TX", msg.data)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining_timeout = timeout - (time.time() - start_time)
        if remaining_timeout <= 0:
            break

        msg = bus.recv(timeout=remaining_timeout)
        if msg:
            if msg.arbitration_id == response_id:
                log_print(msg.arbitration_id, "RX", msg.data)
                return msg
    return None


# =========================
# ISO-TP Receive
# =========================
def receive_isotp_response(bus, response_id, timeout=3.0):
    start_time                = time.time()
    full_response_data        = []
    expect_consecutive_frames = False
    seq_number_expected       = 1
    total_uds_length          = 0

    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=1.0)
        if not msg:
            continue

        pci_type = (msg.data[0] & 0xF0) >> 4

        # ---- Single Frame ----
        if pci_type == 0x0:
            uds_length = msg.data[0] & 0x0F
            return list(msg.data[1:1 + uds_length])

        # ---- First Frame ----
        elif pci_type == 0x1:
            total_uds_length          = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            full_response_data        = list(msg.data[2:])
            expect_consecutive_frames = True
            seq_number_expected       = 1

            # ---- Flow Control (CTS) ----
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, TESTER_ID, fc_frame)

        # ---- Consecutive Frame ----
        elif pci_type == 0x2 and expect_consecutive_frames:
            seq_number = msg.data[0] & 0x0F

            if seq_number != seq_number_expected:
                print(f"ISO-TP SEQ ERROR -> expected {seq_number_expected}, got {seq_number}")
                return None

            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16

            if len(full_response_data) >= total_uds_length:
                return full_response_data[:total_uds_length]

    return None


# =========================
# ISO-TP Send
# =========================
def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)

    # ---- Single Frame ----
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True, None

    # ---- First Frame ----
    ff_data = [
        0x10 | ((total_len >> 8) & 0x0F),
        total_len & 0xFF
    ] + data[:6]

    _send_can_frame(bus, arbitration_id, ff_data)

    # ---- Wait for Flow Control ----
    start = time.time()
    st_min_sec = 0.001
    fc_received = False

    while time.time() - start < 2.0:
        fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=0.5)

        if not fc_msg:
            continue

        pci = (fc_msg.data[0] & 0xF0) >> 4

        # ---- Flow Control Frame ----
        if pci == 0x3:
            flow_status = fc_msg.data[0] & 0x0F

            # ---- Continue To Send (CTS) ----
            if flow_status == 0x0:
                st_min = fc_msg.data[2]

                if st_min <= 0x7F:
                    st_min_sec = st_min / 1000.0
                elif 0xF1 <= st_min <= 0xF9:
                    st_min_sec = (st_min - 0xF0) * 0.0001
                else:
                    st_min_sec = 0.001

                fc_received = True
                break

            # ---- Wait ----
            elif flow_status == 0x1:
                continue

            # ---- Overflow / Transmission Rejected ----
            elif flow_status == 0x2:
                return False, "ISOTP_FLOW_CONTROL_OVERFLOW"

            # ---- Unknown Flow Status ----
            else:
                return False, f"ISOTP_FLOW_CONTROL_INVALID_STATUS_0x{flow_status:02X}"

        # ---- Non-FC frame received (unexpected) ----
        else:
            return False, "ISOTP_UNEXPECTED_FRAME_INSTEAD_OF_FC"

    if not fc_received:
        return False, "ISOTP_FLOW_CONTROL_TIMEOUT"

    # ---- Consecutive Frames ----
    remaining_data = data[6:]
    seq = 1

    while remaining_data:
        time.sleep(st_min_sec)

        cf_data_len = min(7, len(remaining_data))
        cf_data = [
            0x20 | (seq & 0x0F)
        ] + remaining_data[:cf_data_len]

        _send_can_frame(bus, arbitration_id, cf_data)

        remaining_data = remaining_data[cf_data_len:]
        seq = (seq + 1) % 16

    return True, None


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

    retry_delay = 3.0
    tp_interval = 1.0

    # ---- Send UDS Request ----
    if len(uds_payload) <= 7:
        isotp_sf_data = ([len(uds_payload)] + uds_payload + [0x00] * (7 - len(uds_payload)))
        _send_can_frame(bus, TESTER_ID, isotp_sf_data)
    else:
        success, isotp_error = send_isotp_request(bus, TESTER_ID, uds_payload)
        if not success:
            return None, isotp_error

    # ---- Receive UDS Response ----
    response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    # ---- Negative Response Handling ----
    if response[0] == 0x7F:
        if len(response) < 3:
            return None, "NRC Received: Invalid Response Format"

        nrc = response[2]

        # ---- NRC 0x78: Response Pending ----
        if nrc == 0x78:
            print("NRC Received: 0x78 (Response Pending)")

            wait_start   = time.time()
            last_tp_time = time.time()

            while time.time() - wait_start < retry_delay:
                pending_response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=0.5)

                if pending_response:
                    # ---- Positive Response ----
                    if pending_response[0] == expected_positive_sid:
                        #print("Positive response received. Stopping Tester Present.\n")
                        return pending_response, None

                    # ---- Another Negative Response ----
                    if pending_response[0] == 0x7F:
                        if len(pending_response) < 3:
                            return None, "NRC Received: Invalid Response Format"

                        pending_nrc = pending_response[2]

                        if pending_nrc == 0x78:
                            print("NRC Received: 0x78 (Response Pending)")
                            wait_start = time.time()
                        else:
                            return None, f"NRC Received: 0x{pending_nrc:02X}"
                    else:
                        return None, f"UNEXPECTED_RESPONSE_SID: 0x{pending_response[0]:02X}"

                # ---- Tester Present ----
                if time.time() - last_tp_time >= tp_interval:
                    send_tester_present(bus)
                    last_tp_time = time.time()

            return None, "NRC Received: 0x78 - Waited no Response Received"

        # ---- Other NRC ----
        return None, f"NRC Received: 0x{nrc:02X}"

    # ---- Validate Positive Response SID ----
    if response[0] == expected_positive_sid:
        return response, None

    return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"


# =========================
# Error Message Helpers
# =========================
def _communication_error_message():
    return (
        "- Verify failed:\n"
        "- No communication from ECU\n"
        "- Check vehicle ignition status\n"
        "- Check CAN wiring\n"
        "- Verify baud rate"
    )


# =========================
# Business Logic
# =========================
PRV_KEY = bytes.fromhex('4A9241B3B1D9F34CFF21ABEC8321EB92')

FIXED_CODE = bytes.fromhex('82E9FC4BB79EFF2A')

def default_diagnostic_session(bus):
    response, error_message = send_uds_request(bus, 0x10, [0x01], 0x50)
    if response and len(response) >= 2 and response[1] == 0x01:
        print("Default Diagnostic Session Passed.\n")
        return True
    print("Default Diagnostic Session Failed.")
    return False

def extended_diagnostic_session(bus):
    response, error_message = send_uds_request(bus, 0x10, [0x03], 0x50)
    if response and len(response) >= 2 and response[1] == 0x03:
        print("Extended Diagnostic Session Passed.\n")
        return True
    print("Extended Diagnostic Session Failed.")
    return False

def request_seed(bus):
    response, error_message = send_uds_request(bus, 0x27, [0x01], 0x67)
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
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    system_os = platform.system()

    # ---- Linux SocketCAN Setup ----
    if system_os == "Linux":
        try:
            interface = "socketcan"
            channel = "can0" if not channel else channel
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {int(bitrate)}")
            os.system(f"sudo ip link set {channel} up")
        except Exception as e:
            error_message = f"Linux SocketCAN setup error: {e}"
            print(error_message)
            return False, error_message

    try:
        try:
            bus = can.Bus(
                interface=interface,
                channel=channel,
                bitrate=int(bitrate),
                fd=False
            )
        except (can.CanInitializationError, can.CanError) as e:
            error_msg_str = str(e).lower()
            if any(term in error_msg_str for term in ["not been initialized", "invalid", "handle", "pcan"]):
                error_message = (
                    "- Verify failed:\n"
                    "- PCAN USB is not connected\n"
                    "- Check PCAN driver installation\n"
                    "- Verify PCAN channel selection"
                )
            elif any(term in error_msg_str for term in ["heavy", "warning", "bus-off"]):
                error_message = _communication_error_message()
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message


        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])
        if not default_diagnostic_session(bus):
            return False, "Failed to enter default diagnostic session."
        if not extended_diagnostic_session(bus):
            return False, "Failed to enter extended diagnostic session."
        seed = request_seed(bus)
        if not seed:
            return False, "Failed to retrieve seed from ECU."
        _, key_to_send = encrypt_seed(seed, PRV_KEY, FIXED_CODE)
        if not key_to_send:
            return False, "Failed to encrypt seed and generate key."
        if not send_key(bus, key_to_send):
            return False, "Failed to send key / Security Access Denied."
        return True, "PASSED"


    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, error_message

    except Exception as e:
        error_message = f"ECU Error: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")

        if system_os == "Linux" and channel:
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    status, result = VCU_Security_Access(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if status:
        print(f"\nSTATUS : SUCCESS - SECURITY ACCESS: {result}")
    else:
        print(f"\nSTATUS : FAILURE / ERROR - {result}")
