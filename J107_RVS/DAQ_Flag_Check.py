# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

# -*- coding: utf-8 -*-
"""

"""

import requests


def DAQ_Flag_Check(vin_number):
    BASE_URL = "http://10.121.2.107:3000/vehicles/flashFile"
    url = f"{BASE_URL}/{vin_number}/0010/CZ14001"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print(f"DAQ Check Failed - HTTP {response.status_code}")
            return False, "HTTP Error"

        result = response.json().get("data", {}).get("result")

        if result == "OK":
            print("DAQ Passed")
            return True, "OK"

        elif result == "NOK":
            print("DAQ Failed")
            return False, "NOK"

        elif result == "Null" or result is None:
            print("DAQ Result is Null")
            return False, "Null"

        else:
            print(f"Unexpected Result: {result}")
            return False, result

    except Exception as e:
        print(f"API Error: {e}")
        return False, "API Error"


if __name__ == "__main__":
    status, message = DAQ_Flag_Check(
        vin_number="MD626AM47S1C00070"
    )
    print(f"Status: {status}, Message: {message}")
