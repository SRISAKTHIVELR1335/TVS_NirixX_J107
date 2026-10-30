# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel

"""

import can
import time
import requests

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7C9
ECU_RESPONSE_ID  = 0x7C1


# =========================
# LOGGING
# =========================
def log_message(direction, msg):
    """Log CAN messages in hex format."""
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    print(f"{direction} {msg.arbitration_id:04X}: {formatted_data}")


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
        if msg:
            if msg.arbitration_id == response_id:
                log_message("RX", msg)
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
def send_isotp_request(bus, arbitration_id, data):
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
    start      = time.time()
    st_min_sec = 0.001

    while time.time() - start < 2.0:
        fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=0.5)
        if not fc_msg:
            continue

        pci = (fc_msg.data[0] & 0xF0) >> 4
        if pci == 0x3:
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
    seq            = 1

    while remaining_data:
        time.sleep(st_min_sec)
        cf_pci      = 0x20 | (seq & 0x0F)
        cf_data_len = min(7, len(remaining_data))
        cf_data     = [cf_pci] + remaining_data[:cf_data_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining_data = remaining_data[cf_data_len:]
        seq            = (seq + 1) % 16

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
# Sessions
# =========================
def default_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x01], 0x50)
    if response and response[1] == 0x01:
        print("Default Diagnostic Session Passed\n")
        return True
    print("Default Diagnostic Session Failed\n")
    return False


def extended_diagnostic_session(bus):
    response = send_uds_request(bus, 0x10, [0x03], 0x50)
    if response and response[1] == 0x03:
        print("Extended Diagnostic Session Passed\n")
        return True
    print("Extended Diagnostic Session Failed\n")
    return False


# =============================================================
# ICCID2 Number Read Function (ECU)
# =============================================================
def Read_IPC_ICCID2_Number(bus):
    response = send_uds_request(bus, 0x22, [0xF2, 0x0C], 0x62)

    if not response:
        print("No response received for ICCID2 Number read")
        return None

    if response[0] != 0x62:
        print(f"Unexpected response SID: 0x{response[0]:02X} (expected 0x62)")
        return None

    if response[1] != 0xF2 or response[2] != 0x0C:
        print(
            f"DID mismatch: got 0x{response[1]:02X} 0x{response[2]:02X}, "
            f"expected 0x{0xF2:02X} 0x{0x0C:02X}"
        )
        return None

    if len(response) < 23:
        print(
            f"Response too short: {len(response)} bytes "
            f"(expected at least 23 bytes)"
        )
        return None

    ICCID2_Bytes = response[3:23]

    if all(b == 0x00 for b in ICCID2_Bytes):
        ICCID2_Number = '0' * len(ICCID2_Bytes)
        print(f"All-zero ICCID2 detected, returning: {ICCID2_Number}")
        return ICCID2_Number

    try:
        ICCID2_Number = bytes(ICCID2_Bytes).rstrip(b"\x00").decode('ascii')
    except (ValueError, UnicodeDecodeError) as e:
        print(f"ASCII decode failed: {e}")
        print(f"Raw bytes: {' '.join(f'0x{b:02X}' for b in ICCID2_Bytes)}")
        return None

    if not ICCID2_Number.isalnum():
        print(f"Non-alphanumeric characters found in ICCID2: {ICCID2_Number!r}")

    return ICCID2_Number


def fetch_ICCID2_from_api(api_url):
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        api_response = response.json()

        modules = api_response.get("data", {}).get("modules", [])

        for module in modules:
            if module.get("module") == "IPC":
                for config in module.get("configs", []):
                    if config.get("refname") == "IMEI_J107":
                        messages = config.get("messages", [])
                        for message in messages:
                            if message.get("refname") == "IMEI_J107":
                                txbytes = message.get("txbytes", "").strip()
                                if txbytes:
                                    print(f"API txbytes (full): {txbytes}")
                                    api_ICCID2 = txbytes[35:55]

                                    if len(api_ICCID2) < 20:
                                        error_message = (
                                            "API txbytes ICCID2 slice too short: "
                                            f"{len(api_ICCID2)} chars (expected 20)"
                                        )
                                        return None, error_message

                                    if not api_ICCID2.isdigit():
                                        print(
                                            f"Warning: Non-numeric characters in "
                                            f"API ICCID2: {api_ICCID2!r}")

                                    return api_ICCID2, None
                                
        error_message = "IMEI_J107 entry not found in API response"
        return None, error_message

    except requests.exceptions.Timeout:
        error_message = "API request timed out"
        return None, error_message
    
    except requests.exceptions.HTTPError as e:
        error_message = f"API HTTP error: {e.response.status_code} - {e.response.reason}"
        return None, error_message
    
    except Exception as e:
        error_message = f"API error: {e}"
        return None, error_message


# =========================
# MAIN FUNCTION
# =========================
def IPC_ICCID2_Number(interface, channel, bitrate, api_url, vin_number):
    api_url = f"{api_url.rstrip('/')}/{vin_number.strip()}"

    bus        = None
    api_ICCID2 = None

    try:
        api_ICCID2, api_error = fetch_ICCID2_from_api(api_url)

        if api_error:
            print(api_error)
            return False, api_error, None

        print(f"API ICCID2 Number: {api_ICCID2}")

        try:
            bus = can.Bus(
                interface=interface,
                channel=channel,
                bitrate=int(bitrate),
                fd=False
            )
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            print(error_message)
            return False, api_ICCID2, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        ecu_ICCID2 = Read_IPC_ICCID2_Number(bus)

        if ecu_ICCID2 is None:
            error_message = "ERROR: ECU ICCID2 read failed."
            print(error_message)
            return False, api_ICCID2, error_message

        print(f"IPC ECU ICCID2 Number : {ecu_ICCID2}")

        ecu_clean = ecu_ICCID2.strip().upper()
        api_clean = api_ICCID2.strip().upper()

        if ecu_clean == api_clean:
            print("ICCID2 MATCHED")
            return True, api_ICCID2, ecu_ICCID2
        else:
            print("ICCID2 MISMATCHED")
            return False, api_ICCID2, ecu_ICCID2

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, api_ICCID2, error_message

    except Exception as e:
        error_message = f"ECU Error: {e}"
        print(error_message)
        return False, api_ICCID2, error_message 

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    success, api_ICCID2, ecu_ICCID2 = IPC_ICCID2_Number(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        api_url="http://10.121.2.174:3002/vehicles/flashFile/ejo",
        vin_number="SH2NJ3553VH002134"
    )

    if success:
        print("STATUS : SUCCESS - ICCID2 MATCH")
    else:
        print("STATUS : FAILURE / MISMATCH")

    print(f"ECU ICCID2 Number : {ecu_ICCID2}")
    print(f"API ICCID2 Number : {api_ICCID2}")