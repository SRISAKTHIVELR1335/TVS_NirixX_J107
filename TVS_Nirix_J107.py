# -*- coding: utf-8 -*-
"""
Created on Wed Nov  5 22:07:41 2025

@author: Sri.Sakthivel

"""

import subprocess
import io
import sys
import os
import configparser
import socket
import threading
import time
import shutil
import requests
from PyQt5.QtWidgets import (
    QApplication, QAbstractItemView, QTextEdit, QWidget, QLabel, QHBoxLayout, QVBoxLayout, 
    QProgressBar, QFrame, QLineEdit, QComboBox, QPushButton, QButtonGroup, QSizePolicy, 
    QScrollArea, QTableWidget, QTableWidgetItem, QHeaderView, QDialog, QMessageBox
)
from PyQt5.QtGui import QFont, QColor, QPalette, QIntValidator,  QPixmap, QPainter, QLinearGradient, QIcon
from PyQt5.QtCore import Qt, QEvent, QTimer, QObject, pyqtSignal, QThread, QMetaObject
import serial.tools.list_ports
import importlib
import xml.etree.ElementTree as ET
import importlib.util
import pandas as pd
from datetime import datetime
import json
import serial
import usb.core
import usb.util
from contextlib import redirect_stdout, redirect_stderr
            
class FlashProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flashing in Progress")
        self.setModal(True)
        self.setFixedSize(700, 450)

        # Background
        self.setStyleSheet("background-color: #F0F0F0;")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # Header label
        self.header_label = QLabel("ECU Flashing", self)
        header_font = QFont("Segoe UI", 18, QFont.Bold)
        self.header_label.setFont(header_font)
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet("color: #003B6F;")
        self.main_layout.addWidget(self.header_label)

        # Scroll area (kept for visual consistency)
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFixedHeight(260)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(
            "background-color: #D3D3D3; border-radius: 8px;"
        )
        self.main_layout.addWidget(self.scroll_area)

        # Container inside scroll
        container = QWidget()
        self.scroll_area.setWidget(container)

        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(15, 15, 15, 15)
        container_layout.setSpacing(18)

        # Single progress bar row
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(20)

        self.progress_label = QLabel("Flashing :", self)
        label_font = QFont("Segoe UI", 14, QFont.Bold)
        self.progress_label.setFont(label_font)
        self.progress_label.setFixedWidth(140)
        self.progress_label.setStyleSheet("color: #003B6F;")

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(28)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid #003B6F;
                border-radius: 10px;
                background-color: #F0F0F0;
                text-align: center;
                font-size: 14px;
                font-weight: bold;
                color: #003B6F;
            }
            QProgressBar::chunk {
                background-color: #008000;
                border-radius: 10px;
            }
        """)

        row_layout.addWidget(self.progress_label)
        row_layout.addWidget(self.progress_bar)

        container_layout.addWidget(row_widget)
        container_layout.addStretch()

        # Cancel button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setFixedSize(120, 40)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF0033;
                color: white;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #e60029;
            }
            QPushButton:pressed {
                background-color: #b20020;
            }
        """)
        btn_layout.addWidget(self.cancel_btn)

        self.main_layout.addLayout(btn_layout)

    # Called from TestWorker via signal
    def update_progress(self, percent, phase=""):
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"Flashing : {percent}%")
        if phase:
            self.header_label.setText(phase)
        
def load_sentinel_return_codes(excel_path=r"D:\TVS NIRIX Flashing\Sentinel\sentinel_return_codes.xlsx.enc"):
    excel_path = resource_path(
        os.path.join("Sentinel", "sentinel_return_codes.xlsx.enc")
    )

    df = pd.read_excel(excel_path)
    return {
        int(row["ExitCode"]): str(row["Message"])
        for _, row in df.iterrows()
    }

DEFAULT_POPUP_ICON = "⚠️"


class TestWorker(QObject):
    result_ready = pyqtSignal(object, float, str)
    error_occurred = pyqtSignal(Exception, float, str)
    log_message = pyqtSignal(str)
    popup_request = pyqtSignal(str, int, str)
    popup_request_delayed = pyqtSignal(str, int, int, str)

    flash_progress = pyqtSignal(int, str)   # NEW

    def __init__(self, library_name, function_name, vin_number, api_url,
                 log_callback, interface, channel, bitrate,
                 front_mac=None, rear_mac=None,
                 flash_file=None, dll_file=None, exe_path=None,
                 sentinel_code_map=None,log_folder = None):
        super().__init__()
        self.library_name = library_name
        self.function_name = function_name
        self.vin_number = vin_number
        self.api_url = api_url
        self.log_callback = log_callback
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self.tpms_fr = front_mac
        self.tpms_rr = rear_mac
        self.flash_file = flash_file
        self.dll_file = dll_file
        self.exe_path = exe_path
        self.sentinel_code_map = sentinel_code_map or {}
        self.stop_requested = False
        self.log_folder = log_folder

    def request_popup(self, message, duration, icon=DEFAULT_POPUP_ICON):
        self.popup_request.emit(message, duration, icon or DEFAULT_POPUP_ICON)

    def request_popup_delayed(
        self, message, duration, initial_delay, icon=DEFAULT_POPUP_ICON
    ):
        self.popup_request_delayed.emit(
            message, duration, initial_delay, icon or DEFAULT_POPUP_ICON
        )

    def run(self):
        import time, sys, importlib, subprocess, json
        from contextlib import redirect_stdout, redirect_stderr
        
        stream = EmittingStream(self.log_callback)
        start_time = time.time()
        TRACE_ENABLED = True

        try:
            with redirect_stdout(stream), redirect_stderr(stream): 
                if self.stop_requested:
                    return

                # if self.function_name.lower() == "ems_flashing":
                #     try:
                #         import os
                #         import sys

                #         bosch_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "J107_Flashing")
                #         if bosch_path not in sys.path:
                #             sys.path.insert(0, bosch_path)

                #         try:
                #             from EFI_Flashing_And_Static.Bosch_Flashing import Bosch_Flashing as bosch_hex_flash   
                #         except ImportError:
                #             from EFI_Flashing_And_Static.Bosch_Flashing import Bosch_Flashing as bosch_hex_flash
                #         import EFI_Flashing_And_Static.Bosch_Config as bosch_config

                #         if self.flash_file:
                #             try:
                #                 if getattr(bosch_config, "HEX_FILES", None):
                #                     bosch_config.HEX_FILES[0]["path"] = self.flash_file
                #                 if "Bosch_Config" in sys.modules:
                #                     cfg = sys.modules["Bosch_Config"]
                #                     if hasattr(cfg, "HEX_FILES") and cfg.HEX_FILES:
                #                         cfg.HEX_FILES[0]["path"] = self.flash_file
                #             except Exception as e:
                #                 print(f"[HEX] Failed to override HEX file path: {e}")

                #         self.log_message.emit("Starting Bosch HEX flashing sequence...")
                #         self.flash_progress.emit(5, "HEX: CAN init")

                #         success = bosch_hex_flash(
                #             interface=self.interface,
                #             channel=self.channel,
                #             bitrate=str(self.bitrate),
                #             hex_file=self.flash_file or "",
                #             tx_id=None,
                #             rx_id=None,
                #             progress_callback=self.flash_progress.emit,
                #             can_trace = True,
                #             vin = self.vin_number,
                #             log_dir = self.log_folder,
                #         ) 

                #         self.flash_progress.emit(100, "HEX: Complete" if success else "HEX: Failed")
                #         duration = time.time() - start_time
                #         self.result_ready.emit(bool(success), duration, stream.get_logs())
                #     except Exception as e:
                #         self.error_occurred.emit(e, time.time() - start_time, stream.get_logs())
                #     return

    
                # 🟢 ALL OTHER TESTS (UNCHANGED)
                module_name = f"{self.library_name}.{self.function_name}"
                if module_name in sys.modules:
                    importlib.reload(sys.modules[module_name])
                else:
                    importlib.import_module(module_name)
    
                test_function = getattr(sys.modules[module_name], self.function_name)
    
                if self.stop_requested:
                    return
                
                if self.function_name in ["EMS_Flashing_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["ABS_Flashing_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["VCU_Flashing_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["Static_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["IMU_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["DAQ_Flag_Check"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["EMS_Flag_Update", "ABS_Flag_Update", "VCU_Flag_Update"]:
                    result = test_function(self.vin_number)

                elif self.function_name in ["EMS_Tester_Present", "ABS_Tester_Present", "VCU_Tester_Present", "IPC_Tester_Present"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )

                elif self.function_name in ["EMS_Extended_Session", "ABS_Extended_Session", "VCU_Extended_Session", "IPC_Extended_Session", "IPC_Default_Session", "ABS_Default_Session", "ABS_Ignition_ON", "ABS_Ignition_OFF"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )

                elif self.function_name in ["EMS_Security_Access", "ABS_Security_Access", "VCU_Security_Access", "IPC_Security_Access"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )

                elif self.function_name in ["EMS_Clear_DTC", "ABS_Clear_DTC", "VCU_Clear_DTC", "IPC_Clear_DTC", "EMS_Read_DTC", "ABS_Read_DTC", "VCU_Read_DTC", "IPC_Read_DTC"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )

                elif self.function_name in ["EMS_Read_VIN", "ABS_Read_VIN", "VCU_Read_VIN", "IPC_Read_VIN", "EMS_Read_SKU", "ABS_Read_SKU", "VCU_Read_SKU", "IPC_Read_SKU", 
                                            "IPC_IMEI_Number", "IPC_ICCID1_Number", "IPC_ICCID2_Number", "IPC_Read_Software_Version", "IPC_Read_Bootloader_Version", "EMS_Read_CVN", 
                                            "EMS_Read_CALID", "ABS_Read_CALID", "ABS_Read_BB_Number", "ABS_Read_Software_Version", "IPC_Read_MAC_ID", "VCU_Read_CVN", "VCU_Read_Software_Version"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate, self.api_url, self.vin_number
                    )   

                elif self.function_name in ["ABS_Write_EOL_Mode", "EMS_Quick_Shift_Enable", "EMS_Ride_Mode_Status_Enable", "EMS_Write_Running_Mode", "IPC_Write_ABS_Variant_In_Cluster", 
                                            "IPC_Production_Mode_Enable", "IPC_Write_Test_Stamp", "IPC_Write_MAC_ID_Front_Dummy", "IPC_Write_MAC_ID_Rear_Dummy", "IPC_Write_Varient_Data", 
                                            "EMS_Write_Test_Stamp", "Write_ABS_IME_Feature_Control", "EMS_Write_IMMO_Enable", "ABS_Write_Vehicle_Variant"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    ) 

                elif self.function_name in ["IPC_Write_TPMS_MAC_ID_Front", "IPC_Write_TPMS_MAC_ID_Rear", "EMS_Write_VIN", "IPC_Write_VIN", "ABS_Write_VIN", "VCU_Write_VIN" 
                                            "EMS_Write_SKU", "VCU_Write_SKU", "ABS_Write_SKU", "IPC_Write_MAC_ID", "IPC_Write_Secret_Key", "EMS_Write_Secret_Key", "VCU_Write_Secret_Key"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate, self.api_url, self.vin_number
                    )   


                # Neutral Gear Position Verification
                elif self.function_name == "IPC_Read_Neutral_Gear_Position":
                    initial_popup_duration = 1000
                    self.request_popup(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        "PLEASE ENSURE VEHICLE IS IN NEUTRAL GEAR"
                        "</span>",
                        initial_popup_duration, "⚠️"
                    )

                    gear_result = test_function(self.interface, self.channel, self.bitrate)
                    if isinstance(gear_result, tuple) and len(gear_result) >= 2 and gear_result[0]:
                        popup_message = "VEHICLE IS IN NEUTRAL GEAR"
                        popup_duration = 500
                        popup_icon = "✅"
                    else:
                        popup_message = "VEHICLE IS NOT IN NEUTRAL GEAR"
                        popup_duration = 2000
                        popup_icon = "❌"
                    self.request_popup_delayed(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"{popup_message}"
                        "</span>",
                        popup_duration,
                        initial_popup_duration,
                        popup_icon
                    )
                    result = gear_result


                # Hazard Switch Verification
                elif self.function_name == "IPC_Read_Hazard_Switch_Status":
                    initial_popup_duration = 1000
                    self.request_popup(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        "Please Press the hazard switch"
                        "</span>",
                        initial_popup_duration,
                        "⚠️"
                    )
                    time.sleep(initial_popup_duration / 1000.0)

                    hazard_result = test_function(
                        self.interface, self.channel, self.bitrate
                    )

                    if (
                        isinstance(hazard_result, tuple)
                        and len(hazard_result) >= 2
                        and hazard_result[0]
                        and str(hazard_result[1]).strip().upper()
                        == "HAZARD SWITCH ON (0X01)"
                    ):
                        popup_message = "HAZARD SWITCH IS ON"
                        popup_duration = 5000
                        popup_icon = "✅"
                    else:
                        popup_message = "VEHICLE OR VCI IS NOT COMMUNICATING"
                        popup_duration = 2000
                        popup_icon = "❌"

                    self.request_popup_delayed(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"{popup_message}"
                        "</span>",
                        popup_duration,
                        0,
                        popup_icon
                    )
                    result = hazard_result


                # Ride Mode Verification
                elif self.function_name in [
                    "EMS_ABS_Read_Ride_Mode_1_Urban",
                    "EMS_ABS_Read_Ride_Mode_2_Rain",
                    "EMS_ABS_Read_Ride_Mode_3_Tour",
                    "EMS_ABS_Read_Ride_Mode_4_Enduro",
                    "EMS_ABS_Read_Ride_Mode_5_Sport",
                ]:
                    ride_mode_names = {
                        "EMS_ABS_Read_Ride_Mode_1_Urban": "URBAN",
                        "EMS_ABS_Read_Ride_Mode_2_Rain": "RAIN",
                        "EMS_ABS_Read_Ride_Mode_3_Tour": "TOUR",
                        "EMS_ABS_Read_Ride_Mode_4_Enduro": "ENDURO",
                        "EMS_ABS_Read_Ride_Mode_5_Sport": "SPORT",
                    }
                    ride_mode_name = ride_mode_names[self.function_name]
                    initial_popup_duration = 1000
                    self.request_popup(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"Select the Ride Mode - {ride_mode_name}"
                        "</span>",
                        initial_popup_duration,
                        "⚠️"
                    )

                    ride_mode_result = test_function(
                        self.interface, self.channel, self.bitrate
                    )

                    if isinstance(ride_mode_result, tuple) and len(ride_mode_result) >= 2:
                        passed_flag, status_message = ride_mode_result
                        status_text = str(status_message).strip()

                        if passed_flag and status_text.upper() == "PASSED":
                            popup_message = f"VEHICLE IS IN {ride_mode_name} MODE"
                            popup_duration = 1000
                            popup_icon = "✅"
                        elif not passed_flag and "TIMEOUT" in status_text.upper():
                            popup_message = f"VEHICLE IS NOT IN {ride_mode_name} MODE"
                            popup_duration = 2000
                            popup_icon = "❌"
                        else:
                            popup_message = "VEHICLE OR VCI IS NOT COMMUNICATING"
                            popup_duration = 2000
                            popup_icon = "❌"
                    else:
                        popup_message = "CHECK THE VEHICLE CONNECTION"
                        popup_duration = 2000
                        popup_icon = "❌"

                    self.request_popup_delayed(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"{popup_message}"
                        "</span>",
                        popup_duration,
                        initial_popup_duration,
                        popup_icon
                    )
                    result = ride_mode_result


                # Indicator Switch Verification
                elif self.function_name in [
                    "IPC_Read_Left_Indicator_Switch_Status",
                    "IPC_Read_Right_Indicator_Switch_Status",
                    "IPC_Read_Indicator_OFF_Switch_Status"
                ]:
                    indicator_modes = {
                        "IPC_Read_Left_Indicator_Switch_Status": (
                            "LEFT", "LEFT INDICATOR SWITCH IS ON(0X01)",
                            "LEFT Indicator is ON"
                        ),
                        "IPC_Read_Right_Indicator_Switch_Status": (
                            "RIGHT", "RIGHT INDICATOR SWITCH IS ON(0X02)",
                            "RIGHT Indicator is ON"
                        ),
                        "IPC_Read_Indicator_OFF_Switch_Status": (
                            "OFF", "INDICATOR SWITCH IS OFF(0X00)",
                            "Indicator is OFF"
                        ),
                    }
                    indicator_mode, expected_status, success_message = indicator_modes[self.function_name]
                    initial_popup_duration = 1000
                    self.request_popup(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"Please set the indicator switch to {indicator_mode}"
                        "</span>",
                        initial_popup_duration,
                        "⚠️"
                    )

                    indicator_result = test_function(
                        self.interface, self.channel, self.bitrate
                    )

                    if (
                        isinstance(indicator_result, tuple)
                        and len(indicator_result) >= 2
                        and indicator_result[0]
                        and str(indicator_result[1]).strip().upper()
                        == expected_status
                    ):
                        popup_message = success_message
                        popup_duration = 1500
                        popup_icon = "✅"
                    else:
                        popup_message = "VEHICLE OR VCI IS NOT COMMUNICATING"
                        popup_duration = 2000
                        popup_icon = "❌"

                    self.request_popup_delayed(
                        "<span style='color:#4AA3FF; font-weight:bold; font-size:35px; font-family:Segoe UI;'>"
                        f"{popup_message}"
                        "</span>",
                        popup_duration,
                        initial_popup_duration,
                        popup_icon
                    )
                    result = indicator_result


                # Cruise Control Check
                # Mode Selecton Verification
                # Keyfob Check Verification
                # TPMS Config (Not, Both, Left, Right)
                # Side Stand Verification
                # Headlamp Control Verification
                # Throttle Position Verification(APS1, APS2)
                # Clutch Status Verification
                # Quick Shift Enable Verification
                # Running Mode Enable Verification
                # IMMO Enable Verification
                # Ride Mode Enable Verification
                # Production Mode Enable Verification
                # Kill Switch Verification
                # Traction Control Switch Verification
                # FAN Relay IO Control Verification


                elif self.function_name in ["EMS_Read_Test_Stamp", "IPC_Read_Test_Stamp", "IPC_Bluetooth_Firmware_Version", "EMS_Read_IMMO_Status", "EMS_Read_Engine_Temperature", "EMS_Read_Intake_Air_Temperature", 
                                            "IPC_Read_E_SIM_Status", "EMS_Read_Running_Mode", "EMS_Read_Map_Sensor_Voltage", "EMS_Read_Oil_Temperature_Values", "EMS_Read_Lambda_Additive_Adaptation_Upstream", 
                                            "EMS_Read_Lambda_Average_Upstream_Cylinder_2", "EMS_Read_Lambda_Correction_Upstream_Cylinder_2", "EMS_Read_Lambda_Multiplicative_Adaptation_Upstream", 
                                            "HLC_Read_Headlamp_Software_Version", "IPC_Read_DRL_Status", "IPC_Read_Photo_Sensor", "IPC_Read_Variant_Control", "IPC_Read_Variant_Data", "EMS_Read_Ambient_Pressure_Of_Engine",
                                              "ABS_Read_EOL_Mode", "ABS_Read_EOL_Mode_00", "ABS_Read_Lean_Angle", "ABS_Read_Pitch_Angle", "IPC_Read_Fuel_Level_Sensor_Resistance", "EMS_Read_Hardware_Version", "IPC_Read_Speedometer_Software_Version", "EMS_Read_Hardware_Version"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )    


                elif self.function_name in ["EMS_Canister_Purge_Valve_IO_Control", "EMS_Purge_Valve_IO_Control", "ABS_IMU_EOL_Routine_Flag", "ABS_IMU_EOL_Routine", "EMS_IG_Coil_1_IO_Control", "EMS_IG_Coil_2_IO_Control", 
                                            "EMS_Injector_Coil_1_IO_Control", "EMS_Injector_Coil_2_IO_Control", "IPC_Warning_Light_IO_Control"]:
                    result = test_function(
                        self.interface, self.channel,
                        self.bitrate
                    )    

                else:
                    result = test_function(
                        self.interface, self.channel, self.bitrate
                    )

                duration = time.time() - start_time
                self.result_ready.emit(result, duration, stream.get_logs())
                return

        except Exception as e:
            duration = time.time() - start_time
            self.error_occurred.emit(e, duration, stream.get_logs())
            return
    
# To access files after converting to an exe/elf/runtime
def resource_path(relative_path):
    """
    Get correct path for files whether running in dev mode or PyInstaller EXE.
    """
    if getattr(sys, 'frozen', False):
        # Executable mode
        base_path = os.path.dirname(sys.executable)
    else:
        # Normal Python mode
        base_path = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base_path, relative_path)

# Force the working directory to the EXE folder (fixes _internal path issue)
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))
else:
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
def get_file_name_from_sku(sku_number, active_library):
    from security_manager import (read_encrypted_excel, MASTER_PASSWORD)
    
    mapping_file_path = resource_path("SKU_File_Mapping.xlsx.enc")

    try:
        sheet = read_encrypted_excel(mapping_file_path, MASTER_PASSWORD)

        sheet.columns = sheet.columns.str.strip()
        sheet["SKU No"] = sheet["SKU No"].map(
            lambda value: value.strip() if isinstance(value, str) else "")
        sheet["File Name"] = sheet["File Name"].map(
            lambda value: value.strip() if isinstance(value, str) else "")
        sheet["Library"] = sheet["Library"].map(
            lambda value: value.strip() if isinstance(value, str) else "")

        lookup_sku = sku_number.strip()

        # Match SKU in active library
        matched_row = sheet[
            sheet["Library"].str.lower() == active_library.strip().lower()].copy()

        matched_row["SKU_List"] = matched_row["SKU No"].apply(
            lambda value: [sku.strip() for sku in value.split(",") if sku.strip()])

        matched_row = matched_row[
            matched_row["SKU_List"].apply(lambda sku_list: lookup_sku in sku_list)]
        
        if not matched_row.empty:
            return (matched_row.iloc[0]["File Name"],
                matched_row.iloc[0]["Library"])
        
        # SKU not found
        print(f"SKU Number '{lookup_sku}' is not present in the database")
        return None, None

    except Exception as e:
        print(f"Failed to read SKU mapping file: {e}")
        return None, None

