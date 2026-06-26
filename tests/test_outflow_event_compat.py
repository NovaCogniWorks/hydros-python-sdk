from hydros_agent_sdk.protocol.events import OutflowTimeSeriesEvent


def test_outflow_time_series_event_accepts_time_series_url_and_object_time_series():
    event = OutflowTimeSeriesEvent.model_validate(
        {
            "hydro_event_type": "OUTFLOW_TIME_SERIES",
            "time_series_url": "https://example.com/outflow.json",
            "direct_load_time_series": True,
            "objectTimeSeries": [
                {
                    "objectId": 20100,
                    "objectType": "GateStation",
                    "objectName": "瀑布沟站",
                    "metricsCode": "planned_outflow",
                    "timeSeries": [{"step": 1, "value": 123.0}],
                }
            ],
        }
    )

    assert event.event_content_url == "https://example.com/outflow.json"
    assert event.direct_load_time_series is True
    assert len(event.object_time_series) == 1
    assert event.object_time_series[0].object_id == 20100


def test_outflow_time_series_event_accepts_object_ids():
    event = OutflowTimeSeriesEvent.model_validate(
        {
            "hydro_event_type": "OUTFLOW_TIME_SERIES",
            "object_time_series": [
                {
                    "time_series_name": "发电需求规划时间序列",
                    "object_ids": [20100, 20300, 20500],
                    "object_type": "Station",
                    "object_name": "三站出力",
                    "metrics_code": "output_power",
                    "time_series": [{"step": 1, "value": 123.0}],
                }
            ],
        }
    )

    assert len(event.object_time_series) == 1
    assert event.object_time_series[0].object_ids == [20100, 20300, 20500]
