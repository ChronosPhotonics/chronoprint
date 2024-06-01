import json
import traceback
import time
import sys
import os

from console.utils import wait_key
from bpm.bambuconfig import BambuConfig
from bpm.bambuprinter import BambuPrinter
from bpm.bambutools import PrinterState
from bpm.bambutools import parseStage
from bpm.bambutools import parseFan
from bpm.bambutools import PlateType

gcodeState = ""
completedJobs = 0
subscribed = False
jobSent = False
hostname = os.getenv('BAMBU_HOSTNAME')
access_code = os.getenv('BAMBU_ACCESS_CODE')
serial_number = os.getenv('BAMBU_SERIAL_NUMBER')
fname = "/base_auto_v03.gcode.3mf"

def on_update(printer):
    global gcodeState, completedJobs, subscribed, jobSent
    if gcodeState != printer.gcode_state:
        if gcodeState != "":
            print(f"\rState changed to: {printer.gcode_state} at {time.strftime('%H:%M:%S')}")
        elif gcodeState == "":
            print(f"\rInitial state is: {printer.gcode_state} at {time.strftime('%H:%M:%S')}")
        gcodeState = printer.gcode_state

    if gcodeState != "FINISH":
        jobSent = False
        if subscribed:
            print_status()
        if printer.speed_level != 4 and printer.current_layer >= 6:
            printer.speed_level = 4
        
    elif gcodeState == "FINISH" and not jobSent:
        send_job()
        jobSent = True
        completedJobs += 1
        print(f"\rJob completed at {time.strftime('%H:%M:%S')}. Completed jobs: {completedJobs}")

def print_status():

    print(f"\r\ntool=[{round(printer.tool_temp * 1.0, 1)}/{round(printer.tool_temp_target * 1.0, 1)}] " +
         f"bed=[{round(printer.bed_temp * 1.0, 1)}/{round(printer.bed_temp_target * 1.0, 1)}] " + 
         f"fan=[{parseFan(printer.fan_speed)}] print=[{printer.gcode_state}] speed=[{printer.speed_level}] " +
         f"light=[{'on' if printer.light_state else 'off'}]")

    print(f"\rstg_cur=[{parseStage(printer.current_stage)}] file=[{printer.gcode_file}] " +
          f"layers=[{printer.layer_count}] layer=[{printer.current_layer}] " +
          f"%=[{printer.percent_complete}] eta=[{printer.time_remaining} min] " +
          f"spool=[{printer.active_spool} ({printer.spool_state})]\r")

def send_job():
    printer.print_3mf_file(fname, 1, PlateType.HOT_PLATE, False, "", False, False, False)

def confirm(request):
    printer.pause_session()
    resp = input(f"Confirm [{request}] (y/n): ")
    printer.resume_session()
    return resp == "y" or resp == "Y"

config = BambuConfig(hostname=hostname, access_code=access_code, serial_number=serial_number)
printer = BambuPrinter(config=config)

printer.on_update = on_update
printer.start_session()

while True:
    key = wait_key()
    if key == "q": 
        break
    if key == "b":
        if confirm("START JOB"):
                send_job()
                print(f"\rJob sent to printer")
    if key == "s":
        print(f"\r{subscribed*'UN'}"+"SUBSCRIBED")
        subscribed = not subscribed

printer.quit()
