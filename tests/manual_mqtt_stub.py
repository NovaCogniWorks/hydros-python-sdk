import time
import logging
import sys
import os

# Ensure the package is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from hydros_agent_sdk.mqtt import HydrosMqttClient, CommandDispatcher
from hydros_agent_sdk.protocol.commands import (
    SimTaskInitRequest, SimTaskInitResponse,
    TickCmdRequest, TickCmdResponse,
    HydroCmd, SimCommand
)
from hydros_agent_sdk.protocol.models import HydroAgentInstance, TopHydroObject, CommandStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(pathname)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger("TestStub")

BROKER_URL = "tcp://192.168.1.24"
BROKER_PORT = 1883
TOPIC = "/hydros/commands/coordination/weijiahao"

def mock_init_handler(client: HydrosMqttClient) -> callable:
    def handler(command: SimTaskInitRequest):
        logger.info(f"Handling SimTaskInitRequest: {command.command_id}")

        # Create a mock response
        response = SimTaskInitResponse(
            context=command.context,
            command_status=CommandStatus.SUCCEED,
            command_id=command.command_id,
            source_agent_instance=HydroAgentInstance(
                agent_id="mock_agent",
                agent_code="TWINS_SIMULATION_AGENT",
                agent_type="TWINS_SIMULATION_AGENT",
                agent_configuration_url="http://mock.url/config.yaml",
                biz_scene_instance_id=command.context.biz_scene_instance_id,
                hydros_cluster_id="default_cluster_24",
                hydros_node_id="default_edge",
                context=command.context
            ),
            created_agent_instances=[],
            managed_top_objects={},
            broadcast=False
        )

        # In a real scenario, we might publish this back to a reply topic
        # For this stub, we just publish back to the same topic to demonstrate serialization
        logger.info("Sending response...")
        client.publish_command(TOPIC, response)
    return handler

def mock_tick_handler(client: HydrosMqttClient) -> callable:
    def handler(command: TickCmdRequest):
        logger.info(f"Handling TickCmdRequest: {command.command_id}, TickId: {command.tick_id}")

        response = TickCmdResponse(
            context=command.context,
            command_id=command.command_id,
            source_agent_instance=HydroAgentInstance(
                agent_id="mock_agent",
                agent_code="MOCK_AGENT",
                agent_type="MOCK_TYPE",
                agent_configuration_url="http://mock.url/config.yaml",
                biz_scene_instance_id=command.context.biz_scene_instance_id,
                hydros_cluster_id="mock_cluster",
                hydros_node_id="mock_node",
                context=command.context
            ),
            broadcast=False
        )
        logger.info("Sending tick response...")
        client.publish_command(TOPIC, response)
    return handler

def main():
    dispatcher = CommandDispatcher()
    
    # Initialize Client with Dispatcher
    client_id = "hydros_python_stub"
    mqtt_client = HydrosMqttClient(client_id, dispatcher)
    
    # Register Handlers
    # Note: We pass the client to the handler factory so the handler can send responses
    dispatcher.register_handler("task_init_request", mock_init_handler(mqtt_client))
    dispatcher.register_handler("tick_cmd_request", mock_tick_handler(mqtt_client))
    
    # Connect and Subscribe
    try:
        mqtt_client.connect(BROKER_URL, BROKER_PORT)
        mqtt_client.subscribe(TOPIC)
        
        logger.info(f"Stub started. Listening on {TOPIC}...")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Stopping...")
        mqtt_client.disconnect()
    except Exception as e:
        logger.error(f"Error: {e}")

if __name__ == "__main__":
    main()