class ActionPopup(QWidget):
    def __init__(self, parent=None, message="", icon=DEFAULT_POPUP_ICON):
        super().__init__(parent)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 🔷 Outer layout (for shadow spacing)
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(20, 20, 20, 20)

        # 🔷 Main container
        container = QFrame()
        container.setObjectName("container")
        container.setStyleSheet("""
            QFrame#container {
                background-color: #FFFFFF;
                border-radius: 18px;
                border: 1px solid #D7E0EA;
            }
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 🔷 Header
        header = QLabel("ACTION REQUIRED")
        header.setAlignment(Qt.AlignCenter)
        header.setFixedHeight(45)
        header.setStyleSheet("""
            QLabel {
                background-color: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 #005A9C, stop: 1 #00345F
                );
                color: white;
                font-size: 15px;
                font-weight: bold;
                letter-spacing: 1px;
                border-top-left-radius: 17px;
                border-top-right-radius: 17px;
            }
        """)

        # 🔴 Accent line
        red_line = QFrame()
        red_line.setFixedHeight(4)
        red_line.setStyleSheet("""
            background-color: qlineargradient(
                x1: 0, y1: 0, x2: 1, y2: 0,
                stop: 0 #D32F2F, stop: 1 #F2994A
            );
        """)

        # 🔷 Content layout (icon on left, message on right)
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(28, 28, 28, 28)
        content_layout.setSpacing(24)
        content_layout.setAlignment(Qt.AlignVCenter)

        # 🔶 Keep the warning icon visible across immediate and delayed popup requests.
        icon_badge = QFrame()
        icon_badge.setObjectName("warningIconBadge")
        icon_badge.setFixedSize(86, 86)
        icon_badge.setStyleSheet("""
            QFrame#warningIconBadge {
                background-color: #FFF4D6;
                border: 1px solid #F2D27A;
                border-radius: 43px;
            }
        """)
        icon_layout = QVBoxLayout(icon_badge)
        icon_layout.setContentsMargins(0, 0, 0, 0)

        icon_label = QLabel(icon or DEFAULT_POPUP_ICON, icon_badge)
        icon_label.setObjectName("popupIcon")
        icon_label.setFont(QFont("Segoe UI Emoji", 35))
        icon_label.setAlignment(Qt.AlignCenter)
        icon_layout.addWidget(icon_label)
        icon_label.setAccessibleName(icon_label.text())

        # 🔷 Message — support rich text and left-aligned, vertically centered
        message_label = QLabel()
        message_label.setTextFormat(Qt.RichText)
        message_label.setText(message)
        message_label.setWordWrap(True)
        message_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        message_label.setFont(QFont("Segoe UI", 20, QFont.Bold))
        message_label.setStyleSheet("""
            QLabel {
                color: #1D2B3A;
                font-weight: bold;
            }
        """)

        content_layout.addWidget(icon_badge)
        content_layout.addWidget(message_label, 1)

        # Add all
        layout.addWidget(header)
        layout.addWidget(red_line)
        layout.addLayout(content_layout)

        outer_layout.addWidget(container)

        # 🔥 Size (more balanced)
        self.resize(700, 450)

        # 🔷 Center popup
        if parent:
            parent_rect = parent.geometry()
            self.move(
                parent_rect.center().x() - self.width() // 2,
                parent_rect.center().y() - self.height() // 2
            )

        # 🔥 Shadow effect (IMPORTANT)
        from PyQt5.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(20, 42, 65, 105))
        container.setGraphicsEffect(shadow)

    def show_with_timeout(self, duration):
        self.show()
        QTimer.singleShot(duration, self.close)
    
class ResultOverlay(QWidget):
    # Dhinakar added -1 line
    dismiss_requested = pyqtSignal()
    """Transient overlay shown for 2 seconds after cycle completes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setWindowFlags(Qt.Widget)  # keep as a child widget
        self.setVisible(False)

        # full layout: top 30% (colored) + bottom 70% (white)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top panel (30%)
        self.top_panel = QWidget(self)
        top_layout = QVBoxLayout(self.top_panel)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setAlignment(Qt.AlignCenter)

        self.top_label = QLabel("", self.top_panel)
        self.top_label.setAlignment(Qt.AlignCenter)
        self.top_label.setWordWrap(True)
        self.top_label.setStyleSheet("color: white; font-weight: bold;")
        # Large font; will be resized in resizeEvent
        self.top_label.setFont(QFont("Segoe UI", 40, QFont.Bold))

        top_layout.addWidget(self.top_label)
        layout.addWidget(self.top_panel, stretch=3)

        # Dhinakar added upto next method
        # Bottom panel
        self.bottom_panel = QWidget(self)

        bottom_layout = QHBoxLayout(self.bottom_panel)
        bottom_layout.setContentsMargins(20, 20, 20, 20)
        bottom_layout.setSpacing(20)

        # left side ERROR DESCRIPTION is here
        left_layout = QVBoxLayout()

        self.instructions_heading = QLabel("ERROR DESCRIPTION")
        self.instructions_heading.setAlignment(Qt.AlignCenter)
        self.instructions_heading.setStyleSheet("""
    QLabel {
        font-size: 32px;
        font-weight: bold;
        color: #003B6F;
        border-bottom: 2px solid #003B6F;
        padding: 10px;
    }
""")

        self.instructions_box = QTextEdit()
        self.instructions_box.setReadOnly(True)
        self.instructions_box.setFocusPolicy(Qt.NoFocus)

        left_layout.addWidget(self.instructions_heading)
        left_layout.addWidget(self.instructions_box)

        # right side RESULT is here
        right_layout = QVBoxLayout()

        self.results_heading = QLabel("RESULT")
        self.results_heading.setAlignment(Qt.AlignCenter)
        self.results_heading.setStyleSheet("""
    QLabel {
        font-size: 32px;
        font-weight: bold;
        color: #003B6F;
        border-bottom: 2px solid #003B6F;
        padding: 10px;
    }
""")

        self.results_box = QTextEdit()
        self.results_box.setReadOnly(True)
        self.results_box.setFocusPolicy(Qt.NoFocus)

        right_layout.addWidget(self.results_heading)
        right_layout.addWidget(self.results_box)

        textbox_style = """
QTextEdit {
    background-color: white;
    color: black;
    border: 2px solid #003B6F;
    font-size: 28px;
    font-weight: bold;
    padding: 15px;
}
"""

        self.instructions_box.setStyleSheet(textbox_style)
        self.results_box.setStyleSheet(textbox_style)

        bottom_layout.addLayout(left_layout)
        bottom_layout.addLayout(right_layout)

        layout.addWidget(self.bottom_panel, stretch=7)

    # Dhinakar added instructions and results args only
    def show_result(self, vin: str, is_pass: bool, instructions="", results=""):
        """Set colors/text and show overlay covering parent window."""
        if is_pass:
            color = "#008000"  # green
            text = f"{vin}\nPASS"
        else:
            color = "#FF0000"  # red
            text = f"{vin}\nFAIL"

        self.top_panel.setStyleSheet(f"background-color: {color};")
        self.top_label.setText(text)

    # Dhinakar added if else.
        if not is_pass:
            self.instructions_heading.show()
            self.results_heading.show()
            self.instructions_box.show()
            self.results_box.show()
            self.instructions_box.setText(instructions)
            self.results_box.setText(results)
            
            QTimer.singleShot(0,lambda: 
            self.instructions_box.verticalScrollBar().setValue(
            self.instructions_box.verticalScrollBar().maximum()))

            QTimer.singleShot(0,lambda: 
            self.results_box.verticalScrollBar().setValue(
            self.results_box.verticalScrollBar().maximum()))
            
        else:
            self.instructions_heading.hide()
            self.results_heading.hide()
            self.instructions_box.hide()
            self.results_box.hide()

        self.top_label.setFont(QFont("Segoe UI", max(24, int(self.parent().height() * 0.04)), QFont.Bold))
        self.setGeometry(0, 0, self.parent().width(), self.parent().height())
        self.raise_()
        self.setVisible(True)

    def hide_result(self):
        self.setVisible(False)

# Dhinakar added mouse press method
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dismiss_requested.emit()
        super().mousePressEvent(event)    
    
class EmittingStream(io.StringIO):
    """Custom stream to capture stdout and stderr logs."""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def write(self, text): 
        super().write(text)
        if self.callback:
            self.callback(text)
 
    def flush(self):
        pass  # Optional: override if needed
    
    def get_logs(self):
        # Return everything written so far
        return self.getvalue()

class ScannerSignalEmitter(QObject):
    vin_scanned = pyqtSignal(str)

class ApiHelper(QObject):
    show_message_signal = pyqtSignal(str)
    reset_ui_signal = pyqtSignal()

    def __init__(self, parent):
        super().__init__()
        self.parent = parent

    def fetch_sku_from_api(self, vin, base_url, active_library):
        def api_task():
            url = base_url
            max_attempts = 3
            default_sku = "N6191260"
            selected_mode = self.parent.api_selector.get_selected_api()
            mode_display = "Production (PRD)" if selected_mode == "PRD" else "Engineering Job Order (EJO)"
            active_library = self.parent.active_library_selector.get_selected_library()

            for attempt in range(1, max_attempts + 1):
                try:
                    print(f"Attempt {attempt}: Sending API request to {url}")
                    response = requests.get(url, timeout=5)
                    print(f"API returned status code {response.status_code}")

                    if response.status_code == 200:
                        json_data = response.json()
                        self.parent.json_response = json_data
                        modules = json_data.get("data", {}).get("modules", [])
                        sku = None

                        for module in modules:
                            for config in module.get("configs", []):
                                if active_library not in ["J107_Flashing", "J107_Static", "J107_IMU", "J107_RVS"]:
                                    name = "VCU_SKU_WRITE"
                                else:
                                    name = "PCM_SKU_WRITE"

                                if config.get("refname") == name:
                                    for msg in config.get("messages", []):
                                        if msg.get("refname") == "SKU_WRITE":
                                            sku = msg.get("txbytes")
                                            break

                        if sku:
                            print(f"[SKU fetched: {sku}]")

                            file_name, sku_library = get_file_name_from_sku(sku, active_library)

                            if not file_name:
                                self.show_message_signal.emit(
                                    f'<span style="color:red;">SKU "{sku}" is not present in the database.</span>'
                                 )
                                self.reset_ui_signal.emit()
                                return
                            elif sku_library != active_library:
                                self.show_message_signal.emit(
                                    f'<span style="color:red;">VIN {vin} (SKU {sku}) belongs to {sku_library}, not {active_library}.</span>'
                                )
                                self.reset_ui_signal.emit()
                                return
                            else:
                                self.parent.sku = sku
                                self.parent.sku_fetched.emit(sku)
                                return

                        self.show_message_signal.emit(
                            f'<span style="color:red;">Scanned VIN number is not in Selected API Mode ({mode_display}).</span>'
                        )
                        self.parent.test_cycle_active = False
                        self.reset_ui_signal.emit()
                        return

                    elif response.status_code == 404:
                        self.show_message_signal.emit(
                            f'<span style="color:red;">Scanned VIN number is not in Selected API Mode ({mode_display}).</span>'
                        )
                        self.parent.test_cycle_active = False
                        self.reset_ui_signal.emit()
                        return

                    else:
                        self.show_message_signal.emit(f"API returned unexpected status: {response.status_code}")
                        self.reset_ui_signal.emit()
                        return

                except requests.RequestException as e:
                    self.show_message_signal.emit(f"API attempt {attempt} failed: {e}")

                time.sleep(1)

            self.show_message_signal.emit(f"API call failed after {max_attempts} attempts.")
            file_name, sku_library = get_file_name_from_sku(default_sku, active_library)

            if not file_name:
                self.show_message_signal.emit(
                    f"<span style='color:red;'>Default SKU {default_sku} not found.</span>"
                )
                self.reset_ui_signal.emit()
                return

            self.parent.json_response = None
            self.parent.sku = default_sku
            self.parent.sku_fetched.emit(default_sku)

        threading.Thread(target=api_task, daemon=True).start()

