# -*- coding: utf-8 -*-
"""
Created on Tue May 19 13:52:14 2026

@author: Srisakthivel.R
"""


import can
import hashlib
import time
import threading
from can import Message

# ===========================================================================
# User Configuration
# ===========================================================================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
log_counter = 1

# 16-byte fixed symmetric key
SYMMETRIC_KEY = bytes.fromhex('989648DE3A0AF6EEB9BA89E540A61536')

# ===========================================================================
# Logging Helper
# ===========================================================================
def log_print(arb_id, direction, data):
    global log_counter
    timestamp = time.time() * 1000
    data_str = ' '.join(f"{b:02X}" for b in data)
    print(f"{log_counter:3}  {timestamp:.3f} DT {arb_id:04X} {direction} 8  {data_str}")
    log_counter += 1

# ===========================================================================
# CAN / ISO-TP Transport Layer
# ===========================================================================
def _send_can_frame(bus, arbitration_id, data):
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)
    msg = Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
    log_print(arbitration_id,"TX", msg.data)
    bus.send(msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining = timeout - (time.time() - start_time)
        msg = bus.recv(timeout=remaining)
        if msg and msg.arbitration_id == response_id:
            log_print(response_id,"RX", msg.data)
            return msg
    return None


def receive_isotp_response(bus, response_id, timeout=5.0):
    start_time = time.time()
    full_response_data       = []
    expect_consecutive       = False
    seq_number_expected      = 1
    total_uds_length         = 0

    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not msg:
            continue

        pci_type = (msg.data[0] & 0xF0) >> 4

        # ── Single Frame ────────────────────────────────────────────────────
        if pci_type == 0x0:
            uds_length = msg.data[0] & 0x0F
            full_response_data = list(msg.data[1:1 + uds_length])
            break

        # ── First Frame ─────────────────────────────────────────────────────
        elif pci_type == 0x1:
            total_uds_length = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            print(f"Total UDS length expected: {total_uds_length}")
            full_response_data   = list(msg.data[2:])
            expect_consecutive   = True
            seq_number_expected  = 1
            # Send Flow Control – Continue to Send
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, TESTER_ID, fc_frame)
            time.sleep(0.01)
            continue

        # ── Consecutive Frame ────────────────────────────────────────────────
        elif expect_consecutive and pci_type == 0x2:
            seq_number = msg.data[0] & 0x0F
            if seq_number != seq_number_expected:
                print(f"ISO-TP Sequence mismatch. "
                      f"Expected: {seq_number_expected}, Got: {seq_number}")
                return None
            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16
            if len(full_response_data) >= total_uds_length:
                full_response_data = full_response_data[:total_uds_length]
                break
            continue

    return full_response_data if full_response_data else None


def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)

    # ── Single Frame ─────────────────────────────────────────────────────────
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # ── First Frame ──────────────────────────────────────────────────────────
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # Wait for Flow Control
    max_fc_retries = 3
    fc_msg = None
    for fc_attempt in range(max_fc_retries):
        fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=2.0)
        if fc_msg:
            break
        if fc_attempt < max_fc_retries - 1:
            time.sleep(0.5)

    if not fc_msg:
        print("No flow control received after retries.")
        return False

    pci_type = (fc_msg.data[0] & 0xF0) >> 4
    if pci_type != 0x3:
        print("Invalid flow control frame.")
        return False

    flow_status = fc_msg.data[0] & 0x0F
    st_min      = fc_msg.data[2]

    if st_min <= 127:
        st_min_sec = st_min * 0.001
    elif 0xF1 <= st_min <= 0xF9:
        st_min_sec = (st_min - 0xF0) * 0.0001
    else:
        print("Reserved st_min value, using default 10 ms")
        st_min_sec = 0.01

    if flow_status != 0:
        print(f"Flow control status not CTS: {flow_status}")
        return False

    # ── Consecutive Frames ───────────────────────────────────────────────────
    remaining_data = data[6:]
    seq = 1
    while remaining_data:
        time.sleep(st_min_sec)
        cf_pci      = 0x20 | (seq % 16)
        cf_data_len = min(7, len(remaining_data))
        cf_data     = [cf_pci] + remaining_data[:cf_data_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining_data = remaining_data[cf_data_len:]
        seq += 1

    return True


def send_tester_present(bus):
    uds_payload   = [0x3E, 0x80]
    isotp_sf_data = [len(uds_payload)] + uds_payload
    _send_can_frame(bus, TESTER_ID, isotp_sf_data)


def send_uds_request(bus, sid, sub_payload, expected_positive_sid):
    uds_payload = [sid] + sub_payload
    tp_interval = 1.0
    retry_delay = 3.0

    # ── Transmit ─────────────────────────────────────────────────────────────
    if len(uds_payload) <= 7:
        isotp_sf_data = [len(uds_payload)] + uds_payload
        _send_can_frame(bus, TESTER_ID, isotp_sf_data)
    else:
        if not send_isotp_request(bus, TESTER_ID, uds_payload):
            print("Failed to send ISO-TP request.")
            return None

    # ── Receive ──────────────────────────────────────────────────────────────
    response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=3.0)

    if response and response[0] == 0x7F:
        # Negative Response
        if len(response) >= 3 and response[2] == 0x78:
            # Response Pending – keep sending TesterPresent while waiting
            print("[NRC] 0x78 – Response Pending")
            wait_start   = time.time()
            last_tp_time = time.time()

            while time.time() - wait_start < retry_delay:
                pending = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=0.5)
                if pending:
                    if pending[0] == expected_positive_sid:
                        return pending
                    if pending[0] == 0x7F and len(pending) >= 3:
                        nrc = pending[2]
                        if nrc == 0x78:
                            print("[NRC] 0x78 – Still Pending")
                        else:
                            print(f"Negative Response during wait: NRC 0x{nrc:02X}")
                            return None
                if time.time() - last_tp_time >= tp_interval:
                    send_tester_present(bus)
                    last_tp_time = time.time()

            print("No positive response after NRC 0x78 wait period.")
            return None

        if len(response) >= 3:
            print(f"Negative Response: NRC 0x{response[2]:02X}")
        return None

    if response and response[0] == expected_positive_sid:
        return response

    print("No valid response received.")
    return None

