#!/usr/bin/env python3
"""
Empty NCP-host Example Application.
"""

# Copyright 2021 Silicon Laboratories Inc. www.silabs.com
#
# SPDX-License-Identifier: Zlib
#
# The licensor of this software is Silicon Laboratories Inc.
#
# This software is provided 'as-is', without any express or implied
# warranty. In no event will the authors be held liable for any damages
# arising from the use of this software.
#
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
#
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgment in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.

import argparse
import os.path
import sys
import time
import json
import queue
import threading

from util import BluetoothApp
from util import PeriodicTimer
from awscrt import mqtt
from awsiot import mqtt_connection_builder

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

# AWS Values
AWS_IOT_ENDPOINT = "al9jms4pkzeur-ats.iot.us-east-1.amazonaws.com"
AWS_CERT_FILENAME = "/home/stephen/thing_local_tester/822ccf140cdb4b6387ecf961c6db738928fcc10103f230a6fcaeea5e0e431103-certificate.pem.crt"
AWS_PRI_KEY_FILENAME = "/home/stephen/thing_local_tester/822ccf140cdb4b6387ecf961c6db738928fcc10103f230a6fcaeea5e0e431103-private.pem.key"
AWS_CLIENT_ID = "thing_local_tester"
AWS_MESSAGE_TOPIC = "dt/bt_scan_log_v1/user1/home1/scanner1/localname1"

bt_to_aws_queue = queue.Queue()

class aws_pipe():
    def __init__(self):
        self.mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=AWS_IOT_ENDPOINT,
            cert_filepath=AWS_CERT_FILENAME,
            pri_key_filepath=AWS_PRI_KEY_FILENAME,
            on_connection_interrupted=self.on_connection_interrupted,
            on_connection_resumed=self.on_connection_resumed,
            client_id=AWS_CLIENT_ID,
            clean_session=False,
            keep_alive_secs=30)
        connect_future = self.mqtt_connection.connect()
        connect_future.result()
        print("Connected!")
        #message_json = json.dumps({"timestamp":time.time()})
        #self.mqtt_connection.publish(
        #        topic=AWS_MESSAGE_TOPIC,
        #        payload=message_json,
        #        qos=mqtt.QoS.AT_LEAST_ONCE)
        #time.sleep(1)
        #disconnect_future = self.mqtt_connection.disconnect()
        #disconnect_future.result()
        #print("Disconnected!")

    def on_timer_expire(self, evt_queue):
        evt_list = []
        while True:
            try:
                evt_list.append(evt_queue.get(block=False))
            except queue.Empty:
                break
        print(f"\r\nParsing {len(evt_list)} events\r\n")
        for evt in evt_list:
            complete_local_name, short_local_name = parse_adv_data(evt.data)
            if complete_local_name == b'monkey':
                topic = f"dt/bt_scan_log_v1/user1/home1/scanner1/{complete_local_name}"
                message_json = json.dumps({"timestamp":time.time()})
                print("Publish...")
                self.mqtt_connection.publish(
                    topic=AWS_MESSAGE_TOPIC,
                    payload=message_json,
                    qos=mqtt.QoS.AT_LEAST_ONCE)
                break

    def start_pipe(self):
        #self.t = threading.Timer(10.0, self.on_timer_expire, [bt_to_aws_queue])
        self.t = PeriodicTimer(10.0, self.on_timer_expire, [bt_to_aws_queue])
        self.t.start()

    def disconnect(self):
        self.t.stop()
        disconnect_future = self.mqtt_connection.disconnect()
        disconnect_future.result()
        print("Disconnected!")        

    def on_connection_interrupted(connection, error, **kwargs):
        print("Connection interrupted. error: {}".format(error))

    # Callback when an interrupted connection is re-established.
    def on_connection_resumed(connection, return_code, session_present, **kwargs):
        print("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

        if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
            print("Session did not persist. Resubscribing to existing topics...")
            resubscribe_future, _ = connection.resubscribe_existing_topics()

            # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
            # evaluate result with a callback instead.
            resubscribe_future.add_done_callback(on_resubscribe_complete)

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
                bt_to_aws_queue.put(evt)
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
    ap = aws_pipe()
    ap.start_pipe()
    parser = argparse.ArgumentParser(description=__doc__)
    # Instantiate the application.
    app = App(parser=parser)
    # Running the application blocks execution until it terminates.
    app.run()
    ap.disconnect()