class SerialReaderThread(QThread):
    vin_received = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, port, baudrate):
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.serial_port = None
        self.running = True
        self.max_retries = 3
        self.retry_delay = 1

    def run(self):
        retry_count = 0
        while retry_count < self.max_retries and self.running:
            try:
                print(f"SerialReaderThread: Attempt {retry_count + 1}/{self.max_retries} to open port {self.port} at {self.baudrate} baud")
                self.serial_port = serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=1,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    bytesize=serial.EIGHTBITS
                )
                print(f"SerialReaderThread: Successfully opened port {self.port}")
                while self.running:
                    if self.serial_port.in_waiting > 0:
                        vin = self.serial_port.readline().decode('utf-8', errors='ignore').strip()
                        if vin:
                            print(f"SerialReaderThread: Scanned VIN: {vin}")
                            self.vin_received.emit(vin)
                            break
                    self.msleep(100)
                break
            except serial.SerialException as e:
                retry_count += 1
                error_msg = f"Failed to open port {self.port} on attempt {retry_count}: {str(e)}"
                print(error_msg)
                self.error_occurred.emit(error_msg)
                if retry_count < self.max_retries:
                    time.sleep(self.retry_delay)
                else:
                    self.error_occurred.emit(f"Serial port {self.port} failed after {self.max_retries} attempts")
            except Exception as e:
                retry_count += 1
                error_msg = f"Unexpected error reading from port {self.port}: {str(e)}"
                print(error_msg)
                self.error_occurred.emit(error_msg)
                if retry_count < self.max_retries:
                    time.sleep(self.retry_delay)
                else:
                    self.error_occurred.emit(f"Serial port {self.port} failed after {self.max_retries} attempts")
            finally:
                if self.serial_port and self.serial_port.is_open:
                    print(f"SerialReaderThread: Closing port {self.port}")
                    self.serial_port.close()
                    self.serial_port = None

    def stop(self):
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            print(f"SerialReaderThread: Stopping and closing port {self.port}")
            self.serial_port.close()
            self.serial_port = None
        self.quit()
        self.wait()

def load_scanner_config(config_file=resource_path("scanner.ini.enc")):
    from security_manager import (read_encrypted_ini,MASTER_PASSWORD)
    config = read_encrypted_ini(config_file,MASTER_PASSWORD)
    if 'ScannerConfig' not in config:
        return 'AUTO', ['COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8'], 9600
    mode = config.get('ScannerConfig', 'connection_mode', fallback='AUTO').upper()
    ports = config.get('ScannerConfig', 'ports', fallback='COM2,COM3,COM4,COM5,COM6,COM7,COM8').split(',')
    baudrate = config.getint('ScannerConfig', 'baudrate', fallback=9600)
    return mode, ports, baudrate

def load_station_config():
    from security_manager import (read_encrypted_ini,MASTER_PASSWORD)

    config = configparser.ConfigParser()
    config_data = {}
    try:
        ini_path = resource_path("station.ini.enc")
        if not os.path.exists(ini_path):
            raise FileNotFoundError(f"station.ini.enc not found at {ini_path}")
        config = read_encrypted_ini(ini_path, MASTER_PASSWORD)
        if "SETTINGS" in config:
            config_data = dict(config["SETTINGS"])
        else:
            print("No [SETTINGS] section in station.ini.enc")
    except Exception as e:
        print(f"Error reading station.ini.enc: {e}")
    return config_data

class FlashingWorker(QObject):
    progress_changed = pyqtSignal(int, str)  # percentage, status text
    flashing_done = pyqtSignal(bool, str)    # success, message
    flashing_error = pyqtSignal(str)

    def run(self):
        try:
            total_steps = 10
            for step in range(total_steps):
                # Simulate work
                time.sleep(0.5)

                percent = int((step + 1) / total_steps * 100)
                status = f"Flashing step {step + 1} of {total_steps}..."
                self.progress_changed.emit(percent, status)

            # Simulate success
            self.flashing_done.emit(True, "Flashing completed successfully.")

        except Exception as e:
            self.flashing_error.emit(str(e))

class FlashingProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flashing in Progress")
        self.setModal(True)
        self.setFixedSize(700, 450)

        # Set background color to a light shade
        self.setStyleSheet("background-color: #F0F0F0;")

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(20, 20, 20, 20)
        self.main_layout.setSpacing(20)

        # Header label
        self.header_label = QLabel("Flashing", self)
        header_font = QFont("Segoe UI", 18, QFont.Bold)
        self.header_label.setFont(header_font)
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet("color: #003B6F;")
        self.main_layout.addWidget(self.header_label)

        # Scroll area to hold block progress bars
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFixedHeight(260)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet("background-color: #D3D3D3; border-radius: 8px;")
        self.main_layout.addWidget(self.scroll_area)

        # Container widget inside scroll area
        self.blocks_container = QWidget()
        self.scroll_area.setWidget(self.blocks_container)

        self.blocks_layout = QVBoxLayout(self.blocks_container)
        self.blocks_layout.setContentsMargins(15, 15, 15, 15)
        self.blocks_layout.setSpacing(18)

        self.block_bars = []
        self.block_labels = []

        # Cancel button layout
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setFixedSize(120, 40)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF0033;
                color: white;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                padding: 8px;
            }
            QPushButton:hover {
                background-color: #e60029;
            }
            QPushButton:pressed {
                background-color: #b20020;
            }
        """)
        btn_layout.addWidget(self.cancel_btn)
        self.main_layout.addLayout(btn_layout)

    def init_progress_bars(self, block_count):
        # Clear previous bars and labels if any
        for i in reversed(range(self.blocks_layout.count())):
            widget_to_remove = self.blocks_layout.itemAt(i).widget()
            if widget_to_remove:
                widget_to_remove.setParent(None)

        self.block_bars.clear()
        self.block_labels.clear()

        for i in range(block_count):
            block_widget = QWidget()
            block_layout = QHBoxLayout(block_widget)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(20)

            label = QLabel(f"Block {i+1} : ", self)
            label.setFixedWidth(100)
            label_font = QFont("Segoe UI", 14, QFont.Bold)
            label.setFont(label_font)
            label.setStyleSheet("color: #003B6F;")

            progress_bar = QProgressBar(self)
            progress_bar.setRange(0, 100)
            progress_bar.setValue(0)
            progress_bar.setTextVisible(True)
            progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            progress_bar.setFixedHeight(28)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 2px solid #003B6F;
                    border-radius: 10px;
                    background-color: #F0F0F0;
                    text-align: center;
                    font-size: 14px;
                    font-weight: bold;
                    color: #003B6F;
                }
                QProgressBar::chunk {
                    background-color: #008000;
                    border-radius: 10px;
                }
            """)

            block_layout.addWidget(label)
            block_layout.addWidget(progress_bar)

            self.blocks_layout.addWidget(block_widget)

            self.block_labels.append(label)
            self.block_bars.append(progress_bar)

    def update_block_progress(self, block_index, chunk_done, total_chunks):
        if 0 <= block_index < len(self.block_bars):
            percent = int((chunk_done / total_chunks) * 100)
            self.block_bars[block_index].setValue(percent)
            self.block_labels[block_index].setText(f"Block {block_index + 1}: {percent}%")
            self.header_label.setText(f"Flashing block {block_index + 1} - {percent}% complete")

class ApiSelector(QFrame):
    def __init__(self, api_ini_path=resource_path("api.ini.enc"), parent=None):
        super().__init__(parent)
        self.setFixedSize(350, 120)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border: 2px solid #003B6F;
            }
            QLabel {
                color: #003B6F;
                font-family: 'Segoe UI';
                font-weight: bold;
                font-size: 28px;
                border: none;
            }
            QPushButton {
                background-color: #F0F0F0;
                color: black;
                font-size: 26px;
                border: 2px solid #D3D3D3;
                border-radius: 6px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                border: 2px solid #FF0033;
                background-color: #ffffff;
            }
            QPushButton:checked {
                background-color: #003B6F;
                color: white;
                border: 2px solid #003B6F;
            }
        """)
        self.api_ini_path = api_ini_path
        self.selected_api = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        #layout.setSpacing(4)

        label = QLabel("Select Mode")
        #label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        #label.setStyleSheet("color: black; background: transparent; border: none; font-size: 30px;")
        
        self.btn_prd = QPushButton("PRD")
        self.btn_ejo = QPushButton("EJO")

        for btn in (self.btn_prd, self.btn_ejo):
            btn.setCheckable(True)

        self.group = QButtonGroup()
        self.group.addButton(self.btn_prd)
        self.group.addButton(self.btn_ejo)

        self.btn_prd.setChecked(True)

        self.btn_prd.clicked.connect(lambda: self.select_api("PRD"))
        self.btn_ejo.clicked.connect(lambda: self.select_api("EJO"))

        btn_layout = QHBoxLayout()
        #btn_layout.setSpacing(10)
        btn_layout.addWidget(self.btn_prd)
        btn_layout.addWidget(self.btn_ejo)

        layout.addWidget(label)
        layout.addLayout(btn_layout)
        
        self.select_api("PRD")

    def select_api(self, name):
        self.selected_api = name.upper()
        
    def get_selected_api(self):
        return self.selected_api
        
    def get_selected_api_url(self, vin=""):
        from security_manager import (read_encrypted_ini,MASTER_PASSWORD)

        default_url = "http://10.121.2.107:3000/vehicles/flashFile/prd"
        try:
            if not os.path.exists(self.api_ini_path):
                print(f"[ApiSelector] Error: api.ini.enc not found at {self.api_ini_path}")
                self.parent().instruction_box.append(f"Error: api.ini.enc not found at {self.api_ini_path}. Using default URL.")
                return default_url.rstrip("/") + f"/{vin}" if vin else default_url

            config = read_encrypted_ini(self.api_ini_path, MASTER_PASSWORD)
            if not config.sections():
                print(f"[ApiSelector] Error: api.ini.enc is empty or corrupted at {self.api_ini_path}")
                self.parent().instruction_box.append("Error: api.ini.enc is empty or corrupted. Using default URL.")
                return default_url.rstrip("/") + f"/{vin}" if vin else default_url

            if not self.selected_api:
                print("Selected API not set!")
                self.parent().instruction_box.append("Error: No API mode selected (PRD/EJO). Using default URL.")
                return default_url.rstrip("/") + f"/{vin}" if vin else default_url

            api_key = self.selected_api.upper()
            if "API" not in config or api_key not in config["API"]:
                print(f"Error: Section 'API' or key '{api_key}' not found in {self.api_ini_path}")
                self.parent().instruction_box.append(f"Error: Section 'API' or key '{api_key}' not found in api.ini.enc. Using default URL.")
                return default_url.rstrip("/") + f"/{vin}" if vin else default_url

            base_url = config["API"][api_key]
            if not base_url:
                print(f"Error: Empty URL for key '{api_key}' in {self.api_ini_path}")
                self.parent().instruction_box.append(f"Error: Empty URL for '{api_key}' in api.ini.enc. Using default URL.")
                return default_url.rstrip("/") + f"/{vin}" if vin else default_url

            if vin:
                base_url = base_url.rstrip("/") + f"/{vin}"
            print(f"Selected API URL: {base_url}")
            return base_url
        except Exception as e:
            print(f"[ApiSelector] Error reading '{self.api_ini_path}': {e}")
            self.parent().instruction_box.append(f"Error reading api.ini.enc: {e}. Using default URL.")
            return default_url.rstrip("/") + f"/{vin}" if vin else default_url

class EditableInfoBox(QFrame):
    def __init__(self, label_text: str):
        super().__init__()
        self.setFixedSize(350, 120)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border: 2px solid #003B6F;
            }
            QLabel {
                color: #003B6F;
                font-family: 'Segoe UI';
                font-weight: bold;
                font-size: 28px;
                border: none;
            }
            QLineEdit {
                background-color: #F0F0F0;
                color: black;
                font-size: 26px;
                padding: 8px;
                border: 2px solid #D3D3D3;
                border-radius: 6px;
            }
            QLineEdit:hover {
                border: 2px solid #FF0033;
                background-color: #ffffff;
            }
            QLineEdit:focus {
                border: 2px solid #003B6F;
                background-color: #FFFFFF;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        #layout.setSpacing(4)

        label = QLabel(label_text)
        self.line_edit = QLineEdit()
        #label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        #label.setStyleSheet("color: black; background: transparent; border: none; font-size: 30px;")

        #self.line_edit = QLineEdit()
        #self.line_edit.setStyleSheet("""
        #    background-color: #f0f0f0;
        #    color: black;
        #    border: 1px solid #555;
        #    border-radius: 5px;
        #    padding: 4px;
        #    font-size: 25px;
        #""")
        self.line_edit.setPlaceholderText("Enter Employee No")
        self.line_edit.setValidator(QIntValidator(0, 9999999))
        layout.addWidget(label)
        layout.addWidget(self.line_edit)

    def get_text(self):
        return self.line_edit.text()
    
