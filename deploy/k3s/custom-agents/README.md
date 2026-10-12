# 自定义调度服务部署基线

这些服务承接案例中的 `CENTRAL_SCHEDULING_AGENT_POWER` / `CENTRAL_SCHEDULING_AGENT_PUMP`，不能用普通 Java Central 或仅 HTTP 的 `hydros-control-algorithms` 替代。不要在同一集群启动重复的同类调度进程，包括保留但仍运行的备份容器。

| 环境 | Power | Pump |
| --- | --- | --- |
| production | Docker 192.168.20.52:2375，容器 hydros-power-agent，端口 8016 | 同主机 hydros-pump-agent，端口 8015 |
| staging | Docker 192.168.20.51:2375，容器 hydros-power-agent，端口 8015 | staging-pump.yaml |
| on-premises | on-premises-power.yaml | on-premises-pump.yaml |

Power 已验证镜像为 `registry.zot-oci.hydros.yuma.intra/yuma/images/hydros/dev/hydros-power-agent@sha256:f5a6acc3f6d856456af3d08a1579f39dd058943ef8f03b8cafc83a3120681e5f`。生产 Pump 本次保留原有镜像与容器，不能因为 staging/on-premises 新增服务而覆盖生产实例。

## 配置与检查

- 镜像不包含本地 `env.properties`。Power 使用运行时环境变量；Pump 模板从同 namespace 的 `hydros-pump-agent` Secret 挂载 `env.properties`，该 Secret 必须在部署前由现有凭据流程准备，禁止把凭据提交到仓库。
- Pump 配置文件必须包含 `mqtt_broker_url`、`mqtt_broker_port`、`hydros_cluster_id`、`hydros_node_id=default_central`；需要鉴权时还包括 `mqtt_username`、`mqtt_password`。配置值取目标环境 Central 的实际配置，不得从其他环境复制凭据。
- 模板显式设置 `HYDROS_METRICS_TOPIC=/hydros/data/edges/{hydros_cluster_id}`。只连上 MQTT 或 HTTP 探针通过，不代表已订阅任务指标。任务初始化日志必须出现带当前集群和任务 ID 的 `Subscribing central field metrics topic`。
- on-premises 使用已有 `hydros-onprem-trust` CA，保留 TLS 校验。
- on-premises Edge 默认远程算法地址为 `http://hydros-pump-agent.hydros.svc.cluster.local:8015`；Power 算法专用地址仍为 `http://hydros-control-algorithms.hydros.svc.cluster.local:8015`。不可只切默认地址而丢失 Power override。

部署前确认目标 context、镜像 digest、Secret/CA 存在，保存当前 Deployment/Service 及 Docker inspect 到权限受限的备份目录。先执行 `kubectl --context <target> -n hydros apply --dry-run=server -f <manifest>`，确认差异后应用并等待 rollout。首次部署和升级均须运行案例完整默认步数、核对最终任务状态及落库结果；TCP ready 不替代业务验收。

Docker 升级保留原 Env、HostConfig、挂载和端口，停止并重命名旧容器后再以固定 digest 创建新容器；旧容器保留停止状态。回退停止新容器、恢复旧名称与原启动配置。禁止同时启动新旧调度进程。

Kubernetes 升级回退使用本次变更前的 Deployment spec；首次新增的服务回退只删除本次创建的 Deployment/Service/Secret，执行前核对名称和资源归属。Edge endpoint 同步恢复原值。备份和回退不得覆盖运行中的任务，应先确认该环境相关任务已终止。

静态回归：`python tests/test_custom_agent_deployments.py`。
