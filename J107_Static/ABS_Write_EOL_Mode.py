# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel

"""

import can
import time
import os
import platform

REQUEST_ID  = 0x7E1
RESPONSE_ID = 0x7E9

log_counter = 1


def log_print(arb_id, direction, data):
    global log_counter
    timestamp = time.time() * 1000
    data_str = ' '.join(f"{b:02X}" for b in data)
    print(f"{log_counter:>3}  {timestamp:.3f} DT {arb_id:04X} {direction} 8  {data_str}")
    log_counter += 1


def ABS_Write_EOL_Mode(interface, channel, bitrate):

    bus  = None
    OS   = platform.system()

    try:
        # ── OS-specific CAN setup ─────────────────────────────────────────────
        if OS == "Linux":
            interface = "socketcan"
            channel   = "can0"

            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")

        elif OS.upper() == "WINDOWS":
            pass

        # ── Bus initialisation ────────────────────────────────────────────────
        try:
            bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate)
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            print(error_message)
            return error_message
        bus.set_filters([{"can_id": RESPONSE_ID, "can_mask": 0x7FF, "extended": False}])

        # ── Write EOL Mode request ──────────────────────────────────────────
        data = [0x04, 0x2E, 0xF1, 0xF1, 0x01, 0x00, 0x00, 0x00]
        msg  = can.Message(arbitration_id=REQUEST_ID, data=data, is_extended_id=False)

        bus.send(msg)
        log_print(msg.arbitration_id, "TX", msg.data)

        # ── Wait for response ─────────────────────────────────────────────────
        timeout    = 2
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = bus.recv(timeout=0.5)

            if response is None:
                continue

            if response.arbitration_id != RESPONSE_ID:
                continue

            log_print(response.arbitration_id, "RX", response.data)

            if len(response.data) > 3:
                # ── Positive Response ─────────────────────────────────────────
                if response.data[1] == 0x6E:
                    if response.data[2] == 0xF1 and response.data[3] == 0xF1:
                        print("Write EOL Mode Success")
                        return True, "PASSED"

                # ── Negative Response ─────────────────────────────────────────
                elif response.data[1] == 0x7F:
                    nrc = response.data[3]
                    if nrc == 0x78:
                        print("Response Pending")
                        start_time = time.time()
                        continue
                    else:
                        error_message = f"Negative Response Received - NRC: 0x{nrc:02X}"
                        print(error_message)
                        return False, error_message

                else:
                    error_message = f"Unexpected Response: {response.data}"
                    return False, error_message

        error_message = "No response from ECU"
        return False, error_message

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

        if OS == "Linux":
            os.system(f"sudo ip link set {channel} down")
            print(f"{channel} Down Complete")


if __name__ == "__main__":
    result = ABS_Write_EOL_Mode(
        interface = "pcan",
        channel   = "PCAN_USBBUS1",
        bitrate   = 500000
    )