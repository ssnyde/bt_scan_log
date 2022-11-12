import queue
import json
import time

from awscrt import mqtt
from awsiot import mqtt_connection_builder, iotshadow
from util import PeriodicTimer

from concurrent.futures import Future
import sys
import threading
import traceback
from uuid import uuid4

# AWS Values
AWS_IOT_ENDPOINT = "al9jms4pkzeur-ats.iot.us-east-1.amazonaws.com"
AWS_CERT_FILENAME = "/home/stephen/thing_local_tester/822ccf140cdb4b6387ecf961c6db738928fcc10103f230a6fcaeea5e0e431103-certificate.pem.crt"
AWS_PRI_KEY_FILENAME = "/home/stephen/thing_local_tester/822ccf140cdb4b6387ecf961c6db738928fcc10103f230a6fcaeea5e0e431103-private.pem.key"
AWS_CLIENT_ID = "thing_local_tester"
TOPIC_PREFIX = "dt/bt_scan_log_v1/"
SHADOW_PROPERTY = "scan_period_s"
SHADOW_VALUE_DEFAULT = "yo donkey"
SHADOW_THING_NAME = "local_tester"

class LockedData:
    def __init__(self):
        self.lock = threading.Lock()
        self.shadow_value = None
        self.disconnect_called = False
        self.request_tokens = set()

