import json
import traceback
import time
import sys
import os

from enum import Enum
from console.utils import wait_key
from bpm.bambuconfig import BambuConfig
from bpm.bambuprinter import BambuPrinter
from bpm.bambutools import PrinterState
from bpm.bambutools import parseStage
from bpm.bambutools import parseFan
from bpm.bambutools import PlateType

#gcodeState = ""
#completedJobs = 0
#subscribed = False
#jobSent = False
hostname = os.getenv('BAMBU_HOSTNAME')
access_code = os.getenv('BAMBU_ACCESS_CODE')
serial_number = os.getenv('BAMBU_SERIAL_NUMBER')
#fname = "/cap_auto_v08.gcode.3mf"
#fname_calib = "/cap_auto_v08_calib.gcode.3mf"

class Status(Enum):
    ERROR   =-1
    IDLE    = 0
    RUN     = 1
    START   = 2
    PAUSE   = 3

class PrintQ():
    _status: Status
    _status_cache: Status
    _files: set
    _entries: list
    loud: bool
    
    def __init__(self) -> None:
        self._status = Status.IDLE
        self._status_cache = Status.IDLE
        self._files = []
        self._entries = []
        self.loud = False

    def get_files(self):
        return set([entry[0] for entry in self._entries])

    def get_entries(self):
        return self._entries
    
    def add_entry(self,file,count):
        self._entries.append([file,count,count])

    def start(self):
        if self._entries and not self._status in {Status.RUN, Status.START}:
            # set running status directly to trigger cache mismatch in printer.on_update
            self.set_status(Status.START)
        elif self._status == Status.RUN:
            print("Queue is already running")
        elif self._status == Status.START:
            print("Queue is already starting")
        elif not self._entries:
            print("Cannot start an empty queue")

    def pause(self):
        if self._entries and self._status in {Status.RUN, Status.START}:
             self.set_status(Status.PAUSE)
        elif not self._entries:
             print("Cannot pause an empty queue")
        elif self._status in {Status.PAUSE, Status.ERROR, Status.IDLE}:
             print(f"\rCannot pause queue with status {self._status.name}")

    def set_status(self,status):
        self._status = status
        if self._status != self._status_cache:
            self._announce_status()
            self._status_cache = self._status

    def _announce_status(self):
        if self.loud:
            print(f"\rQueue status is currently {self._status.name}")

    def _announce_job(self):
        if self.loud:
            print(f"\r{self._entries[0][1]-self._entries[0][2]}/{self._entries[0][1]} for file {self._entries[0][0]}")

    def remove_entry(self):
        if self.entries:
            removed = self.entries.pop()
            print(f"\rRemoved {removed} from queue.")
        else:
            print("\rQueue is empty.")

    def get_nextjob(self):
        if self._entries:
            if self._entries[0][2] == 0: #delete first entry if all jobs are completed
                print(f"\rCompleted {self._entries[0][1]} units of {self._entries[0][0]}")
                self._entries.pop(0)
                if self._entries:
                    return self._entries[0][0]
                else:
                    print("Queue emptied")
                    return None
            else:
                return self._entries[0][0]
        else:
            return None

    def decrement_job(self):
        if self._entries:
            if self._entries[0][2] >= 1:
                self._entries[0][2] -= 1
                self._announce_job()
            else:
                pass

class Printer(BambuPrinter):
    loud_sensors: bool
    loud_status: bool
    job_sent: bool
    queue: PrintQ
    _gcode_state_cache: PrinterState

    def __init__(self, config):
        super().__init__(config=config)
        self._gcode_state_cache = self.gcode_state
        self.loud_sensors = False
        self.loud_status = False
        self._job_sent = False
        self.queue = PrintQ()

    def on_update(self):
        if self._gcode_state_cache != self.gcode_state:
            if self.loud_status:
                print(f"\rState changed to: {self.gcode_state} at {time.strftime('%H:%M:%S')}")
                self._gcode_state_cache = self.gcode_state
            if self.gcode_state != "FINISH":
                self._job_sent = False
            else:
                if self.queue._status == Status.RUN:
                    self.queue.decrement_job()
                if self._job_sent == False:
                    self.queue.set_status(
                        self.send_job(self.queue.get_nextjob())
                        )
        elif self.queue._status == Status.START:
            self.queue.set_status(
                        self.send_job(self.queue.get_nextjob())
                        )

        if self.loud_sensors:
            self.print_status()


    def print_status(self):

        print(f"\r\ntool=[{round(self.tool_temp * 1.0, 1)}/{round(self.tool_temp_target * 1.0, 1)}] " +
            f"bed=[{round(self.bed_temp * 1.0, 1)}/{round(self.bed_temp_target * 1.0, 1)}] " + 
            f"fan=[{parseFan(self.fan_speed)}] print=[{self.gcode_state}] speed=[{self.speed_level}] " +
            f"light=[{'on' if self.light_state else 'off'}]")

        print(f"\rstg_cur=[{parseStage(self.current_stage)}] file=[{self.gcode_file}] " +
            f"layers=[{self.layer_count}] layer=[{self.current_layer}] " +
            f"%=[{self.percent_complete}] eta=[{self.time_remaining} min] " +
            f"spool=[{self.active_spool} ({self.spool_state})]\r")

    def send_job(self, fname):
        if fname:
            if self.gcode_state == "FINISH" and not self._job_sent:
                self.print_3mf_file(fname, 1, PlateType.HOT_PLATE, False, "", False, False, False)
                self._job_sent = True
                return Status.RUN
            elif self.gcode_state != "RUNNING" and self.queue._status == Status.START and not self._job_sent:
                self.print_3mf_file(fname, 1, PlateType.HOT_PLATE, False, "", False, False, False)
                self._job_sent = True
                return Status.RUN
            else:
                print("\rWarning: Could not send job. Queue will try to start when current job ends.")
                return Status.ERROR
        else:
            return Status.IDLE

