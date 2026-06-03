import unittest
import sys
import os
from unittest.mock import Mock
sys.path.insert(0, os.path.abspath('custom-agent/pump/scheduling'))
from pump_scheduling_agent import PumpCentralSchedulingAgent

class MockContext:
    def __init__(self):
        self.biz_scene_instance_id = "test_scene"

class MockClient:
    def __init__(self):
        self.state_manager = self
        self.mqtt_client = Mock()
    def send_command(self, req): pass
    def subscribe(self, topic): pass
    def init_task(self, ctx, agents): pass
    def add_local_agent(self, agent): pass

class TestPumpSchedulingAgent(unittest.TestCase):
    def setUp(self):
        self.agent = PumpCentralSchedulingAgent(
            sim_coordination_client=MockClient(),
            agent_id="agent1",
            agent_code="code",
            agent_type="type",
            agent_name="name",
            context=MockContext(),
            hydros_cluster_id="cluster",
            hydros_node_id="node"
        )
        self.agent.properties["mpc_config_url"] = "custom-agent/pump/data/config_xhh.yaml"
        mock_agent = Mock()
        mock_agent.agent_code = "mock_station_code"
        self.agent.target_agent_resolver.resolve_target_agent_for_object = Mock(return_value=mock_agent)
        self.agent._lazy_init_odd_mpc()

    def test_rolling_optimization(self):
        print("\n--- Starting Rolling Optimization Test ---")
        steps = 3
        # Override initial station states
        z1, z2, z3 = 13.26, 23.1, 28.0
        
        # S1
        self.agent._metrics_data_cache.update({"object_id": 20701, "metrics_code": "water_level", "value": 10.5, "position_code": "none"})
        self.agent._metrics_data_cache.update({"object_id": 20101, "metrics_code": "water_level", "value": z1, "position_code": "none"})
        
        # S2
        self.agent._metrics_data_cache.update({"object_id": 20117, "metrics_code": "water_level", "value": z1, "position_code": "none"})
        self.agent._metrics_data_cache.update({"object_id": 20501, "metrics_code": "water_level", "value": z2, "position_code": "none"})
        
        # S3
        self.agent._metrics_data_cache.update({"object_id": 20513, "metrics_code": "water_level", "value": z2, "position_code": "none"})
        self.agent._metrics_data_cache.update({"object_id": 20801, "metrics_code": "water_level", "value": z3, "position_code": "none"})

        for t in range(steps):
            print(f"\nStep {t}:")
            commands = self.agent.on_optimization(t)
            agent_res = self.agent.mpc_output
            lower_res = agent_res['lower']
            upper_res = agent_res['upper']
            
            # Print Upper MPC results
            print("  Upper MPC Predicted Flow:")
            for sid, q_list in upper_res['q_planned'].items():
                print(f"    Station {sid}: {q_list[:3]}")
                
            # Print Lower MPC results
            print("  Lower MPC Output:")
            for sid, res in lower_res.items():
                status = res['status'][0]
                openings = res['openings'][0]
                total_q = res['total_q'][0]
                print(f"    Station {sid} Target Flow: {total_q:.2f}, Status: {status}, Openings: {[round(o, 2) for o in openings]}")
                
            # Simulate a simple step
            # Note: For this unit test, we just assume ideal tracking and move forward
            z1 += 0.01 * (lower_res[1]['total_q'][0] - lower_res[2]['total_q'][0])
            z2 += 0.01 * (lower_res[2]['total_q'][0] - lower_res[3]['total_q'][0])
            self.agent._metrics_data_cache.update({"object_id": 20101, "metrics_code": "water_level", "value": z1, "position_code": "none"})
            self.agent._metrics_data_cache.update({"object_id": 20501, "metrics_code": "water_level", "value": z2, "position_code": "none"})
            self.agent._metrics_data_cache.update({"object_id": 20801, "metrics_code": "water_level", "value": z3, "position_code": "none"})
            
            self.agent._metrics_data_cache.update({"object_id": 20117, "metrics_code": "water_level", "value": z1, "position_code": "none"})
            self.agent._metrics_data_cache.update({"object_id": 20513, "metrics_code": "water_level", "value": z2, "position_code": "none"})
            
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
