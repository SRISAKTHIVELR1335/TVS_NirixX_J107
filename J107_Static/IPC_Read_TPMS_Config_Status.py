# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel
"""

import can
import time
import os
import platform

# =========================
# IPC Configuration
# =========================
IPC_TESTER_ID = 0x7C9
IPC_RESPONSE_ID = 0x7C1

# =========================
# TPMS Status Definitions
# =========================
TPMS_STATUS_MAP = {
    0x00: "Not Configured",
    0x01: "Both Configured",
    0x02: "Front Configured",
    0x03: "Rear Configured"
}

log_counter = 1


# =========================
# LOGGING
# =========================
def log_message(direction, msg):
    global log_counter
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    timestamp = time.time() * 1000
    print(f"{log_counter:>3}  {timestamp:.3f} DT {msg.arbitration_id:04X} {direction} 8  {formatted_data}")
    log_counter += 1


# =========================
# CAN Helpers
# =========================
def _send_can_frame(bus, arbitration_id, data):
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
    bus.send(msg)
    log_message("TX", msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
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
def receive_isotp_response(bus, response_id, tester_id, timeout=3.0):
    start_time = time.time()
    full_response_data = []
    expect_consecutive_frames = False
    seq_number_expected = 1
    total_uds_length = 0

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
            total_uds_length = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            full_response_data = list(msg.data[2:])
            expect_consecutive_frames = True
            seq_number_expected = 1

            # Flow Control (CTS)
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, tester_id, fc_frame)

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
def send_isotp_request(bus, arbitration_id, response_id, data):
    total_len = len(data)

    # Single Frame
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # First Frame
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # Wait Flow Control
    start = time.time()
    st_min_sec = 0.001

    while time.time() - start < 2.0:
        fc_msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not fc_msg:
            continue

        pci = (fc_msg.data[0] & 0xF0) >> 4
        if pci == 0x3:  # FC frame
            st_min = fc_msg.data[2]
            if st_min <= 0x7F:
                st_min_sec = st_min / 1000.0
            elif 0xF1 <= st_min <= 0xF9:
                st_min_sec = (st_min - 0xF0) * 0.0001
            else:
                st_min_sec = 0.001
            break
    else:
        print("No Flow Control received")
        return False

    # Consecutive Frames
    remaining_data = data[6:]
    seq = 1

    while remaining_data:
        time.sleep(st_min_sec)
        cf_pci = 0x20 | (seq & 0x0F)
        cf_data_len = min(7, len(remaining_data))
        cf_data = [cf_pci] + remaining_data[:cf_data_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining_data = remaining_data[cf_data_len:]
        seq = (seq + 1) % 16

    return True


# =========================
# Tester Present (SID 0x3E)
# =========================
def send_tester_present(bus, tester_id=IPC_TESTER_ID):
    uds_payload = [0x3E, 0x00]
    isotp_sf_data = [len(uds_payload)] + uds_payload
    _send_can_frame(bus, tester_id, isotp_sf_data)


# =========================
# UDS Core
# =========================
def send_uds_request(bus, sid, sub_payload, expected_positive_sid, tester_id=IPC_TESTER_ID, response_id=IPC_RESPONSE_ID):
    uds_payload = [sid] + sub_payload
    retry_delay = 3.0
    tp_interval = 1.0

    if len(uds_payload) <= 7:
        isotp_sf_data = [len(uds_payload)] + uds_payload
        _send_can_frame(bus, tester_id, isotp_sf_data)
    else:
        if not send_isotp_request(bus, tester_id, response_id, uds_payload):
            print("Failed to send ISO-TP request.")
            return None

    response = receive_isotp_response(bus, response_id, tester_id, timeout=3.0)

    if response and response[0] == 0x7F:
        if len(response) >= 3 and response[2] == 0x78:
            print("[NRC] 0x78 - Response Pending")
            wait_start = time.time()
            last_tp_time = time.time()

            while time.time() - wait_start < retry_delay:
                pending_response = receive_isotp_response(bus, response_id, tester_id, timeout=0.5)

                if pending_response:
                    if pending_response[0] == expected_positive_sid:
                        print("Positive response received. Stopping Tester Present.\n")
                        return pending_response
                    if pending_response[0] == 0x7F and len(pending_response) >= 3:
                        nrc = pending_response[2]
                        if nrc == 0x78:
                            print("[NRC] 0x78 Received again - Still Pending")
                        else:
                            print(f"Negative Response during wait: NRC 0x{nrc:02X}")
                            return None

                if time.time() - last_tp_time >= tp_interval:
                    send_tester_present(bus, tester_id)
                    last_tp_time = time.time()

            print("No positive response after NRC 0x78.")
            return None

        if len(response) >= 3:
            print(f"Negative Response: NRC 0x{response[2]:02X}")
        return None

    if response and response[0] == expected_positive_sid:
        return response

    return None


# =============================================================================
# Application-Specific Read Function
# =============================================================================
def Read_TPMS_Config_Status(bus, expected_value=0x01, timeout=5.0, poll_interval=0.2):
    """
    Reads DID 0xB1DB and validates the TPMS Config Status.
    """
    start_time = time.time()
    last_received_desc = "None"
    last_received_val = None

    while True:
        response = send_uds_request(bus, 0x22, [0xB1, 0xDB], 0x62)
        if response:
            if response[0] != 0x62:
                print(f"Unexpected SID: 0x{response[0]:02X}")
                time.sleep(poll_interval)
                continue

            if response[1] != 0xB1 or response[2] != 0xDB:
                print(f"DID mismatch: got 0x{response[1]:02X} 0x{response[2]:02X}")
                time.sleep(poll_interval)
                continue

            if len(response) < 4:
                print("Response payload too short")
                time.sleep(poll_interval)
                continue

            raw_value = response[3]
            last_received_val = raw_value
            last_received_desc = TPMS_STATUS_MAP.get(raw_value, f"Unknown (0x{raw_value:02X})")

            print(f"TPMS Config Status (0xB1DB): 0x{raw_value:02X} -> {last_received_desc}")

            # Check against expected status
            if raw_value == expected_value:
                print(f"PASS: Expected TPMS status matched: '{last_received_desc}' (0x{raw_value:02X})")
                return True, last_received_desc

        else:
            print("No response received from ECU")

        # Timeout Check
        if timeout is not None and (time.time() - start_time) >= timeout:
            expected_desc = TPMS_STATUS_MAP.get(expected_value, f"0x{expected_value:02X}")
            if last_received_val is not None:
                error_message = (
                    f"ERROR: Expected '{expected_desc}' (0x{expected_value:02X}), "
                    f"but ECU returned '{last_received_desc}' (0x{last_received_val:02X})"
                )
            else:
                error_message = f"ERROR: Timeout waiting for TPMS Config Status = '{expected_desc}' (0x{expected_value:02X})"
            
            print(error_message)
            return False, error_message

        time.sleep(poll_interval)


# =========================
# MAIN CALLABLE FUNCTION
# =========================
def IPC_Read_TPMS_Config_Status(interface, channel, bitrate):
    bus = None
    OS = platform.system()
    expected_value = 0x01

    try:
        # OS-Specific CAN Setup
        if OS == "Linux":
            interface = "socketcan"
            channel = "can0"
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")
            bus = can.interface.Bus(interface=interface, channel=channel)

        elif OS.upper() == "WINDOWS":
            try:
                bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate)
            except can.CanInitializationError:
                error_message = "ERROR: PCAN is not connected or not initialized."
                return False, error_message

        bus.set_filters([{"can_id": IPC_RESPONSE_ID, "can_mask": 0x7FF, "extended": False}])

        # Perform Read and Verification
        status, result = Read_TPMS_Config_Status(
            bus=bus,
            expected_value=expected_value,
            timeout=5.0,
            poll_interval=0.2
        )
        return status, result

    except can.CanError as e:
        error_msg = str(e).lower()

        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."
        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = "ERROR: No communication from ECU. Check ECU power, CAN wiring and baud rate."
        else:
            error_message = f"CAN Error: {e}"

        print(error_message)
        return False, error_message

    except KeyboardInterrupt:
        error_message = "ERROR: Operation interrupted by user."
        print(error_message)
        return False, error_message

    except Exception as e:
        error_message = f"ERROR: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    success, result_text = IPC_Read_TPMS_Config_Status(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    print("\n" + "=" * 40)
    if success:
        print("STATUS      : SUCCESS (PASSED)")
        print(f"TPMS CONFIG : {result_text}")
    else:
        print("STATUS      : FAILURE (FAILED)")
        print(f"DETAILS     : {result_text}")
    print("=" * 40)