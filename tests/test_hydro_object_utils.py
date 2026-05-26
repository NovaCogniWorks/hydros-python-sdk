from unittest.mock import patch

from hydros_agent_sdk.utils.hydro_object_utils import HydroObjectUtilsV2


def build_yaml_data():
    return {
        "cross_sections": [
            {
                "id": 20001,
                "type": "CrossSection",
                "name": "Section 20001",
                "parameters": {
                    "bottom_elevation": 12.3,
                    "ignored": "value",
                },
            }
        ],
        "objects": [
            {
                "id": 20000,
                "type": "UnifiedCanal",
                "name": "Canal 20000",
                "cross_section_children": [
                    {
                        "role": "INLET",
                        "section_ref": {
                            "id": 20001,
                            "name": "Section 20001",
                        },
                    },
                    {
                        "role": "BROKEN",
                    },
                ],
                "device_children": [
                    {
                        "id": 20002,
                        "type": "Gate",
                        "name": "Gate 20002",
                    },
                    {
                        "type": "Gate",
                        "name": "Missing ID",
                    },
                ],
            }
        ],
        "connections": [],
    }


def test_parse_objects_resolves_cross_section_child_from_section_ref():
    top_objects = HydroObjectUtilsV2.parse_objects(
        "https://example.test/objects.yaml",
        param_keys={"bottom_elevation"},
        yaml_data=build_yaml_data(),
    )

    assert len(top_objects) == 1
    assert len(top_objects[0].children) == 2
    assert top_objects[0].children[0].object_id == 20001
    assert top_objects[0].children[0].object_type == "CrossSection"
    assert top_objects[0].children[0].object_name == "Section 20001"
    assert top_objects[0].children[0].params == {"bottom_elevation": 12.3}
    assert top_objects[0].children[1].object_id == 20002


def test_build_waterway_topology_loads_yaml_once():
    with patch(
        "hydros_agent_sdk.utils.hydro_object_utils.HydroObjectUtilsV2.load_remote_yaml",
        return_value=build_yaml_data(),
    ) as load_remote_yaml:
        topology = HydroObjectUtilsV2.build_waterway_topology(
            "https://example.test/objects.yaml",
            with_metrics_code=True,
        )

    load_remote_yaml.assert_called_once_with("https://example.test/objects.yaml")
    assert len(topology.top_objects) == 1
    assert topology.get_object(20001).object_name == "Section 20001"
    assert topology.child_to_parent_map[20001] == 20000
