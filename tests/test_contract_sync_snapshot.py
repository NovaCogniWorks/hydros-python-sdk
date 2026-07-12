from scripts.contract_sync_snapshot import java_fields, java_test_method_source


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