class HeaderBar(QFrame):
    def __init__(self, left_logo_path, right_logo_path):
        super().__init__()
        self.setFixedHeight(75)
        self.setStyleSheet("""
            QFrame {
                background-color: #003B6F;  /* Smalt Blue */
                border: none;
            }
            QLabel#TitleLabel {
                color: white;
                font-size: 38px;
                font-weight: bold;
                font-family: 'Segoe UI', sans-serif;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(30, 0, 30, 0)
        title_row.setSpacing(0)
        
        # LEFT LOGO
        left_logo_label = QLabel()
        left_pixmap = QPixmap(left_logo_path)
        if not left_pixmap.isNull():
            left_pixmap = left_pixmap.scaled(195, 195, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            left_logo_label.setPixmap(left_pixmap)
        left_logo_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        title_row.addWidget(left_logo_label, stretch=2)

        # Center title
        title = QLabel("")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignCenter)
        title_row.addWidget(title, stretch=4)

        # RIGHT LOGO
        right_logo_label = QLabel()
        right_pixmap = QPixmap(right_logo_path)
        if not right_pixmap.isNull():
            right_pixmap = right_pixmap.scaled(195, 195, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            right_logo_label.setPixmap(right_pixmap)
        right_logo_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        title_row.addWidget(right_logo_label, stretch=2)

        # Add the title row
        main_layout.addLayout(title_row)

        # Full-width red underline (Torch Red)
        underline = QFrame()
        underline.setFixedHeight(5)
        underline.setStyleSheet("background-color: #FF0033; border: none;")
        main_layout.addWidget(underline)

class InfoBox(QFrame):
    def __init__(self, label_text: str, value_text: str):
        super().__init__()
        self.setFixedSize(350, 120)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border: 2px solid #003B6F;
            }
            QLabel {
                color: #003B6F;
                font-family: 'Segoe UI';
                font-weight: bold;
                font-size: 28px;
                background: transparent;
                border: none;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        label = QLabel(label_text)
        #label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        #label.setStyleSheet("color: black; background: transparent; border: none; font-size: 30px;")

        value = QLabel(value_text)
        #value.setFont(QFont("Segoe UI", 9))
        value.setStyleSheet("color: black; background: transparent; border: none; font-size: 30px;")

        layout.addWidget(label)
        layout.addWidget(value)

class CycleTimeBox(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedSize(400, 240)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border: 2px solid #003B6F;
            }
            QLabel {
                background: transparent;
                font-family: 'Segoe UI';
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        #layout.setSpacing(10)

        self.label = QLabel("Cycle Time:")
        self.label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.label.setStyleSheet("color: #003B6F; border:none; font-size: 30px;")
        #self.label.setAlignment(Qt.AlignLeft)

        self.timer_display = QLabel("0 sec")
        self.timer_display.setFont(QFont("Consolas", 28, QFont.Bold))
        self.timer_display.setStyleSheet("color: black; font-size: 45px;")
        self.timer_display.setAlignment(Qt.AlignCenter)

        layout.addWidget(self.label)
        layout.addWidget(self.timer_display)

        self.timer = QTimer()
        self.timer.timeout.connect(self.update_time)
        self.seconds = 0

    def start_timer(self):
        self.seconds = 0
        self.timer_display.setText("0 sec")
        self.timer.start(1000)

    def stop_timer(self):
        self.timer.stop()

    def reset_timer(self):
        self.seconds = 0
        self.timer_display.setText("0 sec")

    def update_time(self):
        self.seconds += 1
        self.timer_display.setText(f"{self.seconds} sec")

class LabeledEntryBox(QFrame):
    def __init__(self, label_text, placeholder_text="", max_length=100):
        super().__init__()
        self.setFixedSize(450, 120)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border: 2px solid #003B6F;
            }
            QLabel {
                color: #003B6F;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI';
                border: none;
            }
            QLineEdit {
                font-size: 26px;
                padding: 8px;
                border: 2px solid #D3D3D3;
                border-radius: 6px;
                background-color: #F0F0F0;
                color: black;
            }
            QLineEdit:hover {
                border: 2px solid #FF0033;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #003B6F;
                background-color: white;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        self.label = QLabel(label_text)
        #self.label.setFont(QFont("Segoe UI", 12, QFont.Bold))
        #self.label.setStyleSheet("color: black; background: transparent; border: none; font-size: 30px;")
        layout.addWidget(self.label)

        self.entry = QLineEdit()
        self.entry.setPlaceholderText(placeholder_text)
        self.entry.setMaxLength(max_length)
        layout.addWidget(self.entry)

    def set_value(self, text):
        self.entry.setText(text)

    def get_value(self):
        return self.entry.text()

class ActiveLibrarySelector(QFrame):
    def __init__(self, library_list, default_value=None):
        super().__init__()
        self.setFixedSize(950, 120)
        self.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 15px;
                border:2px solid #003B6F;
            }
            QLabel {
                color: #003B6F;
                font-size: 28px;
                font-weight: bold;
                font-family: 'Segoe UI';
                border:none;
            }
            QComboBox {
                font-size: 26px;
                padding: 6px;
                border-radius: 6px;
                background-color: #F0F0F0;
                color: black;
                border: 2px solid #D3D3D3;
            }
            QComboBox:hover {
                border: 2px solid #FF0033;
                background-color: white;
            }
            QComboBox:focus {
                border: 2px solid #003B6F;
                background-color: white;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                selection-background-color: #818689;
                selection-color: white; 
                color: black;
                border: 1px solid #003B6F;
                font-size: 24px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        #layout.setSpacing(6)

        self.label = QLabel("Active Library")
        layout.addWidget(self.label)

        self.combo = QComboBox()
        self.combo.addItems(library_list)

        if default_value and default_value in library_list:
            self.combo.setCurrentText(default_value)
        else:
            self.combo.setCurrentIndex(0)

        layout.addWidget(self.combo)
        self.combo_box = self.combo
        self.combo.currentTextChanged.connect(self.lock_selection)
        self.selection_locked = False

    def lock_selection(self, library):
        if not self.selection_locked:
            self.selection_locked = True
            self.save_to_station_ini(library)
            print(f"Active library updated to: {library}")

    def save_to_station_ini(self, library):
        from security_manager import (read_encrypted_ini,write_encrypted_ini,MASTER_PASSWORD)
        ini_path = resource_path("station.ini.enc")
        try:
            config = read_encrypted_ini(ini_path, MASTER_PASSWORD)
            if "SETTINGS" not in config:
                config["SETTINGS"] = {}

            config["SETTINGS"]["active_library"] = library
            write_encrypted_ini(config, ini_path, MASTER_PASSWORD)
            print(f"Saved active_library '{library}' to {ini_path}")
        except Exception as e:
            print(f"Failed to save active_library to station.ini.enc: {e}")


    def get_selected_library(self):
        return self.combo.currentText()

class MainWindow(QWidget):
    sku_fetched = pyqtSignal(str)
    def __init__(self):
        super().__init__()
        self.cycle_time_box = CycleTimeBox()
        self.sku = None
        self.test_cycle_completed = False
        self.pass_screen_active = False
        # Dhinakar added -1 line
        self.fail_screen_active = False
        self.test_cycle_active = False
        self.test_boxes = []
        self.sku_fetched.connect(self.on_sku_fetched)
        
        self.retry_count = 0
        self.max_retries = 3
        self.global_retry_count = 0
        self.max_global_retries = 3
        self.worker_thread = None
        self.worker = None
        self.result = None
        self.test_duration = 0
        self.test_results = []
        self.current_vin = ""
        self.mac_ids = {}
        self.stop_requested = False
        self.api_helper = ApiHelper(self)
        
        header_bar = HeaderBar(resource_path("NIRIX Logo.png"), resource_path("TVS logo white.png"))

        config_data = load_station_config()
        log_folder = config_data.get("log_folder", r"D:\Nirixx\Trace")
        
        
        
        try:
            log_cleanup_module = importlib.import_module("log_cleanup")
            log_cleanup_module.cleanup_old_logs(log_folder)
        except ImportError as e:
            print(f"Failed to import log_cleanup.py: {e}")
        except AttributeError as e:
            print(f"Failed to call cleanup_old_logs in log_cleanup.py: {e}")
        except Exception as e:
            print(f"Error executing log_cleanup.py: {e}")

        self.setWindowTitle("TVS NIRIX")
        self.setStyleSheet("background-color: white;")
        self.setWindowState(Qt.WindowMaximized)
        screen = QApplication.desktop().screenGeometry()
        self.setGeometry(0, 0, screen.width(), screen.height())
        self.setWindowFlags(self.windowFlags() & ~Qt.FramelessWindowHint)

        pc_name = socket.gethostname()
        config_data = load_station_config()
        operation_number = config_data.get("operation_no", "N/A")

        top_row = QHBoxLayout()
        top_row.setSpacing(20)
        top_row.setContentsMargins(20, 20, 20, 0)
        
        self.version = "0926_V1.8.12.0"

        program_box = InfoBox("J107-Flashing/Static/IMU/RVS", self.version)
        self.cycle_time_box = CycleTimeBox()
        pc_box = InfoBox("PC Name:", pc_name)
        op_box = InfoBox("Operation No:", operation_number)
        emp_box = EditableInfoBox("Emp No:")
        self.api_selector = ApiSelector(parent=self)

        top_row.addWidget(program_box)
        top_row.addWidget(pc_box)
        top_row.addWidget(op_box)
        top_row.addWidget(emp_box)
        top_row.addWidget(self.api_selector)
        top_row.addStretch(1)

        second_row = QHBoxLayout()
        second_row.setContentsMargins(20, 10, 20, 20)

        self.vin_box = LabeledEntryBox("Identifier Number:", "Eg: MD612345678912345", max_length=17)
        self.vin_input = self.vin_box.entry
        self.vin_input.installEventFilter(self)
        self.vin_input.returnPressed.connect(self.start_test_cases)

        self.second_sub_box = LabeledEntryBox("Part Number:", "SKU", max_length=10)

        side_vbox = QVBoxLayout()
        side_vbox.addWidget(self.vin_box)
        side_vbox.addWidget(self.second_sub_box)
        side_vbox.addStretch()

        station_config = load_station_config()
        active_library_default = station_config.get("active_library", "J107_Flashing")
        raw = config_data.get("available_libraries", "")
        available_libraries = [item.strip() for item in raw.split(",") if item.strip()]
        self.active_library_selector = ActiveLibrarySelector(available_libraries, active_library_default)

        active_row = QHBoxLayout()
        active_row.addWidget(self.active_library_selector)
        active_row.addSpacing(12)
        active_row.addStretch()
        
        # Progress bar (no change)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                color: black;
                border: 2px solid #003B6F;
                border-radius: 15px;
                text-align: center;
                height: 30px;
                font-size: 40px;
                width: 50%;
            }
            QProgressBar::chunk {
                background-color: #008000;
                border-radius: 15px;
            }
        """)
        
        side_active_process_bar_box = QVBoxLayout()
        side_active_process_bar_box.addLayout(active_row)  # <-- Replace selector placement
        side_active_process_bar_box.addSpacing(25)
        side_active_process_bar_box.addWidget(self.progress_bar)
        side_active_process_bar_box.addStretch()
        
        # Final row assembly
        second_row.addWidget(self.cycle_time_box)
        second_row.addLayout(side_vbox)
        second_row.addLayout(side_active_process_bar_box)
        

        third_row = QHBoxLayout()
        third_row.setContentsMargins(20, 0, 20, 20)

        self.test_table = QTableWidget()
        self.test_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                alternate-background-color: #c9ccce;
                color: black;
                font-size: 24px;
                font-family: 'Segoe UI', sans-serif;
                border: none;
                border-radius: 12px;
                gridline-color: transparent;  
                selection-background-color: #FF0033;  /* torch red */
                selection-color: white;
            }
        
            QHeaderView::section {
                background-color: #003B6F;  /* smalt blue */
                color: white;
                font-size: 26px;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-bottom: 2px solid #FF0033;
            }
        
            QTableWidget::item {
                padding: 14px;
                border: none;
            }
        
            QTableWidget::item:hover {
                background-color: #f5f5f5;
            }
        
            QTableWidget::item:selected {
                background-color: #FF0033;
                color: white;
            }
        
            QScrollBar:vertical {
                border: none;
                background: #e0e0e0;
                width: 18px;
                margin: 2px 0 2px 0;
                border-radius: 9px;
            }
        
            QScrollBar::handle:vertical {
                background: #003B6F;
                min-height: 25px;
                border-radius: 9px;
            }
        
            QScrollBar::handle:vertical:hover {
                background: #0055aa;
            }
        
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-origin: margin;
            }
        
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        
            QScrollBar:horizontal {
                border: none;
                background: #e0e0e0;
                height: 18px;
                margin: 0px 2px 0px 2px;
                border-radius: 9px;
            }
        
            QScrollBar::handle:horizontal {
                background: #003B6F;
                min-width: 25px;
                border-radius: 9px;
            }
        
            QScrollBar::handle:horizontal:hover {
                background: #0055aa;
            }
        
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                subcontrol-origin: margin;
            }
        
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """)
        
        self.test_table.setAlternatingRowColors(True)
        self.test_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.test_table.verticalHeader().setVisible(False)
        self.test_table.verticalHeader().setDefaultSectionSize(60)
        self.test_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.test_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.test_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.test_table.setMinimumHeight(400)
        self.test_table.setMaximumHeight(800)
        
        self.pass_image_label = QLabel()
        self.fail_image_label = QLabel()
        
        self.pass_image_label.setFixedSize(120, 120)
        self.fail_image_label.setFixedSize(120, 120)
        
        self.pass_image_label.setScaledContents(True)
        self.fail_image_label.setScaledContents(True)
        
        # Initially hide both
        self.pass_image_label.hide()
        self.fail_image_label.hide()
        
        common_textedit_style = ("""
            QTextEdit {
                background-color: white;
                color: #1a1a1a;
                font-size: 20px;
                font-weight: bold;
                border: 2px solid #003B6F;
                border-radius: 12px;
                padding: 10px;
            }
            
            QTextEdit:hover {
                background-color: #f1f1f1;
            }
            
            QScrollBar:vertical {
                border: none;
                background: #e0e0e0;
                width: 18px;
                margin: 2px 0 2px 0;
                border-radius: 9px;
            }
            
            QScrollBar::handle:vertical {
                background: #003B6F;
                min-height: 25px;
                border-radius: 9px;
            }
            
            QScrollBar::handle:vertical:hover {
                background: #0055aa;
            }
            
            QScrollBar:horizontal {
                border: none;
                background: #e0e0e0;
                height: 18px;
                margin: 0px 2px 0px 2px;
                border-radius: 9px;
            }
            
            QScrollBar::handle:horizontal {
                background: #003B6F;
                min-width: 25px;
                border-radius: 9px;
            }
            
            QScrollBar::handle:horizontal:hover {
                background: #0055aa;
            }
            """)
        
        instruction_label = QLabel("Instructions:")
        #instruction_label.setStyleSheet("color: black; font-size: 25px; font-weight: bold; margin-bottom: 5px;")
        instruction_label.setStyleSheet("color: #003D6F; font-size: 28px; font-weight: bold; margin-bottom: 5px;")


        self.instruction_box = QTextEdit()
        self.instruction_box.setReadOnly(True)
        self.instruction_box.setStyleSheet(common_textedit_style)
        self.instruction_box.setPlaceholderText("Instructions will appear here...")
        self.instruction_box.setMinimumWidth(300)

        result_label = QLabel("Result:")
        #result_label.setStyleSheet("color: black; font-size: 25px; font-weight: bold; margin-bottom: 5px;")
        result_label.setStyleSheet("color: #003D6F; font-size: 28px; font-weight: bold; margin-bottom: 5px;")


        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setStyleSheet(common_textedit_style)
        self.result_box.setPlaceholderText("Result will appear here...")
        self.result_box.setMinimumWidth(300)
        
        self.reset_button = QPushButton("RESET")
        self.reset_button.setFixedHeight(42)
        self.reset_button.setFixedWidth(110)
        self.reset_button.setCursor(Qt.PointingHandCursor)
        
        self.reset_button.setStyleSheet("""
            QPushButton {
                background-color: #004A8F;        /* Deep TVS Corporate Blue */
                color: white;
                border: none;
                border-radius: 18px;              /* Smooth modern pill */
                padding: 10px 26px;
                font-size: 16px;
                font-weight: 600;
                letter-spacing: 0.6px;
                box-shadow: 0px 4px 10px rgba(0, 40, 90, 0.35);
            }
        
            QPushButton:hover {
                background-color: #0063C6;        /* Slightly Brighter on hover */
                box-shadow: 0px 6px 14px rgba(0, 70, 150, 0.45);
                transform: translateY(-2px);
            }
        
            QPushButton:pressed {
                background-color: #00315C;        /* Slightly darker press */
                box-shadow: 0px 2px 6px rgba(0, 40, 90, 0.3);
                transform: translateY(0px);
            }
        """)
       
        self.reset_button.clicked.connect(self.handle_reset_button)
        # Right aligned row for reset button
        reset_button_row = QHBoxLayout()
        reset_button_row.addStretch()
        reset_button_row.addWidget(self.reset_button)
        reset_button_row.setContentsMargins(0, 0, 0, 10)
        
        instruction_result_layout = QVBoxLayout()
        instruction_result_layout.addLayout(reset_button_row)
        instruction_result_layout.addWidget(instruction_label)
        instruction_result_layout.addWidget(self.instruction_box, stretch=1)
        instruction_result_layout.addWidget(result_label)
        instruction_result_layout.addWidget(self.result_box, stretch=1)
        instruction_result_layout.addStretch()
        instruction_result_layout.addWidget(self.pass_image_label, alignment=Qt.AlignRight)
        instruction_result_layout.addWidget(self.fail_image_label, alignment=Qt.AlignRight)

        third_row.addWidget(self.test_table, stretch=2)
        third_row.addSpacing(20)
        third_row.addLayout(instruction_result_layout, stretch=1)
        
        # ----- Footer Label -----
        footer_label = QLabel("2026 PED@CT&T. All rights reserved.")
        footer_label.setAlignment(Qt.AlignCenter)
        footer_label.setFixedHeight(40)  # Adjust the height as needed
        footer_label.setStyleSheet("""
            background-color: #003D6F;
            color: white;
            font-size: 11pt;
            padding-top: 8px;
        """)

        main_layout = QVBoxLayout()
        main_layout.addWidget(header_bar)
        self.active_library_selector.combo_box.currentTextChanged.connect(self.on_active_library_changed)
        self.active_library_selector.combo_box.installEventFilter(self)
        self.test_table.installEventFilter(self)
        self.test_table.horizontalHeader().installEventFilter(self)
        self.api_selector.btn_prd.installEventFilter(self)
        self.api_selector.btn_ejo.installEventFilter(self)
        main_layout.addLayout(top_row)
        main_layout.addLayout(second_row)
        main_layout.addLayout(third_row, stretch=1)
        main_layout.addWidget(footer_label)
        self.setLayout(main_layout)
        self.result_overlay = ResultOverlay(self)
        # dhinakar added -2 lines
        #self.result_overlay.dismiss_requested.connect(self.clear_fail_screen)
        self.result_overlay.dismiss_requested.connect(self.clear_result_screen)
        self.result_overlay.setGeometry(0, 0, self.width(), self.height())
        self.result_overlay.raise_()
        self.load_tests_from_sku("N6191260", self.active_library_selector.get_selected_library())
        self.api_helper.show_message_signal.connect(self.instruction_box.append)
        self.api_helper.reset_ui_signal.connect(self.reset_input_and_timer)

        self.scanner_signals = ScannerSignalEmitter()
        self.scanner_signals.vin_scanned.connect(self.handle_scanned_vin)

        connection_mode, ports, baudrate = load_scanner_config()
        self.connection_mode = connection_mode
        self.ports = ports
        self.baudrate = baudrate
        self.serial_reader_thread = None
        self.hid_thread = None
        self.scanner_mode = None
        self.detect_scanner_mode()
        self.prepare_for_next_cycle()

# Dhinakar changes clear_fail_screen method
    # def clear_fail_screen(self):
    #     if not self.fail_screen_active:
    #         return
    def clear_result_screen(self):
        self.fail_screen_active = False
        self.pass_screen_active = False
        self.result_overlay.hide_result()
        self.reset_for_next_cycle()

    def resizeEvent(self, event):
        # keep the overlay full-size
        try:
            if hasattr(self, "result_overlay") and self.result_overlay:
                self.result_overlay.setGeometry(0, 0, self.width(), self.height())
        except Exception:
            pass
        return super().resizeEvent(event)

    def _should_keep_pass_result_screen(self):
        try:
            config_data = load_station_config()
            flag_value = config_data.get("pass_result_screen", "false")

            flag_text = str(flag_value).strip().lower()
            if flag_text in {"1", "true", "yes", "on"}:
                return True
            if flag_text in {"0", "false", "no", "off", ""}:
                return False
            return False
        except Exception as e:
            print(f"Error reading Pass_Result_Screen flag: {e}")
            return False
        
    def stop_current_cycle(self):
        try:
            if self.worker:
                self.worker.stop_requested = True
            if self.worker_thread:
                self.worker_thread.quit()
                self.worker_thread.wait()
            self.test_cycle_active = False
            print("✅ Test cycle force-stopped")
        except Exception as e:
            print(f"Error stopping worker: {e}")
            
    def show_final_result_screen(self, is_pass: bool):
        """Show the overlay for 2 seconds, then hide and reset UI."""
        vin = self.current_vin or self.vin_input.text().strip()
        try:
            # Dhinakar added -3 lines
            fail_instructions = self.instruction_box.toPlainText()
            fail_results = self.result_box.toPlainText()
            self.result_overlay.show_result(vin,is_pass,fail_instructions,fail_results)

            # self.result_overlay.show_result(vin, is_pass)
        except Exception as e:
            print(f"Error showing result overlay: {e}")

        # Dhinakar changes -10 lines
        # Save results right away
        try:
            QTimer.singleShot(100, self.save_results_to_log)
        except Exception:
            pass
        self.test_cycle_active = False
        if is_pass:
            self.fail_screen_active = False
            self.pass_screen_active = True
            if not self._should_keep_pass_result_screen():
                QTimer.singleShot(1500, self._close_result_screen)
        else:
            self.fail_screen_active = True
            self.pass_screen_active = False

        # # Hide overlay after 2 seconds and then reset UI
        # QTimer.singleShot(2000, self._close_result_screen)

    

    def _close_result_screen(self):
        self.fail_screen_active = False
        self.pass_screen_active = False
        #self.result_overlay.hide_result()
        if hasattr(self, "result_overlay") and self.result_overlay:
            self.result_overlay.hide_result()
        try:
            self.reset_for_next_cycle()
        except Exception as e:
            print(f"Error resetting UI after overlay close: {e}")

            
    def handle_reset_button(self):
        self.stop_current_cycle()     
        self.reset_for_next_cycle()

    def detect_scanner_mode(self):
        ports = serial.tools.list_ports.comports()
        available_ports = [p.device for p in ports]
    
        if any(port in available_ports for port in self.ports):
            self.scanner_mode = "CDC"
            print("CDC Scanner detected")
        else:
            self.scanner_mode = "HID"   # fallback
            print("Assuming HID scanner (keyboard mode)")

    def start_com_scanner(self):
        ports = serial.tools.list_ports.comports()
        available_ports = [p.device for p in ports]
        print(f"Checking ports: {self.ports}, Available: {available_ports}")

        usb_serial_ports = []
        for port in ports:
            if port.device in self.ports and ("USB" in port.description or "CDC" in port.description):
                usb_serial_ports.append(port.device)

        if not usb_serial_ports:
            print("No USB serial ports available")
            return

        max_retries = 3
        scanner_started = False

        for port in usb_serial_ports:
            for attempt in range(max_retries):
                try:
                    if self.serial_reader_thread:
                        print(f"Stopping previous serial reader thread before trying {port}")
                        self.serial_reader_thread.stop()
                        self.serial_reader_thread.wait()

                    self.serial_reader_thread = SerialReaderThread(port, self.baudrate)
                    self.serial_reader_thread.vin_received.connect(self.handle_scanned_vin)
                    self.serial_reader_thread.start()

                    print(f"CDC Scanner started on port {port} (attempt {attempt + 1})")
                    scanner_started = True
                    break

                except PermissionError as pe:
                    print(f"PermissionError on {port} (attempt {attempt + 1}): {pe}")
                except Exception as e:
                    print(f"Attempt {attempt + 1}/{max_retries} on {port} failed: {e}")

                time.sleep(1)

            if scanner_started:
                break

        if not scanner_started:
            print("All attempts failed on all USB serial ports.")

    def start_hid_scanner(self):
        def read_hid_input():
            try:
                vin = ""
                while True:
                    char = sys.stdin.read(1)
                    if char == '\r' or char == '\n':
                        if vin:
                            print(f"HID Scanner: Scanned VIN: {vin}")
                            self.scanner_signals.vin_scanned.emit(vin)
                            break
                    elif char == '\b':
                        vin = vin[:-1]
                    elif char.isalnum():
                        vin += char
            except Exception as e:
                print(f"HID Scanner error: {e}")

        self.hid_thread = threading.Thread(target=read_hid_input, daemon=True)
        self.hid_thread.start()
        print("Started HID scanner")

    def handle_scanned_vin(self, vin):
        # Dhinakar added -2 lines
        # if self.result_overlay.isVisible():
        #    self.result_overlay.hide_result()

        print(f"handle_scanned_vin: Received VIN: {vin}")

        if self.pass_screen_active or self.fail_screen_active:
           self.clear_result_screen()

        self.vin_input.setText(vin)
        self.vin_input.repaint()
        self.start_test_cases()
        if self.serial_reader_thread:
            print("handle_scanned_vin: Stopping serial reader thread")
            self.serial_reader_thread.stop()
            self.serial_reader_thread = None
        if self.hid_thread:
            print("handle_scanned_vin: Stopping HID reader thread")
            self.hid_thread = None

    def _restore_vin_focus(self):
        if hasattr(self, "vin_input"):
            self.vin_input.setFocus()

    def eventFilter(self, source, event):
        if source == self.vin_input and event.type() == QEvent.FocusIn:
            self.detect_scanner_mode()
            if self.scanner_mode == "CDC":
                if self.serial_reader_thread:
                    print("eventFilter: Stopping existing serial reader thread")
                    self.serial_reader_thread.stop()
                self.start_com_scanner()
            elif self.scanner_mode == "HID":
                if self.hid_thread:
                    print("eventFilter: Stopping existing HID reader thread")
                    self.hid_thread = None
                self.start_hid_scanner()
        elif source in (self.api_selector.btn_prd, self.api_selector.btn_ejo, self.test_table, self.active_library_selector.combo_box) and event.type() in (QEvent.MouseButtonRelease, QEvent.FocusOut):
            QTimer.singleShot(0, self._restore_vin_focus)        
        return super().eventFilter(source, event)
    
    def on_active_library_changed(self):
        active_library = self.active_library_selector.get_selected_library()
    
        if active_library == "3W_Battery_Healthcheck":
            self.vin_input.setPlaceholderText("Enter 12-digit Battery Number")
            self.api_selector.setDisabled(True)
            self.second_sub_box.setDisabled(True)
        else:
            self.vin_input.setPlaceholderText("Scan 17-digit VIN starting with MD6")
            self.api_selector.setDisabled(False)
            self.second_sub_box.setDisabled(False)
        if active_library == "3W_Battery_Healthcheck":
            self.vin_input.setMaxLength(12)
        else:
            self.vin_input.setMaxLength(17)

        self.vin_input.setFocus()
            
    def load_sentinel_return_codes(excel_path=r"D:\TVS NIRIX Flashing\Sentinel\sentinel_return_codes.xlsx.enc"):
        excel_path = resource_path(
        os.path.join("Sentinel", "sentinel_return_codes.xlsx.enc")
        )
    
        df = pd.read_excel(excel_path)
        return {
            int(row["ExitCode"]): str(row["Message"])
            for _, row in df.iterrows()
        }

    def prepare_for_next_cycle(self):
        self.vin_input.clear()
        self.vin_input.setFocus()
        self.detect_scanner_mode()
        if self.scanner_mode == "CDC":
            self.start_com_scanner()
        elif self.scanner_mode == "HID":
            self.start_hid_scanner()
        else:
            print("No Scanner Detected")
        self.on_active_library_changed()

    def reset_for_next_cycle(self):
        try:
            if hasattr(self, "worker"):
                self.worker.stop_requested = True  # Signal stop to worker
    
            if hasattr(self, "worker_thread") and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
                print("Worker and thread stopped.")
        except Exception as e:
            print(f"Error stopping worker thread: {e}")
    
        # --- RESET STATE VARIABLES ---
        self.current_test_index = 0
        self.test_results = []
        self.test_times = []
        self.final_status = "OK"
        self.vin_input.setText("")
        self.cumulative_time = 0
        self.second_sub_box.entry.setText("")
        self.test_failed = False
        self.start_time = None
    
        # --- RESET UI ELEMENTS ---
        self.progress_bar.setValue(0)
        self.instruction_box.clear()
        self.instruction_box.append("Scan VIN to start next test cycle...")
        self.result_box.clear()
        self.cycle_time_box.stop_timer()
        self.cycle_time_box.reset_timer()
    
        # Re-enable VIN input field
        self.vin_input.setReadOnly(False)
        self.vin_input.setStyleSheet("""
            QLineEdit {
                font-size: 26px;
                padding: 8px;
                border: 2px solid #D3D3D3;
                border-radius: 6px;
                background-color: #F0F0F0;
                color: black;
            }
            QLineEdit:hover {
                border: 2px solid #FF0033;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #003B6F;
                background-color: white;
            }
        """)
        self.vin_input.clearFocus()
        self.vin_input.setFocus()
    
        # --- CLEAR TABLE COLORS & VALUES ---
        for row in range(self.test_table.rowCount()):
            for col in range(self.test_table.columnCount()):
                item = self.test_table.item(row, col)
                if item:
                    item.setBackground(QColor("#ffffff"))
                    item.setForeground(QColor("black"))
    
            # Clear Actual Value & Result columns
            self.test_table.setItem(row, self.test_table.columnCount() - 2, QTableWidgetItem(""))
            self.test_table.setItem(row, self.test_table.columnCount() - 1, QTableWidgetItem(""))
            self.test_table.removeCellWidget(row, self.test_table.columnCount() - 1)
    
        self.test_cases = []
        self.sku = None
        self.json_response = None
    
        # --- RESET SCROLL POSITION ---
        self.test_table.verticalScrollBar().setValue(0)
    
        # --- CLEAR LIBRARY MODULE CACHE ---
        importlib.invalidate_caches()
        active_library = self.active_library_selector.get_selected_library()
    
        for module_name in list(sys.modules.keys()):
            if module_name.startswith(active_library):
                del sys.modules[module_name]
                print(f"Cleared module cache: {module_name}")
    
        # --- STOP SERIAL/HID THREADS IF RUNNING ---
        if hasattr(self, "serial_reader_thread") and self.serial_reader_thread:
            print("Stopping serial reader thread...")
            self.serial_reader_thread.stop()
            self.serial_reader_thread = None
    
        if hasattr(self, "hid_thread") and self.hid_thread:
            print("Stopping HID reader thread...")
            self.hid_thread = None
    
        # --- SHUTDOWN CAN BUS ---
        try:
            import can
            can.rc['interface'] = 'pcan'
            can.rc['channel'] = 'PCAN_USBBUS1'
            bus = can.interface.Bus()
            bus.shutdown()
            print("CAN bus shutdown successful.")
        except Exception as e:
            print(f"CAN bus shutdown failed: {e}")
    
        # --- PREPARE AGAIN FOR NEXT VIN ---
        self.prepare_for_next_cycle()
        print("System Reset Complete")

    
    def fetch_flash_file_name_from_api(self, vin_number, api_url):
        """
        Fetches and returns the flashfilename for the given VIN from the API.
        Returns None if flashfilename is not found or API fails.
        """
        try:
            response = requests.get(api_url, timeout=5)
    
            if response.status_code != 200:
                print(f"API Error: Status {response.status_code}")
                return None
    
            json_data = response.json()
            modules = json_data.get("data", {}).get("modules", [])
    
            for module in modules:
                flash_file = module.get("flashfilename")
                if flash_file:
                    print(f"[Flash File Fetched: {flash_file}]")
                    return flash_file  #return immediately once found
    
            print("Flash file Name not found in response.")
            self.reset_input_and_timer(clear_input=False)
            return None
    
        except requests.RequestException as e:
            print(f"API Request Failed: {e}")
            return None
        
    def resolve_flash_file(self, flash_file_name):

        # Local flash storage path
        local_storage = resource_path("Storage")
        local_file_path = os.path.join(local_storage, flash_file_name)
    
        # 1. Check if file already exists locally
        if os.path.isfile(local_file_path):
            print(f"[FLASH FILE] Using local file: {local_file_path}")
            return local_file_path
    
        print("[FLASH FILE] Local file not found, preparing to fetch from server...")
    
        # 2. Read paths from api.ini.enc
        from security_manager import (read_encrypted_ini,MASTER_PASSWORD)
        config = read_encrypted_ini("api.ini.enc", MASTER_PASSWORD)
    
        selected_mode = self.api_selector.get_selected_api()   # PRD or EJO
    
        remote_folder = config.get("FLASHFILE", selected_mode, fallback=None)
    
        if not remote_folder:
            self.instruction_box.append(f"<span style='color:red;'>FLASH FILE paths missing in api.ini.enc for {selected_mode}.</span>")
            self.reset_input_and_timer(clear_input=False)
            return None
    
        remote_file_path = os.path.join(remote_folder, flash_file_name)
    
        # 3. Check file exists in remote location
        if not os.path.isfile(remote_file_path):
            self.instruction_box.append(
                f"<span style='color:red;'>FLASH FILE {flash_file_name} not found in server path</span>"
            )
            self.reset_input_and_timer(clear_input=False)
            return None
    
        # 4. Copy from server → local
        try:
            if not os.path.exists(local_storage):
                os.makedirs(local_storage)
    
            print(f"[Flash File] Copying from {remote_file_path} → {local_file_path}")
            shutil.copy(remote_file_path, local_file_path)
    
            self.instruction_box.append(
                f"<span style='color:green;'>FLASH FILE copied to local storage successfully.</span>"
            )
            return local_file_path
    
        except Exception as e:
            self.instruction_box.append(f"<span style='color:red;'>Failed to copy flash file: {e}</span>")
            self.reset_input_and_timer(clear_input=False)
            return None
    
    def reset_input_and_timer(self, clear_input=True):
        self.vin_input.setReadOnly(False)
        if clear_input:
            self.vin_input.setText("")
        self.vin_input.clearFocus()
        self.vin_input.setFocus()
        self.cycle_time_box.stop_timer()
        self.cycle_time_box.reset_timer()
        self.test_cycle_active = False
             
    def update_test_result_row(self, row_index, actual_value, result):
        active_library = self.active_library_selector.get_selected_library()
        actual_value_col = 6 if active_library in [ "J107_Flashing", "J107_Static", "J107_IMU", "J107_RVS"] else 3
        result_col = 7 if active_library in [ "J107_Flashing", "J107_Static", "J107_IMU", "J107_RVS"] else 4

        #Update actual value normally ---
        self.test_table.setItem(row_index, actual_value_col, QTableWidgetItem(str(actual_value)))
    
        #Create QLabel for image ---
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
    
        result_text = str(result).upper()
        if result_text in ["PASS", "PASSED"]:
            pixmap = QPixmap(resource_path("Pass picture.png"))
            logical_result = "PASS"
        elif result_text in ["FAIL", "FAILED"]:
            pixmap = QPixmap(resource_path("fail picture.png"))
            logical_result = "FAIL"
        else:
            pixmap = QPixmap()
            logical_result = "NA"
    
        # Resize image and assign
        pixmap = pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        label.setPixmap(pixmap)
    
        #Remove any existing widget and set new one ---
        self.test_table.removeCellWidget(row_index, result_col)
        self.test_table.setCellWidget(row_index, result_col, label)
    
        #Also store logical result text invisibly ---
        hidden_item = QTableWidgetItem(logical_result)
        hidden_item.setData(Qt.UserRole, logical_result)
        hidden_item.setFlags(Qt.ItemIsEnabled)  # not editable
        self.test_table.setItem(row_index, result_col, hidden_item)

    
    def on_sku_changed(self, new_sku):
        active_library = self.active_library_selector.get_selected_library()
        self.load_tests_from_sku(new_sku, active_library)

    def load_tests_from_sku(self, sku_number, active_library):
        active_library = self.active_library_selector.get_selected_library()
        if active_library == "3W_Battery_Healthcheck":
            battery_number = self.vin_input.text().strip()
            if not battery_number:
                return
            if len(battery_number) != 12:
                self.instruction_box.append("Invalid Battery Number. Please enter a 12-digit number.")
                return
        
            battery_name = self.get_battery_name_dynamic(battery_number)
        
            if not battery_name:
                self.instruction_box.append("No mapping found for this battery number prefix.")
                return
        
            test_file_name = f"{battery_name} - details.xlsx.enc"
            full_path = resource_path(os.path.join("Battery Specification", test_file_name))

        else:
            print(f"Loading tests for SKU: {sku_number}, Library: {active_library}")
            active_library = self.active_library_selector.get_selected_library()
            test_file_name, matched_library = get_file_name_from_sku(sku_number, active_library)
            
            print(test_file_name, matched_library)

            if not test_file_name:
                raise ValueError("No SKU file found for this SKU and library")           
            full_path = resource_path(os.path.join("sku_files", test_file_name))

        if not os.path.isfile(full_path):
            print(f"[ERROR] Test file not found: {full_path}")
            self.instruction_box.append(f"Test file for SKU '{sku_number}' not found.")
            self.test_table.setRowCount(0)
            return

        try:
            from security_manager import (read_encrypted_excel,MASTER_PASSWORD)
            df = read_encrypted_excel(full_path,MASTER_PASSWORD)
        except Exception as e:
            print(f"Failed to read test file: {e}")
            self.instruction_box.append(f"Failed to read test file: {e}")
            self.test_table.setRowCount(0)
            return

        self.test_table.setRowCount(0)

        if active_library in ["J107_Flashing", "J107_Static", "J107_IMU", "J107_RVS"]:
            self.test_table.setColumnCount(8)
            self.test_table.setHorizontalHeaderLabels([
                "S.No", "Test Sequence", "Parameter", "Value", "LSL", "USL", "Actual Value", "Result"
            ])
            self.test_table.setColumnWidth(0, 80)
            self.test_table.setColumnWidth(1, 250)
            self.test_table.setColumnWidth(2, 150)
            self.test_table.setColumnWidth(3, 150)
            self.test_table.setColumnWidth(4, 90)
            self.test_table.setColumnWidth(5, 90)
            self.test_table.setColumnWidth(6, 200)
            self.test_table.setColumnWidth(7, 200)
        else:  # TPMS
            self.test_table.setColumnCount(5)
            self.test_table.setHorizontalHeaderLabels([
                "S.No", "Test Sequence", "Parameter", "Actual Value", "Result"
            ])
            self.test_table.setColumnWidth(0, 60)
            self.test_table.setColumnWidth(1, 400)
            self.test_table.setColumnWidth(2, 250)
            self.test_table.setColumnWidth(3, 250)
            self.test_table.setColumnWidth(4, 200)

        for idx, row in df.iterrows():
            self.test_table.insertRow(idx)
            columns = ["S.No", "Test Sequence", "Parameter", "Value", "LSL", "USL"] if active_library in ["J107_Flashing", "J107_Static", "J107_IMU", "J107_RVS"] else ["S.No", "Test Sequence", "Parameter"]
            for col_idx, key in enumerate(columns):
                self.test_table.setItem(idx, col_idx, QTableWidgetItem(str(row.get(key, ''))))
                
            # Add empty items for 'Actual Value' and 'Result' to avoid NoneType errors
            self.test_table.setItem(idx, 6, QTableWidgetItem(""))  # Actual Value
            self.test_table.setItem(idx, 7, QTableWidgetItem(""))  # Result
            
    def get_battery_name_dynamic(self, battery_number):
        from security_manager import (read_encrypted_excel,MASTER_PASSWORD)
        mapping_file = resource_path("Battery Mapping.xlsx.enc")
        try:
            df = read_encrypted_excel(mapping_file, MASTER_PASSWORD)
    
            # Ensure correct column names
            df.columns = [str(col).strip().replace('\u200b', '') for col in df.columns]
            if "Battery Type" not in df.columns or "Battery Name" not in df.columns:
                raise ValueError("Battery Mapping file is missing required columns.")

            # Take first 3 characters of battery_number
            prefix = battery_number[:3]
    
            # Find matching row
            row = df[df["Battery Type"] == prefix]
            if not row.empty:
                return row.iloc[0]["Battery Name"]
    
        except Exception as e:
            print(f"[ERROR] Failed to load battery mapping: {e}")
            self.instruction_box.append(f"Error reading Battery Mapping: {e}")    
        return None
    
    def append_to_log_file(self, text):
        """Thread-safe log collector for test result capturing."""
        if not hasattr(self, "current_test_log"):
            self.current_test_log = ""   
        self.current_test_log += text

    def fetch_sku_from_api(self, vin, base_url, active_library):
        self.api_helper.fetch_sku_from_api(vin, base_url, active_library)

    def parse_test_file(self, file_path):
        try:
            from security_manager import (read_encrypted_excel,MASTER_PASSWORD)
            df = read_encrypted_excel(file_path, MASTER_PASSWORD)
            if "Test Sequence" not in df.columns:
                self.instruction_box.append("No test sequence")
                print("[ERROR] 'Test Sequence' column missing in Excel.")
                return []
            test_cases = []
            for test_name in df["Test Sequence"].dropna():
                clean_name = str(test_name).strip().replace(" ", "_")
                test_cases.append((clean_name, clean_name))
            return test_cases
        except Exception as e:
            print(f"[ERROR] Failed to parse test file '{file_path}': {e}")
            return []
        
    def get_active_library_path(self, active_library):
        if getattr(sys, 'frozen', False):
            # Executable mode
            base_path = os.path.dirname(sys.executable)
        else:
            # Normal Python mode
            base_path = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_path, active_library)

    def on_sku_fetched(self, sku):
        active_library = self.active_library_selector.get_selected_library()
    
        # === NEW FLOW for Battery Healthcheck ===
        if active_library == "3W_Battery_Healthcheck":
            battery_number = self.vin_input.text()
    
            battery_name = self.get_battery_name_dynamic(battery_number)
            if not battery_name:
                self.instruction_box.append(f"No battery mapping found for number: {battery_number}")
                return
    
            test_file_name = f"{battery_name} - details.xlsx.enc"
            full_path = resource_path(os.path.join("Battery Specification", test_file_name))
    
            if not os.path.exists(full_path):
                self.instruction_box.append(f"Test file '{test_file_name}' not found in Battery Specification folder.")
                self.cycle_time_box.stop_timer()
                self.cycle_time_box.reset_timer()
                return
    
            self.test_file_path = full_path
            self.test_cases = self.parse_test_file(self.test_file_path)
            if not self.test_cases:
                self.instruction_box.append("No test cases found in the test file.")
                self.cycle_time_box.stop_timer()
                self.cycle_time_box.reset_timer()
                return
    
            # Set correct library path (internal for EXE, external for dev mode)
            self.active_library_path = self.get_active_library_path(active_library)
            if not os.path.isdir(self.active_library_path):
                self.instruction_box.append(f"Active library folder '{active_library}' not found.")
                self.cycle_time_box.stop_timer()
                self.cycle_time_box.reset_timer()
                return
    
            self.load_tests_from_sku(battery_number, active_library)
    
            self.current_test_index = 0
            self.test_results = []
            self.test_times = []
            self.cumulative_time = 0.0
            self.start_time = time.time()
            self.final_status = "OK"
            self.run_next_test()
            return
    
        # === OLD FLOW for Diagnostics / TPMS ===
        if sku == "ERROR":
            selected_mode = self.api_selector.get_selected_api()
            mode_display = "Production (PRD)" if selected_mode == "PRD" else "Engineering Job Order (EJO)"
            self.instruction_box.setText(f'<span style="color:red;">Scanned VIN number is not in the Selected Mode: {mode_display}.</span>')
            self.vin_input.setText("")
            self.vin_input.clearFocus()
            self.vin_input.setFocus()
            self.cycle_time_box.stop_timer()
            self.cycle_time_box.reset_timer()
            self.test_cycle_active = False
            return
    
        self.second_sub_box.set_value(sku)
        self.on_sku_changed(sku)
        self.sku = sku
    
        test_file_name, matched_library = get_file_name_from_sku(sku, active_library)
        test_file = resource_path(os.path.join("sku_files", test_file_name))
        if not os.path.exists(test_file):
            self.instruction_box.append(f"Test file for SKU '{sku}' not found.")
            self.reset_input_and_timer()
            return 
    
        self.test_file_path = test_file
    
        if not active_library:
            self.instruction_box.append("Missing 'active_library' in station.ini.enc")
            self.cycle_time_box.stop_timer()
            self.cycle_time_box.reset_timer()
            return
    
        self.active_library = active_library
    
        # Set correct library folder path
        self.active_library_path = self.get_active_library_path(active_library)
        if not os.path.isdir(self.active_library_path):
            self.instruction_box.append(f"Active library folder '{active_library}' not found.")
            self.cycle_time_box.stop_timer()
            self.cycle_time_box.reset_timer()
            return
    
        self.test_cases = self.parse_test_file(self.test_file_path)
        if not self.test_cases:
            self.instruction_box.append("No test cases found in the test file.")
            self.cycle_time_box.stop_timer()
            self.cycle_time_box.reset_timer()
            return
    
        self.current_test_index = 0
        self.test_results = []
        self.test_times = []
        self.cumulative_time = 0.0
        self.start_time = time.time()
        self.final_status = "OK"
        self.run_next_test()

# Dhinakar changed start_test_cases method
    def start_test_cases(self):
        # Ignore Enter if a test cycle is already running
        if self.test_cycle_active:
            print("Test cycle already running; ignoring Enter press.")
            return
        # Enter pressed while FAIL screen is displayed
        #if self.fail_screen_active:
        #    self.clear_fail_screen()
        if self.fail_screen_active or self.pass_screen_active:
            self.clear_result_screen()
            return
        vin_number = "".join(self.vin_input.text().split()).upper()
        if not vin_number:
            return
    
        self.instruction_box.setText('')
        active_library = self.active_library_selector.get_selected_library()
        if active_library == "Sedemac_RVS_Station":
            self.instruction_box.append(
                "<span style='color:#4AA3FF; font-weight:bold; font-size:40px; font-family:Segoe UI;'>"
                "Please turn on the engine"
                "</span>"
            )
        if (
            (active_library == "3W_Battery_Healthcheck" and len(vin_number) != 12) or
            (active_library != "3W_Battery_Healthcheck" and (not vin_number.startswith("MD6") or len(vin_number) != 17))
        ):    
            self.instruction_box.append("Invalid identifier. Please scan a valid identifier.")
            self.vin_input.setText("")
            self.cycle_time_box.stop_timer()
            self.cycle_time_box.reset_timer()
            return
        
        # Capture VIN immediately to avoid race conditions where the
        self.current_vin = vin_number
        self.vin_input.setText(vin_number)
        self.vin_input.setReadOnly(True)
        self.test_cycle_active = True
        api_url = self.api_selector.get_selected_api_url(vin_number)
        self.url = api_url
        self.cycle_start_time = datetime.now()
        self.cycle_time_box.start_timer()
        if active_library != "3W_Battery_Healthcheck":
            self.fetch_sku_from_api(vin_number, api_url, active_library)
        else:
            self.on_sku_fetched(vin_number[0])  # Just pass first digit

    def run_test(self, library_name, function_name, vin_number, api_url):
        self.test_thread = QThread()
        self.test_worker = TestWorker(library_name, function_name, vin_number, api_url)
        self.test_worker.moveToThread(self.test_thread)
    
        # Correct signal connections
        self.test_worker.result_ready.connect(lambda result, duration, logs: self._on_worker_result(result, duration, logs, self.current_test_index, function_name))
        self.test_worker.error_occurred.connect(lambda error, duration, logs: self._on_worker_error(error, duration, logs, self.current_test_index))
    
        self.test_thread.started.connect(self.test_worker.run)
        self.test_thread.finished.connect(self.test_worker.deleteLater)
        self.test_thread.finished.connect(self.test_thread.deleteLater)
    
        self.test_thread.start()

        
    def _on_worker_result(self, result, duration, logs, row, function_name):
        try:
            if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
        except Exception:
            pass
 
        # If tests were reset while worker was running, ignore late results
        if (not hasattr(self, 'test_cases')) or (self.current_test_index >= len(self.test_cases)):
            print("[Info] Reset Signal Received; ignoring running test sequences.")
            return
    
        self.result = result
        self.test_duration = duration
        attempt_time = self.cycle_time_box.seconds
    
        # Ensure structure is list-based
        while len(self.test_results) <= self.current_test_index:
            self.test_results.append([])
            if function_name in ["Flag_Chunk"]:
                self.instruction_box.append(result)
            self.test_times.append([])
    
        if not isinstance(self.test_results[self.current_test_index], list):
            self.test_results[self.current_test_index] = list(self.test_results[self.current_test_index])
        if not isinstance(self.test_times[self.current_test_index], list):
            self.test_times[self.current_test_index] = list(self.test_times[self.current_test_index])
    
        self.test_results[self.current_test_index].append(logs)
        self.test_times[self.current_test_index].append(attempt_time)
    
        attempt_num = len(self.test_results[self.current_test_index])
        log_entry = (
            f"--- Retry {attempt_num} ---\n{logs.strip()}\nCycle Time (Retry {attempt_num}): {attempt_time:.2f} sec"
            if attempt_num > 1 else
            f"{logs.strip()}\nCycle Time: {attempt_time:.2f} sec"
        )
    
        self.append_to_log_file(log_entry)
        self._continue_after_worker(row)
    
    def _on_worker_error(self, error, duration, logs, row):
        try:
            if hasattr(self, 'worker_thread') and self.worker_thread and self.worker_thread.isRunning():
                self.worker_thread.quit()
                self.worker_thread.wait()
        except Exception:
            pass
 
        # If tests were reset while worker was running, ignore late results
        if (not hasattr(self, 'test_cases')) or (self.current_test_index >= len(self.test_cases)):
            print("[Info] Reset Signal Received; ignoring running test sequences.")
            return
    
        self.result = error
        self.test_duration = duration
        attempt_time = self.cycle_time_box.seconds
    
        # Ensure structure is list-based
        while len(self.test_results) <= self.current_test_index:
            self.test_results.append([])
            self.test_times.append([])
    
        if not isinstance(self.test_results[self.current_test_index], list):
            self.test_results[self.current_test_index] = list(self.test_results[self.current_test_index])
        if not isinstance(self.test_times[self.current_test_index], list):
            self.test_times[self.current_test_index] = list(self.test_times[self.current_test_index])
    
        self.test_results[self.current_test_index].append(logs)
        self.test_times[self.current_test_index].append(attempt_time)  # ✅ fixed: no extra []
    
        attempt_num = len(self.test_results[self.current_test_index])
        log_entry = (
            f"--- Retry {attempt_num} ---\n{logs.strip()}\nCycle Time (Retry {attempt_num}): {attempt_time:.2f} sec"
            if attempt_num > 1 else
            f"{logs.strip()}\nCycle Time: {attempt_time:.2f} sec"
        )
        self.append_to_log_file(log_entry)
    
        self.instruction_box.clear()
        self.instruction_box.append(f"{self.test_cases[self.current_test_index][1]} failed due to: {error}")
    
        self.retry_count += 1
        if self.retry_count < self.max_retries:
            retry_index = self.current_test_index
            retry_function_name = self.test_cases[retry_index][1]
            QTimer.singleShot(
                2000,
                lambda: (
                    self._start_worker(retry_index, retry_function_name)
                    if (
                        self.test_cases
                        and self.current_test_index == retry_index
                        and retry_index < len(self.test_cases)
                        and self.test_cases[retry_index][1] == retry_function_name
                    )
                    else print("[Info] Skipping stale retry after reset or test change.")
                )
            )
        else:
            self.test_failed = True
            self.final_status = "NOK"
            self.update_test_result_row(row, "Timeout/Error", "FAILED")
            self.progress_bar.setValue(100)
            self.test_cycle_completed = True
            self.cycle_time_box.stop_timer()
            self.send_api_status()
            #QTimer.singleShot(500, self.save_results_to_log)
            self.show_final_result_screen(self.final_status == "OK")

    def run_next_test(self):
        active_library = self.active_library_selector.get_selected_library()
        if self.current_test_index < len(self.test_cases):
            test_label, function_name = self.test_cases[self.current_test_index]
            row = self.current_test_index
    
            self.retry_count = 0  # Reset retry count for this test
    
            if test_label.lower() == "flashing" and active_library == "Flashing_Static":  
                # Special handling for flashing step
                self.run_flashing_process(row)
            #elif test_label.lower() == "flashing" and active_library == "Flashing_U666":  
                # Special handling for flashing step
                #self.flashing_sentinel(row)
            else:
                # Normal tests
                self._start_worker(row, function_name)
        else:
            # All tests done
            self.progress_bar.setValue(100)
            self.test_cycle_completed = True
            self.cycle_time_box.stop_timer()
            self.result_box.setText('<span style="color:green; font-weight:bold; font-size:24px;">All tests passed successfully!</span>')
            self.instruction_box.setText("System ready for next VIN number.")
            self.send_api_status()
            #QTimer.singleShot(500, self.save_results_to_log)
            self.show_final_result_screen(self.final_status == "OK")
            
    def show_popup(self, message, duration, icon=DEFAULT_POPUP_ICON):
        self.popup = ActionPopup(self, message, icon)
        self.popup.show_with_timeout(duration)

    def show_popup_delayed(
        self, message, duration, initial_delay, icon=DEFAULT_POPUP_ICON
    ):
        QTimer.singleShot(
            initial_delay,
            lambda: self.show_popup(message, duration, icon)
        )

    def _start_worker(self, row, function_name):
        active_library = self.active_library_selector.get_selected_library()
        vin_number = getattr(self, 'current_vin', '').strip() or self.vin_input.text().strip()
        api_url = self.url
        flash_file=None
        flash_file_name = self.fetch_flash_file_name_from_api(vin_number, api_url)
        if active_library != ["J107_Static", "J107_IMU", "J107_RVS"]:
            flash_file_name = self.fetch_flash_file_name_from_api(vin_number, api_url)
        if flash_file_name == None and active_library in ["Flashing_U666", "Flashing_Static"]:
            self.instruction_box.append("Error while fetching the flash file name.")
            self.reset_input_and_timer(clear_input=False)
            return
            
        if active_library == "U666_Flashing_and_Diagnostics":
            self.sentinel_return_codes = load_sentinel_return_codes()
        else:
            self.sentinel_return_codes = None
        if flash_file_name:
            flash_file = self.resolve_flash_file(flash_file_name)
        print(flash_file)
        #dll_file = r"D:\TVS NIRIX Flashing\Sentinel\VCU.dll"
        dll_file = resource_path(
        os.path.join("Sentinel", "VCU.dll")
        )
        #exe_path = r"D:\TVS NIRIX Flashing\Sentinel\SentinelCLI.exe"
        exe_path = resource_path(
        os.path.join("Sentinel", "SentinelCLI.exe")
        )
        config_data = load_station_config()
        interface = config_data.get("interface", "N/A")
        channel = config_data.get("channel", "N/A")
        bitrate = config_data.get("bitrate", "N/A")
        log_folder = config_data.get("log_folder", r"D:\Nirixx\Trace")


        
        front_mac = self.mac_ids.get('Front_Mac_ID')
        rear_mac = self.mac_ids.get('Rear_Mac_ID')
    
        self.worker_thread = QThread()
        self.worker = TestWorker(active_library, function_name, vin_number, api_url, self.append_to_log_file, interface, channel, bitrate, front_mac, rear_mac, flash_file, dll_file, log_folder=log_folder, exe_path = exe_path, sentinel_code_map=self.sentinel_return_codes)
        self.worker.popup_request.connect(self.show_popup)
        self.worker.popup_request_delayed.connect(self.show_popup_delayed)
        if function_name.lower() in ["bosch_flashing", "keihin_flashing", "sedemac_flashing"]:
            self.flash_dialog = FlashProgressDialog(self)
            self.flash_dialog.show()
            self.worker.flash_progress.connect(self.flash_dialog.update_progress)
            self.worker.result_ready.connect(self.flash_dialog.close)
            self.worker.error_occurred.connect(self.flash_dialog.close)
            self.worker.result_ready.connect(self.flash_dialog.close)
            self.worker.error_occurred.connect(self.flash_dialog.close)
            
        self.worker.moveToThread(self.worker_thread)
      
        self.worker.result_ready.connect(lambda r, d, l: self._on_worker_result(r, d, l, row, function_name))
        self.worker.error_occurred.connect(lambda e, d, l: self._on_worker_error(e, d, l, row))
        self.worker.log_message.connect(self.update_instruction_box)
    
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()
        
    def update_instruction_box(self, message):
        try:
            self.instruction_box.append(f"{message}")
        except:
            pass
        
    def _continue_after_worker(self, row):
        if (not hasattr(self, 'test_cases')) or (not self.test_cases) or (self.current_test_index >= len(self.test_cases)):
            print("[Info] _continue_after_worker: no valid test case (possibly reset); skipping.")
            return
        function_name = self.test_cases[self.current_test_index][1]
        #test_name = self.test_table.item(row, 1).text()
        test_name = self.test_table.item(row, 1).text().strip() if self.test_table.item(row, 1) else ""
        active_library = self.active_library_selector.get_selected_library()
        config_data = load_station_config()
        time_delay = config_data.get("time_delay", "N/A")
    
        self.cumulative_time += self.test_duration
        self.test_times.append((function_name, self.cumulative_time))    
        expected_value = self.test_table.item(row, 3).text() if self.test_table.item(row, 3) else ""
        lsl = self.test_table.item(row, 4).text() if self.test_table.item(row, 4) else ""
        usl = self.test_table.item(row, 5).text() if self.test_table.item(row, 5) else ""    
        passed = False
        actual_value = ""
    
        try:
            result = self.result    
            if active_library == "J107_Static":
                if function_name == "IPC_Read_Neutral_Gear_Position":
                    if isinstance(result, tuple) and len(result) >= 2:
                        passed, gear = result
                        if passed and gear is not None:
                            actual_value = f"Gear=0x{gear:02X}"
                        else:
                            passed = False
                            actual_value = "Neutral Gear Check Failed"
                    else:
                        passed = bool(result)
                        actual_value = str(result)

                elif function_name == "IPC_Read_Hazard_Switch_Status":
                    if isinstance(result, tuple) and len(result) >= 2:
                        passed, status_message = result
                        actual_value = str(status_message).strip()
                        passed = (
                            bool(passed)
                            and actual_value.upper() == "HAZARD SWITCH ON (0X01)"
                        )
                    else:
                        passed = False
                        actual_value = str(result)

                elif function_name in [
                    "EMS_ABS_Read_Ride_Mode_1_Urban",
                    "EMS_ABS_Read_Ride_Mode_2_Rain",
                    "EMS_ABS_Read_Ride_Mode_3_Tour",
                    "EMS_ABS_Read_Ride_Mode_4_Enduro",
                    "EMS_ABS_Read_Ride_Mode_5_Sport",
                ]:
                    if isinstance(result, tuple) and len(result) >= 2:
                        passed, status_message = result
                        status_text = str(status_message).strip()
                        actual_value = status_text
                        if passed and status_text.upper() == "PASSED":
                            passed = True
                        elif not passed and "TIMEOUT" in status_text.upper():
                            passed = False
                        else:
                            passed = False
                    else:
                        passed = bool(result)
                        actual_value = str(result)

                elif function_name in [
                    "IPC_Read_Left_Indicator_Switch_Status",
                    "IPC_Read_Right_Indicator_Switch_Status",
                    "IPC_Read_Indicator_OFF_Switch_Status",]:
                    
                    indicator_expected_status = {
                        "IPC_Read_Left_Indicator_Switch_Status": "LEFT INDICATOR SWITCH IS ON(0X01)",
                        "IPC_Read_Right_Indicator_Switch_Status": "RIGHT INDICATOR SWITCH IS ON(0X02)",
                        "IPC_Read_Indicator_OFF_Switch_Status": "INDICATOR SWITCH IS OFF(0X00)",
                    }[function_name]
                    if isinstance(result, tuple) and len(result) >= 2:
                        passed, status_message = result
                        actual_value = str(status_message).strip()
                        passed = (
                            bool(passed)
                            and actual_value.upper()
                            == indicator_expected_status
                        )
                    else:
                        passed = False
                        actual_value = str(result)

                elif test_name in ["Read_Read_Wheel_Speed"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        success, value = result
                        actual_value = value
                        passed = success
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Bosch_EMS_Read_DTC"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, dtc_list = result
                        if not isinstance(dtc_list, list):
                            dtc_list = []
            
                        if dtc_list:
                            dtc_texts = [f"{dtc.get('code', 'N/A')}: {dtc.get('DTC_Description', 'Unknown')}" for dtc in dtc_list]
                            dtc_display = "\n".join(dtc_texts)
                            self.instruction_box.append(f"DTCs Detected:\n{dtc_display}")
                            actual_value = f"{len(dtc_list)} DTC(s): " + ", ".join([dtc.get('code', '') for dtc in dtc_list])
                            passed = False
                        else:
                            self.instruction_box.append("No DTCs detected.")
                            actual_value = "No DTCs"
                            passed = True
                    else:
                        self.instruction_box.append("Error: Invalid DTC response format.")
                        actual_value = "Error"
                        passed = False

                elif isinstance(result, bool):
                    actual_value = "True" if result else "False"
                    passed = result
            
                elif isinstance(result, tuple):
                    success = result[0]
                    actual_value = str(result[1]) if len(result) > 1 else ""
                    passed = success and actual_value == expected_value
                else:
                    actual_value = str(result)
                    passed = bool(result)
                    
                    
            elif active_library == "J107_RVS":
                if isinstance(result, bool):
                    actual_value = "True" if result else "False"
                    passed = result
                    
                elif test_name in ["Flashing_Flag_Check", "Static_Flag_Check", "DAQ_Flag_Check"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, msg = result
                        actual_value = str(msg)
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Bosch_EMS_Tester_Present"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, value = result
                        actual_value = value
                    else:
                        actual_value = "Error"
                        passed = False
                        
                elif test_name in ["Bosch_EMS_Read_VIN"]:
                    if isinstance(result, tuple) and len(result) == 3:
                        passed, api_value, actual_value = result
                        self.test_table.setItem(row, 3, QTableWidgetItem(str(api_value)))
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Bosch_EMS_Read_DTC"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, dtc_list = result

                        if not isinstance(dtc_list, list):
                            dtc_list = []
                
                        if len(dtc_list) > 0:
                            dtc_texts = [f"{dtc.get('code', 'N/A')}: {dtc.get('DTC_Description', 'Unknown')}" for dtc in dtc_list]
                            dtc_display = "\n".join(dtc_texts)
                            self.instruction_box.append(f"DTCs Detected:\n{dtc_display}")
                            actual_value = f"{len(dtc_list)} DTC(s): " + ", ".join([dtc.get('code', '') for dtc in dtc_list])
                            passed = False
                        else:
                            self.instruction_box.append("No DTCs detected.")
                            actual_value = "No DTCs"
                            passed = True
                    else:
                        self.instruction_box.append("Error: Invalid DTC response format.")
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Sedemac_Read_VIN","Sedemac_Read_CALID","Sedemac_Read_CVN"]:
                    if isinstance(result, tuple) and len(result) >= 3:
                        passed, api_value, actual_value = result
                        self.test_table.setItem(row, 3, QTableWidgetItem(str(api_value)))
                        if not passed:
                            api_error_message = (f"{test_name}\n"f"API Data Mismatch\n"f"API Data    : {api_value}\n"f"Actual Data : {actual_value}\n")
                            self.instruction_box.append(api_error_message)
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in [ "Sedemac_Read_Date_Of_Last_Programming","Sedemac_Read_Engine_Speed","Sedemac_Read_Fuel_Pump_Status_00","Sedemac_Read_Fuel_Pump_Status_01",
                                   "Sedemac_Read_Vehicle_Speed","Sedemac_Tester_Present"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        success, value = result
                        actual_value = value
                        passed = success
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Sedemac_Engine_RPM_Check", "Sedemac_Read_Throttle_Percentage", "Sedemac_Read_Battery_Voltage", "Sedemac_Read_HEGO_Sensor_Voltage"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, actual_value = result
                        try:
                            val = float(actual_value)
                            lsl_val = float(lsl) if lsl and lsl != "N/A" else float('-inf')
                            usl_val = float(usl) if usl and usl != "N/A" else float('inf')
                            passed = passed and (lsl_val <= val <= usl_val)
                        except Exception:
                            passed = False
                            actual_value = "Error"
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Sedemac_Read_DTC"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, dtc_list = result
                        if not isinstance(dtc_list, list):
                            dtc_list = []
            
                        if dtc_list:
                            dtc_texts = [f"{dtc.get('code', 'N/A')}: {dtc.get('DTC_Description', 'Unknown')}" for dtc in dtc_list]
                            dtc_display = "\n".join(dtc_texts)
                            self.instruction_box.append(f"DTCs Detected:\n{dtc_display}")
                            actual_value = f"{len(dtc_list)} DTC(s): " + ", ".join([dtc.get('code', '') for dtc in dtc_list])
                            passed = False
                        else:
                            self.instruction_box.append("No DTCs detected.")
                            actual_value = "No DTCs"
                            passed = True
                    else:
                        self.instruction_box.append("Error: Invalid DTC response format.")
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Keihin_Tester_Present", "Keihin_Read_Dealer_Number",
                                   "Keihin_Read_Fuel_Pump_Status","Keihin_Read_Last_Date_Of_Programming"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, value = result
                        actual_value = value
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Keihin_Read_Engine_Rpm", "Keihin_Read_Throttle_Position", "Keihin_Read_Battery_Voltage"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, actual_value = result
                        try:
                            val = float(actual_value)
                            lsl_val = float(lsl) if lsl and lsl != "N/A" else float('-inf')
                            usl_val = float(usl) if usl and usl != "N/A" else float('inf')
                            passed = passed and (lsl_val <= val <= usl_val)
                        except Exception:
                            passed = False
                            actual_value = "Error"
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Keihin_Read_CVN_Number","Keihin_Read_Calibration_ID"]:
                    if isinstance(result, tuple) and len(result) == 3:
                        passed, api_value, actual_value = result
                        self.test_table.setItem(row, 3, QTableWidgetItem(str(api_value)))
                    else:
                        actual_value = "Error"
                        passed = False

                elif test_name in ["Keihin_Read_DTC"]:
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, dtc_list = result
                        if not isinstance(dtc_list, list):
                            dtc_list = []
            
                        if dtc_list:
                            dtc_texts = [f"{dtc.get('code', 'N/A')}: {dtc.get('DTC_Description', 'Unknown')}" for dtc in dtc_list]
                            dtc_display = "\n".join(dtc_texts)
                            self.instruction_box.append(f"DTCs Detected:\n{dtc_display}")
                            actual_value = f"{len(dtc_list)} DTC(s): " + ", ".join([dtc.get('code', '') for dtc in dtc_list])
                            passed = False
                        else:
                            self.instruction_box.append("No DTCs detected.")
                            actual_value = "No DTCs"
                            passed = True
                    else:
                        self.instruction_box.append("Error: Invalid DTC response format.")
                        actual_value = "Error"
                        passed = False
                    
                elif isinstance(result, tuple):
                    success = result[0]
                    actual_value = str(result[1]) if len(result) > 1 else ""
                    passed = success and actual_value == expected_value
                else:
                    actual_value = str(result)
                    passed = bool(result)
                    
            else:#TPMS
                if test_name == "API_CALL":
                    if isinstance(result, tuple) and len(result) >= 3:
                        front_mac, rear_mac, passed = result[:3]
                        self.mac_ids['Front_Mac_ID'] = front_mac
                        self.mac_ids['Rear_Mac_ID'] = rear_mac
                        actual_value = "TRUE"
                    else:
                        actual_value = "Error"
                        passed = False
                elif test_name == "WRITE_TPMS_FRONT":
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, actual_value = result
                    elif isinstance(result, bool):
                        passed = result
                        actual_value = "True" if result else "False"
                    else:
                        passed = False
                        actual_value = str(result)
                elif test_name == "WRITE_TPMS_REAR":
                    if isinstance(result, tuple) and len(result) == 2:
                        passed, actual_value = result
                    elif isinstance(result, bool):
                        passed = result
                        actual_value = "True" if result else "False"
                    else:
                        passed = False
                        actual_value = str(result)
                else:
                    if isinstance(result, bool):
                        actual_value = "True" if result else "False"
                        passed = result
                    elif isinstance(result, tuple) and len(result) == 2:
                        passed, actual_value = result
                    else:
                        actual_value = str(result)
                        passed = bool(result)   
        except Exception as e:
            print(f"[Error] Result parsing failed: {e}")
            self.instruction_box.append(f"{e}")
            actual_value = "Exception"
            passed = False    
        # Update GUI
        status = "PASSED" if passed else "FAILED"
        color = "#008000" if passed else "red"
        self.update_test_result_row(row, actual_value, status)
        self.result_box.setText(f'<span style="color:{color}; font-weight:bold; font-size:24px;">{function_name} - {status}</span>')
        self.test_table.scrollToItem(self.test_table.item(row, 0), QAbstractItemView.PositionAtCenter)
        self.progress_bar.setValue(int(((self.current_test_index + 1) / len(self.test_cases)) * 100))
    
        if passed:
            self.instruction_box.append(f"{function_name} passed")
            if active_library != "Sedemac_RVS_Station":
                QTimer.singleShot(int(time_delay), self._proceed_to_next_test)
            else:
                QTimer.singleShot(1, self._proceed_to_next_test)
        else:
            self.retry_count += 1
            if self.retry_count < self.max_retries:
                self.instruction_box.append(f"{function_name} failed on attempt {self.retry_count}. Retrying...")
                QTimer.singleShot(2000, lambda: self._start_worker(row, function_name))
            else:
                self.test_failed = True
                self.final_status = "NOK"
                self.instruction_box.append(f"{function_name} failed after {self.max_retries} retries.")
                self.progress_bar.setValue(100)
                self.send_api_status()
                self.test_cycle_completed = True
                self.cycle_time_box.stop_timer()
                #QTimer.singleShot(500, self.save_results_to_log)
                self.show_final_result_screen(self.final_status == "OK")
                print("Failed Test =", function_name)
                print("Result Box =", self.result_box.toPlainText())

    def _proceed_to_next_test(self):
        try:
            if hasattr(self, 'test_failed') and self.test_failed:
                return
            self.current_test_index += 1
            self.run_next_test()
        except Exception as e:
            print(f"[Error] Proceed to next test failed: {e}")
            self.instruction_box.append(f'<span style="color:red;">Exception in _proceed_to_next_test: {e}</span>')

    def send_api_status(self):
        vin_number = getattr(self, 'current_vin', '').strip() or self.vin_input.text().strip()
        active_library = self.active_library_selector.get_selected_library()
        self.API_URL = "http://10.121.2.107:3000/vehicles/flashFile/updateProcessParams"
    
        if not vin_number:
            print("VIN number is empty. Cannot send API status.")
            return
    
        headers = {'Content-Type': 'application/json'}
    
        # Define param-opn pairs
        if active_library in ["J107_Flashing"]:
             param_pairs = [
                 ("CZ14001", "0010")
             ]

        elif active_library in ["J107_Static"]:
             param_pairs = [
                 ("CZ14002", "0020")
             ]

        elif active_library in ["J107_IMU"]:
             param_pairs = [
                 ("CZ14002", "0020")
             ]
             
        elif active_library in ["J107_RVS"]:
             param_pairs = [
                 ("CZ14004", "0040")
             ]
         
    
        for param_id, opn_no in param_pairs:
            payload = {
                "VIN": vin_number,
                "paramId": param_id,
                "opnNo": opn_no,
                "identifier": vin_number,
                "result": self.final_status
            }
    
            try:
                print(f"\n[API CALL] Sending status for ParamID={param_id}, OPNNo={opn_no} ...")
                print("Payload:", json.dumps(payload, indent=4))
    
                response = requests.post(self.API_URL, headers=headers, data=json.dumps(payload))
    
                print(f"[API Response] Status Code: {response.status_code}")
    
                # Try to print JSON cleanly, else print raw text
                try:
                    print("Response JSON:", json.dumps(response.json(), indent=4))
                except:
                    print("Response Text:", response.text)
    
            except Exception as e:
                print(f"[ERROR] Failed sending API status for ParamID={param_id}, OPNNo={opn_no}: {e}")
                
    def build_api_payload(self, vin_number):
        config_data = load_station_config()
        operator = config_data.get("operation_no", "N/A")
        modelcode = config_data.get("modelcode", "N/A")
        timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sub_param_traces = []
        
    
        for idx in range(len(self.test_results)):
    
            def safe_text(item):
                return item.text() if item else "NA"
    
            # Result
            result_item = self.test_table.item(idx, 7)
            if result_item:
                result_text = result_item.data(Qt.UserRole) or result_item.text() or "NA"
            else:
                result_text = "NA"
    
            # Cycle Time
            if idx < len(self.test_times) and self.test_times[idx]:
                try:
                    cycle_time = float(self.test_times[idx][-1])
                except Exception:
                    cycle_time = None
            else:
                cycle_time = None
    
            sub_param_traces.append({
                "sno": safe_text(self.test_table.item(idx, 0)),
                "paramName": safe_text(self.test_table.item(idx, 1)),
                "parameter": safe_text(self.test_table.item(idx, 2)),
                "value": safe_text(self.test_table.item(idx, 3)),
                "lsl": safe_text(self.test_table.item(idx, 4)),
                "usl": safe_text(self.test_table.item(idx, 5)),
                "actualValue": safe_text(self.test_table.item(idx, 6)),
                "result": result_text,
                "cycleTime": cycle_time,
                "machineNo": socket.gethostname(),
                "version": getattr(self, self.version, self.version),
                "faultsCode": None
            })
    
        payload = {
            "VIN": vin_number,
            "modelCode": getattr(self, modelcode, "Not_mentioned"),   
            "operator": getattr(self, operator, "Not_mentioned"),     
            "cycle": getattr(self, "cycle_count", 1),
            "testResult": "OK" if self.final_status == "OK" else "NOK",
            "dateTime": timestamp_now,
            "stationId": self.active_library,
            "vendorId": "NIRIX",
            "subParamTraces": sub_param_traces
        }
    
        return payload
    def push_results_to_api(self, vin_number, payload):
        from security_manager import (read_encrypted_ini,MASTER_PASSWORD)
        config = read_encrypted_ini("api.ini.enc",MASTER_PASSWORD)
 
        base_url = config.get("TVS_PARAMETER", "API", fallback=None)
 
        if not base_url:
            print("❌ API URL missing in api.ini.enc")
 
            return {
                "success": False,
                "status_code": None,
                "response": None,
                "response_body": None,
                "request_url": None,
                "message": "API URL missing in api.ini.enc"
            }
 
        url = base_url.rstrip('/')
        print("Final API URL:", url)
        headers = {
            "Content-Type": "application/json"
        }
 
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=10)
 
            status_code = response.status_code
 
            try:
                response_data = response.json()
            except Exception:
                response_data = response.text
 
            if status_code in (200, 201):
                print("✅ API push successful")
                print(response.text)
 
                return {
                    "success": True,
                    "status_code": status_code,
                    "response": response_data,
                    "response_body": response_data,
                    "request_url": url,
                    "message": "✅ Report generated and pushed successfully"
                }
 
            else:
                print(f"❌ API failed: {status_code}")
                print(response.text)
 
                return {
                    "success": False,
                    "status_code": status_code,
                    "response": response_data,
                    "response_body": response_data,
                    "request_url": url,
                    "message": f"❌ Report generated but API push failed with HTTP {status_code}"
                }
 
        except requests.exceptions.Timeout:
            print("⚠️ API connection timeout")
 
            return {
                "success": False,
                "status_code": None,
                "response": None,
                "response_body": None,
                "request_url": url,
                "message": "❌ Report generated but API connection timed out"
            }
 
        except requests.exceptions.ConnectionError as e:
            print(f"⚠️ API connection error: {e}")
 
            return {
                "success": False,
                "status_code": None,
                "response": None,
                "response_body": None,
                "request_url": url,
                "message": "❌ Report generated but server connection failed"
            }
 
        except Exception as e:
            print(f"⚠️ API error: {e}")
 
            return {
                "success": False,
                "status_code": None,
                "response": None,
                "response_body": None,
                "request_url": url,
                "message": f"❌ Report generated but API push failed: {str(e)}"
            }


    def save_results_to_log(self):
        try:
            vin_number = self.current_vin or "".join(self.vin_input.text().split()).upper()
            active_library = self.active_library
            Vendor_ID = "NIRIX"
 
            timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            start_cycle_time = getattr(self,'cycle_start_time','N/A')
            if start_cycle_time != 'N/A':
                start_cycle_time = start_cycle_time.strftime("%Y-%m-%d %H:%M:%S")
            total_cycle_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
 
            url = getattr(self,'url','No request sent')
            json_response = getattr(self,'json_response','No response available')

            if isinstance(json_response, dict):
                api_response_text = json.dumps(json_response, indent=4)
            elif json_response is None:
                api_response_text = "No response"
            else:
                api_response_text = str(json_response)
 
            # Default API status
            # This will be updated after the API call.
            api_status = {
                "success": False,
                "status_code": None,
                "response": None,
                "message": "API push not attempted"
            }
 
            root = ET.Element("Log")
 
            ET.SubElement(root,"IdentifierNumber").text = vin_number
            # ECU/Test result
            ET.SubElement(root,"TestStatus").text = str(self.final_status)
            ET.SubElement(root,"Date").text = timestamp_now
            ET.SubElement(root,"StationID").text = active_library
            ET.SubElement(root,"VendorID").text = Vendor_ID
            # Report itself is being generated
            ET.SubElement(root,"ReportStatus").text = "GENERATED"
 
            # ============================================================
            # API SECTION
            # ============================================================
 
            api_section = ET.SubElement(root,"API")
            ET.SubElement(api_section,"Get_Request").text = str(url)
            ET.SubElement(api_section,"Get_Response").text = api_response_text
            ET.SubElement(api_section,"Post_Request").text = ""
            ET.SubElement(api_section,"Post_Response").text = ""
            ET.SubElement(api_section,"StatusCode").text = "NOT_ATTEMPTED"
            ET.SubElement(api_section,"PushStatus").text = "NOT_ATTEMPTED"
            ET.SubElement(api_section,"Message").text = "API push not attempted"
 
 
            tests_element = ET.SubElement(root,"Tests")
            version_text = getattr(self,self.version,self.version)
 
            for idx in range(self.test_table.rowCount()):
                test_element = ET.SubElement(tests_element,"Test",id=str(idx + 1))
                # --------------------------------------------------------
                # ATTEMPTS
                # --------------------------------------------------------
                if (idx < len(self.test_results) and self.test_results[idx]):
 
                    for attempt_num, log_text in enumerate(self.test_results[idx],start=1):
                        attempt_element = ET.SubElement(test_element,"Attempt",number=str(attempt_num))
                        ET.SubElement(attempt_element,"Log").text = str(log_text).strip()
 
                try:
                    details_element = ET.SubElement(test_element,"Details")
                    def safe_text(item):
                        return (item.text() if item else "NA")

                    result_item = self.test_table.item(idx, 7)
                    if result_item:
                        result_text = (result_item.data(Qt.UserRole) or result_item.text() or "NA")
                    else:
                        result_widget = (self.test_table.cellWidget(idx, 7))
 
                        if (result_widget and isinstance( result_widget, QLabel)):
                            pixmap = result_widget.pixmap()
                            if pixmap:
                                result_text = "PASS"
                            else:
                                result_text = "NA"
 
                        else:
                            result_text = "NA"

                    details_data = {
                        "SNo":safe_text(self.test_table.item(idx, 0)),
                        "TestSequence":safe_text(self.test_table.item( idx, 1)),
                        "Parameter":safe_text(self.test_table.item(idx,2)),
                        "Value":safe_text(self.test_table.item(idx,3)),
                        "LSL":safe_text(self.test_table.item(idx,4)),
                        "USL":safe_text(self.test_table.item(idx,5)),
                        "ActualValue":safe_text(self.test_table.item(idx,6)),
                        "Result":result_text
                    }

 
                    if (idx < len(self.test_times) and self.test_times[idx]):
 
                        try:
                            cycle_time_value = float(self.test_times[idx][-1])
                            details_data["CycleTime"] = (f"{cycle_time_value:.2f} sec")
 
                        except Exception:
                            details_data["CycleTime"] = "NA"
                    else:
                        details_data["CycleTime"] = "NA"
 
                    details_data["PC_Name"] = socket.gethostname()
                    details_data["Version"] = version_text
                    for key, value in details_data.items():
                        ET.SubElement(details_element,key).text = str(value)
 
                except Exception as e:
                    print(f"⚠️ Error adding Details "f"for test {idx + 1}: {e}")
 
            Sequence_End = "True"
 
            ET.SubElement(root,"StartCycleTime").text = start_cycle_time
            ET.SubElement(root,"TotalCycleTime").text = total_cycle_time
            ET.SubElement(root,"Sequence_End").text = Sequence_End
 
            try:
                print("\n====================================")
                print("Preparing API Payload...")
                print("====================================")
 
                payload = self.build_api_payload(vin_number)
 
                print("API Payload:")
                print(payload)
 
                # Call API
                api_status = self.push_results_to_api(vin_number,payload)
 
                # Safety check
                if not isinstance(api_status,dict):
                    api_status = {
                        "success": False,
                        "status_code": None,
                        "response": None,
                        "message":
                            "Invalid API status returned"
                    }
 
            except Exception as e:
                print(f"❌ Failed to push API data: {e}")
                api_status = {
                    "success": False,
                    "status_code": None,
                    "response": None,
                    "message":
                        f"API push exception: {str(e)}"
                }
 
            api_section = root.find("API")
            if api_section is not None:
                status_code = api_status.get("status_code")
 
                if status_code is None:
                    status_code_text = "N/A"
                else:
                    status_code_text = str(status_code)
 
                # Update only the push metadata. Keep the GET and POST request/response fields separately.
                for tag in ["StatusCode","PushStatus","Message"]:
 
                    old_element = (api_section.find(tag))
 
                    if old_element is not None:
                        api_section.remove(old_element)
 
                post_request_url = api_status.get("request_url") or getattr(self, 'push_api_url', '') or 'N/A'
                post_request_element = api_section.find("Post_Request")
                if post_request_element is not None:
                    post_request_element.text = str(post_request_url)
 
                post_response = api_status.get("response_body")
                if isinstance(post_response, dict):
                    post_response_text = json.dumps(post_response, indent=4)
                elif post_response is None:
                    post_response_text = "No response"
                else:
                    post_response_text = str(post_response)
 
                post_response_element = api_section.find("Post_Response")
                if post_response_element is not None:
                    post_response_element.text = post_response_text

 
                ET.SubElement(api_section,"StatusCode").text = status_code_text

                if api_status.get("success"):
                    push_status = "SUCCESS"
                else:
                    push_status = "FAILED"
 
                ET.SubElement(api_section,"PushStatus").text = push_status
 
                message = api_status.get("message","Unknown API status")
                ET.SubElement(api_section,"Message").text = str(message)

            log_datetime = datetime.now()
            log_folder = load_station_config().get("log_folder", r"D:\Nirixx\Trace")
            daily_log_folder = os.path.join(log_folder, log_datetime.strftime("%d-%m-%Y"))
            os.makedirs(daily_log_folder, exist_ok=True)
            xml_filename = (
                f"{vin_number}_"
                f"{log_datetime.strftime('%Y%m%d_%H%M%S_%f')}_"
                f"{self.final_status}.xml"
            )
            xml_path = os.path.join(daily_log_folder, xml_filename)

            tree = ET.ElementTree(root)
            ET.indent(tree,space="  ",level=0)
 
            tree.write(xml_path,encoding="utf-8",xml_declaration=True)
 
            print(f"\n✅ XML log saved successfully:")
            print(xml_path)
 
            if api_status.get("success"):
                print("✅ Report generated ""and pushed successfully.")
                try:
                    self.instruction_box.append(
                        "<span style='color:green;'>"
                        "Report generated and pushed "
                        "successfully."
                        "</span>"
                    )
 
                except Exception:
                    pass
 
            else:
                status_code = api_status.get("status_code")
                print(
                    f"⚠️ Report generated successfully, "
                    f"but API push failed. "
                    f"Status Code: {status_code}"
                )
 
                try:
 
                    self.instruction_box.append(
                        "<span style='color:red;'>"
                        "Report generated successfully, "
                        "but API push failed. "
                        f"Status Code: {status_code}"
                        "</span>"
                    )
 
                except Exception:
                    pass
 
        except Exception as e:
            print(f"❌ Error saving XML log file: {e}")

            try:
                self.instruction_box.append(
                    "<span style='color:red;'>"
                    "Error saving XML log file"
                    "</span>"
                )
 
                self.instruction_box.append(str(e))
 
            except Exception:
                pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    light_palette = QPalette()
    light_palette.setColor(QPalette.Window, QColor(255, 255, 255))
    light_palette.setColor(QPalette.WindowText, Qt.black)
    light_palette.setColor(QPalette.Base, QColor(240, 240, 240))
    light_palette.setColor(QPalette.AlternateBase, QColor(230, 230, 230))
    light_palette.setColor(QPalette.ToolTipBase, Qt.black)
    light_palette.setColor(QPalette.ToolTipText, Qt.black)
    light_palette.setColor(QPalette.Text, Qt.black)
    light_palette.setColor(QPalette.Button, QColor(230, 230, 230))
    light_palette.setColor(QPalette.ButtonText, Qt.black)
    light_palette.setColor(QPalette.BrightText, Qt.red)
    light_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    light_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(light_palette)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())