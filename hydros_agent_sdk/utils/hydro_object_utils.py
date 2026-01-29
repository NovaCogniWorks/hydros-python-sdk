"""
Utility class for loading and parsing water network topology objects from YAML.

This module provides functionality similar to the Java HydroObjectUtilsV2 class,
allowing Python agents to load complex water network topology objects and properties
from YAML configuration files.
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
    """Enumeration of hydro object types."""
    GATE_STATION = "GateStation"
    DIVERSION_POINT = "DiversionPoint"
    CROSS_SECTION = "CrossSection"
    PUMP_STATION = "PumpStation"
    GATE = "Gate"
    SENSOR = "Sensor"
    CHANNEL = "Channel"
    SIPHON = "Siphon"
    TURBINE = "Turbine"


class MetricsCodes(str, Enum):
    """Enumeration of metrics codes for hydro objects."""
    WATER_LEVEL = "water_level"
    WATER_FLOW = "water_flow"
    GATE_OPENING = "gate_opening"
    GATE_OPENING_PERCENTAGE = "gate_opening_percentage"
    WATER_DEPTH = "water_depth"


class SimpleChildObject(BaseModel):
    """
    Represents a child object (cross-section, gate, sensor) under a parent hydro object.

    Attributes:
        object_id: Unique identifier for the child object
        object_type: Type of the child object
        object_name: Display name of the child object
        params: Custom parameters for the child object
        metrics: List of associated metrics codes
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
    Represents a top-level hydro object in the waterway.

    Attributes:
        object_id: Unique identifier for the object
        object_type: Type of the object (e.g., GateStation, Channel)
        object_name: Display name of the object
        params: Custom parameters for the object
        children: List of child objects (cross-sections, gates, sensors)
        km_pos: Kilometer position in the waterway
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
    Represents the complete waterway network structure with topology relationships.

    This class maintains the waterway topology with optimization indices for:
    - Child-to-parent mapping
    - Upstream/downstream relationships
    - Object caching for fast lookups

    Attributes:
        top_objects: List of top-level hydro objects
        child_to_parent_map: Maps child object IDs to parent object IDs
        upstream_map: Maps each object to its upstream neighbors
        downstream_map: Maps each object to its downstream neighbors
    """
    top_objects: List[TopHydroObject] = Field(default_factory=list, alias='topObjects')
    child_to_parent_map: Dict[int, int] = Field(default_factory=dict, alias='childToParentMap')
    upstream_map: Dict[int, List[int]] = Field(default_factory=dict, alias='upstreamMap')
    downstream_map: Dict[int, List[int]] = Field(default_factory=dict, alias='downstreamMap')

    # Internal cache for fast object lookups
    _object_cache: Dict[int, Any] = {}

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True

    def get_top_object(self, top_object_id: int) -> Optional[TopHydroObject]:
        """
        Get a top-level object by its ID.

        Args:
            top_object_id: The ID of the top-level object

        Returns:
            The TopHydroObject if found, None otherwise
        """
        for obj in self.top_objects:
            if obj.object_id == top_object_id:
                return obj
        return None

    def get_object(self, object_id: int) -> Optional[Any]:
        """
        Get any object (parent or child) by its ID with caching.

        Args:
            object_id: The ID of the object

        Returns:
            The object if found, None otherwise
        """
        # Check cache first
        if object_id in self._object_cache:
            return self._object_cache[object_id]

        # Search in top objects
        for top_obj in self.top_objects:
            if top_obj.object_id == object_id:
                self._object_cache[object_id] = top_obj
                return top_obj

            # Search in children
            for child in top_obj.children:
                if child.object_id == object_id:
                    self._object_cache[object_id] = child
                    return child

        return None

    def get_top_object_by_child_id(self, child_object_id: int) -> Optional[TopHydroObject]:
        """
        Find the parent top-level object of a child object.

        Args:
            child_object_id: The ID of the child object

        Returns:
            The parent TopHydroObject if found, None otherwise
        """
        parent_id = self.child_to_parent_map.get(child_object_id)
        if parent_id is not None:
            return self.get_top_object(parent_id)
        return None

    def is_child_object(self, object_id: int) -> bool:
        """
        Check if an object ID corresponds to a child object.

        Args:
            object_id: The ID to check

        Returns:
            True if it's a child object, False otherwise
        """
        return object_id in self.child_to_parent_map

    def get_objects(
        self,
        agent_managed_top_object_ids: Optional[Set[int]] = None,
        child_object_types: Optional[Set[str]] = None
    ) -> List[Any]:
        """
        Filter objects by managed IDs and child object types.

        Args:
            agent_managed_top_object_ids: Set of top-level object IDs to filter by
            child_object_types: Set of child object types to include

        Returns:
            List of filtered objects
        """
        result = []

        for top_obj in self.top_objects:
            # Filter by managed IDs if specified
            if agent_managed_top_object_ids and top_obj.object_id not in agent_managed_top_object_ids:
                continue

            # Add top object
            result.append(top_obj)

            # Add filtered children
            if child_object_types:
                for child in top_obj.children:
                    if child.object_type in child_object_types:
                        result.append(child)
            else:
                result.extend(top_obj.children)

        return result

    def find_neighbors(self, any_object_id: int) -> Dict[str, List[int]]:
        """
        Get upstream and downstream neighbors of an object.

        Args:
            any_object_id: The ID of the object

        Returns:
            Dictionary with 'upstream' and 'downstream' lists of neighbor IDs
        """
        return {
            'upstream': self.upstream_map.get(any_object_id, []),
            'downstream': self.downstream_map.get(any_object_id, [])
        }


class HydroObjectUtilsV2:
    """
    Utility class for loading and parsing water network topology objects from YAML.

    This class provides functionality similar to the Java HydroObjectUtilsV2,
    allowing agents to load complex water network topology objects and properties
    from YAML configuration files hosted on remote servers.

    Example usage:
        # Load topology with specific parameters and metrics
        params = {'max_opening', 'min_opening'}
        topology = HydroObjectUtilsV2.build_waterway_topology(
            modeling_yml_uri='http://example.com/objects.yaml',
            param_keys=params,
            with_metrics_code=True
        )

        # Access top-level objects
        for obj in topology.top_objects:
            print(f"Object: {obj.object_name} ({obj.object_type})")

        # Find object by ID
        obj = topology.get_object(1018)
    """

    @staticmethod
    def load_remote_yaml(url: str) -> Dict[str, Any]:
        """
        Load YAML content from a remote URL.

        Args:
            url: The URL of the YAML file

        Returns:
            Parsed YAML content as a dictionary

        Raises:
            Exception: If the URL cannot be accessed or YAML cannot be parsed
        """
        try:
            # Handle non-ASCII characters in URL
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
        param_keys: Optional[Set[str]] = None
    ) -> List[TopHydroObject]:
        """
        Parse hydro objects from YAML configuration.

        Args:
            topology_model_config_url: URL of the YAML configuration file
            param_keys: Set of parameter keys to include (None = include all)

        Returns:
            List of parsed TopHydroObject instances
        """
        yaml_data = HydroObjectUtilsV2.load_remote_yaml(topology_model_config_url)

        # Extract objects and cross_sections
        objects_list = yaml_data.get('objects', [])
        cross_sections_list = yaml_data.get('cross_sections', [])

        # Build cross_sections map for efficient lookup
        cross_sections_map = {cs['id']: cs for cs in cross_sections_list}

        logger.info(f"Parsing {len(objects_list)} objects from YAML")

        top_objects = []

        for obj_data in objects_list:
            # Extract basic properties
            object_id = obj_data.get('id')
            object_type = obj_data.get('type')
            object_name = obj_data.get('name', '')
            km_pos = obj_data.get('km_pos')

            # Filter parameters if param_keys specified
            params = {}
            if 'parameters' in obj_data:
                obj_params = obj_data['parameters']
                if param_keys:
                    params = {k: v for k, v in obj_params.items() if k in param_keys}
                else:
                    params = obj_params.copy()

            # Process children
            children = []

            # Process cross_section_children
            cross_section_children = obj_data.get('cross_section_children', [])
            for cs_child in cross_section_children:
                child_id = cs_child.get('id')
                child_type = cs_child.get('type', 'CrossSection')
                child_name = cs_child.get('name', '')

                # Get parameters from cross_sections map
                child_params = {}
                if child_id in cross_sections_map:
                    cs_data = cross_sections_map[child_id]
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

            # Process device_children
            device_children = obj_data.get('device_children', [])
            for dev_child in device_children:
                child_id = dev_child.get('id')
                child_type = dev_child.get('type', 'Device')
                child_name = dev_child.get('name', '')

                # Filter parameters
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

            # Create top object
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
        Append metrics codes to child objects.

        Args:
            top_objects: List of top-level objects to process
            with_metrics_code: Whether to generate metrics codes
        """
        if not with_metrics_code:
            return

        logger.info("Appending metrics codes to child objects")

        for top_obj in top_objects:
            for child in top_obj.children:
                metrics = []

                # Add metrics based on child object type
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
                elif child.object_type == HydroObjectType.PUMP_STATION:
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
        Build topology indices for child-to-parent, upstream, and downstream relationships.

        Args:
            top_objects: List of top-level objects
            yaml_data: Original YAML data containing connections

        Returns:
            Tuple of (child_to_parent_map, upstream_map, downstream_map)
        """
        child_to_parent_map = {}
        upstream_map = {}
        downstream_map = {}

        # Build child-to-parent map
        for top_obj in top_objects:
            for child in top_obj.children:
                child_to_parent_map[child.object_id] = top_obj.object_id

        # Build upstream/downstream maps from connections
        connections = yaml_data.get('connections', [])
        for conn in connections:
            from_obj = conn.get('from', {})
            to_obj = conn.get('to', {})

            from_id = from_obj.get('id')
            to_id = to_obj.get('id')

            if from_id and to_id:
                # from_id -> to_id means from_id is upstream of to_id
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
        Build complete waterway topology from YAML configuration.

        This is the main entry point for loading water network topology.

        Args:
            modeling_yml_uri: URL of the YAML configuration file
            param_keys: Set of parameter keys to include (None = include all)
            with_metrics_code: Whether to generate metrics codes for child objects

        Returns:
            WaterwayTopology object containing the complete topology

        Example:
            >>> params = {'max_opening', 'min_opening'}
            >>> topology = HydroObjectUtilsV2.build_waterway_topology(
            ...     'http://example.com/objects.yaml',
            ...     param_keys=params,
            ...     with_metrics_code=True
            ... )
            >>> print(f"Loaded {len(topology.top_objects)} objects")
        """
        logger.info(f"Building waterway topology from: {modeling_yml_uri}")

        # Load YAML data
        yaml_data = HydroObjectUtilsV2.load_remote_yaml(modeling_yml_uri)

        # Parse objects
        top_objects = HydroObjectUtilsV2.parse_objects(modeling_yml_uri, param_keys)

        # Append metrics codes if requested
        HydroObjectUtilsV2.append_with_metrics_codes(top_objects, with_metrics_code)

        # Build topology indices
        child_to_parent_map, upstream_map, downstream_map = \
            HydroObjectUtilsV2.build_topology_indices(top_objects, yaml_data)

        # Create topology object
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
        Convenience method to load topology from URL with default settings.

        Args:
            url: URL of the YAML configuration file

        Returns:
            WaterwayTopology object
        """
        return cls.build_waterway_topology(url, with_metrics_code=True)
