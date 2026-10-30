import sys
import requests
import urllib3

# Suppress SSL warnings (for testing only)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# -------------------------------
# CONFIG
# -------------------------------

POST_TOKEN_URL = "https://api.move.tatacommunications.com/api-connect/token"
GET_STATUS_URL = "https://api.move.tatacommunications.com/moveiotapi/v8/subscriptions/search"

OCP_APIM_SUBSCRIPTION_KEY = "86266ca207ce461baa9dd5d08f25f64f"
CLIENT_ID = "d655dce2-5f9b-41b6-8c69-1a47f32220fa"
CLIENT_SECRET = "RKS8Q~-LeEuafKbM3Kkr~m1qEzOOjeQa0Rlu-bRE"
SCOPE = "api://e0acacc3-8bb3-4baf-8a52-64b1bf7bd4c2/.default"

# -----------------------------------------------
# InitiatorID is REQUIRED by the API — must not be null
# -----------------------------------------------
INITIATOR_ID = "550e8400-e29b-41d4-a716-446655440000"

# Set to True in production once SSL is resolved
VERIFY_SSL = False


# -------------------------------
# STEP 1: GET ACCESS TOKEN
# -------------------------------

def get_access_token():
    headers = {
        "Content-Type"             : "application/x-www-form-urlencoded",
        "Ocp-Apim-Subscription-Key": OCP_APIM_SUBSCRIPTION_KEY,
    }

    payload = {
        "grant_type"   : "client_credentials",
        "client_id"    : CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope"        : SCOPE,
    }

    try:
        response = requests.post(
            POST_TOKEN_URL,
            headers=headers,
            data=payload,
            verify=VERIFY_SSL,
            timeout=30
        )

        print(f"Token Status Code : {response.status_code}")
        print(f"Token Response    : {response.text[:300]}")

        response.raise_for_status()

        token_data   = response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            raise ValueError("Access token not found in response")

        return access_token

    except requests.exceptions.SSLError as e:
        print(f"SSL Error during token request         : {e}")
        return None

    except requests.exceptions.ConnectionError as e:
        print(f"Connection Error during token request  : {e}")
        return None

    except requests.exceptions.Timeout:
        print("Token request timed out")
        return None

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error during token request        : {e}")
        print(f"Response Body                          : {response.text}")
        return None

    except Exception as e:
        print(f"Unexpected error during token request  : {e}")
        return None


# -------------------------------
# STEP 2: CHECK ICCID STATUS
# -------------------------------

def check_iccid_status(access_token, iccid):

    headers = {"Content-Type"             : "application/json",
        "Accept"                   : "application/json",
        "Ocp-Apim-Subscription-Key": OCP_APIM_SUBSCRIPTION_KEY,
        "Authorization"            : f"Bearer {access_token}",
        "InitiatorID"              : INITIATOR_ID,}

    params = {"iccid": iccid}

    try:
        response = requests.get(
            GET_STATUS_URL,
            headers=headers,
            params=params,
            verify=VERIFY_SSL,
            timeout=30
        )

        print(f"ICCID Status Code : {response.status_code}")
        print(f"ICCID Response    : {response.text[:500]}")

        response.raise_for_status()

        data   = response.json()
        status = data.get("status", "").strip()

        print(f"  ICCID          : {data.get('iccid',          'N/A')}")
        print(f"  Status         : {status}")
        print(f"  MSISDN         : {data.get('msisdns',        'N/A')}")
        print(f"  Activation Date: {data.get('activationDate', 'N/A')}")

        status_lower = status.lower()

        if status_lower == "active":
            print("SIM is ACTIVE")
            return True, "Active"

        elif status_lower == "suspended":
            print("SIM is SUSPENDED")
            return True, "Suspended"

        elif status_lower == "preactive":
            print("SIM is in PreActive")
            return False, "PreActive"

        else:
            print(f"Unknown or missing status: '{status}'")
            return False, "Unknown"

    except requests.exceptions.SSLError as e:
        print(f"SSL Error during ICCID check           : {e}")
        return False, "SSL Error"

    except requests.exceptions.ConnectionError as e:
        print(f"[Connection Error during ICCID check    : {e}")
        return False, "Connection Error"

    except requests.exceptions.Timeout:
        print("ICCID check request timed out")
        return False, "Timeout"

    except requests.exceptions.HTTPError as e:
        print(f"HTTP Error during ICCID check          : {e}")
        print(f"Response Body                          : {response.text}")
        return False, "HTTP Error"

    except Exception as e:
        print(f"Unexpected error during ICCID check    : {e}")
        return False, "API Error"


# -------------------------------
# STEP 3: MAIN ENTRY POINT
# -------------------------------

def ICCID1_Status_Check(iccid):
    if not iccid:
        print("No ICCID provided")
        return False, "Invalid ICCID"

    # Extract digits only
    digits_only = "".join(ch for ch in str(iccid).strip() if ch.isdigit())

    if len(digits_only) < 8:
        print("ICCID must contain at least 8 digits")
        return False, "Invalid ICCID"

    # Trim to standard 18-digit ICCID
    clean_iccid = digits_only[:18]

    print(f"Using ICCID : {clean_iccid}")

    # Get Access Token
    token = get_access_token()

    if not token:
        print("Could not retrieve access token")
        return False, "Token Error"

    print("Access token retrieved successfully")

    # Check ICCID Status
    return check_iccid_status(token, clean_iccid)


# -------------------------------
# MAIN — EXE Entry Point
# -------------------------------

if __name__ == "__main__":
    if len(sys.argv) > 1:
        iccid_input = sys.argv[1]
    else:
        iccid_input = input("Enter ICCID : ").strip()

    if not iccid_input:
        print("No ICCID provided. Exiting.")
        sys.exit(1)

    # Run the check
    result_flag, result_message = ICCID1_Status_Check(iccid_input)