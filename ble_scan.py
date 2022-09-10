import argparse
import queue

from util import BluetoothApp
from aws_iot import aws_pipe

# Characteristic values
GATTDB_DEVICE_NAME = b"Empty Example"
GATTDB_MANUFACTURER_NAME_STRING = b"Silicon Labs"

def parse_adv_data(adv_data):
    i = 0
    complete_local_name = None
    short_local_name = None
    while i < len(adv_data):
        ad_field_length = adv_data[i]
        ad_field_type = adv_data[i + 1]
        ad_data = adv_data[i + 2: i + 1 + ad_field_length]
        if ad_field_type == 0x09:
            complete_local_name = ad_data
        if ad_field_type == 0x08:
            short_local_name = ad_data
        i += ad_field_length + 1
    return (complete_local_name, short_local_name)

bt_to_aws_queue = queue.Queue()

class App(BluetoothApp):
    """ Application derived from generic BluetoothApp. """
    def event_handler(self, evt):
        """ Override default event handler of the parent class. """
        # This event indicates the device has started and the radio is ready.
        # Do not call any stack command before receiving this boot event!
        if evt == "bt_evt_system_boot":
            self.adv_handle = None
            print("BT system boot")
            #self.gattdb_init()
            #self.adv_start()
            self.scan_start()

        # This event indicates that a new connection was opened.
        elif evt == "bt_evt_connection_opened":
            print("Connection opened")

        # This event indicates that a connection was closed.
        elif evt == "bt_evt_connection_closed":
            print("Connection closed")
            self.adv_start()

        elif evt == "bt_evt_scanner_scan_report":
            complete_local_name, short_local_name = parse_adv_data(evt.data)
            if complete_local_name is not None and complete_local_name != b'Cosori Gooseneck Kettle':
                bt_to_aws_queue.put(complete_local_name)
                print(evt)
                #print(f"Scan Report\n\tAddress: {evt.address}\n\tLong Name: {complete_local_name}\n\tShort Name: {short_local_name}")

        ####################################
        # Add further event handlers here. #
        ####################################

    def scan_start(self):
        """ Start scanning. """
        """ 1M PHY, 10ms scan interval, 10ms scan window, time in units of 0.625ms """
        self.lib.bt.scanner.set_timing(1, 16000, 1600)
        #self.lib.bt.scanner.set_timing(1, 16, 16)
        """ 1M PHY, active scanning, which will ask make scan request """
        self.lib.bt.scanner.set_mode(1,1)
        """ Scan on 1M PHY, both limited and general discoverable """
        self.lib.bt.scanner.start(1,1)
        
    def adv_start(self):
        """ Start advertising. """
        if self.adv_handle is None:
            # Create advertising set for the first call.
            _, self.adv_handle = self.lib.bt.advertiser.create_set()
            # Set advertising interval to 100 ms.
            self.lib.bt.advertiser.set_timing(
                self.adv_handle,
                160,  # interval min
                160,  # interval max
                0,    # duration
                0)    # max events
        self.lib.bt.advertiser.start(
            self.adv_handle,
            self.lib.bt.advertiser.DISCOVERY_MODE_GENERAL_DISCOVERABLE,
            self.lib.bt.advertiser.CONNECTION_MODE_CONNECTABLE_SCANNABLE)

# Script entry point.
if __name__ =="__main__":
    ap = aws_pipe(bt_to_aws_queue)
    ap.start_pipe()
    parser = argparse.ArgumentParser(description=__doc__)
    # Instantiate the application.
    app = App(parser=parser)
    # Running the application blocks execution until it terminates.
    app.run()
    ap.disconnect()
