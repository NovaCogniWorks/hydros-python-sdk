"""
Tests for MQTT metrics utility module.

This module tests the MqttMetrics model and utility functions for sending metrics data.
"""

import time
import unittest
from unittest.mock import Mock, MagicMock, patch
from hydros_agent_sdk.utils.mqtt_metrics import (
    MqttMetrics,
    send_metrics,
    send_metrics_batch,
    create_mock_metrics
)


class TestMqttMetrics(unittest.TestCase):
    """Test cases for MqttMetrics model."""

    def test_create_metrics_with_all_fields(self):
        """Test creating MqttMetrics with all required fields."""
        metrics = MqttMetrics(
            source_id="TWINS_SIMULATION_AGENT",
            job_instance_id="task_123",
            object_id=1001,
            object_name="Gate_01",
            step_index=10,
            source_timestamp_ms=1706601234567,
            metrics_code="gate_opening",
            value=0.75
        )

        self.assertEqual(metrics.source_id, "TWINS_SIMULATION_AGENT")
        self.assertEqual(metrics.job_instance_id, "task_123")
        self.assertEqual(metrics.object_id, 1001)
        self.assertEqual(metrics.object_name, "Gate_01")
        self.assertEqual(metrics.step_index, 10)
        self.assertEqual(metrics.source_timestamp_ms, 1706601234567)
        self.assertEqual(metrics.metrics_code, "gate_opening")
        self.assertEqual(metrics.value, 0.75)

    def test_metrics_json_serialization(self):
        """Test JSON serialization of MqttMetrics."""
        metrics = MqttMetrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            source_timestamp_ms=1000000,
            metrics_code="test_metric",
            value=1.23
        )

        json_str = metrics.model_dump_json()
        self.assertIn('"source_id":"AGENT"', json_str)
        self.assertIn('"job_instance_id":"task_1"', json_str)
        self.assertIn('"object_id":100', json_str)
        self.assertIn('"metrics_code":"test_metric"', json_str)
        self.assertIn('"value":1.23', json_str)

    def test_metrics_dict_conversion(self):
        """Test converting MqttMetrics to dictionary."""
        metrics = MqttMetrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            source_timestamp_ms=1000000,
            metrics_code="test_metric",
            value=1.23
        )

        metrics_dict = metrics.model_dump()
        self.assertEqual(metrics_dict['source_id'], "AGENT")
        self.assertEqual(metrics_dict['job_instance_id'], "task_1")
        self.assertEqual(metrics_dict['object_id'], 100)
        self.assertEqual(metrics_dict['metrics_code'], "test_metric")
        self.assertEqual(metrics_dict['value'], 1.23)


class TestCreateMockMetrics(unittest.TestCase):
    """Test cases for create_mock_metrics helper function."""

    def test_create_mock_metrics_with_timestamp(self):
        """Test creating mock metrics with explicit timestamp."""
        timestamp = 1706601234567
        metrics = create_mock_metrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            metrics_code="test_metric",
            value=1.23,
            timestamp_ms=timestamp
        )

        self.assertEqual(metrics.source_id, "AGENT")
        self.assertEqual(metrics.job_instance_id, "task_1")
        self.assertEqual(metrics.object_id, 100)
        self.assertEqual(metrics.object_name, "Object_1")
        self.assertEqual(metrics.step_index, 5)
        self.assertEqual(metrics.source_timestamp_ms, timestamp)
        self.assertEqual(metrics.metrics_code, "test_metric")
        self.assertEqual(metrics.value, 1.23)

    def test_create_mock_metrics_auto_timestamp(self):
        """Test creating mock metrics with automatic timestamp."""
        before = int(time.time() * 1000)
        metrics = create_mock_metrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            metrics_code="test_metric",
            value=1.23
        )
        after = int(time.time() * 1000)

        # Timestamp should be between before and after
        self.assertGreaterEqual(metrics.source_timestamp_ms, before)
        self.assertLessEqual(metrics.source_timestamp_ms, after)