def request_seed(bus):
    response = send_uds_request(bus, 0x27, [0x01], 0x67)
    if response and len(response) >= 2 and response[1] == 0x01:
        seed = bytes(response[2:])
        if len(seed) == 8:
            print(f"Seed Received: {seed.hex().upper()}")
            return seed
        print(f"Unexpected seed length: {len(seed)} bytes (expected 8).")
        return None
    print("Seed Request Failed.")
    return None

def calculate_key(seed, symmetric_key):

    if len(seed) != 8:
        print(f"Invalid seed length: {len(seed)} (expected 10).")
        return None
    if len(symmetric_key) != 16:
        print(f"Invalid symmetric key length: {len(symmetric_key)} (expected 16).")
        return None

    ripemd_input = symmetric_key + seed
    print(f"Symmetric Key : {symmetric_key.hex().upper()}")
    print(f"Sym + Seed : {ripemd_input.hex().upper()}")

    h = hashlib.new('ripemd160')
    h.update(ripemd_input)
    digest = h.digest()
    print(f"RIPEMD-160 Key : {digest.hex().upper()}")

    key_to_send = digest[:8]
    print(f"Calculated Key   : {key_to_send.hex().upper()}")
    return key_to_send

def default_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x01], 0x50)
    if response and len(response) >= 2 and response[1] == 0x01:
        print("Default Diagnostic Session Passed.\n")
        return True
    print("Default Diagnostic Session Failed.")
    return False

def programming_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x02], 0x50)
    if response and len(response) >= 2 and response[1] == 0x02:
        print("Programming Diagnostic Session Passed.\n")
        return True
    print("Programming Diagnostic Session Failed.")
    return False

def extended_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x03], 0x50)
    if response and len(response) >= 2 and response[1] == 0x03:
        print("Extended Diagnostic Session Passed.\n")
        return True
    print("Extended Diagnostic Session Failed.")
    return False

def send_key(bus, key_to_send):
    if not key_to_send or len(key_to_send) != 8:
        print("Invalid key: must be exactly 8 bytes.")
        return False

    response = send_uds_request(bus,0x27,[0x02] + list(key_to_send),0x67)

    if response and len(response) >= 2 and response[1] == 0x02:
        print("Security Access Passed\n")
        return True

    print("Security Access Failed")
    return False


def EMS_Security_Access(interface, channel, bitrate):
    bus = None
    try:
        try:
            bus = can.interface.Bus(
                interface=interface,
                channel=channel,
                bitrate=bitrate
            )
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        if not default_diagnostic_session(bus):
            error_message = "Failed to enter default diagnostic session."
            return False, error_message

        if not extended_diagnostic_session(bus):
            error_message = "Failed to enter extended diagnostic session."
            return False, error_message

        seed = request_seed(bus)
        if not seed:
            error_message = "Failed to retrieve seed from ECU."
            return False, error_message

        key_to_send = calculate_key(seed, SYMMETRIC_KEY)
        if not key_to_send:
            error_message = "Failed to calculate key from seed."
            return False, error_message

        if not send_key(bus, key_to_send):
            error_message = "Failed to send key to ECU."
            return False, error_message
        
        return True, "PASSED"
        
    except can.CanError as e:
        error_msg = str(e).lower()

        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."

        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = (
                "ERROR: No communication from ECU.\n"
                "Check ECU power, CAN wiring and baud rate."
            )

        else:
            error_message = f"CAN Error: {e}"

        print(error_message)
        return False, error_message
    
    except ValueError as e:
        error_message = f"Value Error: {e}"
        print(error_message)
        return False, error_message
    
    except Exception as e:
        error_message = f"Unexpected Error: {e}"
        print(error_message)
        return False, error_message
    finally:
        if bus:
            bus.shutdown()
            print("CAN bus shutdown")


if __name__ == "__main__":
    EMS_Security_Access(interface="pcan",channel="PCAN_USBBUS1",bitrate=500000)