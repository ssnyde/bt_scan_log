import argparse
import queue
import time
import random

from aws_iot import aws_pipe

bt_to_aws_queue = queue.Queue()

def sim_one_advertiser():
    try:
        while True:
            adv_data = {}
            adv_data['scanner_thing_name'] = 'scanner_sim_1'
            adv_data['timestamp'] = time.time()
            adv_data['DATETIME'] = time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(adv_data['timestamp']))
            adv_data['COMPLETE_LOCAL_NAME'] = 'one_advertiser_name'
            adv_data['RSSI'] = -60 + random.randint(-100,100)*0.1
            bt_to_aws_queue.put(adv_data)
            print("Added event")
            time.sleep(1)
    except KeyboardInterrupt:
        print('\r\nInterrupted, exitting')

def main():
    ap = aws_pipe(bt_to_aws_queue)
    ap.start_pipe()

    parser = argparse.ArgumentParser(
                    prog = 'ble_scan_sim',
                    description = 'Simulated receiving BLE advertisements')
    parser.add_argument('scenario')
    args = parser.parse_args()
    if args.scenario == "one_advertiser":
        sim_one_advertiser()

    ap.disconnect()

if __name__ =="__main__":
    main()