class TestSendMetrics(unittest.TestCase):
    """Test cases for send_metrics function."""

    def test_send_metrics_success(self):
        """Test successful metrics sending."""
        # Create mock MQTT client
        mock_client = Mock()
        mock_result = Mock()
        mock_result.rc = 0  # Success
        mock_client.publish.return_value = mock_result

        # Create metrics
        metrics = create_mock_metrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            metrics_code="test_metric",
            value=1.23
        )

        # Send metrics
        result = send_metrics(mock_client, "test/topic", metrics, qos=0)

        # Verify
        self.assertTrue(result)
        mock_client.publish.assert_called_once()
        call_args = mock_client.publish.call_args
        self.assertEqual(call_args[0][0], "test/topic")  # topic
        self.assertEqual(call_args[1]['qos'], 0)  # qos

    def test_send_metrics_failure(self):
        """Test metrics sending failure."""
        # Create mock MQTT client with failure
        mock_client = Mock()
        mock_result = Mock()
        mock_result.rc = 1  # Failure
        mock_client.publish.return_value = mock_result

        # Create metrics
        metrics = create_mock_metrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            metrics_code="test_metric",
            value=1.23
        )

        # Send metrics
        result = send_metrics(mock_client, "test/topic", metrics, qos=0)

        # Verify failure
        self.assertFalse(result)

    def test_send_metrics_exception(self):
        """Test metrics sending with exception."""
        # Create mock MQTT client that raises exception
        mock_client = Mock()
        mock_client.publish.side_effect = Exception("Connection error")

        # Create metrics
        metrics = create_mock_metrics(
            source_id="AGENT",
            job_instance_id="task_1",
            object_id=100,
            object_name="Object_1",
            step_index=5,
            metrics_code="test_metric",
            value=1.23
        )

        # Send metrics
        result = send_metrics(mock_client, "test/topic", metrics, qos=0)

        # Verify failure
        self.assertFalse(result)


class TestSendMetricsBatch(unittest.TestCase):
    """Test cases for send_metrics_batch function."""

    def test_send_metrics_batch_all_success(self):
        """Test sending batch of metrics with all successful."""
        # Create mock MQTT client
        mock_client = Mock()
        mock_result = Mock()
        mock_result.rc = 0  # Success
        mock_client.publish.return_value = mock_result

        # Create multiple metrics
        metrics_list = [
            create_mock_metrics(
                source_id="AGENT",
                job_instance_id="task_1",
                object_id=100 + i,
                object_name=f"Object_{i}",
                step_index=5,
                metrics_code="test_metric",
                value=1.0 + i
            )
            for i in range(3)
        ]

        # Send batch
        success_count = send_metrics_batch(mock_client, "test/topic", metrics_list, qos=0)

        # Verify all succeeded
        self.assertEqual(success_count, 3)
        self.assertEqual(mock_client.publish.call_count, 3)

    def test_send_metrics_batch_partial_success(self):
        """Test sending batch of metrics with partial success."""
        # Create mock MQTT client with alternating success/failure
        mock_client = Mock()
        mock_results = [Mock(rc=0), Mock(rc=1), Mock(rc=0)]  # success, fail, success
        mock_client.publish.side_effect = mock_results

        # Create multiple metrics
        metrics_list = [
            create_mock_metrics(
                source_id="AGENT",
                job_instance_id="task_1",
                object_id=100 + i,
                object_name=f"Object_{i}",
                step_index=5,
                metrics_code="test_metric",
                value=1.0 + i
            )
            for i in range(3)
        ]

        # Send batch
        success_count = send_metrics_batch(mock_client, "test/topic", metrics_list, qos=0)

        # Verify partial success (2 out of 3)
        self.assertEqual(success_count, 2)
        self.assertEqual(mock_client.publish.call_count, 3)

    def test_send_metrics_batch_empty_list(self):
        """Test sending empty batch of metrics."""
        mock_client = Mock()
        metrics_list = []

        # Send empty batch
        success_count = send_metrics_batch(mock_client, "test/topic", metrics_list, qos=0)

        # Verify no calls made
        self.assertEqual(success_count, 0)
        mock_client.publish.assert_not_called()


class TestMetricsIntegration(unittest.TestCase):
    """Integration tests for metrics workflow."""

    def test_complete_metrics_workflow(self):
        """Test complete workflow: create, serialize, send."""
        # Create mock MQTT client
        mock_client = Mock()
        mock_result = Mock()
        mock_result.rc = 0
        mock_client.publish.return_value = mock_result

        # Create metrics using helper
        metrics = create_mock_metrics(
            source_id="TWINS_SIMULATION_AGENT",
            job_instance_id="simulation_task_001",
            object_id=1001,
            object_name="Gate_01",
            step_index=10,
            metrics_code="gate_opening",
            value=0.75
        )

        # Verify metrics structure
        self.assertEqual(metrics.source_id, "TWINS_SIMULATION_AGENT")
        self.assertEqual(metrics.object_name, "Gate_01")
        self.assertEqual(metrics.metrics_code, "gate_opening")
        self.assertEqual(metrics.value, 0.75)

        # Send metrics
        result = send_metrics(mock_client, "hydros/metrics", metrics, qos=0)

        # Verify success
        self.assertTrue(result)
        mock_client.publish.assert_called_once()

        # Verify JSON payload
        call_args = mock_client.publish.call_args
        payload = call_args[0][1]  # Second argument is payload
        self.assertIn("TWINS_SIMULATION_AGENT", payload)
        self.assertIn("Gate_01", payload)
        self.assertIn("gate_opening", payload)


if __name__ == '__main__':
    # Run tests
    unittest.main()
