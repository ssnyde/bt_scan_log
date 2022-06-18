import bgapi
def my_event_handler(evt):
    print("Received event: {}".format(evt))
l = bgapi.BGLib(bgapi.SerialConnector('/dev/ttyACM0'),'sl_bt.xapi',event_handler=my_event_handler)
l.open()
l.bt.system.hello()