class Subscriptions():
        
        chans:     dict
        _printer:  Printer

        def __init__(self,printer):
            self._printer = printer
            self.chans = {
                "printer": printer.loud_sensors,
                "queue": False,
                "status": printer.loud_status
            }
        
        def toggle_chan(self, chan):
            self.chans[chan] = not self.chans[chan]
            if chan == "printer":
                self._printer.loud_sensors = self.chans["printer"]
            elif chan == "status":
                self._printer.loud_status = self.chans["status"]
                print(f"\rGcode state is: {self._printer.gcode_state} at {time.strftime('%H:%M:%S')}")
            elif chan == "queue":
                self._printer.queue.loud = self.chans["queue"]
            return self.chans[chan]

commands = {
    "help": "Display this help message",
    "quit": "Quit the application",
    "connect": "Initiate connection or display connection status",
    "disconnect": "Disconnect the printer",
    "queue": "Manage print queue",
    "print": "Print a specified file",
    "subscribe": "Subscribe/Unsubscribe from updates"
}

def get_command(input_cmd, commands):
    matches = [cmd for cmd in commands if cmd.startswith(input_cmd)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        print(f"Ambiguous command: {input_cmd}. Possible matches: {', '.join(matches)}")
        return None
    else:
        print(f"Unknown command: {input_cmd}")
        return None

def main():
    config  = BambuConfig(hostname=hostname, access_code=access_code, serial_number=serial_number)
    printer = Printer(config=config)
    printer.start_session()
    queue   = printer.queue
    subs    = Subscriptions(printer)
    try:
        while True:
            cmd_input = input("Enter command: ").strip().lower().split()
            if not cmd_input:
                continue
            
            cmd = get_command(cmd_input[0], commands)
            if cmd is None:
                continue

            if cmd == "help":
                for cmd, desc in commands.items():
                    print(f"{cmd}: {desc}")

            elif cmd == "quit":
                break

            elif cmd == "connect":
                if printer.is_connected():
                    print(f"Already connected by config: {config}")
                else:
                    printer.connect()
                    print("Printer connected.")

            elif cmd == "disconnect":
                printer.disconnect()
                print("Printer disconnected.")

            elif cmd == "queue":
                if len(cmd_input) > 1:
                    queue_cmd = cmd_input[1]
                    if queue_cmd == "start":
                        queue.start()
                    elif queue_cmd == "pause":
                        queue.pause()
                    elif queue_cmd == "add":
                        filename = input("Enter 3MF filename: ").strip()
                        printer.get_sdcard_3mf_files()
                        #if filename in printer._sdcard_3mf_files:
                        quantity = int(input("Enter print quantity: ").strip())
                        queue.add_entry(filename, quantity)
                        #else:
                        #    print(f"File {filename} not found on SD card.")
                    elif queue_cmd == "rm":
                        entry_id = int(input("Enter entry ID to remove: ").strip())
                        queue.remove_entry(entry_id)
                    else:
                        print("Usage: queue [start | pause | add | rm]")
                else:
                    print("Usage: queue [start | pause | add | rm]")

            elif cmd == "print":
                if len(cmd_input) > 1:
                    fname = cmd_input[1]
                    if queue._status != Status.RUN:
                         printer.print_3mf_file(fname, 1, PlateType.HOT_PLATE, False, "", False, False, False)
                    else:
                        print("Cannot send print while queue is running")
                else:
                    print("Usage: print [filename]")

            elif cmd == "subscribe":
                if len(cmd_input) > 1:
                    arg = cmd_input[1]
                    if arg == "help":
                        print("subscribe [channel] - Toggles subscription. Channels: printer | queue | status")
                    else:
                        channel = get_command(arg, subs.chans.keys())
                        if channel:
                            print(f'Subscribed to {channel}' if subs.toggle_chan(channel) else f'Unsubscribed from {channel}')
                else:
                    print("Usage: subscribe [channel]")

    finally:
            printer.quit()

if __name__ == "__main__":
    main()
