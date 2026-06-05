"""
Hydros MQTT topic 规则收口。

这里尽量和 Java 侧 HydroTopics 保持一致，别在各处手拼字符串。
"""


class HydrosTopics:
    """用于 Hydros MQTT topic 的构造器。"""

    HYDROS_COMMANDS_COORDINATION_TOPIC = "/hydros/commands/coordination"
    HYDROS_COMMANDS_AGENT_TOPIC = "/hydros/commands/agent"
    HYDROS_COMMANDS_SYSTEM_TOPIC = "/hydros/commands/system"
    HYDROS_DATA_EDGE_TOPIC_PREFIX = "/hydros/data/edges"
    HYDROS_DATA_EDGES_TOPIC = "/hydros/data/edges/#"

    @classmethod
    def get_coordination_command_topic(cls, cluster_id: str) -> str:
        return cls.HYDROS_COMMANDS_COORDINATION_TOPIC + "/" + cls._normalize_cluster_id(cluster_id)

    @classmethod
    def get_agent_command_topic(cls, cluster_id: str) -> str:
        return cls.HYDROS_COMMANDS_AGENT_TOPIC + "/" + cls._normalize_cluster_id(cluster_id)

    @classmethod
    def get_system_command_topic(cls, cluster_id: str) -> str:
        return cls.HYDROS_COMMANDS_SYSTEM_TOPIC + "/" + cls._normalize_cluster_id(cluster_id)

    @classmethod
    def get_hydro_data_topic(cls, cluster_id: str) -> str:
        return cls.HYDROS_DATA_EDGE_TOPIC_PREFIX + "/" + cls._normalize_cluster_id(cluster_id)

    @classmethod
    def get_hydro_data_generic_topic(cls, cluster_id: str) -> str:
        return cls.get_hydro_data_topic(cluster_id) + "/+"

    @staticmethod
    def _normalize_cluster_id(cluster_id: str) -> str:
        if cluster_id is None:
            raise ValueError("cluster_id 不能为空")

        normalized = str(cluster_id).strip().strip("/")
        if not normalized:
            raise ValueError("cluster_id 不能为空")
        return normalized
