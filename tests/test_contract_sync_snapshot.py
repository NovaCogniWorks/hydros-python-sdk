from scripts.contract_sync_snapshot import (
    java_enum_members,
    java_fields,
    java_string_constants,
    java_test_method_source,
    python_enum_members,
    python_string_constants,
)


def test_java_fields_uses_explicit_json_name_and_snake_case_default():
    source = """
public class ExampleCommand {
    @JsonProperty(required = true)
    private String commandId;

    @JsonProperty("exec_run_id")
    private String execRunId;
}
"""

    assert java_fields(source) == [
        "command_id (Java `commandId`, String,required)",
        "exec_run_id (Java `execRunId`, String,optional)",
    ]


def test_java_test_method_source_keeps_only_requested_method():
    source = """
@Test
void expectedMethod() {
    assertTrue(true);
}

@Test
void otherMethod() {
    assertTrue(false);
}
"""

    extracted = java_test_method_source(source, "expectedMethod")

    assert "expectedMethod" in extracted
    assert "otherMethod" not in extracted


def test_java_fields_recognizes_non_null_and_initialized_fields():
    source = """
public class ExampleCommand {
    @NonNull
    private String objectType;
    private Map<Long, Object> targetValueMap = new HashMap<>();
}
"""

    assert java_fields(source) == [
        "object_type (Java `objectType`, String,required)",
        "target_value_map (Java `targetValueMap`, Map<Long, Object>,optional)",
    ]


def test_catalog_and_enum_source_summaries_are_literal():
    java_catalog = 'public static final String AGTCMD_ACK = "ack";'
    python_catalog = 'class Catalog:\n    AGTCMD_ACK = "ack"\n'
    java_enum = 'ACK("ack", "Ack", String.class),'
    python_enum = 'class Values:\n    ACK = ("ack", "Ack", str)\n'

    assert java_string_constants(java_catalog) == ["AGTCMD_ACK = ack"]
    assert python_string_constants(python_catalog, "Catalog") == ["AGTCMD_ACK = ack"]
    assert java_enum_members(java_enum) == ["ACK = (ack, Ack, String)"]
    assert python_enum_members(python_enum, "Values") == ["ACK = ('ack', 'Ack', str)"]
