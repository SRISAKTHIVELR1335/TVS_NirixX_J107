# -*- coding: utf-8 -*-
"""
Created on Tue Sep 2 15:34:08 2025
@author: Sri.Sakthivel
"""
import can
import time
from can import Message

#User Configuration
TESTER_ID = 0x7E1
ECU_RESPONSE_ID = 0x7E9
Flag = True


def log_message(direction, msg):
    formatted_data = ' '.join(f'{byte:02X}' for byte in msg.data)
    print(f"{direction} {msg.arbitration_id:04X}: {formatted_data}")


def _send_can_frame(bus, arbitration_id, data):
    padded_data = list(data)
    while len(padded_data) < 8:
        padded_data.append(0x00)
    msg = Message(arbitration_id=arbitration_id, data=bytearray(
        padded_data[:8]), is_fd=False, is_extended_id=False)
    log_message("TX", msg)
    bus.send(msg)


def _receive_single_can_frame(bus, response_id, timeout=0.5):
    start_time = time.time()
    while time.time() - start_time < timeout:
        msg = bus.recv(timeout=timeout - (time.time() - start_time))
        if msg and msg.arbitration_id == response_id:
            log_message("RX", msg)
            return msg
    return None


def receive_isotp_response(bus, response_id, timeout=5.0):
    start_time = time.time()
    full_response_data = []
    expect_consecutive_frames = False
    seq_number_expected = 1
    total_uds_length = 0
    while time.time() - start_time < timeout:
        msg = _receive_single_can_frame(bus, response_id, timeout=0.5)
        if not msg:
            continue
        pci_type = (msg.data[0] & 0xF0) >> 4
        if pci_type == 0x0:  # Single Frame
            uds_length = msg.data[0] & 0x0F
            full_response_data = list(msg.data[1:1 + uds_length])
            break
        elif pci_type == 0x1:  # First Frame
            total_uds_length = ((msg.data[0] & 0x0F) << 8) + msg.data[1]
            print(f"Total UDS length expected: {total_uds_length}")
            full_response_data = list(msg.data[2:])
            expect_consecutive_frames = True
            seq_number_expected = 1
            fc_frame = [0x30, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
            time.sleep(0.01)
            _send_can_frame(bus, TESTER_ID, fc_frame)
            time.sleep(0.01)
            continue
        elif expect_consecutive_frames and pci_type == 0x2:  # Consecutive Frame
            seq_number = msg.data[0] & 0x0F
            if seq_number != seq_number_expected:
                print(
                    f"ISO-TP Sequence mismatch. Expected: {seq_number_expected}, Got: {seq_number}")
                return None
            full_response_data.extend(msg.data[1:])
            seq_number_expected = (seq_number_expected + 1) % 16
            if len(full_response_data) >= total_uds_length:
                full_response_data = full_response_data[:total_uds_length]
                break
            continue
    if not full_response_data:
        return None
    return full_response_data


def send_isotp_request(bus, arbitration_id, data):
    total_len = len(data)
    if total_len <= 7:
        sf = [total_len] + data + [0x00] * (7 - total_len)
        _send_can_frame(bus, arbitration_id, sf)
        return True
    # Send First Frame
    ff_data = [0x10 | ((total_len >> 8) & 0x0F), total_len & 0xFF] + data[:6]
    _send_can_frame(bus, arbitration_id, ff_data)
    # Wait for Flow Control
    fc_msg = _receive_single_can_frame(bus, ECU_RESPONSE_ID, timeout=1.0)
    if not fc_msg:
        print("No flow control received.")
        return False
    pci_type = (fc_msg.data[0] & 0xF0) >> 4
    if pci_type != 0x3:
        print("Invalid flow control frame.")
        return False
    flow_status = fc_msg.data[0] & 0x0F
    st_min = fc_msg.data[2]
    if st_min <= 127:
        st_min_sec = st_min * 0.05
    elif 0xF1 <= st_min <= 0xF9:
        st_min_sec = (st_min - 0xF0) * 0.05
    else:
        print("Reserved st_min value, using default 0.001")
        st_min_sec = 0.001
    if flow_status != 0:  # Not Clear to Send
        print(f"Flow control status not CTS: {flow_status}")
        return False
    # Send Consecutive Frames
    remaining_data = data[6:]
    seq = 1
    while remaining_data:
        time.sleep(st_min_sec)
        cf_pci = 0x20 | (seq % 16)
        cf_data_len = min(7, len(remaining_data))
        cf_data = [cf_pci] + remaining_data[:cf_data_len]
        _send_can_frame(bus, arbitration_id, cf_data)
        remaining_data = remaining_data[cf_data_len:]
        seq += 1
    return True


def send_uds_request(bus, sid, sub_payload, expected_positive_sid):
    uds_payload = [sid] + sub_payload
    max_retries = 1
    retry_delay = 5.0 # Wait 5 seconds for NRC 0x78
    # Send the request once per attempt cycle
    if len(uds_payload) <= 7:
        isotp_sf_data = [len(uds_payload)] + uds_payload
        _send_can_frame(bus, TESTER_ID, isotp_sf_data)
    else:
        if not send_isotp_request(bus, TESTER_ID, uds_payload):
            print("Failed to send ISO-TP request.")
            return None
    # Retry loop for receiving response
    for attempt in range(max_retries):
        response = receive_isotp_response(bus, ECU_RESPONSE_ID, timeout=5.0)
        if response and response[0] == 0x7F:
            if len(response) >= 3 and response[2] == 0x78:
                time.sleep(retry_delay)
                continue
            if len(response) >= 3:
                print(f"Negative Response: NRC 0x{response[2]:02X}")
            return None
        if response and response[0] == expected_positive_sid:
            return response
        #print(f"Attempt {attempt + 1}: No valid response received.")
        if attempt < max_retries - 1:
            # Resend the request only if we need to retry
            if len(uds_payload) <= 7:
                _send_can_frame(bus, TESTER_ID, isotp_sf_data)
            else:
                if not send_isotp_request(bus, TESTER_ID, uds_payload):
                    print(f"Attempt {attempt + 1}: Failed to resend ISO-TP request.")
                    return None
            time.sleep(retry_delay)
    #print(f"Failed after {max_retries} attempts.")
    return None


def calculate_key(seed_hb, seed_lb):
    genkey = (seed_hb << 8) | seed_lb
    key = (((genkey + 0xAEFB) - 0x1111) << 4) + 0x00A0
    key = key & 0xFFFF
    return (key >> 8, key & 0xFF)


def request_seed(bus):
    response = send_uds_request(bus, 0x27, [0x01], 0x67)
    if response and len(response) >= 4 and response[1] == 0x01:
        seed_hb, seed_lb = response[2], response[3]
        print(f"Raw Seed Received: HB={seed_hb:02X}, LB={seed_lb:02X}")
        return seed_hb, seed_lb
    print("Seed Request Failed.")
    return None


def send_key(bus, key_hb, key_lb):
    response = send_uds_request(bus, 0x27, [0x02, key_hb, key_lb], 0x67)
    if response and len(response) >= 2 and response[1] == 0x02:
        print("Security Access Passed.\n")
        return True
    print("Security Access Failed.")
    return False

def ABS_Security_Access(interface, channel, bitrate):
    bus = None
    try:
        try:
            bus = can.interface.Bus(
                interface=interface,
                channel=channel,
                bitrate=bitrate
            )
        except can.CanInitializationError:
            error_message = "ERROR: PCAN is not connected or not initialized."
            return False, error_message

        bus.set_filters([{"can_id": ECU_RESPONSE_ID, "can_mask": 0x7FF}])
       
        seed = request_seed(bus)
        if not seed:
            error_message = "Failed to retrieve seed from ECU."
            return False, error_message
        
        seed_hb, seed_lb = seed
        key_hb, key_lb = calculate_key(seed_hb, seed_lb)
        print(f"Key:HB={key_hb:02X},LB={key_lb:02X}")
       
        if not send_key(bus, key_hb, key_lb):
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
        return False, error_message
    
    except Exception as e:
        error_message = f"Unexpected Error: {e}"
        print(error_message)
        return False, error_message
    finally:
        if bus:
            bus.shutdown()
            print("CAN bus shutdown completed")
            
if __name__ == "__main__":
    ABS_Security_Access(interface="pcan",channel="PCAN_USBBUS1",bitrate=500000)