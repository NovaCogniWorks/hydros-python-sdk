import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# 将外发计划智能体目录加入系统路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../custom-agent/pump/outflowplan')))

from pump_outflow_plan_agent import PumpOutflowPlanAgent
from hydros_agent_sdk.protocol.commands import (
    OutflowTimeSeriesRequest,
    SimTaskTerminateRequest,
)
from hydros_agent_sdk.protocol.models import (
    SimulationContext,
    TopHydroObject,
)
from hydros_agent_sdk.protocol.events import OutflowTimeSeriesEvent

class TestPumpOutflowPlanAgent(unittest.TestCase):
    def setUp(self):
        self.mock_client = MagicMock()
        self.mock_client.topic = "test/topic"
        
        self.context = SimulationContext(
            biz_scene_instance_id="test_scene",
            valid=True
        )
        
        self.agent = PumpOutflowPlanAgent(
            sim_coordination_client=self.mock_client,
            agent_id="test_agent_123",
            agent_code="test_code",
            agent_type="test_type",
            agent_name="Test Agent",
            context=self.context,
            hydros_cluster_id="cluster_1",
            hydros_node_id="node_1"
        )
        
        # 模拟 state_manager
        self.agent.state_manager = MagicMock()
        
        # 模拟拓扑结构
        mock_topology = MagicMock()
        mock_top_obj = TopHydroObject(object_id=1, object_name="Gate1", object_type="Gate")
        mock_topology.top_objects = [mock_top_obj]
        self.agent._topology = mock_topology
        
        # 模拟配置属性
        self.agent.properties.update({'planning_horizon': 5})
        
    def test_on_outflow_time_series(self):
        """测试响应外发流量请求"""
        mock_event = OutflowTimeSeriesEvent(
            hydro_event_type="OUTFLOW_TIME_SERIES",
            event_content_url="http://test.url"
        )
        
        request = OutflowTimeSeriesRequest(
            command_id="cmd_123",
            context=self.context,
            target_agent_instance=self.agent,
            hydro_event=mock_event
        )
        
        # 为了捕获 response，需要mock send_response或者依赖基类实现，基类调用了 sim_coordination_client.send_response / enqueue
        # 查看 OutflowPlanAgent 和 BaseHydroAgent 实现，如果使用了 send_response 实际上会调用 client.enqueue
        
        self.agent.on_outflow_time_series(request)
        
        # 验证协调客户端确实发送了响应
        self.mock_client.enqueue.assert_called_once()
        
        # 获取发送的数据
        sent_response = self.mock_client.enqueue.call_args[0][0]
        self.assertEqual(sent_response.command_type, "outflow_time_series_response")
        self.assertEqual(sent_response.command_id, "cmd_123")
        self.assertEqual(sent_response.command_status, "SUCCEED")
        
        # 验证计算出的计划
        self.assertIn("Gate", sent_response.outflow_time_series_map)
        plans = sent_response.outflow_time_series_map["Gate"]
        self.assertEqual(len(plans), 1)
        plan = plans[0]
        self.assertEqual(plan.object_name, "Gate1")
        self.assertEqual(len(plan.time_series), 5) # 匹配前面模拟的步长 5
        
        # 验证 _calculate_planned_outflow 的逻辑 (base 100 + step * 5)
        self.assertEqual(plan.time_series[0].step, 0)
        self.assertEqual(plan.time_series[0].value, 100.0)
        self.assertEqual(plan.time_series[1].step, 1)
        self.assertEqual(plan.time_series[1].value, 105.0)
        self.assertEqual(plan.time_series[4].step, 4)
        self.assertEqual(plan.time_series[4].value, 120.0)

    def test_on_terminate(self):
        """测试终止任务逻辑"""
        request = SimTaskTerminateRequest(
            command_id="cmd_term",
            context=self.context,
        )
        
        response = self.agent.on_terminate(request)
        
        self.assertEqual(response.command_status, "SUCCEED")
        self.assertIsNone(self.agent._topology)
        self.agent.state_manager.terminate_task.assert_called_once_with(self.context)
        self.agent.state_manager.remove_local_agent.assert_called_once_with(self.agent)

if __name__ == '__main__':
    unittest.main()
