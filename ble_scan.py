import argparse
import queue
import time

from util import BluetoothApp
from aws_iot import aws_pipe

#Reference Bluetooth Specification Assigned Numbers Doc, Common Data Types Section
BT_COMMON_DATA_TYPES_LOOKUP = {
    0x01: 'FLAGS',
    0x02: 'INCOMPLETE_LIST_OF_16-BIT_SERVICE_CLASS_UUIDS',
    0x03: 'COMPLETE_LIST_OF_16-BIT_SERVICE_CLASS_UUIDS',
    0x04: 'INCOMPLETE_LIST_OF_32-BIT_SERVICE_CLASS_UUIDS',
    0x05: 'COMPLETE_LIST_OF_32-BIT_SERVICE_CLASS_UUIDS',
    0x06: 'INCOMPLETE_LIST_OF_128-BIT_SERVICE_CLASS_UUIDS',
    0x07: 'COMPLETE_LIST_OF_128-BIT_SERVICE_CLASS_UUIDS',
    0x08: 'SHORTENED_LOCAL_NAME',
    0x09: 'COMPLETE_LOCAL_NAME',
    0x0A: 'TX_POWER_LEVEL',
    0x0D: 'CLASS_OF_DEVICE',
    0x0E: 'SIMPLE_PAIRING_HASH_C-192',
    0x0F: 'SIMPLE_PAIRING_RANDOMIZER_R-192',
    0x10: 'DEVICE_ID', #Also listed as Security Manager TK Value
    0x11: 'SECURITY_MANAGER_OUT_OF_BAND_FLAGS',
    0x12: 'SLAVE_CONNECTION_INTERVAL_RANGE',
    0x14: 'LIST_OF_16-BIT_SERVICE_SOLICITATION_UUIDS',
    0x15: 'LIST_OF_128-BIT_SERVICE_SOLICITATION_UUIDS',
    0x16: 'SERVICE_DATA_16-BIT_UUID',
    0x17: 'PUBLIC_TARGET_ADDRESS',
    0x18: 'RANDOM_TARGET_ADDRESS',
    0x19: 'APPEARANCE',
    0x1A: 'ADVERTISING_INTERVAL',
    0x1B: 'LE_BLUETOOTH_DEVICE_ADDRESS',
    0x1C: 'LE_ROLE',
    0x1D: 'SIMPLE_PAIRING_HASH_C-256',
    0x1E: 'SIMPLE_PAIRING_RANDOMIZER_R-256',
    0x1F: 'LIST_OF_32-BIT_SERVICE_SOLICITATION_UUIDS',
    0x20: 'SERVICE_DATA_32-BIT_UUID',
    0x21: 'SERVICE_DATA_128-BIT_UUID',
    0x22: 'LE_SECURE_CONNECTIONS_CONFIRMATION_VALUE',
    0x23: 'LE_SECURE_CONNECTIONS_RANDOM_VALUE',
    0x24: 'URI',
    0x25: 'INDOOR_POSITIONING',
    0x26: 'TRANSPORT_DISCOVERY_DATA',
    0x27: 'LE_SUPPORTED_FEATURES',
    0x28: 'CHANNEL_MAP_UPDATE_INDICATION',
    0x29: 'PB-ADV',
    0x2A: 'MESH_MESSAGE',
    0x2B: 'MESH_BEACON',
    0x2C: 'BIGINFO',
    0x2D: 'BROADCAST_CODE',
    0x2E: 'RESOLVABLE_SET_IDENTIFIER',
    0x2F: 'ADVERTISING_INTERVAL_LONG',
    0x30: 'BROADCAST_NAME',
    0x3D: '3D_INFORMATION',
    0xFF: 'MANUFACTURER_SPECIFIC_DATA'
}

BT_COMMON_DATA_TYPES_STR = [0x08, 0x09]

def parse_adv_data(adv_data):
    i = 0
    adv_data_dict = {}
    while i < len(adv_data):
        ad_field_length = adv_data[i]
        ad_field_type = adv_data[i + 1]
        ad_data = adv_data[i + 2: i + 1 + ad_field_length]
        try:
            ad_field_name = BT_COMMON_DATA_TYPES_LOOKUP[ad_field_type]
            if ad_field_type in BT_COMMON_DATA_TYPES_STR:
                adv_data_dict[ad_field_name] = ad_data.decode('utf-8')
            else:
                adv_data_dict[ad_field_name] = '0x' + ad_data.hex().upper()
                #adv_data_dict[ad_field_name] = base64.b64encode(ad_data).decode('utf-8')
        except KeyError:
            #adv_data_dict[ad_field_type] = base64.b64encode(ad_data).decode('utf-8')
            adv_data_dict[ad_field_type] = '0x' + ad_data.hex().upper()

        i += ad_field_length + 1
    return adv_data_dict

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

        elif evt == "bt_evt_scanner_legacy_advertisement_report" or evt == "bt_evt_scanner_extended_advertisement_report":
            adv_data = parse_adv_data(evt.data)
            adv_data['scanner_thing_name'] = 'scanner1'
            adv_data['timestamp'] = time.time()
            adv_data['DATETIME'] = time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(adv_data['timestamp']))
            adv_data['PDU'] = 'LEGACY' if evt == "bt_evt_scanner_legacy_advertisement_report" else 'EXTENDED'
            adv_data['CONNECTABLE'] = True if evt.event_flags & 1 else False
            adv_data['SCANNABLE'] = True if evt.event_flags & 2 else False
            adv_data['DIRECTED'] = True if evt.event_flags & 4 else False
            adv_data['SCAN_RESPONSE'] = True if evt.event_flags & 8 else False
            adv_data['ADDRESS'] = evt.address
            if evt.address_type == 0:
                adv_data['ADDRESS_TYPE'] = 'PUBLIC'
            elif evt.address_type == 1:
                adv_data['ADDRESS_TYPE'] = 'RANDOM'
            else:
                adv_data['ADDRESS_TYPE'] = 'DECODE_ERROR'
            if evt == "bt_evt_scanner_extended_advertisement_report":
                adv_data['ADV_SID'] = evt.adv_sid
                if evt.tx_power == 127:
                    adv_data['TX_POWER'] = 'INFORMATION_UNAVAILABLE'
                else:
                    adv_data['TX_POWER'] = evt.tx_power
                adv_data['RSSI'] = evt.rssi
                adv_data['CHANNEL'] = evt.channel
                adv_data['PERIODIC_INTERVAL'] = evt.periodic_interval * 1.25 #units of ms
            bt_to_aws_queue.put(adv_data)
            #print(evt)
            #print(adv_data)
            #print(f"Scan Report\n\tAddress: {evt.address}\n\tLong Name: {complete_local_name}\n\tShort Name: {short_local_name}")

        ####################################
        # Add further event handlers here. #
        ####################################

    def scan_start(self):
        """ Start scanning. """
        """ 1M PHY, 10ms scan interval, 10ms scan window, time in units of 0.625ms """
        #self.lib.bt.scanner.set_timing(1, 16000, 1600)
        #self.lib.bt.scanner.set_timing(1, 16, 16)
        """ 1M PHY, active scanning, which will ask make scan request """
        #self.lib.bt.scanner.set_mode(1,1)
        self.lib.bt.scanner.set_parameters(1, 16000, 1600)
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
