#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from cluster_runtime import load_cluster_runtime, apply_cluster_policy

LIVE_DEPLOY_TEMPLATE_NAME = "hydros-k3s-app-live-deploy-skill/app-live-deploy"
LIVE_DEPLOY_TEMPLATE_VERSION = "0.1.20"
LIVE_DEPLOY_TEMPLATE_SOURCE = "hydros-k3s-app-live-deploy-skill/assets/app-live-deploy/live_deploy.py"

# App-specific block. Modify only this block when copying or upgrading the template.
APP_NAME = "hydros-control-algorithms"
APP_PLACEMENT = "agentSandbox"  # shared or agentSandbox
APP_SPECIFIC_ENV_DEFAULTS: dict[str, str] = {}
APP_CLUSTER_METADATA_ENV: dict[str, str] = {}
BUILD_SCRIPT_ARGS = ["--tag", "{image_tag}"]
ROLLOUT_DEPLOYMENT_ENV: str | None = "DEPLOYMENT_NAME"
# End app-specific block.

METADATA_NAMESPACE = "hydros-system"
METADATA_CONFIGMAP = "hydros-cluster-deployment-metadata"
VALID_DEPLOYMENT_PROFILES = {"standard", "agent-sandbox"}
RUNTIME_CONFIG_PROTECTED_KEYS = {
    "APP_NAME",
    "APP_PORT",
    "DEPLOYMENT_NAME",
    "SERVICE_NAME",
    "SERVICE_PORT",
    "PVC_NAME",
    "PVC_STORAGE_SIZE",
    "IMAGE_REGISTRY",
    "IMAGE_REPOSITORY",
    "KUBE_CONTEXT",
    "KUBE_NAMESPACE",
    "REPLICA_COUNT",
    "GATEWAY_CLASS_NAME",
    "GATEWAY_NAME",
    "GATEWAY_NAMESPACE",
    "HTTP_HOST",
    "HTTP_GATEWAY_HOSTNAME",
    "HTTP_ROUTE_HOSTNAME",
    "HTTP_ROUTE_NAME",
    "HTTP_GATEWAY_IP",
    "HTTPS_HOST",
    "HTTPS_TLS_SECRET_NAME",
}

VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def fail(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)
    raise SystemExit(1)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def require_command(name: str, purpose: str) -> None:
    if command_exists(name):
        return
    fail(
        f"missing command: {name}; {purpose} requires {name}. "
        f"Please install {name} yourself and ensure it is available in PATH."
    )


def registries_conf_has_insecure_registry(content: str, registry: str) -> bool:
    current_location = ""
    insecure = False
    in_registry_block = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("[[") and line.endswith("]]"):
            if in_registry_block and current_location == registry and insecure:
                return True
            in_registry_block = line == "[[registry]]"
            current_location = ""
            insecure = False
            continue
        if not in_registry_block:
            continue
        if line.startswith("location"):
            current_location = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("insecure"):
            insecure = line.split("=", 1)[1].strip().lower() == "true"
    return in_registry_block and current_location == registry and insecure


def podman_host_insecure_registry_configured(registry: str) -> bool:
    candidates = [
        Path.home() / ".config" / "containers" / "registries.conf",
        Path("/etc/containers/registries.conf"),
    ]
    for path in candidates:
        if path.exists() and registries_conf_has_insecure_registry(path.read_text(encoding="utf-8"), registry):
            return True
    return False


