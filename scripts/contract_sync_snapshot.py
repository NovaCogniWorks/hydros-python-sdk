#!/usr/bin/env python3
"""Emit source-derived input for an AI review of Java/Python contract mirrors.

This tool deliberately does not define a schema or decide whether two DTOs are
aligned. Java protocol source remains authoritative. The output is a small,
repeatable evidence bundle that an AI reviewer can compare before a Python
contract change is accepted.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JAVA_PROTOCOL_ROOT = (
    PROJECT_ROOT.parents[1] / "hydros-agent-parent" / "hydros-agent-protocol"
)
JAVA_SUBTYPE_TEST_RELATIVE_PATH = (
    "src/test/java/com/hydros/protocol/CommandSubtypeRegistrationTest.java"
)


@dataclass(frozen=True)
class ContractSurface:
    """One Java DTO and its Python mirror selected for the current baseline."""

    name: str
    java_relative_path: str
    python_relative_path: str
    python_class_name: str
    java_test_method: Optional[str] = None


PHASE_ZERO_SURFACES = (
    ContractSurface(
        name="SimTaskInitRequest",
        java_relative_path=(
            "src/main/java/com/hydros/protocol/coordination/commands/SimTaskInitRequest.java"
        ),
        python_relative_path="hydros_agent_sdk/protocol/commands.py",
        python_class_name="SimTaskInitRequest",
    ),
    ContractSurface(
        name="TickCmdResponse",
        java_relative_path=(
            "src/main/java/com/hydros/protocol/coordination/commands/TickCmdResponse.java"
        ),
        python_relative_path="hydros_agent_sdk/protocol/commands.py",
        python_class_name="TickCmdResponse",
    ),
    ContractSurface(
        name="MpcExecutionStatusReport",
        java_relative_path=(
            "src/main/java/com/hydros/protocol/coordination/commands/report/"
            "MpcExecutionStatusReport.java"
        ),
        python_relative_path="hydros_agent_sdk/protocol/commands.py",
        python_class_name="MpcExecutionStatusReport",
        java_test_method="shouldDeserializeMpcExecutionStatusReportWithAnnotatedSubtypeName",
    ),
    ContractSurface(
        name="EdgeControlExecutionReport",
        java_relative_path=(
            "src/main/java/com/hydros/protocol/coordination/commands/report/"
            "EdgeControlExecutionReport.java"
        ),
        python_relative_path="hydros_agent_sdk/protocol/commands.py",
        python_class_name="EdgeControlExecutionReport",
        java_test_method="shouldDeserializeEdgeControlExecutionReportWithAnnotatedSubtypeName",
    ),
)


def find_class(module: ast.Module, class_name: str) -> ast.ClassDef:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise ValueError(f"Python class not found: {class_name}")


def python_fields(source: str, class_name: str) -> List[str]:
    """Return source-level Python field declarations without inferring semantics."""
    class_node = find_class(ast.parse(source), class_name)
    fields: List[str] = []
    for node in class_node.body:
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        annotation = ast.unparse(node.annotation)
        value = ""
        if node.value is not None:
            value = f" = {ast.unparse(node.value)}"
        fields.append(f"{node.target.id}: {annotation}{value}")
    return fields


def to_snake(name: str) -> str:
    """Mirror the Java protocol's snake-case JSON naming convention for field names."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def java_fields(source: str) -> List[str]:
    """Return direct Java DTO fields with their explicit or snake-case wire keys.

    This is intentionally a source summary, not a Java parser or a schema. It
    only covers direct fields in the selected DTO class, which keeps the AI
    review input small and makes inherited command-envelope fields explicit in
    the reviewer prompt rather than silently guessing them.
    """
    field_pattern = re.compile(
        r"^\s*(?:(?:private|protected|public)\s+)?(?:(?:final)\s+)?"
        r"(?P<type>[\w<>?, ]+)\s+(?P<name>\w+)\s*;$"
    )
    class_started = False
    depth = 0
    json_name: Optional[str] = None
    required = False
    fields: List[str] = []

    for line in source.splitlines():
        stripped = line.strip()
        if not class_started and " class " in f" {stripped} ":
            class_started = True

        if class_started and depth == 1:
            if stripped.startswith("@JsonProperty"):
                name_match = re.search(r'@JsonProperty\("([^"]+)"\)', stripped)
                json_name = name_match.group(1) if name_match else None
                required = "required = true" in stripped
            else:
                match = field_pattern.match(line)
                if match and " static " not in f" {line} ":
                    field_name = match.group("name")
                    wire_key = json_name or to_snake(field_name)
                    marker = " required" if required else " optional"
                    fields.append(
                        f"{wire_key} (Java `{field_name}`, {match.group('type').strip()},{marker.strip()})"
                    )
                    json_name = None
                    required = False

        if class_started:
            depth += line.count("{") - line.count("}")

    return fields


