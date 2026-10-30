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
    log_message("Tx", msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        remaining_timeout = timeout - (time.time() - start_time)
        if remaining_timeout <= 0:
            break

        msg = bus.recv(timeout=remaining_timeout)
        if msg and msg.arbitration_id == response_id:
            log_message("Rx", msg)
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

            # ---- Flow Control (CTS) ----
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, tester_id, fc_frame)

        # ---- Consecutive Frame ----
        elif pci_type == 0x2 and expect_consecutive_frames:
            seq_number = msg.data[0] & 0x0F

            if seq_number != seq_number_expected:
                print(f"ISO-TP SEQ ERROR → expected {seq_number_expected}, got {seq_number}")
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

    # ---- Single Frame ----
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # ---- First Frame ----
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # ---- Wait Flow Control ----
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

    # ---- Consecutive Frames ----
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
            return False, "ERROR: Failed to send ISO-TP request."

    response = receive_isotp_response(bus, response_id, tester_id, timeout=3.0)

    if not response:
        return False, "ERROR: No response received from ECU."

    # Negative Response Handling (SID 0x7F)
    if response[0] == 0x7F:
        if len(response) >= 3 and response[2] == 0x78:  # Response Pending
            print("[NRC] 0x78 - Response Pending")
            wait_start = time.time()
            last_tp_time = time.time()

            while time.time() - wait_start < retry_delay:
                pending_response = receive_isotp_response(bus, response_id, tester_id, timeout=0.5)

                if pending_response:
                    if pending_response[0] == expected_positive_sid:
                        return True, pending_response
                    if pending_response[0] == 0x7F and len(pending_response) >= 3:
                        nrc = pending_response[2]
                        if nrc == 0x78:
                            print("[NRC] 0x78 Still Pending...")
                        else:
                            return False, f"NRC: 0x{nrc:02X}"

                if time.time() - last_tp_time >= tp_interval:
                    send_tester_present(bus, tester_id)
                    last_tp_time = time.time()

            return False, "ERROR: Timeout waiting for response after NRC 0x78."

        nrc = response[2] if len(response) >= 3 else 0x00
        return False, f"NRC: 0x{nrc:02X}"

    if response[0] == expected_positive_sid:
        return True, response

    return False, f"ERROR: Unexpected Response SID: 0x{response[0]:02X}"


# =============================================================================
# Application-Specific Read Function
# =============================================================================
def Read_Fuel_Level_Sensor_Resistance(bus, tester_id=IPC_TESTER_ID, response_id=IPC_RESPONSE_ID):
    success, response = send_uds_request(bus=bus,sid=0x22,sub_payload=[0xE0, 0x65],expected_positive_sid=0x62,tester_id=tester_id,response_id=response_id)

    if not success:
        return False, response

    # Validate DID matches 0xE065 and response contains data
    if len(response) < 4 or response[1] != 0xE0 or response[2] != 0x65:
        return False, "ERROR: Response DID mismatch or missing payload data."

    # Parse Sensor Value:
    # If 2 or more bytes data payload: (Byte 0 << 8) | Byte 1
    if len(response) >= 5:
        fuel_level_resistance = (response[3] << 8) | response[4]
    else:
        # Single-byte data payload
        fuel_level_resistance = response[3]

    return True, fuel_level_resistance


# =========================
# MAIN CALLABLE FUNCTION
# =========================
def IPC_Read_Fuel_Level_Sensor_Resistance(interface, channel, bitrate):
    bus = None
    OS = platform.system()

    try:
        # ── OS-Specific CAN Setup ─────────────────────────────────────────
        if OS == "Linux":
            interface = "socketcan"
            channel = "can0"
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")
            bus = can.interface.Bus(interface=interface, channel=channel)

        elif OS.upper() == "WINDOWS":
            try:
                bus = can.interface.Bus(
                    interface=interface,
                    channel=channel,
                    bitrate=bitrate
                )
            except can.CanInitializationError:
                error_message = "ERROR: PCAN is not connected or not initialized."
                return False, error_message

        bus.set_filters([{"can_id": IPC_RESPONSE_ID, "can_mask": 0x7FF, "extended": False}])

        # Read Fuel Level Sensor Resistance
        status, result = Read_Fuel_Level_Sensor_Resistance(bus, tester_id=IPC_TESTER_ID, response_id=IPC_RESPONSE_ID)
        return status, result

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
        return False, f"ERROR: {e}"

    finally:
        if bus:
            bus.shutdown()


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    success, value = IPC_Read_Fuel_Level_Sensor_Resistance(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if success:
        print("STATUS     : SUCCESS")
        print(f"FUEL LEVEL : 0x{value:04X} ({value} Raw/Ohm)")
    else:
        print("STATUS     : FAILURE")
        print(f"ERROR      : {value}")