def podman_machine_insecure_registry_configured(registry: str) -> bool:
    result = subprocess.run(
        ["podman", "machine", "ssh", "cat", "/etc/containers/registries.conf"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return False
    return registries_conf_has_insecure_registry(result.stdout, registry)


def podman_insecure_registry_configured(registry: str) -> bool:
    if sys.platform == "darwin":
        return podman_machine_insecure_registry_configured(registry)
    return podman_host_insecure_registry_configured(registry)


def podman_insecure_registry_help(registry: str) -> str:
    if sys.platform == "darwin":
        return (
            f"podman on macOS runs inside a Podman machine. Add the insecure registry inside the machine:\n"
            "  podman machine ssh "
            f"'printf \"%s\\n\" \"[[registry]]\" \"location=\\\"{registry}\\\"\" \"insecure=true\" "
            "| sudo tee -a /etc/containers/registries.conf'\n"
            "Then restart the Podman machine:\n"
            "  podman machine stop && podman machine start"
        )
    return (
        f"Add [[registry]] location=\"{registry}\" insecure=true to "
        "~/.config/containers/registries.conf or /etc/containers/registries.conf."
    )


def preflight_build_registry(env: dict[str, str]) -> None:
    registry = env.get("IMAGE_REGISTRY", "").split("/", 1)[0]
    if not registry.endswith(".yuma.intra"):
        return
    if not command_exists("podman"):
        return
    if podman_insecure_registry_configured(registry):
        return
    fail(
        f"podman build/push to {registry} requires an insecure registry entry. "
        + podman_insecure_registry_help(registry)
    )


def parse_env_file(path: Path, base: dict[str, str]) -> dict[str, str]:
    values = dict(base)
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value.startswith("export "):
            value = value[len("export ") :].strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        values[key] = expand_vars(value, values)
    return values


def apply_runtime_env_aliases(env: dict[str, str]) -> None:
    redis_host = env.get("REDIS_HOST", "")
    redis_port = env.get("REDIS_PORT", "")
    redis_username = env.get("REDIS_USERNAME", "")
    redis_password = env.get("REDIS_PASSWORD", "")
    redis_database = env.get("REDIS_DATABASE", "")

    if redis_host:
        env["SPRING_DATA_REDIS_HOST"] = redis_host
        env["SPRING_REDIS_HOST"] = redis_host
        env["HYDROS_SSO_CLIENT_REDIS_HOST"] = redis_host
    if redis_port:
        env["SPRING_DATA_REDIS_PORT"] = redis_port
        env["SPRING_REDIS_PORT"] = redis_port
        env["HYDROS_SSO_CLIENT_REDIS_PORT"] = redis_port
    if redis_username:
        env["SPRING_DATA_REDIS_USERNAME"] = redis_username
        env["SPRING_REDIS_USERNAME"] = redis_username
    if redis_password:
        env["SPRING_DATA_REDIS_PASSWORD"] = redis_password
        env["SPRING_REDIS_PASSWORD"] = redis_password
    if redis_database:
        env["SPRING_DATA_REDIS_DATABASE"] = redis_database
        env["SPRING_REDIS_DATABASE"] = redis_database

    if redis_host and redis_port and redis_database:
        auth = ""
        if redis_username and redis_password:
            auth = f"{redis_username}:{redis_password}@"
        elif redis_password:
            auth = f":{redis_password}@"
        env["JETCACHE_REDIS_URI"] = f"redis://{auth}{redis_host}:{redis_port}/{redis_database}"


def expand_vars(value: str, env: dict[str, str]) -> str:
    for _ in range(10):
        expanded = VAR_PATTERN.sub(lambda match: env.get(match.group(1), ""), value)
        if expanded == value:
            return expanded
        value = expanded
    return value


def render_text(value: str, env: dict[str, str]) -> str:
    missing: set[str] = set()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in env:
            missing.add(key)
            return match.group(0)
        return env[key]

    rendered = VAR_PATTERN.sub(replace, value)
    if missing:
        fail(f"missing manifest variables: {', '.join(sorted(missing))}")
    return rendered


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, env=env, check=True)


def run_capture(command: list[str]) -> str:
    print("$ " + " ".join(command))
    result = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE)
    return result.stdout


def run_capture_optional(command: list[str]) -> tuple[int, str]:
    print("$ " + " ".join(command))
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.returncode, result.stdout


def live_deploy_context(cluster_target: str) -> str:
    return f"{cluster_target}-live-deploy"


def reject_legacy_positional_cluster_target(argv: list[str]) -> None:
    if len(argv) < 2 or argv[0] not in {"deploy", "smoke"} or argv[1].startswith("-"):
        return
    fail(
        f"positional cluster target is no longer supported: {argv[1]!r}; "
        f"use './deploy_k3s.sh {argv[0]} --cluster-target {argv[1]}'"
    )


def reject_deprecated_cluster_target(cluster_target: str) -> None:
    if not cluster_target.startswith("hydros-k3s-"):
        return
    replacement = "hydros-cluster-" + cluster_target.removeprefix("hydros-k3s-")
    fail(
        f"deprecated cluster target alias {cluster_target!r} is not supported; "
        f"use {replacement!r}"
    )



