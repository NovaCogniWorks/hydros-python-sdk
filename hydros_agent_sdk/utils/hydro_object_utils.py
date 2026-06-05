"""
用于从 YAML 加载和解析水网拓扑对象的工具类。

本模块提供类似 Java HydroObjectUtilsV2 的能力，让 Python 智能体可以从
YAML 配置文件加载复杂水网拓扑对象和属性。
"""

import logging
import urllib.request
import urllib.parse
from typing import Dict, List, Optional, Set, Any
from enum import Enum

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class HydroObjectType(str, Enum):
    """水利对象类型枚举。"""
    GATE_STATION = "GateStation"
    DIVERSION_POINT = "DiversionPoint"
    CROSS_SECTION = "CrossSection"
    STATION = "Station"
    PUMP = "Pump"
    GATE = "Gate"
    SENSOR = "Sensor"
    CHANNEL = "Channel"
    SIPHON = "Siphon"
    TURBINE = "Turbine"


class MetricsCodes(str, Enum):
    """水利对象指标编码枚举。"""
    WATER_LEVEL = "water_level"
    WATER_FLOW = "water_flow"
    GATE_OPENING = "gate_opening"
    GATE_OPENING_PERCENTAGE = "gate_opening_percentage"
    WATER_DEPTH = "water_depth"


class SimpleChildObject(BaseModel):
    """
    表示父级水利对象下的子对象（断面、闸门、传感器等）。

    Attributes:
        object_id: 子对象唯一标识
        object_type: 子对象类型
        object_name: 子对象展示名称
        params: 子对象自定义参数
        metrics: 关联指标编码列表
    """
    object_id: int = Field(alias='objectId')
    object_type: str = Field(alias='objectType')
    object_name: str = Field(alias='objectName')
    params: Dict[str, Any] = Field(default_factory=dict)
    metrics: List[str] = Field(default_factory=list)

    class Config:
        populate_by_name = True
        use_enum_values = True


class TopHydroObject(BaseModel):
    """
    表示水道中的顶层水利对象。

    Attributes:
        object_id: 对象唯一标识
        object_type: 对象类型（例如 GateStation、Channel）
        object_name: 对象展示名称
        params: 对象自定义参数
        children: 子对象列表（断面、闸门、传感器等）
        km_pos: 对象在水道中的千米位置
    """
    object_id: int = Field(alias='objectId')
    object_type: str = Field(alias='objectType')
    object_name: str = Field(alias='objectName')
    params: Dict[str, Any] = Field(default_factory=dict)
    children: List[SimpleChildObject] = Field(default_factory=list)
    km_pos: Optional[float] = Field(default=None, alias='kmPos')

    class Config:
        populate_by_name = True
        use_enum_values = True


