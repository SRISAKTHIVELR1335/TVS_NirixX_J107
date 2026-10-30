# -*- coding: utf-8 -*-
"""
Created on 2026-08-19 11:51:25

@author: Sri.Sakthivel

"""

import requests


def Flashing_Flag_Check(vin_number):
    BASE_URL = "http://10.121.2.107:3000/vehicles/flashFile"

    # Flashing station URL only
    url = f"{BASE_URL}/{vin_number}/0010/CZ14001"

    try:
        response = requests.get(url, timeout=5)

        if response.status_code != 200:
            error_message = f"HTTP Error: {response.status_code}"
            return False, error_message

        data = response.json().get("data", {})
        result = data.get("result")

        if result == "OK":
            print("Flashing Passed")
            return True, "OK"

        elif result == "NOK":
            error_message = "Flashing Result is NOK"
            return False, error_message

        elif result == "Null" or result is None:
            error_message = "Flashing Result is Null"
            return False, error_message

        else:
            error_message = f"Unexpected Result: {result}"
            return False, error_message

    except requests.exceptions.RequestException as e:
        error_message = f"API Request Failed: {e}"
        return False, error_message


if __name__ == "__main__":
    status, message = Flashing_Flag_Check(
        vin_number="MD625AF98T1G09224"
    )
    print(f"Status: {status}, Message: {message}")
