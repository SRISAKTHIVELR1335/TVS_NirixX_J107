# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import can
import time
from can import Message

# =========================
# Configuration
# =========================
TESTER_ID = 0x7E0
ECU_RESPONSE_ID = 0x7E8

# =========================
# Utility
# =========================
def log_message(direction, msg):
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    print(f"{direction} {msg.arbitration_id:04X}: {formatted_data}")


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
    log_message("TX", msg)
    bus.send(msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining_timeout = timeout - (time.time() - start_time)
        if remaining_timeout <= 0:
            break
        
        msg = bus.recv(timeout=remaining_timeout)
        if msg:
            if msg.arbitration_id == response_id:
                log_message("RX", msg)
                return msg
    return None


# =========================
# ISO-TP Receive
# =========================
def receive_isotp_response(bus, response_id, timeout=3.0):
    start_time = time.time()
    full_response_data = []
    expect_cf = False
    seq_expected = 1
    total_len = 0

    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not msg:
            continue

        pci_type = (msg.data[0] & 0xF0) >> 4

        # Single Frame
        if pci_type == 0x0:
            uds_len = msg.data[0] & 0x0F
            full_response_data = list(msg.data[1:1 + uds_len])
            break

        # First Frame
        elif pci_type == 0x1:
            total_len = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            full_response_data = list(msg.data[2:])
            expect_cf = True
            seq_expected = 1

            # Flow Control
            fc = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, TESTER_ID, fc)
            continue

        # Consecutive Frame
        elif expect_cf and pci_type == 0x2:
            seq = msg.data[0] & 0x0F
            if seq != seq_expected:
                print("[ERROR] ISO-TP SEQ ERROR")
                return None

            full_response_data.extend(msg.data[1:])
            seq_expected = (seq_expected + 1) % 16

            if len(full_response_data) >= total_len:
                full_response_data = full_response_data[:total_len]
                break

    if not full_response_data:
        return None

    return full_response_data


# =========================
# ISO-TP Send
# =========================
def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)

    # Single Frame
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # First Frame
    ff = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff)

    # Flow Control
    fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=1.0)
    if not fc_msg:
        print("[ERROR] No Flow Control")
        return False

    pci = (fc_msg.data[0] & 0xF0) >> 4
    if pci != 0x3:
        print("[ERROR] Invalid Flow Control Frame")
        return False

    st_min = fc_msg.data[2]
    if st_min <= 127:
        st_min_sec = st_min * 0.001
    elif 0xF1 <= st_min <= 0xF9:
        st_min_sec = (st_min - 0xF0) * 0.0001
    else:
        st_min_sec = 0.001

    remaining = data[6:]
    seq = 1

    while remaining:
        time.sleep(st_min_sec)
        cf = [0x20 | (seq % 16)] + remaining[:7]
        _send_can_frame(bus, arbitration_id, cf)
        remaining = remaining[7:]
        seq += 1

    return True

# =========================
# Tester Present (SID 0x3E)
# =========================
def send_tester_present(bus):
    uds_payload = [0x3E, 0x80]
    isotp_sf_data = [len(uds_payload)] + uds_payload
    _send_can_frame(bus, TESTER_ID, isotp_sf_data)

# =========================
# UDS Core
# =========================
def send_uds_request(bus, sid, sub_payload, expected_positive_sid):
    uds_payload   = [sid] + sub_payload
    max_retries   = 0
    retry_delay   = 3.0
    tp_interval   = 1.0
    
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
# Clear DTC API Function
# =========================
def EMS_Clear_DTC(interface, channel, bitrate):
    bus = None
    try:
        bus = can.interface.Bus(interface=interface,channel=channel,bitrate=int(bitrate),fd=False)

        response = send_uds_request(bus, 0x14, [0xFF, 0xFF, 0xFF], 0x54)

        if response:
            print("Clear DTC: PASSED\n")
            return True, "PASSED"
        else:
            error_message = "ERROR: Clear DTC: No valid response"
            print(error_message)
            return False, error_message

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            print("PCAN CAN bus shutdown.")


# =========================
# Direct Execution Support
# =========================
if __name__ == "__main__":
    success, message = EMS_Clear_DTC("pcan", "PCAN_USBBUS1", 500000)
