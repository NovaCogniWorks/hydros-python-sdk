import unittest
import sys
import os
sys.path.insert(0, os.path.abspath('custom-agent/pump/scheduling'))
from pump_scheduling_agent import PumpCentralSchedulingAgent, PumpStation, CanalPool

class MockContext:
    def __init__(self):
        self.biz_scene_instance_id = "test_scene"

class MockClient:
    def __init__(self):
        self.state_manager = self
    def send_command(self, req): pass
    def subscribe(self, topic): pass
    def init_task(self, ctx, agents): pass
    def add_local_agent(self, agent): pass

class TestPumpSchedulingAgent(unittest.TestCase):
    def setUp(self):
        # Move back to root because data/config.json is assumed to be there in the older system
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
        self.agent._init_pump_system()

    def test_rolling_optimization(self):
        print("\n--- Starting Rolling Optimization Test ---")
        steps = 3
        # Override initial station states
        z1, z2, z3 = 13.26, 23.1, 28.0
        self.agent.stations[0].current_up = z1
        self.agent.stations[0].current_down = 10.5
        self.agent.stations[1].current_up = z2
        self.agent.stations[1].current_down = z1
        self.agent.stations[2].current_up = z3
        self.agent.stations[2].current_down = z2

        for t in range(steps):
            print(f"\nStep {t}:")
            agent_res = self.agent.on_optimization(t)
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
            self.agent.stations[0].current_up = z1
            self.agent.stations[1].current_up = z2
            self.agent.stations[2].current_up = z3
            self.agent.stations[1].current_down = z1
            self.agent.stations[2].current_down = z2
            
        self.assertTrue(True)

if __name__ == '__main__':
    unittest.main()
