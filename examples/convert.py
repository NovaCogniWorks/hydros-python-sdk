import json
import yaml
import sys

def convert_daduhe(json_file, yaml_file):
    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        base = data['大渡河']['baseData']
        init = data['大渡河']['initialData']

    objects = []
    cross_sections = []
    connections = []
    next_id = 2000

    # 名称到 ID 的映射
    sec_name_to_id = {}
    channel_name_to_id = {}
    node_name_to_id = {}
    curve_name_to_id = {}
    turbine_name_to_id = {}
    gate_station_name_to_id = {}

    # 断面
    for sec_name, sec in base['sections'].items():
        sec_id = next_id
        next_id += 1
        sec_name_to_id[sec_name] = sec_id
        cs = {
            'id': sec_id,
            'type': 'CrossSection',
            'name': sec_name,
            'parameters': {
                'cross_section_geometry': {
                    'data_points': sec['yz'],
                    'left_bank_geometry_coordination': [sec['x1'], sec['y1']],
                    'right_bank_geometry_coordination': [sec['x2'], sec['y2']],
                },
                'location': sec.get('location', 0),
            }
        }
        cross_sections.append(cs)

    # 河道
    for ch_name, ch in base['channels'].items():
        ch_id = next_id
        next_id += 1
        channel_name_to_id[ch_name] = ch_id
        sec_children = [sec_name_to_id[sn] for sn in ch['sec_names'] if sn in sec_name_to_id]
        first_loc = 0
        if ch['sec_names'] and ch['sec_names'][0] in base['sections']:
            first_loc = base['sections'][ch['sec_names'][0]].get('location', 0)
        canal = {
            'id': ch_id,
            'type': 'UnifiedCanal',
            'name': ch_name,
            'geometry_coordination': ch['points'],
            'cross_section_children': sec_children,
            'parameters': {
                'manning_n': ch['nc'],
                'location': first_loc,
            }
        }
        objects.append(canal)

    # 节点
    for node_name, node in base['nodes'].items():
        node_id = next_id
        next_id += 1
        node_name_to_id[node_name] = node_id
        node_obj = {
            'id': node_id,
            'type': 'DisturbanceNode',
            'name': node_name,
            'geometry_coordination': [[node['x'], node['y']]],
            'device_children': [],
            'parameters': {'location': 0}
        }
        if node['nodeType'] == 2:   # 入流
            child = {
                'id': next_id,
                'type': 'DisturbanceNode_child',
                'name': f"{node_name}_inflow",
                'parameters': {'boundary_type': 'flow'}
            }
            next_id += 1
            node_obj['device_children'].append(child)
        elif node['nodeType'] == 1: # 出流
            child = {
                'id': next_id,
                'type': 'DisturbanceNode_child',
                'name': f"{node_name}_waterlevel",
                'parameters': {'boundary_type': 'waterlevel'}
            }
            next_id += 1
            node_obj['device_children'].append(child)
        objects.append(node_obj)

    # 曲线
    for curve_name, curve in base.get('curves', {}).items():
        curve_id = next_id
        next_id += 1
        curve_name_to_id[curve_name] = curve_id
        curve_obj = {
            'id': curve_id,
            'type': 'Curve',
            'name': curve_name,
            'parameters': {
                'curve_type': curve.get('type', '水轮机特性曲线'),
                'data': curve['data'],
                'header': curve.get('header', ['工况', '扬程(m)', '流量(m³/s)'])
            },
            'curve_children': []  # 稍后填充
        }
        objects.append(curve_obj)

    # 水轮机
    turbine_objects = []
    turbine_curve_map = {}  # 曲线名 -> 水轮机ID列表
    for turb_name, turb in base.get('turbines', {}).items():
        turb_id = next_id
        next_id += 1
        turbine_name_to_id[turb_name] = turb_id
        init_value = init['turbines'].get(turb_name, 0.0)
        turbine = {
            'id': turb_id,
            'type': 'Turbine',
            'name': turb_name,
            'locX': turb['locX'],
            'locY': turb['locY'],
            'turbines': init_value,
        }
        turbine_objects.append(turbine)
        curve_name = turb['curve']
        turbine_curve_map.setdefault(curve_name, []).append(turb_id)

    objects.extend(turbine_objects)

    # 将水轮机ID填入对应曲线的 curve_children
    for curve_name, turb_ids in turbine_curve_map.items():
        curve_id = curve_name_to_id.get(curve_name)
        if curve_id:
            for obj in objects:
                if obj['id'] == curve_id:
                    obj['curve_children'] = turb_ids
                    break

    # 闸门分组为 GateStation
    gate_groups = {}  # (node1, node2) -> list of (gate_name, gate)
    for gate_name, gate in base.get('gates', {}).items():
        key = (gate['node1'], gate['node2'])
        gate_groups.setdefault(key, []).append((gate_name, gate))

    for (node1, node2), gates in gate_groups.items():
        station_id = next_id
        next_id += 1
        station_name = f"GateStation_{node1}_{node2}"
        gate_station_name_to_id[station_name] = station_id
        device_children = []
        for gate_name, gate in gates:
            gate_id = next_id
            next_id += 1
            gate_obj = {
                'id': gate_id,
                'type': 'Gate',
                'name': gate_name,
                'parameters': {
                    'gate_width': gate['b'],
                    'max_opening': 10.0,  # 默认值，需根据实际调整
                    'bottom_elevation': gate['zb'],
                }
            }
            if 'c1' in gate:
                gate_obj['parameters']['c1'] = gate['c1']
                gate_obj['parameters']['c2'] = gate['c2']
                gate_obj['parameters']['c3'] = gate['c3']
                gate_obj['parameters']['c4'] = gate['c4']
            device_children.append(gate_obj)
        station_obj = {
            'id': station_id,
            'type': 'GateStation',
            'name': station_name,
            'geometry_coordination': [[base['nodes'][node1]['x'], base['nodes'][node1]['y']]],
            'cross_section_children': [],
            'device_children': device_children,
            'parameters': {'location': 0}
        }
        objects.append(station_obj)

    # 生成连接关系（包含 id 字段）
    # 河道-节点
    for ch_name, ch in base['channels'].items():
        node1 = ch['node1']
        node2 = ch['node2']
        connections.append({
            'from': {
                'type': 'DisturbanceNode',
                'name': node1,
                'id': node_name_to_id[node1],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'UnifiedCanal',
                'name': ch_name,
                'id': channel_name_to_id[ch_name],
                'to_port': 'inlet'
            }
        })
        connections.append({
            'from': {
                'type': 'UnifiedCanal',
                'name': ch_name,
                'id': channel_name_to_id[ch_name],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'DisturbanceNode',
                'name': node2,
                'id': node_name_to_id[node2],
                'to_port': 'inlet'
            }
        })

    # 闸站-节点
    for (node1, node2), _ in gate_groups.items():
        station_name = f"GateStation_{node1}_{node2}"
        connections.append({
            'from': {
                'type': 'DisturbanceNode',
                'name': node1,
                'id': node_name_to_id[node1],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'GateStation',
                'name': station_name,
                'id': gate_station_name_to_id[station_name],
                'to_port': 'inlet'
            }
        })
        connections.append({
            'from': {
                'type': 'GateStation',
                'name': station_name,
                'id': gate_station_name_to_id[station_name],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'DisturbanceNode',
                'name': node2,
                'id': node_name_to_id[node2],
                'to_port': 'inlet'
            }
        })

    # 水轮机-节点
    for turb_name, turb in base.get('turbines', {}).items():
        node1, node2 = turb['node1'], turb['node2']
        connections.append({
            'from': {
                'type': 'DisturbanceNode',
                'name': node1,
                'id': node_name_to_id[node1],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'Turbine',
                'name': turb_name,
                'id': turbine_name_to_id[turb_name],
                'to_port': 'inlet'
            }
        })
        connections.append({
            'from': {
                'type': 'Turbine',
                'name': turb_name,
                'id': turbine_name_to_id[turb_name],
                'from_port': 'outlet'
            },
            'to': {
                'type': 'DisturbanceNode',
                'name': node2,
                'id': node_name_to_id[node2],
                'to_port': 'inlet'
            }
        })

    # 最终输出
    output = {
        'cross_sections': cross_sections,
        'objects': objects,
        'connections': connections,
    }

    with open(yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(output, f, allow_unicode=True, sort_keys=False)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python convert.py input.json output.yaml")
        sys.exit(1)
    convert_daduhe(sys.argv[1], sys.argv[2])