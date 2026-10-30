from pathlib import Path

from security_manager import encrypt_file


PASSWORD = "NirixX@CT&T#2026"

BASE_DIR = Path(__file__).resolve().parent


FILES = [
    "station.ini",
    "api.ini",
    "scanner.ini",
    "SKU_File_Mapping.xlsx",
    "sku_files/Raider_Bosch_Flashing_and_Static.xlsx",
    "sku_files/Raider_Sedemac_Flashing_and_Static.xlsx",
    "sku_files/Raider_Keihin_Flashing_and_Static.xlsx",
]


for relative_path in FILES:

    source = BASE_DIR / relative_path
    output = Path(str(source) + ".enc")

    if not source.exists():
        print(f"❌ File not found: {source}")
        continue

    encrypt_file(
        str(source),
        str(output),
        PASSWORD
    )

    print(f"✅ Encrypted: {relative_path}")