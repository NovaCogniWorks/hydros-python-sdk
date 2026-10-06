# 集群配置驱动的 on-premises live deploy

在本应用目录执行：

```bash
./deploy_k3s.sh deploy --cluster-target hydros-cluster-on-premises --render-only
./deploy_k3s.sh deploy --cluster-target hydros-cluster-on-premises --dry-run
./deploy_k3s.sh deploy --cluster-target hydros-cluster-on-premises
```

只需本仓库、构建工具、镜像仓库权限和目标的 `-live-deploy` context；不需要 operator 的
`deployment-local` 目录或 `runtime-config.env`。render-only 和 dry-run 不构建、不推送镜像。
正常 deploy 仍从源码构建并推送 Zot，再 apply 和等待 rollout。

集群 metadata 的 `runtimeConfigSecret` 指向目标命名空间内的 Secret；
`deploymentPolicyConfigMap` 指向资源及部署策略。配置缺失、身份不匹配或应用未登记时，
构建前终止，不回退到其他环境。testing/staging/production 原有配置来源保持不变。

先合并集群管理的运行参数，再合并资源策略，之后统一部署。因此 CPU/memory、Java 堆、
Ontology 并发、Portal 登录跳转配置不再需要部署后手工 patch。集群管理的 env 列表优先于
源码模板；新增/删除运行参数也需要 operator 更新 Secret 内对应应用的配置。

生成的清单可能包含凭据，只能保存在私有目录，不应提交 Git、发到聊天或作为公开制品。
变更客户现场 IP 时，operator 需同步更新 metadata、Secret/策略里的 URL、网关和证书；
前端公开地址参与构建，需重新构建相关前端镜像。
