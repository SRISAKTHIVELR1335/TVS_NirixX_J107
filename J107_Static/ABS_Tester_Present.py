# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import can
import os
import time
import platform
from can import Message

TESTER_ID       = 0x7E1
ECU_RESPONSE_ID = 0x7E9

log_counter = 1

def log_print(arb_id, direction, data):

    global log_counter

    timestamp = time.time() * 1000
    data_str  = ' '.join(f"{b:02X}" for b in data)

    print(
        f"{log_counter:03}  "
        f"{timestamp:.3f}  "
        f"{arb_id:03X}  "
        f"{direction}  "
        f"{len(data):1}  "
        f"{data_str}"
    )

    log_counter += 1

def send_can_frame(bus, arbitration_id, data):

    tx_data = list(data)

    while len(tx_data) < 8:
        tx_data.append(0x00)

    msg = Message(arbitration_id = arbitration_id, data= bytearray(tx_data[:8]), is_extended_id = False, is_fd= False)
    log_print(arbitration_id, "Tx", msg.data)
    bus.send(msg)


def ABS_Tester_Present(interface, channel, bitrate):

    bus = None
    OS  = platform.system()

    try:
        if OS == "Linux":
            interface = "socketcan"
            channel   = "can0"

            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")

        elif OS.upper() == "WINDOWS":
            pass

        bus = can.interface.Bus(interface = interface,channel   = channel,bitrate   = bitrate)
        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])
        session_start  = time.time()
        last_send_time = None
        send_count     = 0

        while time.time() - session_start < 2.0:

            current_time = time.time()
            if last_send_time is None or (current_time - last_send_time) >= 0.1:

                send_count += 1
                print(f"\nSending Tester Present (Attempt {send_count})")

                send_can_frame(bus, TESTER_ID, [0x02, 0x3E, 0x00])
                last_send_time = time.time()

            # --------------------------------------------------------
            # Check for Response
            # --------------------------------------------------------
            response = bus.recv(timeout=0.02)

            if response is None:
                continue

            if response.arbitration_id != ECU_RESPONSE_ID:
                continue

            log_print(response.arbitration_id, "Rx", response.data)

            data = response.data

            if len(data) < 2:
                continue

            if data[1] == 0x7E:

                if len(data) >= 3 and data[2] == 0x00:
                    print("Tester Present : PASSED")
                    return True, "PASSED"
                
            elif data[1] == 0x7F:

                if len(data) >= 4:
                    nrc = data[3]

                    if nrc == 0x78:
                        print("Response Pending (0x78) - Continuing...")
                        continue

                    else:
                        error_message = f"Negative Response Received - NRC: 0x{nrc:02X}"
                        print(error_message)
                        return False, error_message

            else:
                error_message = "ERROR: Unexpected Response Received"
                print(error_message)
                return False, error_message

        print("\nTester Present : FAILED")
        print(f"Total Sends    : {send_count}")
        print(f"No positive response received within {2.0} seconds")

        error_message = "ERROR: Tester Present failed: no positive response received."
        print(error_message)
        return False, error_message

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, error_message

    except Exception as e:
        error_message = f"ERROR: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            print("CAN Bus Shutdown Complete")

            if platform.system() == "Linux":
                os.system(f"sudo ip link set {channel} down")
                print(f"{channel} Down Complete")

if __name__ == "__main__":

    result = ABS_Tester_Present(
        interface = "pcan",
        channel   = "PCAN_USBBUS1",
        bitrate   = 500000,
    )
