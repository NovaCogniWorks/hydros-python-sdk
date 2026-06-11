from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True

with open('/Users/macbook/WorkSpace/WJH/hydros-python-sdk/custom-agent/pump/data/mpc_config.yaml', 'r') as f:
    data = yaml.load(f)

for seg in data.get('topology', {}).get('channel_segments', []):
    if seg.get('hydro_profile_node') == '0-泗洪-睢宁段':
        seg['hydro_profile_node'] = '20100'
    elif seg.get('hydro_profile_node') == '1-睢宁-邳州段':
        seg['hydro_profile_node'] = '20500'
        
    if seg.get('disturbance_node') == '沙集站分水':
        seg['disturbance_node'] = '20200'
    elif seg.get('disturbance_node') == '沙集站入水':
        seg['disturbance_node'] = '20400'

station_map = {1: 20000, 2: 20300, 3: 20600}
pump_map = {
    1: {1: 20001, 2: 20002, 3: 20003, 4: 20004, 5: 20005},
    2: {1: 20301, 2: 20302, 3: 20303, 4: 20304},
    3: {1: 20601, 2: 20602, 3: 20603, 4: 20604}
}

for seg in data.get('topology', {}).get('channel_segments', []):
    up_id = seg.get('upstream_station_id')
    dn_id = seg.get('downstream_station_id')
    if up_id in station_map: seg['upstream_station_id'] = station_map[up_id]
    if dn_id in station_map: seg['downstream_station_id'] = station_map[dn_id]

for grp in data.get('topology', {}).get('channel_groups', []):
    up_id = grp.get('upstream_station_id')
    dn_id = grp.get('downstream_station_id')
    if up_id in station_map: grp['upstream_station_id'] = station_map[up_id]
    if dn_id in station_map: grp['downstream_station_id'] = station_map[dn_id]

for st in data.get('stations', []):
    old_id = st.get('id')
    if old_id in station_map:
        st['id'] = station_map[old_id]
        
        for u in st.get('units', []):
            old_uid = u.get('id')
            if old_id in pump_map and old_uid in pump_map[old_id]:
                u['id'] = pump_map[old_id][old_uid]

uas = data.get('runtime', {}).get('unit_availability', {}).get('unit_availability_scenarios', {}).get('baseline', {})
if uas:
    new_uas = {}
    for k, v in uas.items():
        try:
            ik = int(k)
            if ik in station_map:
                new_uas[str(station_map[ik])] = v
            else:
                new_uas[k] = v
        except ValueError:
            new_uas[k] = v
    data['runtime']['unit_availability']['unit_availability_scenarios']['baseline'] = new_uas

with open('/Users/macbook/WorkSpace/WJH/hydros-python-sdk/custom-agent/pump/data/mpc_config.yaml', 'w') as f:
    yaml.dump(data, f)
print("Updated YAML.")
