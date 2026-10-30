# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel

"""

import can
import time
import ctypes
import os
from pathlib import Path
from typing import Optional
from can import Message


TESTER_ID       = 0x7C9
ECU_RESPONSE_ID = 0x7C1

BASE_DIR        : Path          = Path(__file__).resolve().parent
KEYGEN_DLL_PATH : Optional[str] = str(BASE_DIR.parent / "DLL_File" / "VIC_Cluster.dll")

# =============================================================================
# Logging
# =============================================================================
def log_message(direction: str, msg: Message) -> None:
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    print(f"{direction} {msg.arbitration_id:04X}: {formatted_data}")


# =============================================================================
# CAN Helpers
# =============================================================================
def _send_can_frame(bus, arbitration_id: int, data: list) -> None:
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)

    msg = Message(arbitration_id=arbitration_id,data=bytearray(padded_data[:8]),is_fd=False,is_extended_id=False)
    bus.send(msg)
    log_message("TX", msg)


def _receive_single_can_frame(bus,response_id: int,timeout: float = 0.5) -> Optional[Message]:
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


# =============================================================================
# ISO-TP Layer
# =============================================================================
def receive_isotp_response(bus,response_id: int,tester_id: int,timeout: float = 3.0) -> Optional[list]:
    start_time          = time.time()
    full_response_data  = []
    expect_consecutive  = False
    seq_number_expected = 1
    total_uds_length    = 0

    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=1.0)
        if not msg:
            continue

        pci_type = (msg.data[0] & 0xF0) >> 4

        # ── Single Frame ──────────────────────────────────────────────────
        if pci_type == 0x0:
            uds_length = msg.data[0] & 0x0F
            return list(msg.data[1:1 + uds_length])

        # ── First Frame ───────────────────────────────────────────────────
        elif pci_type == 0x1:
            total_uds_length    = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            full_response_data  = list(msg.data[2:])
            expect_consecutive  = True
            seq_number_expected = 1

            # Send Flow Control: Continue To Send, BS=0, STmin=0
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, tester_id, fc_frame)

        # ── Consecutive Frame ─────────────────────────────────────────────
        elif pci_type == 0x2 and expect_consecutive:
            seq_number = msg.data[0] & 0x0F

            if seq_number != seq_number_expected:
                print(
                    f"ISO-TP SEQ ERROR → "
                    f"expected {seq_number_expected}, got {seq_number}"
                )
                return None

            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16

            if len(full_response_data) >= total_uds_length:
                return full_response_data[:total_uds_length]

    return None


def send_isotp_request(
    bus,
    arbitration_id: int,
    response_id: int,
    data: list
) -> bool:
    total_len = len(data)

    # ── Single Frame ──────────────────────────────────────────────────────
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True

    # ── First Frame ───────────────────────────────────────────────────────
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)

    # ── Wait for Flow Control ─────────────────────────────────────────────
    start      = time.time()
    st_min_sec = 0.001  # default 1 ms

    while time.time() - start < 2.0:
        fc_msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not fc_msg:
            continue

        pci = (fc_msg.data[0] & 0xF0) >> 4
        if pci == 0x3:
            st_min_raw = fc_msg.data[2]

            # Decode STmin per ISO 15765-2
            if st_min_raw <= 0x7F:
                st_min_sec = st_min_raw / 1000.0        # 0–127 ms
            elif 0xF1 <= st_min_raw <= 0xF9:
                st_min_sec = (st_min_raw - 0xF0) * 0.0001  # 100–900 µs
            else:
                st_min_sec = 0.001                      # reserved → default
            break
    else:
        print("No Flow Control received.")
        return False

    # ── Consecutive Frames ────────────────────────────────────────────────
    remaining = data[6:]
    seq       = 1

    while remaining:
        time.sleep(st_min_sec)
        cf_pci     = 0x20 | (seq & 0x0F)
        chunk_len  = min(7, len(remaining))
        cf_data    = [cf_pci] + remaining[:chunk_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining  = remaining[chunk_len:]
        seq        = (seq + 1) % 16

    return True


# =============================================================================
# Tester Present (SID 0x3E)
# =============================================================================
def send_tester_present(bus, tester_id: int = TESTER_ID) -> None:
    uds_payload = [0x3E, 0x80]
    isotp_sf    = [len(uds_payload)] + uds_payload
    _send_can_frame(bus, tester_id, isotp_sf)


# =============================================================================
# UDS Core
# =============================================================================
def send_uds_request(
    bus,
    sid: int,
    sub_payload: list,
    expected_positive_sid: int,
    tester_id: int   = TESTER_ID,
    response_id: int = ECU_RESPONSE_ID
) -> Optional[list]:
    uds_payload = [sid] + sub_payload
    max_retries = 1
    retry_delay = 3.0
    tp_interval = 1.0

    # ── Internal helper: transmit the UDS payload ─────────────────────────
    def _transmit() -> bool:
        if len(uds_payload) <= 7:
            isotp_sf = [len(uds_payload)] + uds_payload
            _send_can_frame(bus, tester_id, isotp_sf)
            return True
        return send_isotp_request(bus, tester_id, response_id, uds_payload)

    # ── Initial transmit ──────────────────────────────────────────────────
    if not _transmit():
        print("Failed to send ISO-TP request.")
        return None

    # ── Retry loop ────────────────────────────────────────────────────────
    for attempt in range(max_retries + 1):
        response = receive_isotp_response(
            bus, response_id, tester_id, timeout=3.0
        )

        # ── Negative Response ─────────────────────────────────────────────
        if response and response[0] == 0x7F:

            # NRC 0x78: ECU still processing — wait with TP keepalive
            if len(response) >= 3 and response[2] == 0x78:
                print("[NRC] 0x78 - Response Pending …")
                wait_start   = time.time()
                last_tp_time = time.time()

                while time.time() - wait_start < retry_delay:
                    pending = receive_isotp_response(
                        bus, response_id, tester_id, timeout=0.5
                    )

                    if pending:
                        if pending[0] == expected_positive_sid:
                            print("Positive response received after 0x78.\n")
                            return pending

                        if pending[0] == 0x7F and len(pending) >= 3:
                            nrc = pending[2]
                            if nrc == 0x78:
                                print("[NRC] 0x78 - Still pending …")
                            else:
                                print(
                                    f"Negative Response during wait: "
                                    f"NRC 0x{nrc:02X}"
                                )
                                return None

                    # Send TesterPresent periodically to hold session
                    if time.time() - last_tp_time >= tp_interval:
                        send_tester_present(bus, tester_id)
                        last_tp_time = time.time()

                print("No positive response after NRC 0x78 wait period.")
                return None

            # Other NRC
            if len(response) >= 3:
                print(f"Negative Response: NRC 0x{response[2]:02X}")
            return None

        # ── Positive Response ─────────────────────────────────────────────
        if response and response[0] == expected_positive_sid:
            return response

        # ── No valid response — retry ─────────────────────────────────────
        if attempt < max_retries:
            print(f"Attempt {attempt + 1}: No valid response, retrying …")
            if not _transmit():
                print(f"Attempt {attempt + 1}: Failed to retransmit.")
                return None
        else:
            print(f"No valid response after {max_retries + 1} attempts.")

    return None


def compute_key(seed_bytes: bytes) -> bytes:
    seed_hex = seed_bytes.hex().upper().encode("ascii")

    if KEYGEN_DLL_PATH and os.path.isfile(KEYGEN_DLL_PATH):
        dll = ctypes.CDLL(KEYGEN_DLL_PATH)
        dll.CalculateKey.argtypes = [ctypes.c_char_p]
        dll.CalculateKey.restype  = ctypes.c_char_p

        result = dll.CalculateKey(seed_hex)

        if result is None:
            raise RuntimeError(
                f"DLL CalculateKey returned NULL for seed "
                f"{seed_hex.decode()}"
            )

        key_hex = result.decode("ascii").strip()
        print(f"  [SA] DLL  seed={seed_hex.decode()} → key={key_hex}")
        return bytes.fromhex(key_hex)

    # ── Fallback: DLL not present ─────────────────────────────────────────
    print(
        "  [SA] WARNING: DLL not found at:\n"
        f"       {KEYGEN_DLL_PATH}\n"
        "       Using XOR placeholder — NOT suitable for production!"
    )
    seed_int = int.from_bytes(seed_bytes, "big")
    key_int  = seed_int ^ 0xDEADBEEF
    return key_int.to_bytes(len(seed_bytes), "big")



def request_seed(bus) -> Optional[bytes]:
    response = send_uds_request(bus, 0x27, [0x01], 0x67)
    if response and len(response) >= 4 and response[1] == 0x01:
        seed_bytes = bytes(response[2:10])
        print(f"  [SA] Seed received: {seed_bytes.hex().upper()}")
        return seed_bytes
    print("Seed Request - FAILED\n")
    return None


def send_key(bus, key_bytes: bytes) -> bool:
    key_payload = list(key_bytes)
    response    = send_uds_request(bus, 0x27, [0x02] + key_payload, 0x67)
    if response and len(response) >= 2 and response[1] == 0x02:
        print("Security Access - PASSED\n")
        return True
    print("Security Access - FAILED\n")
    return False


def IPC_Security_Access(interface,channel,bitrate):
    bus = None
    try:
        try:
            bus = can.Bus(
                interface=interface,
                channel=channel,
                bitrate=bitrate,
                fd=False
            )
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF},])
        seed_bytes = request_seed(bus)
        if not seed_bytes:
            error_message = "Failed to retrieve seed from ECU."
            return False, error_message

        key_bytes = compute_key(seed_bytes)
        print(f" Key calculated: {key_bytes.hex().upper()}")

        if not send_key(bus, key_bytes):
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
    
    except Exception as e:
        error_message = f"Unexpected Error: {e}"
        print(error_message)
        return False, error_message
    finally:
        if bus:
            bus.shutdown()
            print("CAN channel closed.")


# =============================================================================
# Entry Point
# =============================================================================
if __name__ == "__main__":
    success = IPC_Security_Access(interface="pcan",channel="PCAN_USBBUS1",   bitrate=500000)