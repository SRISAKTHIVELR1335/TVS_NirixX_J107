# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel

"""

import can
import time
import os
import platform


REQUEST_ID = 0x7C9
RESPONSE_ID = 0x7C1

log_counter = 1


def log_print(arbitration_id, direction, data):
    global log_counter
    time_stamp = time.time() * 1000
    data_str = " ".join(f"{b:02X}" for b in data)
    print(
        f"{log_counter:>3}  "
        f"{time_stamp:.3f} DT "
        f"{arbitration_id:04X} "
        f"{direction} 8  {data_str}"
    )
    log_counter += 1


def send_data(bus,data):
    msg = can.Message(arbitration_id=REQUEST_ID, data=data, is_extended_id=False)
    bus.send(msg)
    log_print(msg.arbitration_id, "TX", msg.data)

def receive_data(bus):
    res = bus.recv(timeout=0.5)
    if res:
        log_print(res.arbitration_id, "RX", res.data)
        return res

    print("No response received")
    return False

def IPC_Read_Test_Stamp(interface,channel,bitrate):
    bus = None
    OS = platform.system()
    try:
        if OS == "Linux":
            interface="socketcan"
            channel="can0"

            os.system(f"sudo ip link set {channel} down")
            os.system(f"sudo ip link set {channel} type can bitrate {bitrate}")
            os.system(f"sudo ip link set {channel} up")

        elif OS.upper() == "WINDOWS":
            pass

        try:
            bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate)
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            print(error_message)
            return False, error_message
        
        bus.set_filters([{"can_id":RESPONSE_ID, "can_mask":0x7FF, "extended":False}])

        data = [0x03, 0x22, 0x10, 0xFF, 0x00, 0x00, 0x00, 0x00]
        send_data(bus,data)

        data_bytes = []

        timeOut = 5
        start_time = time.time()
        while time.time() - start_time < timeOut:
            response = receive_data(bus)

            if not response:
                continue
            if response.arbitration_id != RESPONSE_ID:
                continue

            data = list(response.data)

            pci = data[0]
            frame_type = (pci & 0xF0) >> 4

            if frame_type == 0x0 and data[1] == 0x62:
                payload_length = (data[0] & 0x0F) - 3
                data_bytes.extend(data[4:4 + payload_length])
                break

            elif len(data) >= 4 and data[1] == 0x7F:
                nrc = data[3]

                if nrc == 0x78:
                    print("Response Pending...")
                    session_start = time.time()
                    continue
                else:
                    error_message = f"Negative Response NRC: 0x{nrc:02X}"
                    return False, error_message
            
        
        if not data_bytes:
            error_message = "Timeout / No response from ECU"
            return False, error_message
        
        #raw = int.from_bytes(data_bytes[:2], byteorder="big")
        raw = "".join(f"{b:02X}" for b in data_bytes[:2])
        phys = raw 
        print(f"Phys value: {phys}")

        if phys:
            return True, phys
        else:
            error_message = "No valid data received from ECU"
            return False, error_message
    
    except can.CanError as error:
        error_msg = str(error).lower()
        if "not been initialized" in error_msg:
            error_message = "ERROR: PCAN is not connected or not initialized."

        elif "heavy" in error_msg or "warning" in error_msg:
            error_message = (
                "ERROR: No communication from ECU.\n"
                "Check ECU power, CAN wiring and baud rate."
            )
        else:
            error_message = f"CAN Error: {error}"

        print(error_message)
        return False, error_message

    except Exception as error:
        error_message = f"Unexpected Error: {error}"
        print(error_message)
        return False, error_message

    finally:
        if bus:
            bus.shutdown()
            
            if OS == "Linux":
                os.system(f"sudo ip link set {channel} down")
                print(f"{channel} Down Complete")

if __name__ == "__main__":

    result = IPC_Read_Test_Stamp(interface="pcan", channel="PCAN_USBBUS1", bitrate=500000)

    print("Status:",result)

                