def parse_simple_yaml_data(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_data = False
    current_key: str | None = None
    current_lines: list[str] = []

    def flush_block() -> None:
        nonlocal current_key, current_lines
        if current_key is not None:
            values[current_key] = "\n".join(current_lines).rstrip("\n")
            current_key = None
            current_lines = []

    for raw_line in text.splitlines():
        if raw_line.startswith("data:"):
            in_data = True
            continue
        if not in_data:
            continue
        if raw_line and not raw_line.startswith((" ", "\t")):
            flush_block()
            break
        line = raw_line[2:] if raw_line.startswith("  ") else raw_line.strip()
        if current_key is not None:
            if raw_line.startswith("    "):
                current_lines.append(raw_line[4:])
                continue
            flush_block()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {"|", "|-"}:
            current_key = key
            current_lines = []
            continue
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        values[key] = value
    flush_block()
    return values


def load_metadata_from_text(text: str, source: str) -> dict[str, str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        data = parse_simple_yaml_data(text)
    else:
        data = parsed.get("data", parsed)
    if not isinstance(data, dict):
        fail(f"invalid cluster metadata from {source}: expected object data")
    return {str(key): str(value) for key, value in data.items()}


def load_cluster_metadata(args: argparse.Namespace) -> dict[str, str]:
    reject_deprecated_cluster_target(args.cluster_target)

    if args.cluster_metadata_file:
        path = Path(args.cluster_metadata_file)
        if not path.exists():
            fail(f"missing cluster metadata file: {path}")
        return load_metadata_from_text(path.read_text(encoding="utf-8"), str(path))

    require_command("kubectl", "cluster metadata lookup")
    text = run_capture(
        [
            "kubectl",
            "--context",
            live_deploy_context(args.cluster_target),
            "-n",
            METADATA_NAMESPACE,
            "get",
            "configmap",
            METADATA_CONFIGMAP,
            "-o",
            "json",
        ]
    )
    return load_metadata_from_text(text, f"{METADATA_NAMESPACE}/{METADATA_CONFIGMAP}")


def active_agent_sandbox_namespaces(metadata: dict[str, str]) -> list[str]:
    raw = metadata.get("activeAgentSandboxNamespaces", "")
    return [item.strip() for item in re.split(r"[\n,]+", raw) if item.strip()]


def require_metadata(metadata: dict[str, str], key: str) -> str:
    value = metadata.get(key, "").strip()
    if not value:
        fail(f"cluster metadata missing required field: {key}")
    return value


def on_premises_entrypoint_env(metadata: dict[str, str]) -> dict[str, str]:
    from ipaddress import ip_address
    from urllib.parse import urlsplit

    scheme = require_metadata(metadata, "runtimeScheme")
    if scheme != "https":
        fail("on-premises ip-only live deploy currently requires runtimeScheme=https")
    host = str(ip_address(require_metadata(metadata, "hostname")))
    values = {
        "HYDROS_IP_ONLY": "true", "HYDROS_HOSTNAME_SCOPE": "on-premises",
        "HYDROS_PUBLIC_HOSTNAME": host, "HYDROS_RUNTIME_SCHEME": scheme,
        "HYDROS_COOKIE_DOMAIN": "", "HTTP_GATEWAY_TLS_SECRET_NAME": require_metadata(metadata, "httpGatewayTlsSecretName"),
        "HYDROS_LOOP_TESTING_HOST": "", "HYDROS_ADMIN_HOST": "", "HYDROS_DOCS_HOST": "",
    }
    ports = {}
    keys = ["portal", "site", "api", "playground", "mcp"]
    for optional in ("loopTesting", "admin", "docs"):
        if metadata.get(optional + "Host"):
            keys.append(optional)
    required = {"hydros-ui-loop-testing": "loopTesting", "hydros-aio-admin": "admin", "hydros-ui-docs": "docs"}.get(APP_NAME)
    if required and required not in keys:
        fail(f"cluster metadata missing required field: {required}Host")
    for key in keys:
        authority = require_metadata(metadata, key + "Host")
        parsed = urlsplit("https://" + authority)
        if parsed.hostname != host or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            fail(f"{key}Host must use the selected IP and an explicit NodePort")
        try:
            port = parsed.port
        except ValueError:
            fail(f"invalid {key}Host port")
        if port is None or not 30000 <= port <= 32767:
            fail(f"{key}Host must specify a NodePort between 30000 and 32767")
        ports[key] = port
        values[f"HYDROS_{key.replace('loopTesting', 'loop_testing').upper()}_HOST"] = authority
        values[f"HYDROS_{key.replace('loopTesting', 'loop_testing').upper()}_ORIGIN"] = "https://" + authority
    if len(set(ports.values())) != len(ports):
        fail("on-premises public application NodePorts must be distinct")
    endpoint = {"hydros-ui-portal": "portal", "hydros-accounts": "site", "hydros-data": "api",
                "hydros-ui-playground": "playground", "hydros-engine-mcp-server": "mcp", "hydros-ui-loop-testing": "loop-testing", "hydros-aio-admin": "admin", "hydros-ui-docs": "docs"}.get(APP_NAME)
    values["HYDROS_IP_ENTRYPOINT"] = "hydros-" + endpoint if endpoint else ""
    return values


def render_onprem_trust(content: str, env: dict[str, str]) -> str:
    configmap = env.get("HYDROS_ONPREM_TRUST_CONFIGMAP", "")
    if env.get("HYDROS_IP_ONLY") != "true" or not configmap or manifest_kind(content) != "Deployment":
        return content
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", configmap):
        fail("invalid on-premises trust ConfigMap name")
    before, marker, containers = content.partition("      containers:\n")
    if not marker or "          env:\n" not in containers:
        fail("on-premises trust requires the standard container/env layout")
    trust_env = "".join(
        f"            - name: {key}\n              value: /etc/hydros/pki/{filename}\n"
        for key, filename in (("NODE_EXTRA_CA_CERTS", "ca.crt"), ("REQUESTS_CA_BUNDLE", "ca-bundle.crt"),
                              ("SSL_CERT_FILE", "ca-bundle.crt"), ("AWS_CA_BUNDLE", "ca-bundle.crt"))
    )
    containers = containers.replace("          env:\n", "          env:\n" + trust_env, 1)
    mount = "            - name: onprem-trust\n              mountPath: /etc/hydros/pki\n              readOnly: true\n"
    if "          volumeMounts:\n" in containers:
        containers = containers.replace("          volumeMounts:\n", "          volumeMounts:\n" + mount, 1)
    else:
        containers = containers.replace("          env:\n", "          volumeMounts:\n" + mount + "          env:\n", 1)
    volume = f"        - name: onprem-trust\n          configMap:\n            name: {configmap}\n"
    if "      volumes:\n" in containers:
        containers = containers.replace("      volumes:\n", "      volumes:\n" + volume, 1)
    else:
        containers = containers.rstrip() + "\n      volumes:\n" + volume
    return before + marker + containers


def render_ip_only_route(content: str, env: dict[str, str]) -> str:
    if env.get("HYDROS_IP_ONLY") != "true" or manifest_kind(content) != "Service":
        return ""
    entrypoint = env.get("HYDROS_IP_ENTRYPOINT", "")
    service_name = env.get("SERVICE_NAME", APP_NAME)
    if not entrypoint or not re.search(r"(?m)^  name: [\"']?" + re.escape(service_name) + r"[\"']?\s*$", content):
        return ""
    port = re.search(r"(?m)^      port: ([0-9]+)\s*$", content)
    if not port:
        fail("ip-only public Service must declare an explicit numeric service port")
    return json.dumps({
        "apiVersion": "traefik.io/v1alpha1", "kind": "IngressRoute",
        "metadata": {"name": APP_NAME + "-ip-only", "namespace": env["KUBE_NAMESPACE"]},
        "spec": {"entryPoints": [entrypoint],
                 "routes": [{"kind": "Rule", "match": "PathPrefix(`/`)",
                             "services": [{"name": service_name, "port": int(port[1])}]}],
                 "tls": {"secretName": env["HTTP_GATEWAY_TLS_SECRET_NAME"]}},
    }, indent=2)


def standard_public_entrypoint_env(metadata: dict[str, str]) -> dict[str, str]:
    if metadata.get("appEnv") == "on-premises" and metadata.get("dnsMode") == "ip-only":
        return on_premises_entrypoint_env(metadata)
    runtime_scheme = require_metadata(metadata, "runtimeScheme")
    if runtime_scheme not in {"http", "https"}:
        fail("cluster metadata runtimeScheme must be http or https")
    hostname = require_metadata(metadata, "hostname")
    hostname_suffix = hostname[2:] if hostname.startswith("*.") else hostname
    if not hostname_suffix or hostname_suffix == "-":
        fail("cluster metadata hostname must define a public hostname suffix")
    portal_host = require_metadata(metadata, "portalHost")
    site_host = require_metadata(metadata, "siteHost")
    api_host = require_metadata(metadata, "apiHost")
    playground_host = require_metadata(metadata, "playgroundHost")
    mcp_host = require_metadata(metadata, "mcpHost")
    cookie_domain = require_metadata(metadata, "cookieDomain")
    return {
        "HYDROS_HOSTNAME_SCOPE": require_metadata(metadata, "hostnameScope"),
        "HYDROS_PUBLIC_HOSTNAME": hostname,
        "HYDROS_RUNTIME_SCHEME": runtime_scheme,
        "HYDROS_PORTAL_HOST": portal_host,
        "HYDROS_SITE_HOST": site_host,
        "HYDROS_API_HOST": api_host,
        "HYDROS_PLAYGROUND_HOST": playground_host,
        "HYDROS_MCP_HOST": mcp_host,
        "HYDROS_LOOP_TESTING_HOST": f"loop-testing.{hostname_suffix}",
        "HYDROS_ADMIN_HOST": f"admin.{hostname_suffix}",
        "HYDROS_DOCS_HOST": f"docs.{hostname_suffix}",
        "HYDROS_COOKIE_DOMAIN": cookie_domain,
        "HYDROS_PORTAL_ORIGIN": f"{runtime_scheme}://{portal_host}",
        "HYDROS_SITE_ORIGIN": f"{runtime_scheme}://{site_host}",
        "HYDROS_API_ORIGIN": f"{runtime_scheme}://{api_host}",
        "HYDROS_PLAYGROUND_ORIGIN": f"{runtime_scheme}://{playground_host}",
        "HYDROS_MCP_ORIGIN": f"{runtime_scheme}://{mcp_host}",
        "HTTP_GATEWAY_TLS_SECRET_NAME": require_metadata(
            metadata, "httpGatewayTlsSecretName"
        ),
    }


def apply_cluster_metadata_env(
    env: dict[str, str], metadata: dict[str, str], deployment_profile: str
) -> None:
    if deployment_profile != "standard":
        return
    env.update(standard_public_entrypoint_env(metadata))
    for key, value in APP_CLUSTER_METADATA_ENV.items():
        env[key] = expand_vars(value, env)


def resolve_deployment(
    metadata: dict[str, str], cluster_target: str, namespace: str | None
) -> tuple[str, str, str]:
    metadata_cluster_target = require_metadata(metadata, "clusterTarget")
    if metadata_cluster_target != cluster_target:
        fail(f"cluster metadata target {metadata_cluster_target!r} does not match {cluster_target!r}")

    app_env = require_metadata(metadata, "appEnv")
    deployment_profile = require_metadata(metadata, "deploymentProfile")
    namespace_mode = require_metadata(metadata, "namespaceMode")
    if deployment_profile not in VALID_DEPLOYMENT_PROFILES:
        fail(f"unsupported deploymentProfile: {deployment_profile}")
    if namespace_mode != deployment_profile:
        fail("cluster metadata deploymentProfile and namespaceMode must match")

    if deployment_profile == "standard":
        default_namespace = require_metadata(metadata, "defaultNamespace")
        target_namespace = namespace or default_namespace
        if target_namespace != "hydros":
            fail("standard live deploy namespace must be hydros")
        return app_env, deployment_profile, target_namespace

    shared_namespace = require_metadata(metadata, "sharedNamespace")
    if APP_PLACEMENT == "shared":
        target_namespace = namespace or shared_namespace
        if target_namespace != shared_namespace:
            fail(f"shared app namespace must be {shared_namespace}")
        return app_env, deployment_profile, target_namespace

    if APP_PLACEMENT != "agentSandbox":
        fail(f"unsupported APP_PLACEMENT for agent-sandbox profile: {APP_PLACEMENT}")

    if namespace is None:
        active = active_agent_sandbox_namespaces(metadata)
        examples = "\n".join(f"  --namespace {item}" for item in active[:5])
        if examples:
            fail(
                f"{APP_NAME} placement is agentSandbox on cluster {cluster_target}.\n"
                f"Live deploy must specify one active sandbox namespace:\n{examples}"
            )
        fail(
            f"{APP_NAME} placement is agentSandbox on cluster {cluster_target}. "
            "Live deploy must specify --namespace for an active sandbox namespace."
        )

    pattern = require_metadata(metadata, "agentSandboxNamespacePattern")
    if not fnmatch.fnmatchcase(namespace, pattern):
        fail(f"namespace {namespace!r} does not match agent sandbox pattern {pattern!r}")
    active = active_agent_sandbox_namespaces(metadata)
    if namespace not in active:
        fail(f"namespace {namespace!r} is not in activeAgentSandboxNamespaces")
    if namespace == shared_namespace:
        fail("agentSandbox app namespace must not be the shared namespace")
    return app_env, deployment_profile, namespace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./deploy_k3s.sh",
        description="Developer live deploy for Hydros K3s apps.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy = subparsers.add_parser("deploy")
    deploy.add_argument("--cluster-target", required=True)
    deploy.add_argument("--namespace")
    deploy.add_argument("--cluster-metadata-file")
    deploy.add_argument("--runtime-config-env-file")
    deploy.add_argument("--tag")
    deploy.add_argument("--image")
    deploy.add_argument("--skip-build", action="store_true")
    deploy.add_argument("--dry-run", action="store_true")
    deploy.add_argument("--render-only", action="store_true")
    deploy.add_argument("--render-output-dir")
    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--cluster-target", required=True)
    smoke.add_argument("--namespace")
    smoke.add_argument("--cluster-metadata-file")
    smoke.add_argument("--runtime-config-env-file")
    return parser


def build_args(image_tag: str, app_env: str) -> list[str]:
    values = {"image_tag": image_tag, "app_env": app_env}
    return [item.format(**values) for item in BUILD_SCRIPT_ARGS]


def stable_env_checksum(env: dict[str, str]) -> str:
    payload = json.dumps(
        {key: env[key] for key in sorted(env)},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prepare_deployment_context(args: argparse.Namespace) -> tuple[Path, Path, Path, dict[str, str], str, str, str, str]:
    repo_root = Path(__file__).resolve().parents[3]
    k3s_dir = repo_root / "deploy" / "k3s"
    app_env_file = k3s_dir / "app.env"
    build_script = k3s_dir / "scripts" / "build_image.sh"

    if not app_env_file.exists():
        fail(f"missing app env: {app_env_file}")

    metadata = load_cluster_metadata(args)
    app_env, deployment_profile, target_namespace = resolve_deployment(
        metadata, args.cluster_target, args.namespace
    )
    manifest_dir = k3s_dir / "profiles" / deployment_profile / "manifests"
    if not manifest_dir.is_dir():
        fail(f"missing manifest dir: {manifest_dir}")

    env = dict(os.environ)
    env = parse_env_file(app_env_file, env)
    env = parse_env_file(k3s_dir / "clusters" / f"{app_env}.env", env)
    runtime_config_env_file = (
        getattr(args, "runtime_config_env_file", None)
        or os.environ.get("HYDROS_RUNTIME_CONFIG_ENV_FILE")
        or os.environ.get("YUMA_HYDROS_RUNTIME_CONFIG_ENV_FILE")
    )
    if runtime_config_env_file:
        runtime_config_path = Path(runtime_config_env_file)
        if not runtime_config_path.exists():
            fail(f"missing runtime config env file: {runtime_config_path}")
        protected_runtime_values = {key: env[key] for key in RUNTIME_CONFIG_PROTECTED_KEYS if key in env}
        env = parse_env_file(runtime_config_path, env)
        env.update(protected_runtime_values)
    env, args.cluster_policy = load_cluster_runtime(
        metadata, args.cluster_target, target_namespace, APP_NAME, env, RUNTIME_CONFIG_PROTECTED_KEYS
    )
    apply_runtime_env_aliases(env)

    apply_cluster_metadata_env(env, metadata, deployment_profile)
    app_name = env.get("APP_NAME") or APP_NAME or repo_root.name
    image_registry = env.get("IMAGE_REGISTRY") or env.get("YUMA_ZOT_REGISTRY_HOST") or ""
    image_repository = env.get("IMAGE_REPOSITORY") or f"yuma/images/hydros/dev/{app_name}"
    image_tag = getattr(args, "tag", None) or env.get("IMAGE_TAG") or datetime.now().strftime("dev-%Y%m%d-%H%M%S")
    explicit_image = getattr(args, "image", None)
    if not explicit_image and not image_registry:
        fail("IMAGE_REGISTRY or YUMA_ZOT_REGISTRY_HOST is required when --image is not provided")
    app_image = explicit_image or f"{image_registry}/{image_repository}:{image_tag}"
    kube_context = live_deploy_context(args.cluster_target)

    env.update(
        {
            "HYDROS_DEPLOY_MODE": "k3s",
            "HYDROS_APP_ENV": app_env,
            "HYDROS_K3S_DEPLOYMENT_PROFILE": deployment_profile,
            "HYDROS_K3S_CLUSTER_ID": args.cluster_target,
            "HYDROS_K3S_NAMESPACE": target_namespace,
            "APP_ENV": app_env,
            "APP_IMAGE": app_image,
            "APP_NAME": app_name,
            "APP_VERSION": image_tag,
            "DEPLOYMENT_PROFILE": deployment_profile,
            "NAMESPACE_MODE": deployment_profile,
            "HYDROS_CLUSTER_ID": args.cluster_target,
            "IMAGE_REGISTRY": image_registry,
            "IMAGE_REPOSITORY": image_repository,
            "KUBE_CONTEXT": kube_context,
            "KUBE_NAMESPACE": target_namespace,
            "AGENT_SANDBOX_NAMESPACE": target_namespace,
            "AGENT_SANDBOX_SHARED_NAMESPACE": metadata.get("sharedNamespace", ""),
            "STANDARD_HTTP_GATEWAY_NAME": env.get("STANDARD_HTTP_GATEWAY_NAME", f"hydros-{app_env}-http-gateway"),
        }
    )
    for key, value in APP_SPECIFIC_ENV_DEFAULTS.items():
        env.setdefault(key, expand_vars(value, env))
    env["HYDROS_CONFIG_CHECKSUM"] = stable_env_checksum(env)

    return repo_root, k3s_dir, build_script, env, app_name, app_image, manifest_dir, deployment_profile


def run_optional_capture(command: list[str]) -> tuple[int, str]:
    print("$ " + " ".join(command))
    result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return result.returncode, result.stdout.strip()


def print_smoke_check(name: str, ok: bool, detail: str) -> None:
    status = "ok" if ok else "warn"
    print(f"smoke.{name}={status} {detail}")


def run_smoke(args: argparse.Namespace, env: dict[str, str], app_name: str) -> int:
    require_command("kubectl", "live deploy smoke checks")

    namespace = env["KUBE_NAMESPACE"]
    deployment_name = env.get(ROLLOUT_DEPLOYMENT_ENV, app_name) if ROLLOUT_DEPLOYMENT_ENV else app_name
    service_name = env.get("SERVICE_NAME", app_name)
    route_name = env.get("HTTP_ROUTE_NAME", f"{app_name}-route")
    kubectl = ["kubectl", "--context", env["KUBE_CONTEXT"], "-n", namespace]

    print("== live deploy smoke ==")
    print(f"app={app_name}")
    print(f"cluster={env['HYDROS_CLUSTER_ID']}")
    print(f"kubeContext={env['KUBE_CONTEXT']}")
    print(f"appEnv={env['APP_ENV']}")
    print(f"deploymentProfile={env['DEPLOYMENT_PROFILE']}")
    print(f"namespace={namespace}")

    failed = False
    code, output = run_optional_capture(
        kubectl + ["rollout", "status", f"deployment/{deployment_name}", "--timeout=30s"]
    )
    print_smoke_check("rollout", code == 0, output)
    failed = failed or code != 0

    code, output = run_optional_capture(
        kubectl
        + [
            "get",
            f"deployment/{deployment_name}",
            "-o",
            "jsonpath={.spec.template.spec.containers[0].image}",
        ]
    )
    print_smoke_check("image", code == 0 and bool(output), output or "(missing)")
    failed = failed or code != 0 or not output

    code, output = run_optional_capture(
        kubectl
        + [
            "get",
            "pods",
            "-l",
            f"app={deployment_name}",
            "--field-selector",
            "status.phase=Running",
            "-o",
            "jsonpath={range .items[*]}{.metadata.name}{\" ready=\"}{range .status.containerStatuses[*]}{.ready}{\" \"}{end}{\"phase=\"}{.status.phase}{\"\\n\"}{end}",
        ]
    )
    pods_ready = code == 0 and bool(output) and "false" not in output and "phase=Running" in output
    print_smoke_check("pods", pods_ready, output or "(no pods)")
    failed = failed or not pods_ready

    code, output = run_optional_capture(kubectl + ["get", f"service/{service_name}", "-o", "name"])
    print_smoke_check("service", code == 0, output or f"service/{service_name} not found")

    if env.get("HYDROS_IP_ONLY") == "true" and env.get("HYDROS_IP_ENTRYPOINT"):
        resource = f"ingressroute.traefik.io/{app_name}-ip-only"
        code, output = run_optional_capture(kubectl + ["get", resource, "-o", "name"])
        print_smoke_check("ipRoute", code == 0, output or f"{resource} not found")
        failed = failed or code != 0
    elif env.get("HTTP_HOST") or env.get("HTTP_ROUTE_HOSTNAME"):
        code, output = run_optional_capture(kubectl + ["get", f"ingress/{route_name}", "-o", "name"])
        print_smoke_check("ingress", code == 0, output or f"ingress/{route_name} not found")

    health_scheme = "https" if env.get("HYDROS_IP_ONLY") == "true" else "http"
    health_path = env.get("HEALTH_PATH", "").strip()
    health_host = env.get("HEALTH_HOST", env.get("HTTP_HOST", "")).strip()
    if health_path and health_host and command_exists("curl"):
        code, output = run_optional_capture(["curl", "-fsS", f"{health_scheme}://{health_host}{health_path}"])
        print_smoke_check("health", code == 0, output[:200] if output else f"{health_scheme}://{health_host}{health_path}")

    cors_path = env.get("CORS_PREFLIGHT_PATH", "").strip()
    cors_origin = env.get("CORS_PREFLIGHT_ORIGIN", "").strip()
    cors_host = env.get("CORS_PREFLIGHT_HOST", env.get("HTTP_HOST", "")).strip()
    if cors_path and cors_origin and cors_host and command_exists("curl"):
        code, output = run_optional_capture(
            [
                "curl",
                "-fsS",
                "-o",
                "/dev/null",
                "-X",
                "OPTIONS",
                f"{health_scheme}://{cors_host}{cors_path}",
                "-H",
                f"Origin: {cors_origin}",
                "-H",
                "Access-Control-Request-Method: GET",
                "-H",
                "Access-Control-Request-Headers: accept",
            ]
        )
        print_smoke_check("corsPreflight", code == 0, output or f"{cors_origin} -> {cors_host}{cors_path}")

    if failed:
        return 1
    return 0


def manifest_kind(content: str) -> str:
    for raw_line in content.splitlines():
        if raw_line.startswith((" ", "\\t")):
            continue
        key, separator, value = raw_line.partition(":")
        if separator and key.strip() == "kind":
            return value.strip().strip('"').strip("'")
    return ""


def namespaced_apply_args(render_dir: Path) -> list[str]:
    apply_args: list[str] = []
    for manifest in sorted(render_dir.glob("*.yaml")):
        kind = manifest_kind(manifest.read_text(encoding="utf-8"))
        if kind == "Namespace":
            print(f"skip.cluster-scoped-manifest={manifest.name} kind={kind}")
            continue
        apply_args.extend(["-f", str(manifest)])
    if not apply_args:
        fail(f"no namespace-scoped manifests found in {render_dir}")
    return apply_args


def main(argv: list[str]) -> int:
    reject_legacy_positional_cluster_target(argv)
    args = build_parser().parse_args(argv)
    repo_root, k3s_dir, build_script, env, app_name, app_image, manifest_dir, deployment_profile = prepare_deployment_context(args)

    if args.command == "smoke":
        return run_smoke(args, env, app_name)

    should_build = not args.skip_build and not args.image and not args.render_only and not args.dry_run
    if should_build:
        preflight_build_registry(env)
        require_command("docker", "image build")
        if not build_script.exists():
            fail(f"missing build script: {build_script}")
        build_env = dict(env)
        if build_env.get("HYDROS_LIVE_DEPLOY_PRESERVE_BUILD_JAVA_TOOL_OPTIONS", "").lower() not in {"1", "true", "yes"}:
            build_env.pop("JAVA_TOOL_OPTIONS", None)
        build_env["IMAGE_REPOSITORY"] = f"{env['IMAGE_REGISTRY']}/{env['IMAGE_REPOSITORY']}"
        run([str(build_script), *build_args(env["APP_VERSION"], env["APP_ENV"])], env=build_env)

    render_dir = Path(tempfile.mkdtemp(prefix=f"{app_name}-{env['APP_ENV']}-manifests-"))
    for source in sorted(manifest_dir.glob("*.yaml")):
        if env.get("HYDROS_IP_ONLY") == "true" and manifest_kind(source.read_text(encoding="utf-8")) == "Ingress":
            continue
        target = render_dir / source.name
        target.write_text(render_text(source.read_text(encoding="utf-8"), env), encoding="utf-8")
        target.write_text(render_onprem_trust(target.read_text(encoding="utf-8"), env), encoding="utf-8")
        ip_route = render_ip_only_route(target.read_text(encoding="utf-8"), env)
        if ip_route:
            (render_dir / "90-ip-only-route.yaml").write_text(ip_route, encoding="utf-8")

    print(f"cluster={env['HYDROS_CLUSTER_ID']}")
    print(f"kubeContext={env['KUBE_CONTEXT']}")
    print(f"deploymentProfile={deployment_profile}")
    print(f"namespace={env['KUBE_NAMESPACE']}")
    print(f"image={app_image}")
    apply_cluster_policy(render_dir, args.cluster_policy)
    print(f"manifests={manifest_dir}")
    render_output_dir = getattr(args, "render_output_dir", None)
    if render_output_dir:
        output_dir = Path(render_output_dir)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(render_dir, output_dir)
        render_dir = output_dir

    print(f"rendered={render_dir}")

    if args.render_only:
        return 0

    require_command("kubectl", "live deploy apply")

    kubectl = ["kubectl", "--context", env["KUBE_CONTEXT"]]
    apply_args = namespaced_apply_args(render_dir)
    if args.dry_run:
        run(kubectl + ["apply", "--dry-run=server", *apply_args])
        return 0

    run(kubectl + ["apply", *apply_args])
    rollout_timeout = env.get("ROLLOUT_TIMEOUT", "300s")
    deployment_name = env.get(ROLLOUT_DEPLOYMENT_ENV, app_name) if ROLLOUT_DEPLOYMENT_ENV else app_name
    run(
        kubectl
        + [
            "-n",
            env["KUBE_NAMESPACE"],
            "rollout",
            "status",
            f"deployment/{deployment_name}",
            f"--timeout={rollout_timeout}",
        ]
    )
    return run_smoke(args, env, app_name)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
