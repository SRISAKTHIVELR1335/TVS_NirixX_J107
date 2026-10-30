# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel
"""

import can
from can import Message
import time
import os
import platform

# =========================
# CAN / UDS Identifiers
# =========================
REQUEST_ID  = 0x7C9
RESPONSE_ID = 0x7C1

log_counter = 1


def log_print(arbitration_id, direction, data):
    global log_counter
    time_stamp = time.time() * 1000
    data_str   = " ".join(f"{b:02X}" for b in data)
    print(
        f"{log_counter:>3}  "
        f"{time_stamp:.3f} DT "
        f"{arbitration_id:04X} "
        f"{direction} 8  {data_str}"
    )
    log_counter += 1


def send_frame(bus, arb_id, data):
    padded = list(data) + [0x00] * (8 - len(data))
    msg = Message(arbitration_id=arb_id, data=bytearray(padded[:8]), is_extended_id=False)
    bus.send(msg)
    log_print(msg.arbitration_id, "TX", msg.data)


def send_flow_control(bus, request_id, block_size=0x00, st_min=0x00):
    fc = [0x30, block_size, st_min, 0x00, 0x00, 0x00, 0x00, 0x00]
    send_frame(bus, request_id, fc)
    print(f"  [ISO-TP] Flow Control (CTS) sent -> 0x{request_id:03X}")


def receive_response(bus, response_id, request_id, recv_timeout=5.0):
    uds_payload     = []
    expected_length = 0
    expected_sn     = 1
    in_multi_frame  = False

    start_time = time.time()

    while time.time() - start_time < recv_timeout:
        msg = bus.recv(timeout=1.0)

        # No frame received in this slice
        if msg is None:
            continue

        # Ignore frames not belonging to response ID
        if msg.arbitration_id != response_id:
            continue

        log_print(msg.arbitration_id, "RX", msg.data)
        data     = list(msg.data)
        pci_type = (data[0] & 0xF0) >> 4

        # ---- Single Frame (PCI = 0x0) ----
        if pci_type == 0x0:
            uds_len = data[0] & 0x0F
            if uds_len == 0 or uds_len > 7:
                print(f"  [ISO-TP] Invalid Single Frame length: {uds_len}")
                return None

            uds_payload = data[1: 1 + uds_len]

            # NRC 0x78 (Response Pending) Handling
            if len(uds_payload) >= 3 and uds_payload[0] == 0x7F and uds_payload[2] == 0x78:
                print("  [ISO-TP] 0x78 Response Pending – waiting for final response...")
                uds_payload = []
                in_multi_frame = False
                continue

            return uds_payload

        # ---- First Frame (PCI = 0x1) ----
        elif pci_type == 0x1:
            expected_length = ((data[0] & 0x0F) << 8) | data[1]
            uds_payload     = data[2:]
            expected_sn     = 1
            in_multi_frame  = True

            print(f"  [ISO-TP] First Frame received, total UDS length = {expected_length} bytes")
            send_flow_control(bus, request_id)

        # ---- Consecutive Frame (PCI = 0x2) ----
        elif pci_type == 0x2:
            if not in_multi_frame:
                continue

            sn = data[0] & 0x0F
            if sn != expected_sn:
                print(f"  [ISO-TP] Sequence Number mismatch: expected {expected_sn}, got {sn}")
                return None

            uds_payload += data[1:]
            expected_sn  = (expected_sn + 1) & 0x0F

            if len(uds_payload) >= expected_length:
                uds_payload = uds_payload[:expected_length]
                print(f"  [ISO-TP] Multi-frame complete: {len(uds_payload)} bytes total")
                return uds_payload

    print(f"  [ISO-TP] Timeout waiting for response within {recv_timeout}s")
    return None


def validate_and_extract(uds_data, did_high, did_low):
    if not uds_data:
        return False, "ERROR: No data received"

    # ---- Negative Response ----
    if uds_data[0] == 0x7F:
        if len(uds_data) >= 3:
            nrc = uds_data[2]
            return False, f"NRC: 0x{nrc:02X}"
        return False, "ERROR: Incomplete Negative Response"

    # ---- Positive Response (0x62 DID_HI DID_LO ...) ----
    if (len(uds_data) >= 4 and 
        uds_data[0] == 0x62 and 
        uds_data[1] == did_high and 
        uds_data[2] == did_low):

        data_record = uds_data[3:]
        raw_hex = "".join(f"{b:02X}" for b in data_record)
        return True, raw_hex

    return False, f"ERROR: Unexpected response: {[f'0x{b:02X}' for b in uds_data]}"


# =============================================================================
# Main Callable Function
# =============================================================================
def IPC_Read_Variant_Data(interface, channel, bitrate, max_attempts=2):
    bus = None
    OS  = platform.system()

    try:
        # OS-Specific CAN Setup
        if OS == "Linux":
            interface = "socketcan"
            channel   = "can0"
            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")

        elif OS.upper() == "WINDOWS":
            pass

        bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate)
        bus.set_filters([{"can_id": RESPONSE_ID, "can_mask": 0x7FF, "extended": False}])

        # UDS Request: Read DID 0x092E -> [Len=3, SID=0x22, DID_HI=0x09, DID_LO=0x2E]
        request_data = [0x03, 0x22, 0x09, 0x2E, 0x00, 0x00, 0x00, 0x00]

        # Retry Loop (Fixed to actually execute)
        for attempt in range(1, max_attempts + 1):
            print(f"\n[Attempt {attempt}/{max_attempts}] Sending UDS Read Request...")
            send_frame(bus, REQUEST_ID, request_data)

            uds_data = receive_response(bus, response_id=RESPONSE_ID, request_id=REQUEST_ID, recv_timeout=3.0)

            if uds_data is None:
                print(f"  No response on attempt {attempt}")
                time.sleep(0.5)
                continue

            success, result_or_err = validate_and_extract(uds_data, 0x09, 0x2E)

            if success:
                print(f"  Variant Data (Hex): 0x{result_or_err}")
                try:
                    dec_val = int(result_or_err, 16)
                    print(f"  Variant Data (Dec): {dec_val}")
                except ValueError:
                    pass
                return True, result_or_err
            else:
                print(f"  Failed: {result_or_err}")
                return False, result_or_err

        return False, "ERROR: Timeout - No response from ECU after retries."

    except can.CanError as error:
        error_msg = str(error).lower()
        if "not been initialized" in error_msg:
            err = "ERROR: PCAN is not connected or not initialized."
        elif "heavy" in error_msg or "warning" in error_msg:
            err = "ERROR: No communication from ECU. Check ECU power, CAN wiring, and baud rate."
        else:
            err = f"CAN Error: {error}"
        return False, err

    except KeyboardInterrupt:
        return False, "ERROR: Operation interrupted by user."

    except Exception as error:
        return False, f"Unexpected Error: {error}"

    finally:
        if bus:
            bus.shutdown()
            print("  CAN Channel Closed.")

        if OS == "Linux":
            os.system(f"sudo ip link set {channel} down")


# ==================
# Entry Point
# ==================
if __name__ == "__main__":
    status, result = IPC_Read_Variant_Data(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )

    if status:
        print(f"STATUS       : SUCCESS")
        print(f"VARIANT DATA : 0x{result}")
    else:
        print(f"STATUS       : FAILURE")
        print(f"ERROR        : {result}")