class aws_pipe():
    def __init__(self, bt_to_aws_queue):
        self.bt_to_aws_queue = bt_to_aws_queue
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
        self.shadow_client = iotshadow.IotShadowClient(self.mqtt_connection)
        print("Connected!")
        self.locked_data = LockedData()

        # Subscribe to necessary topics.
        # Note that is **is** important to wait for "accepted/rejected" subscriptions
        # to succeed before publishing the corresponding "request".
        print("Subscribing to Update responses...")
        update_accepted_subscribed_future, _ = self.shadow_client.subscribe_to_update_shadow_accepted(
            request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=SHADOW_THING_NAME),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self.on_update_shadow_accepted)

        update_rejected_subscribed_future, _ = self.shadow_client.subscribe_to_update_shadow_rejected(
            request=iotshadow.UpdateShadowSubscriptionRequest(thing_name=SHADOW_THING_NAME),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self.on_update_shadow_rejected)

        # Wait for subscriptions to succeed
        update_accepted_subscribed_future.result()
        update_rejected_subscribed_future.result()

        print("Subscribing to Get responses...")
        get_accepted_subscribed_future, _ = self.shadow_client.subscribe_to_get_shadow_accepted(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=SHADOW_THING_NAME),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self.on_get_shadow_accepted)

        get_rejected_subscribed_future, _ = self.shadow_client.subscribe_to_get_shadow_rejected(
            request=iotshadow.GetShadowSubscriptionRequest(thing_name=SHADOW_THING_NAME),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self.on_get_shadow_rejected)

        # Wait for subscriptions to succeed
        get_accepted_subscribed_future.result()
        get_rejected_subscribed_future.result()

        print("Subscribing to Delta events...")
        delta_subscribed_future, _ = self.shadow_client.subscribe_to_shadow_delta_updated_events(
            request=iotshadow.ShadowDeltaUpdatedSubscriptionRequest(thing_name=SHADOW_THING_NAME),
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=self.on_shadow_delta_updated)

        # Wait for subscription to succeed
        delta_subscribed_future.result()


    def on_timer_expire(self, evt_queue):
        evt_list = []
        while True:
            try:
                evt_list.append(evt_queue.get(block=False))
            except queue.Empty:
                break
        print(f"\r\nParsing {len(evt_list)} events\r\n")
        for adv_data in evt_list:
            topic = f"{TOPIC_PREFIX}{adv_data['scanner_thing_name']}"
            message_json = json.dumps(adv_data)
            print(message_json)
            print("Publish...")
            self.mqtt_connection.publish(
                topic=topic,
                payload=message_json,
                qos=mqtt.QoS.AT_LEAST_ONCE)

    def start_pipe(self):
        self.t = PeriodicTimer(1, self.on_timer_expire, [self.bt_to_aws_queue])
        self.t.start()

    def disconnect(self):
        try:
            self.t.stop()
        except AttributeError:
            pass
        disconnect_future = self.mqtt_connection.disconnect()
        disconnect_future.result()
        print("Disconnected!")   

    def get_shadow(self):
        with self.locked_data.lock:
            # use a unique token so we can correlate this "request" message to
            # any "response" messages received on the /accepted and /rejected topics
            token = str(uuid4())

            publish_get_future = self.shadow_client.publish_get_shadow(
                request=iotshadow.GetShadowRequest(thing_name=SHADOW_THING_NAME, client_token=token),
                qos=mqtt.QoS.AT_LEAST_ONCE)

            self.locked_data.request_tokens.add(token)

        # Ensure that publish succeeds
        publish_get_future.result()     

    def on_connection_interrupted(self, connection, error, **kwargs):
        print("Connection interrupted. error: {}".format(error))

    def on_resubscribe_complete(self, resubscribe_future):
        resubscribe_results = resubscribe_future.result()
        print("Resubscribe results: {}".format(resubscribe_results))

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("Server rejected resubscribe to topic: {}".format(topic))
    
    # Callback when an interrupted connection is re-established.
    def on_connection_resumed(self, connection, return_code, session_present, **kwargs):
        print("Connection resumed. return_code: {} session_present: {}".format(return_code, session_present))

        if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
            print("Session did not persist. Resubscribing to existing topics...")
            resubscribe_future, _ = connection.resubscribe_existing_topics()

            # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
            # evaluate result with a callback instead.
            resubscribe_future.add_done_callback(self.on_resubscribe_complete)
    
    def set_local_value_due_to_initial_query(self, reported_value):
        with self.locked_data.lock:
            self.locked_data.shadow_value = reported_value

    def change_shadow_value(self, value):
        with self.locked_data.lock:
            if self.locked_data.shadow_value == value:
                print("Local value is already '{}'.".format(value))
                print("Enter desired value: ") # remind user they can input new values
                return

            print("Changed local shadow value to '{}'.".format(value))
            self.locked_data.shadow_value = value

            print("Updating reported shadow value to '{}'...".format(value))

            # use a unique token so we can correlate this "request" message to
            # any "response" messages received on the /accepted and /rejected topics
            token = str(uuid4())

            # if the value is "clear shadow" then send a UpdateShadowRequest with None
            # for both reported and desired to clear the shadow document completely.
            if value == "clear_shadow":
                tmp_state = iotshadow.ShadowState(reported=None, desired=None, reported_is_nullable=True, desired_is_nullable=True)
                request = iotshadow.UpdateShadowRequest(
                    thing_name=SHADOW_THING_NAME,
                    state=tmp_state,
                    client_token=token,
                )
            # Otherwise, send a normal update request
            else:
                # if the value is "none" then set it to a Python none object to
                # clear the individual shadow property
                if value == "none":
                    value = None

                request = iotshadow.UpdateShadowRequest(
                thing_name=SHADOW_THING_NAME,
                state=iotshadow.ShadowState(
                    reported={ SHADOW_PROPERTY: value },
                    desired={ SHADOW_PROPERTY: value },
                    ),
                    client_token=token,
                )

            future = self.shadow_client.publish_update_shadow(request, mqtt.QoS.AT_LEAST_ONCE)

            self.locked_data.request_tokens.add(token)

            future.add_done_callback(self.on_publish_update_shadow)


    def on_get_shadow_accepted(self, response):
        # type: (iotshadow.GetShadowResponse) -> None
        try:
            with self.locked_data.lock:
                # check that this is a response to a request from this session
                try:
                    self.locked_data.request_tokens.remove(response.client_token)
                except KeyError:
                    print("Ignoring get_shadow_accepted message due to unexpected token.")
                    return

                print("Finished getting initial shadow state.")
                if self.locked_data.shadow_value is not None:
                    print("  Ignoring initial query because a delta event has already been received.")
                    return

            if response.state:
                print(response.state)
                if response.state.delta:
                    value = response.state.delta.get(SHADOW_PROPERTY)
                    if value:
                        print("  Shadow contains delta value '{}'.".format(value))
                        self.change_shadow_value(value)
                        return

                if response.state.reported:
                    value = response.state.reported.get(SHADOW_PROPERTY)
                    if value:
                        print("  Shadow contains reported value '{}'.".format(value))
                        self.set_local_value_due_to_initial_query(response.state.reported[SHADOW_PROPERTY])
                        return

            print("  Shadow document lacks '{}' property. Setting defaults...".format(SHADOW_PROPERTY))
            self.change_shadow_value(SHADOW_VALUE_DEFAULT)
            return

        except Exception as e:
            exit(e)

    def on_get_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        try:
            # check that this is a response to a request from this session
            with self.locked_data.lock:
                try:
                    self.locked_data.request_tokens.remove(error.client_token)
                except KeyError:
                    print("Ignoring get_shadow_rejected message due to unexpected token.")
                    return

            if error.code == 404:
                print("Thing has no shadow document. Creating with defaults...")
                self.change_shadow_value(SHADOW_VALUE_DEFAULT)
            else:
                exit("Get request was rejected. code:{} message:'{}'".format(
                    error.code, error.message))

        except Exception as e:
            exit(e)

    def on_shadow_delta_updated(self, delta):
        # type: (iotshadow.ShadowDeltaUpdatedEvent) -> None
        try:
            print("Received shadow delta event.")
            if delta.state and (SHADOW_PROPERTY in delta.state):
                value = delta.state[SHADOW_PROPERTY]
                if value is None:
                    print("  Delta reports that '{}' was deleted. Resetting defaults...".format(SHADOW_PROPERTY))
                    self.change_shadow_value(SHADOW_VALUE_DEFAULT)
                    return
                else:
                    print("  Delta reports that desired value is '{}'. Changing local value...".format(value))
                    if (delta.client_token is not None):
                        print ("  ClientToken is: " + delta.client_token)
                    self.change_shadow_value(value)
            else:
                print("  Delta did not report a change in '{}'".format(SHADOW_PROPERTY))

        except Exception as e:
            exit(e)

    def on_update_shadow_accepted(self, response):
        # type: (iotshadow.UpdateShadowResponse) -> None
        try:
            # check that this is a response to a request from this session
            with self.locked_data.lock:
                try:
                    self.locked_data.request_tokens.remove(response.client_token)
                except KeyError:
                    print("Ignoring update_shadow_accepted message due to unexpected token.")
                    return

            try:
                if response.state.reported != None:
                    if SHADOW_PROPERTY in response.state.reported:
                        print("Finished updating reported shadow value to '{}'.".format(response.state.reported[SHADOW_PROPERTY])) # type: ignore
                    else:
                        print ("Could not find shadow property with name: '{}'.".format(SHADOW_PROPERTY)) # type: ignore
                else:
                    print("Shadow states cleared.") # when the shadow states are cleared, reported and desired are set to None
            except:
                exit("Updated shadow is missing the target property")

        except Exception as e:
            exit(e)

    def on_update_shadow_rejected(self, error):
        # type: (iotshadow.ErrorResponse) -> None
        try:
            # check that this is a response to a request from this session
            with self.locked_data.lock:
                try:
                    self.locked_data.request_tokens.remove(error.client_token)
                except KeyError:
                    print("Ignoring update_shadow_rejected message due to unexpected token.")
                    return

            exit("Update request was rejected. code:{} message:'{}'".format(
                error.code, error.message))

        except Exception as e:
            exit(e)


    def on_publish_update_shadow(self, future):
        #type: (Future) -> None
        try:
            future.result()
            print("Update request published.")
        except Exception as e:
            print("Failed to publish update request.")
            exit(e)
        
if __name__ =="__main__":
    myq = queue.Queue()
    pipe = aws_pipe(myq)
    pipe.get_shadow()
    time.sleep(5)
    pipe.disconnect()