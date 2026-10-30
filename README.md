I want you to go through all these codes thoroughly, in these code we have the functions like (`log_print`, `_send_can_frame`, `_receive_single_can_frame`, `receive_isotp_response`, `send_isotp_request`, `send_tester_present`, `send_uds_request), we need to add these functions exactly to our existing files in J107_IMU, J107_RVS, J107_Static folders, inside these folders there are multiple python files, we need to change all these codes by referring to these codes below. We need to entirely change all the code structure like the reference code but don't change the concept of the existing code. Also we need to refer how to return the proper error messages, how to return the success/error messages to the main, also check how linux configuration has been done, how this code prints the log using log_print function, etc.... In the reference codes One is returning two values with proper success and error messages, one is returning three values with proper success and error messages etc.. First we need to correct the files inside the J107_IMU folder, then we will go further

Sample Tester_Present,

# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import os
import can
import time
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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
# Tester Present (SID 0x3E) — Internal Keep-Alive
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
# Tester Present Service (Retry Loop)
# =========================
def tester_present_service(bus):
    session_start  = time.time()
    last_send_time = None
    send_count     = 0

    while time.time() - session_start < 1.0:

        current_time = time.time()
        if last_send_time is None or (current_time - last_send_time) >= 0.1:

            send_count += 1
            print(f"\nSending Tester Present (Attempt {send_count})")

            # ---- Send TP with bus-error protection ----
            try:
                uds_payload = [0x3E, 0x00]
                sf = [len(uds_payload)] + uds_payload + [0x00] * (7 - len(uds_payload))
                _send_can_frame(bus, TESTER_ID, sf)
            except can.CanError as e:
                print(f"Bus error: {e}")

            last_send_time = time.time()

        # ---- Receive with bus-error protection ----
        try:
            response = bus.recv(timeout=0.02)
        except can.CanError as e:
            print(f"Bus error: {e}")
            continue

        if response is None:
            continue

        if response.arbitration_id != ECU_RESPONSE_ID:
            continue

        log_print(response.arbitration_id, "RX", response.data)
        data = list(response.data)

        if len(data) < 2:
            continue

        # ---- Parse ISO-TP Single Frame Response ----
        pci_type = (data[0] & 0xF0) >> 4

        if pci_type == 0x0:  # Single Frame
            uds_length = data[0] & 0x0F
            uds_data = data[1:1 + uds_length]

            if len(uds_data) < 1:
                continue

            # ---- Positive Response (0x7E) ----
            if uds_data[0] == 0x7E:
                if len(uds_data) >= 2 and uds_data[1] == 0x00:
                    print("Tester Present : PASSED")
                    return True, None

            # ---- Negative Response (0x7F) ----
            elif uds_data[0] == 0x7F:
                if len(uds_data) >= 3:
                    nrc = uds_data[2]

                    if nrc == 0x78:
                        print("Response Pending (0x78) - Continuing...")
                        continue
                    else:
                        error_message = f"NRC Received: 0x{nrc:02X}"
                        print(error_message)
                        return False, error_message

            # ---- Unexpected SID ----
            else:
                error_message = f"UNEXPECTED_RESPONSE_SID: 0x{uds_data[0]:02X}"
                print(error_message)
                return False, error_message

    # ---- Timeout: No Positive Response ----
    print(f"\nTester Present : FAILED")
    print(f"Total Sends    : {send_count}")
    print(f"No positive response received within 1.0 seconds")
    return False, "ECU_RESPONSE_TIMEOUT"


# =========================
# MAIN FUNCTION
# =========================
def Conti_EMS_Tester_Present(interface, channel, bitrate):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    os_name = platform.system()

    try:
        # ---- Linux Configuration ----
        if os_name == "Linux":
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
            bus = can.interface.Bus(interface=interface,channel=channel,bitrate=bitrate)
            
        except can.CanInitializationError:
            error_message = (
                "- Verify failed:\n"
                "- PCAN USB is not connected\n"
                "- Check PCAN driver installation\n"
                "- Verify PCAN channel selection"
            )
            print(error_message)
            return False, error_message
        except can.CanError as e:
            error_message = (
                "- Verify failed:\n"
                "- PCAN USB is not connected\n"
                "- Check PCAN driver installation\n"
                "- Verify PCAN channel selection"
            )
            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        tp_success, tp_error = tester_present_service(bus)

        if not tp_success:
            if tp_error and tp_error != "ECU_RESPONSE_TIMEOUT":
                print(tp_error)
                return False, tp_error

            error_message = _communication_error_message()
            print(error_message)
            return False, error_message

        return True, "PASSED"

    except can.CanError as e:
        error_msg_str = str(e).lower()
        if any(keyword in error_msg_str for keyword in ["not been initialized", "invalid", "handle", "pcan"]):
            error_message = (
                "- Verify failed:\n"
                "- PCAN USB is not connected\n"
                "- Check PCAN driver installation\n"
                "- Verify PCAN channel selection"
            )
        elif any(keyword in error_msg_str for keyword in ["heavy", "warning", "bus-off"]):
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
        else:
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
            print("CAN Bus Shutdown Complete")

        if os_name == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    success, result_message = Conti_EMS_Tester_Present(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if success:
        print("STATUS : SUCCESS - TESTER PRESENT PASSED")
    else:
        print("STATUS : FAILURE")

    print(f"Result : {result_message}")



Sample Returning Read DTC code,
 
# -*- coding: utf-8 -*-
"""
Created on Fri Mar  6 14:00:36 2026

@author: Sri.Sakthivel
"""

import os
import sys
import time
import platform
import can
import pandas as pd

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
log_counter      = 1
START_TIME       = time.perf_counter()


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


EXCEL_DTC_PATH = resource_path(os.path.join("dtc error code", "Keihin_EMS_DTC.xlsx.enc"))


# =========================
# EXCEL DTC MAPPING
# =========================
def normalize_boolean_value(value):
    if pd.isna(value):
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return bool(value)

    if isinstance(value, str):
        value_lower = value.strip().lower()
        if value_lower in ['true', 'pass', 'yes', '1', 'p', 'y', 't']:
            return True
        if value_lower in ['false', 'fail', 'no', '0', 'f', 'n']:
            return False

    return False


def load_dtc_map_from_excel(excel_path):
    if not os.path.exists(excel_path):
        print(f"[ERROR] Excel file not found: {excel_path}")
        return {}

    security_manager_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if security_manager_path not in sys.path:
        sys.path.insert(0, security_manager_path)

    try:
        from security_manager import read_encrypted_excel, MASTER_PASSWORD
        df = read_encrypted_excel(excel_path, MASTER_PASSWORD)
        print(f"[DEBUG] Excel columns found: {list(df.columns)}")

        df = df.copy()
        df.columns = df.columns.str.strip()

        required_columns = ['DTC Code', 'DTC_Description', 'DTC_Required']
        for col in required_columns:
            if col not in df.columns:
                print(f"[ERROR] Missing required column: '{col}'")
                return {}
            
        col_dtc_code = df.columns.get_loc('DTC Code')
        col_dtc_desc = df.columns.get_loc('DTC_Description')
        col_dtc_req  = df.columns.get_loc('DTC_Required')

        df.iloc[:, col_dtc_code] = df['DTC Code'].astype(str).str.strip().str.upper()
        df.iloc[:, col_dtc_desc] = df['DTC_Description'].astype(str).str.strip()
        df.iloc[:, col_dtc_req]  = df['DTC_Required'].apply(normalize_boolean_value)

        dtc_map = {}
        for _, row in df.iterrows():
            dtc_code = row['DTC Code']
            dtc_map[dtc_code] = {
                "DTC_Description": row['DTC_Description'],
                "dtc_required": row['DTC_Required']
            }

        print(f"[INFO] Loaded {len(dtc_map)} DTC mappings from Excel")
        return dtc_map

    except Exception as e:
        print(f"[ERROR] Failed to read Excel: {e}")
        return {}


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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions
# =========================
def default_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x01], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x01:
        print("[OK] Default Diagnostic Session\n")
        return True, None
    print("[FAIL] Default Diagnostic Session\n")
    return False, "INVALID_SESSION_RESPONSE"


def extended_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session\n")
        return True, None
    print("[FAIL] Extended Diagnostic Session\n")
    return False, "INVALID_SESSION_RESPONSE"


# =========================
# SAE J2012 DECODER
# =========================
def decode_j2012_dtc(b1: int, b2: int) -> str:
    systems = {0: 'P', 1: 'C', 2: 'B', 3: 'U'}
    system_bits = (b1 >> 6) & 0x03
    system = systems[system_bits]
    digit1 = (b1 >> 4) & 0x03
    digit2 = b1 & 0x0F
    digit3 = (b2 >> 4) & 0x0F
    digit4 = b2 & 0x0F
    return f"{system}{digit1}{digit2:X}{digit3:X}{digit4:X}"


# =============================================================
# Read DTC Function (ECU - UDS SID 0x19 Subfunction 0x02)
# =============================================================
def Read_Keihin_EMS_DTC(bus, dtc_map):
    response, error = send_uds_request(bus, 0x19, [0x02, 0x8F], 0x59)

    if error:
        return False, [], error

    if not response:
        return False, [], "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x59:
        return False, [], f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3:
        return False, [], f"Response too short: {len(response)} bytes"

    payload = response[3:]

    # No DTCs found
    if not payload:
        print("[INFO] No DTCs detected")
        return True, [], None

    if len(payload) % 4 != 0:
        return False, [], f"Invalid DTC Payload Length: {len(payload)} bytes (not a multiple of 4)"

    detected_dtcs = []
    overall_pass = True
    dtc_count = len(payload) // 4

    for i in range(dtc_count):
        b1 = payload[i * 4]
        b2 = payload[i * 4 + 1]
        obd_code = decode_j2012_dtc(b1, b2)

        dtc_info = dtc_map.get(obd_code, None)
        if dtc_info:
            dtc_description = dtc_info["DTC_Description"]
            dtc_required = dtc_info["dtc_required"]
        else:
            dtc_description = "Unknown DTC (not in Excel)"
            dtc_required = False
            print(f"[WARNING] DTC {obd_code} not found in Excel mapping")

        # If any detected DTC is not marked as allowed/required, overall status fails
        if not dtc_required:
            overall_pass = False

        print(f"[DTC] {obd_code}: {dtc_description} | DTC_Required={dtc_required}")
        detected_dtcs.append({
            "code": obd_code,
            "DTC_Description": dtc_description
        })

    return overall_pass, detected_dtcs, None


# =========================
# MAIN FUNCTION
# =========================
def Keihin_EMS_Read_DTC(interface, channel, bitrate):
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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Load DTC mapping from encrypted Excel
        dtc_map = load_dtc_map_from_excel(EXCEL_DTC_PATH)

        # Step 1: Default Diagnostic Session
        sess_ok, sess_err = default_diagnostic_session(bus)
        if not sess_ok:
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
            if sess_err:
                print(f"Default Session Error: {sess_err}")
            print(error_message)
            return False, error_message

        time.sleep(0.05)

        # Step 2: Extended Diagnostic Session
        sess_ok, sess_err = extended_diagnostic_session(bus)
        if not sess_ok:
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
            if sess_err:
                print(f"Extended Session Error: {sess_err}")
            print(error_message)
            return False, error_message

        time.sleep(0.05)

        # Step 3: Read DTCs from ECU
        overall_pass, detected_dtcs, error = Read_Keihin_EMS_DTC(bus, dtc_map)

        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(error)
                return False, error

        return overall_pass, detected_dtcs

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
    success, dtcs = Keihin_EMS_Read_DTC(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    print(f"\nSTATUS : {'SUCCESS' if success else 'FAILURE'}")

    if isinstance(dtcs, str):
        print(f"ERROR  : {dtcs}")
    elif not dtcs:
        print("RESULT : No DTCs detected (Clean ECU)")
    else:
        print(f"DTC COUNT: {len(dtcs)}")
        print("DETECTED DTCs:")
        for dtc in dtcs:
            print(f"  - Code       : {dtc['code']}")
            print(f"    Description: {dtc['DTC_Description']}")



Sample Returning Three Values Code without API_Fetch MATCH / NOT MATCHED - READ,
 

# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import os
import can
import time
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions
# =========================
def default_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x01], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x01:
        print("Default Diagnostic Session Passed\n")
        return True, None
    print("Default Diagnostic Session Failed\n")
    return False, "INVALID_SESSION_RESPONSE"


def extended_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("Extended Diagnostic Session Passed\n")
        return True, None
    print("Extended Diagnostic Session Failed\n")
    return False, "INVALID_SESSION_RESPONSE"


# =============================================================
# VIN Number Read Function (ECU - DID 0xF190)
# =============================================================
def Read_ECU_VIN_Number(bus):
    response, error = send_uds_request(bus, 0x22, [0xF1, 0x90], 0x62)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x62:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3:
         return None, f"Response too short: {len(response)} bytes"

    if response[1] != 0xF1 or response[2] != 0x90:
        return None, f"DID mismatch: got 0x{response[1]:02X} 0x{response[2]:02X}"

    if len(response) < 4:
        return None, "No data payload in response"

    vin_bytes = response[3:]

    if all(b == 0x00 for b in vin_bytes):
        vin_number = '0' * len(vin_bytes)
        print(f"All-zero VIN detected, returning: {vin_number}")
        return vin_number, None

    try:
        vin_number = bytes(vin_bytes).rstrip(b"\x00").decode('ascii', errors='ignore').strip()
    except Exception as e:
        print(f"ASCII decode failed: {e}")
        vin_number = ''.join(chr(b) for b in vin_bytes if 32 <= b <= 126).strip()

    return vin_number, None


# =========================
# MAIN FUNCTION
# =========================
def Keihin_EMS_Read_VIN(interface, channel, bitrate, api_url, vin):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    expected_vin = vin.strip() if vin else None
    os_name = platform.system()

    # ---- Linux Configuration ----
    if os_name == "Linux":
        try:
            interface = "socketcan"
            channel = "can0" if not channel else channel
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {int(bitrate)}")
            os.system(f"sudo ip link set {channel} up")
        except Exception as e:
            error_message = f"Linux SocketCAN setup error: {e}"
            print(error_message)
            return False, expected_vin, error_message

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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, expected_vin, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # ---- Step 1: Enter Extended Diagnostic Session ----
        session_success, session_error = extended_diagnostic_session(bus)
        if not session_success:
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
            if session_error:
                print(f"Session Error: {session_error}")
            print(error_message)
            return False, expected_vin, error_message

        time.sleep(0.05)

        # ---- Step 2: Read VIN from ECU ----
        ecu_vin, error = Read_ECU_VIN_Number(bus)

        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, expected_vin, error_message
            else:
                print(error)
                return False, expected_vin, error

        print(f"ECU VIN Number   : {ecu_vin}")
        print(f"Target VIN Number: {expected_vin}")

        ecu_clean = ecu_vin.strip().upper()
        expected_clean = expected_vin.strip().upper() if expected_vin else ""

        if ecu_clean == expected_clean:
            print("VIN MATCHED")
            return True, expected_vin, ecu_vin
        else:
            print("VIN MISMATCHED")
            return False, expected_vin, ecu_vin

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, expected_vin, error_message

    except Exception as e:
        error_message = f"ECU Error: {e}"
        print(error_message)
        return False, expected_vin, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")
        
        if os_name == "Linux" and channel:
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    VIN = "MD626BK3XT2H01434"
    api_url = "http://10.121.2.107:3000/vehicles/flashFile/prd"

    success, expected_val, actual_val = Keihin_EMS_Read_VIN(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        api_url=api_url,
        vin=VIN
    )

    if success:
        print("\nSTATUS : SUCCESS - VIN MATCH")
    else:
        print("\nSTATUS : FAILURE / MISMATCH / ERROR")

    print(f"Target VIN       : {expected_val}")
    print(f"ECU VIN / Result : {actual_val}")




Sample Returning Three Values Code with API_Fetch MATCH / NOT MATCHED - READ,

 
# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import os
import can
import time
import requests
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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


# =============================================================
# CVN Number Read Function (ECU) - OBD Mode 0x09 InfoType 0x06
# =============================================================
def Read_Conti_EMS_CVN_Number(bus):
    response, error = send_uds_request(bus, 0x09, [0x06], 0x49)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x49:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3:
        return None, f"Response too short: {len(response)} bytes"

    if response[1] != 0x06:
        return None, f"InfoType mismatch: got 0x{response[1]:02X}, expected 0x06"

    if len(response) < 4:
        return None, "No CVN data bytes in response"

    # response[0] = SID (0x49), response[1] = InfoType (0x06), response[2] = NODI/Count
    cvn_bytes = response[3:]
    cvn_number = ''.join(f"{b:02X}" for b in cvn_bytes)

    return cvn_number, None


# =============================================================
# CVN Fetch from API
# =============================================================
def fetch_cvn_from_api(api_url):
    try:
        response = requests.get(api_url, timeout=5)
        response.raise_for_status()
        api_response = response.json()

        modules = api_response.get("data", {}).get("modules", [])

        for module in modules:
            if module.get("module") == "PCM":
                for config in module.get("configs", []):
                    if config.get("refname") == "PCM_CVN_READ":
                        messages = config.get("messages", [])
                        for message in messages:
                            txbytes = message.get("txbytes", "").strip()
                            if txbytes:
                                print(f"API txbytes (full): {txbytes}")
                                api_cvn = txbytes.replace(" ", "").strip().upper()
                                return api_cvn, None

        error_message = "PCM_CVN_READ entry not found in API response"
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
def Conti_EMS_Read_CVN(interface, channel, bitrate, api_url, vin):
    vin_clean = vin.strip() if vin else ""
    if not api_url.rstrip("/").endswith(vin_clean):
        api_url = f"{api_url.rstrip('/')}/{vin_clean}"

    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    api_cvn = None
    os_name = platform.system()

    try:
        # ---- Step 1: Fetch target CVN from API ----
        api_cvn, api_error = fetch_cvn_from_api(api_url)

        if api_error:
            print(api_error)
            return False, None, api_error

        print(f"API CVN Number: {api_cvn}")

        # ---- Step 2: Linux SocketCAN Setup ----
        if os_name == "Linux":
            try:
                interface = "socketcan"
                channel = "can0" if not channel else channel
                os.system(f"sudo ip link set {channel} down")
                os.system(f"sudo ip link set {channel} type can bitrate {int(bitrate)}")
                os.system(f"sudo ip link set {channel} up")
            except Exception as e:
                error_message = f"Linux SocketCAN setup error: {e}"
                print(error_message)
                return False, api_cvn, error_message

        # ---- Step 3: Initialize CAN Bus ----
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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, api_cvn, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # ---- Step 4: Read CVN from ECU ----
        ecu_cvn, error = Read_Conti_EMS_CVN_Number(bus)

        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, api_cvn, error_message
            else:
                print(error)
                return False, api_cvn, error

        print(f"Conti EMS ECU CVN Number : {ecu_cvn}")

        # ---- Step 5: Verify & Compare ----
        ecu_clean = ecu_cvn.strip().upper()
        api_clean = api_cvn.strip().upper()

        if ecu_clean == api_clean:
            print("CVN MATCHED")
            return True, api_cvn, ecu_cvn
        else:
            print("CVN MISMATCHED")
            return False, api_cvn, ecu_cvn

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, api_cvn, error_message

    except Exception as e:
        error_message = f"ECU Error: {e}"
        print(error_message)
        return False, api_cvn, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")

        if os_name == "Linux" and channel:
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    success, api_val, ecu_val = Conti_EMS_Read_CVN(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        api_url = "http://10.121.2.107:3000/vehicles/flashFile/prd",
        vin="MD625CK27T1L00488"
    )

    if success:
        print("\nSTATUS : SUCCESS - CVN MATCH")
    else:
        print("\nSTATUS : FAILURE / MISMATCH / ERROR")

    print(f"API CVN Number : {api_val}")
    print(f"ECU CVN / Result : {ecu_val}")



Sample Security Access Code,  

# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import can
import time
import hashlib
import os
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions
# =========================
def enter_programming_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x02], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x02:
        print("[OK] Programming Diagnostic Session Passed\n")
        return True, None
    print("[FAIL] Programming Diagnostic Session Failed\n")
    return False, "INVALID_PROGRAMMING_SESSION_RESPONSE"


# =============================================================
# RIPEMD-160 Security Access Helpers
# =============================================================
def bit_reverse(value: int, width: int) -> int:
    rev = 0
    for _ in range(width):
        rev = (rev << 1) | (value & 1)
        value >>= 1
    return rev


def rotL(value: int, bits: int, width: int) -> int:
    return ((value << bits) | (value >> (width - bits))) & ((1 << width) - 1)


def rotR(value: int, bits: int, width: int) -> int:
    return (value >> bits) | (value << (width - bits)) & ((1 << width) - 1)


def calculate_key(S: int) -> bytes:
    EK = 0x5EAEB7F9B8D2D8B1

    S_inv = bit_reverse(S, 32)
    EK_inv = bit_reverse(EK, 64)
    not_EK = (~EK) & 0xFFFFFFFFFFFFFFFF
    not_S = (~S) & 0xFFFFFFFF

    rotL_EK_31 = rotL(EK, 31, 64)
    rotL_EK_13 = rotL(EK, 13, 64)
    not_rotL_EK_13 = (~rotL_EK_13) & 0xFFFFFFFFFFFFFFFF

    rotR_S_10 = rotR(S, 10, 32)
    rotR_S_10_inv = bit_reverse(rotR_S_10, 32)

    # Build 64-byte Buffer B
    B = (
        S.to_bytes(4, 'big') +
        EK.to_bytes(8, 'big') +
        S_inv.to_bytes(4, 'big') +
        not_EK.to_bytes(8, 'big') +
        rotL(S, 14, 32).to_bytes(4, 'big') +
        EK_inv.to_bytes(8, 'big') +
        not_S.to_bytes(4, 'big') +
        rotL_EK_31.to_bytes(8, 'big') +
        S.to_bytes(4, 'big') +
        not_rotL_EK_13.to_bytes(8, 'big') +
        rotR_S_10_inv.to_bytes(4, 'big')
    )

    B_prime = B[::-1]

    ripemd160 = hashlib.new('ripemd160')
    ripemd160.update(B_prime)
    D = ripemd160.digest()

    D_prime = D[::-1]

    # MSB-first bit stream of D'
    bits = []
    for byte in D_prime:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)

    rev_bits = list(reversed(bits))
    rev_positions = list(reversed([
        19, 74, 59, 78, 0, 26, 89, 77, 144, 107,
        47, 134, 61, 88, 58, 135, 121, 95, 29, 158,
        81, 54, 70, 115, 46, 3, 44, 123, 39, 157,
        30, 90
    ]))

    selected_bits = [rev_bits[p] for p in rev_positions]

    key_bytes = bytearray()
    for i in range(0, 32, 8):
        chunk = selected_bits[i:i+8]
        byte_val = 0
        for bit in chunk:
            byte_val = (byte_val << 1) | bit
        key_bytes.append(byte_val)

    print(f"Seed (S)       = 0x{S:08X}")
    print(f"Calculated Key = 0x{key_bytes.hex().upper()}")
    return bytes(key_bytes)


def request_seed_01(bus):
    response, error = send_uds_request(bus, 0x27, [0x01], 0x67)
    if error:
        return None, f"Seed Request Error: {error}"

    if len(response) < 6 or response[1] != 0x01:
        return None, "Invalid Seed Response Format"

    S_bytes = response[2:6]
    S = int.from_bytes(S_bytes, 'big')
    print(f"Raw Seed Received: 0x{S:08X}")
    return S, None


def send_key_02(bus, key_bytes: bytes):
    payload = [0x02] + list(key_bytes)
    response, error = send_uds_request(bus, 0x27, payload, 0x67)
    if error:
        return False, f"Key Validation Error: {error}"

    if len(response) < 2 or response[1] != 0x02:
        return False, "Programming Security Access Key Rejected"

    print("Programming Security Access Passed.\n")
    return True, None


# =========================
# MAIN FUNCTION
# =========================
def Conti_EMS_Programming_Security(interface, channel, bitrate):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    system_os = platform.system()

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
            bus = can.Bus(interface=interface,channel=channel,bitrate=int(bitrate),fd=False)

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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Step 1: Programming Diagnostic Session
        sess_ok, sess_err = enter_programming_diagnostic_session(bus)
        if not sess_ok:
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
            if sess_err:
                print(f"Session Error: {sess_err}")
            print(error_message)
            return False, error_message

        # Step 2: Request Seed (0x01)
        seed, seed_err = request_seed_01(bus)
        if seed_err:
            if seed_err == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(seed_err)
                return False, seed_err

        # # Check if already unlocked (Seed is 0x00000000)
        # if seed == 0x00000000:
        #     print("Programming Security Access already unlocked.")
        #     return True, "ALREADY_UNLOCKED"

        # Step 3: Calculate Key
        key_bytes = calculate_key(seed)

        # Step 4: Send Key (0x02)
        key_ok, key_err = send_key_02(bus, key_bytes)
        if not key_ok:
            print(key_err)
            return False, key_err

        print("Programming Security Access: PASSED")
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

        if system_os == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    status, result = Conti_EMS_Programming_Security(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if status:
        print(f"\nSTATUS : SUCCESS - Programming Security: {result}")
    else:
        print(f"\nSTATUS : FAILURE / ERROR - {result}")


Sample Returning Two Values Code - WRITE,
 
# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import can
import time
import os
import platform
from datetime import datetime

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions
# =========================
def extended_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session Passed\n")
        return True, None
    print("[FAIL] Extended Diagnostic Session Failed\n")
    return False, "INVALID_SESSION_RESPONSE"


# =============================================================
# Write Date of Last Programming Function (DID 0xF199)
# =============================================================
def Write_Conti_EMS_Date_Of_Last_Programming(bus, date_str):
    # Convert date string (DDMMYYYY) to ASCII byte array
    date_bytes = [ord(c) for c in date_str]

    # WriteDataByIdentifier (SID 0x2E), DID: 0xF199
    payload = [0xF1, 0x99] + date_bytes
    response, error = send_uds_request(bus, 0x2E, payload, 0x6E)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x6E:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3 or response[1] != 0xF1 or response[2] != 0x99:
        return None, "DID mismatch in write response"

    print(f"Date of Last Programming ({date_str}) written successfully")
    return date_str, None


# =========================
# MAIN FUNCTION
# =========================
def Conti_EMS_Write_Date_Of_Last_Programming(interface, channel, bitrate):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    system_os = platform.system()
    current_date = datetime.now().strftime("%d%m%Y")

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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        written_date, error = Write_Conti_EMS_Date_Of_Last_Programming(bus, current_date)
        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(error)
                return False, error

        print(f"Written Date: {written_date}")
        return True, written_date

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

        if system_os == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    status, result = Conti_EMS_Write_Date_Of_Last_Programming(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if status:
        print(f"\nSTATUS : SUCCESS - Date Written: {result}")
    else:
        print(f"\nSTATUS : FAILURE / ERROR - {result}")


Sample Returning Three Values Code with API_Fetch MATCH / NOT MATCHED - WRITE,
 

# -*- coding: utf-8 -*-
"""
Created on Fri May 15 2026

@author: Sri.Sakthivel
"""

import can
import time
import requests
import os
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions & Security Access
# =========================
def enter_default_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x01], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x01:
        print("[OK] Default Diagnostic Session Activated\n")
        return True, None
    return False, "INVALID_DEFAULT_SESSION_RESPONSE"


def enter_extended_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session Activated\n")
        return True, None
    return False, "INVALID_EXTENDED_SESSION_RESPONSE"



# =============================================================
# Helper Utilities
# =============================================================
def fetch_sku_from_api(api_url, vin):
    try:
        r = requests.get(f"{api_url}", timeout=5)
        r.raise_for_status()

        api_data = r.json()
        modules = api_data.get("data", {}).get("modules", [])

        for m in modules:
            if m.get("module") == "PCM":
                for cfg in m.get("configs", []):
                    if cfg.get("refname") == "PCM_SKU_WRITE":
                        msg = cfg.get("messages")
                        if isinstance(msg, list) and msg:
                            return msg[0].get("txbytes")
                        elif isinstance(msg, dict):
                            return msg.get("txbytes")
        return None
    except Exception as e:
        print(f"API Fetch Exception: {e}")
        return None


def convert_sku_to_bytes(sku_str, target_len=16):
    if not sku_str:
        return [0x30] * target_len

    if " " in sku_str:
        try:
            bytes_list = [int(x, 16) for x in sku_str.split()]
        except ValueError:
            bytes_list = [ord(c) for c in sku_str]
    else:
        bytes_list = [ord(c) for c in sku_str]

    if len(bytes_list) < target_len:
        bytes_list.extend([0x30] * (target_len - len(bytes_list)))

    return bytes_list[:target_len]


# =============================================================
# Conti EMS Write SKU Function
# =============================================================
def Write_Conti_EMS_SKU(bus, api_sku_str):
    ECU_SKU_SIZE = 16
    sku_bytes = convert_sku_to_bytes(api_sku_str, target_len=ECU_SKU_SIZE)

    if len(sku_bytes) != ECU_SKU_SIZE:
        return None, f"Invalid SKU length: {len(sku_bytes)} (Expected {ECU_SKU_SIZE})"

    print("ECU Write Bytes:", " ".join(f"{b:02X}" for b in sku_bytes))

    # WriteDataByIdentifier (SID 0x2E), DID 0xF185
    payload = [0xF1, 0x85] + sku_bytes
    response, error = send_uds_request(bus, 0x2E, payload, 0x6E)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x6E:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3 or response[1] != 0xF1 or response[2] != 0x85:
        return None, "DID mismatch in write response"

    ascii_value = "".join(chr(x) for x in sku_bytes if x != 0x00)
    print("SKU WRITE SUCCESS")
    return ascii_value, None


# =========================
# MAIN FUNCTION (Returns: status, api_sku, ecu_value)
# =========================
def Conti_EMS_Write_SKU(interface, channel, bitrate, api_url, vin):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None

    api_sku_str = fetch_sku_from_api(api_url, vin)
    if not api_sku_str:
        error_message = "SKU not found from API"
        print(error_message)
        return False, None, error_message

    system_os = platform.system()
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
            return False, api_sku_str, error_message

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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, api_sku_str, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Execute Write SKU
        written_sku, error = Write_Conti_EMS_SKU(bus, api_sku_str)
        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, api_sku_str, error_message
            else:
                print(error)
                return False, api_sku_str, error

        print(f"Written SKU: {written_sku}")
        return True, api_sku_str, written_sku

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, api_sku_str, error_message

    except Exception as e:
        error_message = f"ECU Error: {e}"
        print(error_message)
        return False, api_sku_str, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed")

        if system_os == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    api_url = "http://10.121.2.107:3000/vehicles/flashFile/prd"
    vin = "MD625AF93S2L06342"

    success, api_sku, ecu_value = Conti_EMS_Write_SKU(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        api_url=api_url,
        vin=vin
    )

    print("\nSTATUS:", success)
    print("API SKU:", api_sku)
    print("ECU SKU:", ecu_value)


Sample Returning two Values Code - WRITE,
 
# -*- coding: utf-8 -*-
"""
Created on Fri May 15 2026

@author: Sri.Sakthivel
"""

import can
import time
import hashlib
import os
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
SECRET           = bytes([0x3F, 0x9B, 0x3E, 0x54, 0x43, 0x24, 0x22, 0xDE,0xED, 0xDB, 0x8D, 0x9D, 0xCC, 0x2C, 0xE7, 0x70])
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions & Security Access
# =========================
def enter_extended_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session Activated\n")
        return True, None
    return False, "INVALID_EXTENDED_SESSION_RESPONSE"


# =============================================================
# Conti EMS Write VIN Function
# =============================================================
def Write_Conti_EMS_VIN(bus, vin):
    if len(vin) != 17:
        return None, f"Invalid VIN length: {len(vin)} (Expected 17 characters)"

    vin_bytes = [ord(c) for c in vin]
    print(f"VIN Write Bytes: {' '.join(f'{b:02X}' for b in vin_bytes)}")

    # WriteDataByIdentifier (SID 0x2E), DID 0xF190
    payload = [0xF1, 0x90] + vin_bytes
    response, error = send_uds_request(bus, 0x2E, payload, 0x6E)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x6E:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3 or response[1] != 0xF1 or response[2] != 0x90:
        return None, "DID mismatch in VIN write response"

    print("VIN write successful!")
    return vin, None


# =========================
# MAIN FUNCTION
# =========================
def Conti_EMS_Write_VIN(interface, channel, bitrate, vin):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None

    if len(vin) != 17:
        error_message = f"VIN must be 17 characters (Provided: {len(vin)})"
        print(error_message)
        return False, error_message

    system_os = platform.system()
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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Execute Write VIN
        written_vin, error = Write_Conti_EMS_VIN(bus, vin)
        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(error)
                return False, error

        print(f"Written VIN: {written_vin}")
        return True, written_vin

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

        if system_os == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    vin_value = "MD625AF93S2L06342"

    status, vin_written = Conti_EMS_Write_VIN(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000,
        vin=vin_value
    )

    if status:
        print(f"\nSTATUS : SUCCESS - VIN Written: {vin_written}")
    else:
        print(f"\nSTATUS : FAILURE / ERROR - {vin_written}")



Sample Routine Control Returning Code, 

# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import os
import can
import time
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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


# =============================================================
# Routine Control Function (RID 0x7107 - Injector 1 Test)
# =============================================================
def Start_Routine_Injector_1_Test(bus):
    # Service 0x31 (RoutineControl), Subfunction 0x01 (startRoutine), RID: 0x7107 -> Expected Positive SID 0x71
    response, error = send_uds_request(bus, 0x31, [0x01, 0x71, 0x07], 0x71)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x71:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 4:
        return None, f"Response too short: {len(response)} bytes"

    if response[1] != 0x01 or response[2] != 0x71 or response[3] != 0x07:
        return None, (
            f"Routine Control mismatch in response: got "
            f"0x{response[1]:02X} 0x{response[2]:02X} 0x{response[3]:02X}, "
            f"expected 0x01 0x71 0x07"
        )

    return "Passed", None


# =========================
# MAIN FUNCTION
# =========================
def Keihin_EMS_Routine_Start_Control_Injector_1_Test(interface, channel, bitrate):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None

    # Handle Linux-specific network configuration if applicable
    system_os = platform.system()
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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        status_result, error = Start_Routine_Injector_1_Test(bus)

        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(error)
                return False, error

        print("Injector 1 Test Routine Started Successfully")
        return True, status_result

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
    success, result_message = Keihin_EMS_Routine_Start_Control_Injector_1_Test(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if success:
        print("\nSTATUS : SUCCESS - INJECTOR 1 TEST ROUTINE STARTED")
    else:
        print("\nSTATUS : FAILURE / ERROR")

    print(f"Result : {result_message}")



Sample IO Control Returning Code, 

# -*- coding: utf-8 -*-
"""
Created on Wed Feb 18 12:56:59 2026

@author: Sri.Sakthivel
"""

import can
import time
import os
import platform

# =========================
# Configuration
# =========================
TESTER_ID        = 0x7E0
ECU_RESPONSE_ID  = 0x7E8
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

    msg = can.Message(
        arbitration_id=arbitration_id,
        data=bytearray(padded_data[:8]),
        is_fd=False,
        is_extended_id=False
    )
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
                            wait_start = time.time()  # Reset wait timer on consecutive 0x78
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
# Sessions
# =========================
def extended_diagnostic_session(bus):
    response, error = send_uds_request(bus, 0x10, [0x03], 0x50)
    if error:
        return False, error
    if response and len(response) >= 2 and response[1] == 0x03:
        print("[OK] Extended Diagnostic Session Passed\n")
        return True, None
    print("[FAIL] Extended Diagnostic Session Failed\n")
    return False, "INVALID_SESSION_RESPONSE"


# =============================================================
# Input/Output Control Function (DID 0xFF21 - Coil OFF)
# =============================================================
def IO_Control_Conti_Coil_Off(bus):
    # InputOutputControlByIdentifier (SID 0x2F), DID 0xFF21, Control Option 0x03, State 0x00 0x09
    sub_payload = [0xFF, 0x21, 0x03, 0x00, 0x09]
    response, error = send_uds_request(bus, 0x2F, sub_payload, 0x6F)

    if error:
        return None, error

    if not response:
        return None, "ECU_RESPONSE_TIMEOUT"

    if response[0] != 0x6F:
        return None, f"UNEXPECTED_RESPONSE_SID: 0x{response[0]:02X}"

    if len(response) < 3 or response[1] != 0xFF or response[2] != 0x21:
        return None, "DID mismatch in IO Control response"

    print("IO Control FF21 (COIL OFF) SUCCESS")
    return "PASSED", None


# =========================
# MAIN FUNCTION
# =========================
def Conti_EMS_IOI_COIL_OFF(interface, channel, bitrate):
    global START_TIME, log_counter
    START_TIME  = time.perf_counter()
    log_counter = 1
    bus = None
    system_os = platform.system()

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
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
            else:
                error_message = f"CAN Initialization Error: {e}"

            print(error_message)
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])

        # Step 1: Extended Diagnostic Session
        sess_ok, sess_err = extended_diagnostic_session(bus)
        if not sess_ok:
            error_message = (
                "- Verify failed:\n"
                "- No communication from ECU\n"
                "- Check vehicle ignition status\n"
                "- Check CAN wiring\n"
                "- Verify baud rate"
            )
            if sess_err:
                print(f"Session Error: {sess_err}")
            print(error_message)
            return False, error_message

        # Step 2: IO Control FF21 (Coil OFF)
        control_status, error = IO_Control_Conti_Coil_Off(bus)
        if error:
            if error == "ECU_RESPONSE_TIMEOUT":
                error_message = (
                    "- Verify failed:\n"
                    "- No communication from ECU\n"
                    "- Check vehicle ignition status\n"
                    "- Check CAN wiring\n"
                    "- Verify baud rate"
                )
                print(error_message)
                return False, error_message
            else:
                print(error)
                return False, error

        print(f"Coil OFF Result: {control_status}")
        return True, control_status

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

        if system_os == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


# =========================
# ENTRY POINT
# =========================
if __name__ == "__main__":
    status, result = Conti_EMS_IOI_COIL_OFF(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if status:
        print(f"\nSTATUS : SUCCESS - COIL OFF: {result}")
    else:
        print(f"\nSTATUS : FAILURE / ERROR - {result}")
