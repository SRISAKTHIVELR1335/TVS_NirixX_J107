# security_manager.py

import base64
import hashlib
from pathlib import Path

from Crypto.Cipher import AES

import io
import pandas as pd
import configparser


# IMPORTANT:
# We will improve how this key is stored later.
# Do NOT use your real production key while testing.
MASTER_PASSWORD = "NirixX@CT&T#2026"


def _derive_key(password: str) -> bytes:
    """
    Convert the password into a 32-byte AES-256 key.
    """
    return hashlib.sha256(
        password.encode("utf-8")
    ).digest()


def encrypt_bytes(data: bytes, password: str) -> bytes:
    """
    Encrypt bytes using AES-256-GCM.

    Output format:
        nonce + tag + ciphertext
    """

    key = _derive_key(password)

    cipher = AES.new(
        key,
        AES.MODE_GCM
    )

    ciphertext, tag = cipher.encrypt_and_digest(data)

    return (
        cipher.nonce +
        tag +
        ciphertext
    )


def decrypt_bytes(encrypted_data: bytes, password: str) -> bytes:
    """
    Decrypt AES-256-GCM data.
    """

    key = _derive_key(password)

    nonce = encrypted_data[:16]
    tag = encrypted_data[16:32]
    ciphertext = encrypted_data[32:]

    cipher = AES.new(
        key,
        AES.MODE_GCM,
        nonce=nonce
    )

    return cipher.decrypt_and_verify(
        ciphertext,
        tag
    )


def encrypt_file(
    input_path: str,
    output_path: str,
    password: str
):
    """
    Encrypt an entire file.
    """

    with open(input_path, "rb") as f:
        data = f.read()

    encrypted = encrypt_bytes(
        data,
        password
    )

    with open(output_path, "wb") as f:
        f.write(encrypted)


def decrypt_file(
    input_path: str,
    password: str
) -> bytes:
    """
    Decrypt an encrypted file and return bytes.
    """

    with open(input_path, "rb") as f:
        encrypted_data = f.read()

    return decrypt_bytes(
        encrypted_data,
        password
    )


def read_encrypted_excel(
    file_path: str,
    password: str
):
    """
    Decrypt Excel in memory and return pandas DataFrame.
    """

    encrypted_data = decrypt_file(
        file_path,
        password
    )

    excel_buffer = io.BytesIO(
        encrypted_data
    )

    return pd.read_excel(
        excel_buffer,
        engine="openpyxl"
    )


def read_encrypted_ini(
    file_path: str,
    password: str
):
    """
    Decrypt INI in memory and return ConfigParser.
    """

    encrypted_data = decrypt_file(
        file_path,
        password
    )

    text = encrypted_data.decode(
        "utf-8"
    )

    config = configparser.ConfigParser()

    config.read_string(text)

    return config

def load_encrypted_workbook(
    file_path,
    password
):

    import io
    from openpyxl import load_workbook

    encrypted_data = decrypt_file(
        file_path,
        password
    )

    excel_buffer = io.BytesIO(
        encrypted_data
    )

    return load_workbook(
        excel_buffer
    )


def write_encrypted_ini(
    config,
    file_path: str,
    password: str
):
    """
    Write a ConfigParser object to an encrypted INI file.
    """

    import io

    # Convert ConfigParser to INI text in memory
    string_buffer = io.StringIO()

    config.write(string_buffer)

    ini_text = string_buffer.getvalue()

    # Convert text to bytes
    ini_bytes = ini_text.encode("utf-8")

    # Encrypt
    encrypted_data = encrypt_bytes(
        ini_bytes,
        password
    )

    # Write encrypted data
    with open(file_path, "wb") as f:
        f.write(encrypted_data)