def java_subtype(source: str) -> Optional[str]:
    match = re.search(r"@JsonSubType\(name\s*=\s*([^)]+)\)", source)
    return match.group(1).strip() if match else None


def java_test_method_source(source: str, method_name: str) -> str:
    """Extract one focused Java test method without reading unrelated test code."""
    match = re.search(rf"void\s+{re.escape(method_name)}\s*\([^)]*\)\s*\{{", source)
    if match is None:
        raise ValueError(f"Java test method not found: {method_name}")

    start = match.start()
    cursor = source.find("{", start)
    depth = 0
    for index in range(cursor, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    raise ValueError(f"Java test method has no closing brace: {method_name}")


def render_surface(
    java_protocol_root: Path,
    surface: ContractSurface,
    java_subtype_test_source: Optional[str],
) -> str:
    java_path = java_protocol_root / surface.java_relative_path
    python_path = PROJECT_ROOT / surface.python_relative_path
    if not java_path.is_file():
        raise FileNotFoundError(f"Java DTO not found: {java_path}")
    if not python_path.is_file():
        raise FileNotFoundError(f"Python DTO module not found: {python_path}")

    java_source = java_path.read_text(encoding="utf-8")
    python_source = python_path.read_text(encoding="utf-8")
    fields = java_fields(java_source)
    subtype = java_subtype(java_source)

    lines = [f"## {surface.name}", ""]
    lines.append(f"- Java source: `{java_path}`")
    lines.append(f"- Python mirror: `{python_path}`")
    lines.append(f"- Java subtype: `{subtype or '(none found)'}`")
    lines.append(
        "- Java direct field declarations (wire key inferred as snake case when no explicit annotation):"
    )
    lines.extend(f"  - `{field}`" for field in fields)
    lines.append("- Python field declarations:")
    lines.extend(f"  - `{field}`" for field in python_fields(python_source, surface.python_class_name))
    if surface.java_test_method is not None:
        if java_subtype_test_source is None:
            raise FileNotFoundError(
                "Java subtype test source is required for "
                f"{surface.java_test_method}"
            )
        lines.append(f"- Focused Java serialization test: `{surface.java_test_method}`")
        lines.append("```java")
        lines.append(java_test_method_source(java_subtype_test_source, surface.java_test_method))
        lines.append("```")
    lines.append("")
    return "\n".join(lines)


def render_snapshot(java_protocol_root: Path, surfaces: Iterable[ContractSurface]) -> str:
    surface_list = list(surfaces)
    java_subtype_test_source = None
    if any(surface.java_test_method is not None for surface in surface_list):
        java_subtype_test_path = java_protocol_root / JAVA_SUBTYPE_TEST_RELATIVE_PATH
        if not java_subtype_test_path.is_file():
            raise FileNotFoundError(f"Java subtype test not found: {java_subtype_test_path}")
        java_subtype_test_source = java_subtype_test_path.read_text(encoding="utf-8")
    sections = [
        "# Java → Python contract AI review input",
        "",
        "- Canonical source: Java `hydros-agent-protocol` source and its focused tests.",
        "- Python role: mirror the Java wire contract; do not add alternate V2 wire names.",
        "- This is source-derived review input, not a JSON Schema and not a second contract source.",
        "- Required AI review: compare JSON keys, requiredness, enum/value semantics, "
        "command subtype, and Python aliases. Report `PASS`, `REVIEW`, or `FAIL` per surface.",
        "",
    ]
    sections.extend(
        render_surface(java_protocol_root, surface, java_subtype_test_source)
        for surface in surface_list
    )
    return "\n".join(sections)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--java-protocol-root",
        type=Path,
        default=DEFAULT_JAVA_PROTOCOL_ROOT,
        help="Path to the Java hydros-agent-protocol module.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional file to receive the markdown review input.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        snapshot = render_snapshot(args.java_protocol_root, PHASE_ZERO_SURFACES)
    except (FileNotFoundError, SyntaxError, ValueError) as error:
        print(f"contract sync snapshot failed: {error}", file=sys.stderr)
        return 1

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(snapshot, encoding="utf-8")
    else:
        print(snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