class WaterwayTopology(BaseModel):
    """
    表示带拓扑关系的完整水道网络结构。

    该类维护水道拓扑，并为以下场景建立优化索引：
    - 子对象到父对象映射
    - 上下游关系
    - 用于快速查找的对象缓存

    Attributes:
        top_objects: 顶层水利对象列表
        child_to_parent_map: 子对象 ID 到父对象 ID 的映射
        upstream_map: 每个对象到其上游邻居的映射
        downstream_map: 每个对象到其下游邻居的映射
    """
    top_objects: List[TopHydroObject] = Field(default_factory=list, alias='topObjects')
    child_to_parent_map: Dict[int, int] = Field(default_factory=dict, alias='childToParentMap')
    upstream_map: Dict[int, List[int]] = Field(default_factory=dict, alias='upstreamMap')
    downstream_map: Dict[int, List[int]] = Field(default_factory=dict, alias='downstreamMap')

    # 用于快速对象查找的内部缓存
    _object_cache: Dict[int, Any] = {}

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

    def get_top_object(self, top_object_id: int) -> Optional[TopHydroObject]:
        """
        按 ID 获取顶层对象。

        Args:
            top_object_id: 顶层对象 ID

        Returns:
            找到时返回 TopHydroObject，否则返回 None
        """
        for obj in self.top_objects:
            if obj.object_id == top_object_id:
                return obj
        return None

    def get_object(self, object_id: int) -> Optional[Any]:
        """
        按 ID 获取任意对象（父对象或子对象），并使用缓存加速。

        Args:
            object_id: 对象 ID

        Returns:
            找到时返回对象，否则返回 None
        """
        # 优先检查缓存
        if object_id in self._object_cache:
            return self._object_cache[object_id]

        # 在顶层对象中查找
        for top_obj in self.top_objects:
            if top_obj.object_id == object_id:
                self._object_cache[object_id] = top_obj
                return top_obj

            # 在子对象中查找
            for child in top_obj.children:
                if child.object_id == object_id:
                    self._object_cache[object_id] = child
                    return child

        return None

    def get_top_object_by_child_id(self, child_object_id: int) -> Optional[TopHydroObject]:
        """
        查找子对象所属的父级顶层对象。

        Args:
            child_object_id: 子对象 ID

        Returns:
            找到时返回父级 TopHydroObject，否则返回 None
        """
        parent_id = self.child_to_parent_map.get(child_object_id)
        if parent_id is not None:
            return self.get_top_object(parent_id)
        return None

    def is_child_object(self, object_id: int) -> bool:
        """
        检查对象 ID 是否对应子对象。

        Args:
            object_id: 要检查的 ID

        Returns:
            是子对象时返回 True，否则返回 False
        """
        return object_id in self.child_to_parent_map

    def get_objects(
        self,
        agent_managed_top_object_ids: Optional[Set[int]] = None,
        child_object_types: Optional[Set[str]] = None
    ) -> List[Any]:
        """
        按托管对象 ID 和子对象类型过滤对象。

        Args:
            agent_managed_top_object_ids: 用于过滤的顶层对象 ID 集合
            child_object_types: 要包含的子对象类型集合

        Returns:
            过滤后的对象列表
        """
        result = []

        for top_obj in self.top_objects:
            # 如果指定了 managed IDs，则按其过滤
            if agent_managed_top_object_ids and top_obj.object_id not in agent_managed_top_object_ids:
                continue

            # 添加顶层对象
            result.append(top_obj)

            # 添加过滤后的子对象
            if child_object_types:
                for child in top_obj.children:
                    if child.object_type in child_object_types:
                        result.append(child)
            else:
                result.extend(top_obj.children)

        return result

    def find_neighbors(self, any_object_id: int) -> Dict[str, List[int]]:
        """
        获取对象的上下游邻居。

        Args:
            any_object_id: 对象 ID

        Returns:
            包含 upstream 和 downstream 邻居 ID 列表的字典
        """
        return {
            'upstream': self.upstream_map.get(any_object_id, []),
            'downstream': self.downstream_map.get(any_object_id, [])
        }


