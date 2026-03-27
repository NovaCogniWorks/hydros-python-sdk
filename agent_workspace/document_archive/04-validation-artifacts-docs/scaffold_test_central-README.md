# scaffold_test_central

这是一个基于 hydros-agent-sdk 自动生成的外部 Agent 项目。

## 启动步骤

1. 安装依赖

`powershell
pip install -e .
pip install -e .
`

2. 修改配置

- conf/env.properties
- conf/agent.properties

3. 启动

`powershell
python launcher.py
`
"@

 = @"
mqtt_broker_url=tcp://127.0.0.1
mqtt_broker_port=1883
mqtt_topic=/hydros/commands/coordination/default_cluster
hydros_cluster_id=default_cluster
hydros_node_id=external_node_001
mqtt_username=
mqtt_password=


