# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

# -*- coding: utf-8 -*-
"""

"""

import requests


def Static_Flag_Check(vin_number):
    url = f"http://10.121.2.107:3000/vehicles/flashFile/{vin_number}/0020/CZ14002"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            print(f"Static Check Failed - HTTP {response.status_code}")
            return False, "HTTP Error"

        result = response.json().get("data", {}).get("result")

        if result == "OK":
            print("Static Passed")
            return True, "OK"

        elif result == "NOK":
            print("Static Failed")
            return False, "NOK"

        elif result == "Null" or result is None:
            print("Static Result is Null")
            return False, "Null"

        else:
            print(f"Unexpected Result: {result}")
            return False, result

    except Exception as e:
        print(f"API Error: {e}")
        return False, "API Error"


if __name__ == "__main__":
    status, message = Static_Flag_Check(
        vin_number="MD626AM47S1C00070"
    )
    print(f"Status: {status}, Message: {message}")
