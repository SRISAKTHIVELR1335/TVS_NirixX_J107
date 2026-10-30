# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import can
import time

REQUEST_ID  = 0x7C9
RESPONSE_ID = 0x7C1

log_counter = 1

def log_print(arb_id, direction, data):
    global log_counter

    timestamp = time.time() * 1000  # milliseconds
    data_str = ' '.join(f"{b:02X}" for b in data)

    print(
        f"{log_counter:>3}  "
        f"{timestamp:.3f} DT "
        f"{arb_id:04X} {direction} 8  {data_str}"
    )

    log_counter += 1


def IPC_Extended_Session(interface, channel, bitrate):
    bus = None
    try:
        bus = can.interface.Bus(interface=interface,channel=channel,bitrate=bitrate)
        bus.set_filters([{"can_id": RESPONSE_ID,"can_mask": 0x7FF,"extended": False}])

        data = [0x02,0x10,0x03,0x00,0x00,0x00,0x00,0x00]
        msg = can.Message(arbitration_id=REQUEST_ID,data=data,is_extended_id=False)

        bus.send(msg)
        log_print(msg.arbitration_id, "Tx", msg.data)

        timeout = 3.0
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            remaining_time = timeout - (time.time() - start_time)

            if remaining_time <= 0:
                break

            response = bus.recv(timeout=min(0.5, remaining_time))
            if response is None:
                continue

            if response.arbitration_id != RESPONSE_ID:
                continue

            log_print(response.arbitration_id,"Rx",response.data)

            # Need at least 3 bytes
            if len(response.data) < 3:
                print("Invalid response length")
                continue

            if response.data[1] == 0x50:

                if response.data[2] == 0x03:
                    print("Extended Session Activated")
                    return True, "PASSED"

                else:
                    error_message = "Unexpected Positive Response: "
                    return False, error_message

            elif response.data[1] == 0x7F:

                if len(response.data) < 4:
                    print("Invalid Negative Response")
                    continue

                nrc = response.data[3]
                if nrc == 0x78:
                    print("NRC 0x78 - Response Pending.Continuing to wait...")
                    continue

                else:
                    error_message=f"Negative Response Received - NRC: 0x{nrc:02X}"
                    return False, error_message

            else:
                error_message = "Unexpected Response Received"
                return False, error_message

        error_message = "ERROR: Extended Session Timeout waiting for response " "from IPC"
        print(error_message)
        return False, error_message

    except can.CanError as e:
        error_message = f"CAN Error: {e}"
        print(error_message)
        return False, error_message

    finally:
        if bus is not None:
            bus.shutdown()



if __name__ == "__main__":

    result = IPC_Extended_Session(
        interface="pcan",
        channel="PCAN_USBBUS1",
        bitrate=500000
    )