class HydroObjectUtilsV2:
    """
    用于从 YAML 加载和解析水网拓扑对象的工具类。

    该类提供类似 Java HydroObjectUtilsV2 的能力，让智能体可以从远端服务器
    托管的 YAML 配置文件加载复杂水网拓扑对象和属性。

    使用示例：
        # 加载包含指定参数和指标的拓扑
        params = {'max_opening', 'min_opening'}
        topology = HydroObjectUtilsV2.build_waterway_topology(
            modeling_yml_uri='http://example.com/objects.yaml',
            param_keys=params,
            with_metrics_code=True
        )

        # 访问顶层对象
        for obj in topology.top_objects:
            print(f"Object: {obj.object_name} ({obj.object_type})")

        # 按 ID 查找对象
        obj = topology.get_object(1018)
    """

    @staticmethod
    def load_remote_yaml(url: str) -> Dict[str, Any]:
        """
        从远端 URL 加载 YAML 内容。

        Args:
            url: YAML 文件 URL

        Returns:
            解析后的 YAML 字典

        Raises:
            Exception: URL 无法访问或 YAML 无法解析时抛出
        """
        try:
            # 处理 URL 中的非 ASCII 字符
            parsed_url = urllib.parse.urlparse(url)
            encoded_path = urllib.parse.quote(parsed_url.path.encode('utf-8'))
            encoded_url = urllib.parse.urlunparse((
                parsed_url.scheme,
                parsed_url.netloc,
                encoded_path,
                parsed_url.params,
                parsed_url.query,
                parsed_url.fragment
            ))

            logger.info(f"Loading YAML from URL: {url}")

            with urllib.request.urlopen(encoded_url) as response:
                content = response.read().decode('utf-8')
                yaml_data = yaml.safe_load(content)

            logger.info(f"Successfully loaded YAML from {url}")
            return yaml_data

        except Exception as e:
            logger.error(f"Failed to load YAML from {url}: {e}")
            raise Exception(f"Failed to load remote YAML: {e}") from e

    @staticmethod
    def parse_objects(
        topology_model_config_url: str,
        param_keys: Optional[Set[str]] = None,
        yaml_data: Optional[Dict[str, Any]] = None,
    ) -> List[TopHydroObject]:
        """
        从 YAML 配置解析水利对象。

        Args:
            topology_model_config_url: YAML 配置文件 URL
            param_keys: 要包含的参数键集合（None 表示全部包含）

        Returns:
            解析后的 TopHydroObject 实例列表
        """
        if yaml_data is None:
            yaml_data = HydroObjectUtilsV2.load_remote_yaml(topology_model_config_url)

        # 提取 objects 和 cross_sections
        objects_list = yaml_data.get('objects', [])
        cross_sections_list = yaml_data.get('cross_sections', [])

        # 构建 cross_sections 映射以便高效查找
        cross_sections_map = {}
        for cs in cross_sections_list:
            cs_id = cs.get('id')
            if cs_id is None:
                continue
            cross_sections_map[cs_id] = cs

        logger.info(f"Parsing {len(objects_list)} objects from YAML")

        top_objects = []

        for obj_data in objects_list:
            # 提取基础属性
            object_id = obj_data.get('id')
            object_type = obj_data.get('type')
            object_name = obj_data.get('name', '')
            km_pos = obj_data.get('km_pos')

            # 如果指定 param_keys，则过滤参数
            params = {}
            if 'parameters' in obj_data:
                obj_params = obj_data['parameters']
                if param_keys:
                    params = {k: v for k, v in obj_params.items() if k in param_keys}
                else:
                    params = obj_params.copy()

            # 处理 children
            children = []

            # 处理 cross_section_children
            cross_section_children = obj_data.get('cross_section_children', [])
            for cs_child in cross_section_children:
                section_ref = cs_child.get('section_ref', {})
                child_id = section_ref.get('id')
                if child_id is None:
                    logger.warning(
                        "Skip cross section child without id: parentObjectId=%s, child=%s",
                        object_id,
                        cs_child,
                    )
                    continue

                child_type = 'CrossSection'
                child_name = section_ref.get('name', '')

                # 从 cross_sections 映射获取参数
                child_params = {}
                cs_data = cross_sections_map.get(child_id)
                if cs_data is not None:
                    if 'parameters' in cs_data:
                        cs_params = cs_data['parameters']
                        if param_keys:
                            child_params = {k: v for k, v in cs_params.items() if k in param_keys}
                        else:
                            child_params = cs_params.copy()

                child_obj = SimpleChildObject(
                    objectId=child_id,
                    objectType=child_type,
                    objectName=child_name,
                    params=child_params,
                    metrics=[]
                )
                children.append(child_obj)

            # 处理 device_children
            device_children = obj_data.get('device_children', [])
            for dev_child in device_children:
                child_id = dev_child.get('id')
                if child_id is None:
                    logger.warning(
                        "Skip device child without id: parentObjectId=%s, child=%s",
                        object_id,
                        dev_child,
                    )
                    continue

                child_type = dev_child.get('type', 'Device')
                child_name = dev_child.get('name', '')

                # 过滤参数
                child_params = {}
                if 'parameters' in dev_child:
                    dev_params = dev_child['parameters']
                    if param_keys:
                        child_params = {k: v for k, v in dev_params.items() if k in param_keys}
                    else:
                        child_params = dev_params.copy()

                child_obj = SimpleChildObject(
                    objectId=child_id,
                    objectType=child_type,
                    objectName=child_name,
                    params=child_params,
                    metrics=[]
                )
                children.append(child_obj)

            # 创建顶层对象
            top_obj = TopHydroObject(
                objectId=object_id,
                objectType=object_type,
                objectName=object_name,
                params=params,
                children=children,
                kmPos=km_pos
            )
            top_objects.append(top_obj)

        logger.info(f"Successfully parsed {len(top_objects)} top-level objects")
        return top_objects

    @staticmethod
    def append_with_metrics_codes(
        top_objects: List[TopHydroObject],
        with_metrics_code: bool = False
    ) -> None:
        """
        为子对象追加指标编码。

        Args:
            top_objects: 要处理的顶层对象列表
            with_metrics_code: 是否生成指标编码
        """
        if not with_metrics_code:
            return

        logger.info("Appending metrics codes to child objects")

        for top_obj in top_objects:
            for child in top_obj.children:
                metrics = []

                # 根据子对象类型添加指标
                if child.object_type == HydroObjectType.CROSS_SECTION:
                    metrics.extend([
                        MetricsCodes.WATER_LEVEL,
                        MetricsCodes.WATER_FLOW,
                        MetricsCodes.WATER_DEPTH
                    ])
                elif child.object_type == HydroObjectType.GATE:
                    metrics.extend([
                        MetricsCodes.GATE_OPENING,
                        MetricsCodes.GATE_OPENING_PERCENTAGE
                    ])
                elif child.object_type == HydroObjectType.PUMP:
                    metrics.extend([
                        MetricsCodes.WATER_FLOW
                    ])

                child.metrics = metrics

    @staticmethod
    def build_topology_indices(
        top_objects: List[TopHydroObject],
        yaml_data: Dict[str, Any]
    ) -> tuple[Dict[int, int], Dict[int, List[int]], Dict[int, List[int]]]:
        """
        构建子到父、上游和下游关系的拓扑索引。

        Args:
            top_objects: 顶层对象列表
            yaml_data: 包含连接关系的原始 YAML 数据

        Returns:
            (child_to_parent_map, upstream_map, downstream_map) 元组
        """
        child_to_parent_map = {}
        upstream_map = {}
        downstream_map = {}

        # 构建子对象到父对象的映射
        for top_obj in top_objects:
            for child in top_obj.children:
                child_to_parent_map[child.object_id] = top_obj.object_id

        # 根据 connections 构建上下游映射
        connections = yaml_data.get('connections', [])
        for conn in connections:
            from_obj = conn.get('from', {})
            to_obj = conn.get('to', {})

            from_id = from_obj.get('id')
            to_id = to_obj.get('id')

            if from_id and to_id:
                # 映射关系 from_id -> to_id 表示 from_id 位于 to_id 上游
                if to_id not in upstream_map:
                    upstream_map[to_id] = []
                upstream_map[to_id].append(from_id)

                if from_id not in downstream_map:
                    downstream_map[from_id] = []
                downstream_map[from_id].append(to_id)

        logger.info(f"Built topology indices: {len(child_to_parent_map)} child mappings, "
                   f"{len(connections)} connections")

        return child_to_parent_map, upstream_map, downstream_map

    @staticmethod
    def build_waterway_topology(
        modeling_yml_uri: str,
        param_keys: Optional[Set[str]] = None,
        with_metrics_code: bool = False
    ) -> WaterwayTopology:
        """
        从 YAML 配置构建完整水道拓扑。

        这是加载水网拓扑的主入口。

        Args:
            modeling_yml_uri: YAML 配置文件 URL
            param_keys: 要包含的参数键集合（None 表示全部包含）
            with_metrics_code: 是否为子对象生成指标编码

        Returns:
            包含完整拓扑的 WaterwayTopology 对象

        示例：
            >>> params = {'max_opening', 'min_opening'}
            >>> topology = HydroObjectUtilsV2.build_waterway_topology(
            ...     'http://example.com/objects.yaml',
            ...     param_keys=params,
            ...     with_metrics_code=True
            ... )
            >>> print(f"Loaded {len(topology.top_objects)} objects")
        """
        logger.info(f"Building waterway topology from: {modeling_yml_uri}")

        # 加载 YAML 数据
        yaml_data = HydroObjectUtilsV2.load_remote_yaml(modeling_yml_uri)

        # 解析对象
        top_objects = HydroObjectUtilsV2.parse_objects(
            modeling_yml_uri,
            param_keys,
            yaml_data=yaml_data,
        )

        # 如有需要则追加指标编码
        HydroObjectUtilsV2.append_with_metrics_codes(top_objects, with_metrics_code)

        # 构建拓扑索引
        child_to_parent_map, upstream_map, downstream_map = \
            HydroObjectUtilsV2.build_topology_indices(top_objects, yaml_data)

        # 创建拓扑对象
        topology = WaterwayTopology(
            topObjects=top_objects,
            childToParentMap=child_to_parent_map,
            upstreamMap=upstream_map,
            downstreamMap=downstream_map
        )

        logger.info(f"Successfully built waterway topology with {len(top_objects)} top-level objects")

        return topology

    @classmethod
    def from_url(cls, url: str) -> WaterwayTopology:
        """
        使用默认设置从 URL 加载拓扑的便捷方法。

        Args:
            url: YAML 配置文件 URL

        Returns:
            WaterwayTopology 对象
        """
        return cls.build_waterway_topology(url, with_metrics_code=True)
