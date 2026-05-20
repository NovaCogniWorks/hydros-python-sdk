import sys
import types


if "paho.mqtt.client" not in sys.modules:
    paho_module = types.ModuleType("paho")
    mqtt_module = types.ModuleType("paho.mqtt")
    client_module = types.ModuleType("paho.mqtt.client")
    reasoncodes_module = types.ModuleType("paho.mqtt.reasoncodes")

    class FakePublishResult:
        def wait_for_publish(self):
            return None

    class FakeMqttClient:
        def __init__(self, *args, **kwargs):
            self.published = []
            self.subscriptions = []
            self.on_connect = None
            self.on_message = None
            self.on_disconnect = None

        def reconnect_delay_set(self, *args, **kwargs):
            return None

        def username_pw_set(self, *args, **kwargs):
            return None

        def connect(self, *args, **kwargs):
            return 0

        def loop_start(self):
            return None

        def loop_stop(self):
            return None

        def disconnect(self):
            return None

        def subscribe(self, topic, qos=0):
            self.subscriptions.append((topic, qos))
            return (0, 1)

        def publish(self, topic, payload, qos=0):
            self.published.append((topic, payload, qos))
            return FakePublishResult()

    class FakeReasonCode:
        def __init__(self, packetType=None, aName=None, value=None):
            self.packetType = packetType
            self.aName = aName
            self.value = 0 if value is None and aName == "Success" else value or 0

    client_module.Client = FakeMqttClient
    client_module.CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)
    client_module.MQTTv311 = 4
    reasoncodes_module.ReasonCode = FakeReasonCode
    mqtt_module.client = client_module
    mqtt_module.reasoncodes = reasoncodes_module
    paho_module.mqtt = mqtt_module

    sys.modules["paho"] = paho_module
    sys.modules["paho.mqtt"] = mqtt_module
    sys.modules["paho.mqtt.client"] = client_module
    sys.modules["paho.mqtt.reasoncodes"] = reasoncodes_module
