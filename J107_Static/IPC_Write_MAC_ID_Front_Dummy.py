# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import can
import time
import os
import platform

REQUEST_ID  = 0x7C9
RESPONSE_ID = 0x7C1

log_counter = 1


def log_print(arb_id, direction, data):
    global log_counter
    timestamp = time.time() * 1000
    data_str = ' '.join(f"{b:02X}" for b in data)
    print(
        f"{log_counter:>3}  {timestamp:.3f} DT "
        f"{arb_id:04X} {direction} 8  {data_str}"
    )
    log_counter += 1


def send_frame(bus, arb_id, data):
    padded = list(data) + [0x00] * (8 - len(data))
    msg = can.Message(
        arbitration_id=arb_id,
        data=bytearray(padded[:8]),
        is_extended_id=False
    )
    bus.send(msg)
    log_print(msg.arbitration_id, "TX", msg.data)


def send_isotp(bus, arb_id, payload, timeout=2.0):
    length = len(payload)

    if length <= 7:
        frame = [length] + payload
        send_frame(bus, arb_id, frame)
        return True

    ff = [0x10 | ((length >> 8) & 0x0F), length & 0xFF] + payload[:6]
    send_frame(bus, arb_id, ff)

    fc_start = time.time()
    while time.time() - fc_start < timeout:
        msg = bus.recv(timeout=timeout)
        if not msg or msg.arbitration_id != RESPONSE_ID:
            continue

        log_print(msg.arbitration_id, "RX", msg.data)

        pci_type    = (msg.data[0] & 0xF0) >> 4
        flow_status =  msg.data[0] & 0x0F

        if pci_type != 0x3:
            continue

        if flow_status == 0x0:
            block_size      = msg.data[1]
            st_min_raw      = msg.data[2]
            separation_time = st_min_raw / 1000.0 if st_min_raw <= 0x7F else 0.0
            break

        elif flow_status == 0x1:        # Wait
            print("Flow Control: WAIT")
            continue

        elif flow_status == 0x2:
            print("Flow Control: OVERFLOW")
            return False
    else:
        print("Flow Control Timeout")
        return False

    remaining     = payload[6:]
    seq_num       = 1
    block_counter = 0

    while remaining:
        chunk     = remaining[:7]
        remaining = remaining[7:]

        cf = [0x20 | (seq_num & 0x0F)] + chunk
        send_frame(bus, arb_id, cf)

        seq_num       = (seq_num + 1) % 16
        block_counter += 1

        if block_size != 0 and block_counter >= block_size:
            block_counter = 0
            fc_msg = bus.recv(timeout=timeout)
            if not fc_msg:
                print("Flow Control Timeout During Transfer")
                return False
            log_print(fc_msg.arbitration_id, "RX", fc_msg.data)

        time.sleep(separation_time)

    return True


def receive_isotp(bus, response_id, timeout=5.0):
    start_time        = time.time()
    full_data         = []
    total_length      = 0
    expected_sequence = 1

    while time.time() - start_time < timeout:
        msg = bus.recv(timeout=0.5)

        if not msg or msg.arbitration_id != response_id:
            continue

        log_print(msg.arbitration_id, "RX", msg.data)

        pci_type = (msg.data[0] & 0xF0) >> 4

        if pci_type == 0x0:
            uds_len   = msg.data[0] & 0x0F
            full_data = list(msg.data[1: 1 + uds_len])
            return full_data

        elif pci_type == 0x1:
            total_length = ((msg.data[0] & 0x0F) << 8) | msg.data[1]
            full_data    = list(msg.data[2:])
            print(f"\nMulti-frame Response | Total Length: {total_length} bytes")

            # Send Flow Control
            fc = [0x30, 0x00, 0x00]
            send_frame(bus, REQUEST_ID, fc)

        elif pci_type == 0x2:
            seq_num = msg.data[0] & 0x0F

            if seq_num != expected_sequence:
                error_message = (
                    f"Sequence Error "
                    f"(Expected={expected_sequence}, Got={seq_num})"
                )
                return False, error_message

            full_data.extend(msg.data[1:])
            expected_sequence = (expected_sequence + 1) % 16

            if len(full_data) >= total_length:
                return full_data[:total_length]

    print("ISO-TP Response Timeout")
    return None


def IPC_Write_MAC_ID_Front_Dummy(interface, channel, bitrate):

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

        try:
            bus = can.interface.Bus(interface=interface, channel=channel, bitrate=bitrate)
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            print(error_message)
            return error_message
        bus.set_filters([{"can_id": RESPONSE_ID, "can_mask": 0x7FF, "extended": False}])

        uds_payload = [0x2E, 0xF1, 0x32, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]

        print(f"Payload ({len(uds_payload)} bytes): "
              f"{' '.join(f'{b:02X}' for b in uds_payload)}\n")

        if not send_isotp(bus, REQUEST_ID, uds_payload):
            return False, "Failed to send ISO-TP request"

        timeout    = 5
        start_time = time.time()

        while time.time() - start_time < timeout:
            response = receive_isotp(bus, RESPONSE_ID, timeout=2.0)

            if response is None:
                return False, "No response from ECU"

            if response[0] == 0x6E:
                if response[1] == 0xF1 and response[2] == 0x32 and response[3] == 0x10:
                    print("\nMAC ID Write For Front Success")
                    return True
                else:
                    return False, "Unexpected DID in response"

            elif response[0] == 0x7F:
                if len(response) >= 3:
                    nrc = response[2]
                    if nrc == 0x78:
                        print("Response Pending (NRC 0x78), waiting...")
                        start_time = time.time()
                        continue
                    error_message = f"Negative Response | NRC: 0x{nrc:02X}"
                return False, error_message

            else:
                error_message = f"Unexpected Response SID: 0x{response[0]:02X}"
                return False, error_message

        error_message = "Response Timeout / No response from ECU"
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
    result = IPC_Write_MAC_ID_Front_Dummy(
        interface = "pcan",
        channel   = "PCAN_USBBUS1",
        bitrate   = 500000
    )
