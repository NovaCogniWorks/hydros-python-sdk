# 本地控制算法服务 live deploy

本目录将 SDK 中已有的 `custom-agent/power/control_algorithm_service.py` 独立部署为 `hydros-control-algorithms`，供 Edge 的远程控制算法适配器调用。它不启动示例 Agent，不依赖中央控制算法实例，也不属于 AI 模型服务。

使用仓库根目录 `deploy_k3s.sh deploy --cluster-target <target> --runtime-config-env-file <private-env>` 构建和部署。镜像复用 `custom-agent/power/Dockerfile`，Deployment 显式覆盖启动命令。Service 8015 仅供集群内部访问；调用地址由 Edge 的控制算法 endpoint 配置指定。

首次 on-premises 使用单副本。TCP 探针用于判断监听状态；业务验收还须对 `/engine/v1/api/control-algorithms/power_station_output_power_allocation/solve` 提交有限的测试输入并核对返回的执行器目标值。该验证仅计算输出，不连接真实设备。

渲染检查使用 `--skip-build --render-only`，集群预检使用 `--skip-build --dry-run`；仅 `--render-only` 不会跳过镜像构建。
