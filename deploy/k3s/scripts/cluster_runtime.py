"""Cluster-owned on-premises configuration; copied with each self-contained app."""
import base64
import json
import re
import subprocess


def read_object(context, namespace, kind, name):
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", name):
        raise SystemExit("Invalid cluster runtime object name")
    result = subprocess.run(
        ["kubectl", "--context", context, "-n", namespace, "get", kind, name, "-o", "json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise SystemExit(f"Cannot read {kind}/{name}; check target initialization and live-deploy access")
    return json.loads(result.stdout)


def load_cluster_runtime(metadata, target, namespace, app_name, env, protected):
    if metadata.get("appEnv") != "on-premises":
        return env, {}
    secret = metadata.get("runtimeConfigSecret", "")
    configmap = metadata.get("deploymentPolicyConfigMap", "")
    if not secret or not configmap:
        raise SystemExit("on-premises metadata requires runtimeConfigSecret and deploymentPolicyConfigMap; ask the operator to initialize the target")
    context = target + "-live-deploy"
    try:
        runtime = json.loads(base64.b64decode(read_object(context, namespace, "secret", secret)["data"]["runtime.json"], validate=True))
        policy = json.loads(read_object(context, namespace, "configmap", configmap)["data"]["policy.json"])
        for value in (runtime, policy):
            if value["schemaVersion"] != 1 or value["clusterTarget"] != target:
                raise ValueError("target/schema mismatch")
        values = runtime["env"]
        patches = policy["applications"][app_name]
        if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in values.items()):
            raise ValueError("invalid env")
        if not isinstance(patches, dict) or not patches:
            raise ValueError("missing application policy")
        for filename, patch in patches.items():
            if not re.fullmatch(r"[a-zA-Z0-9_-]+\.yaml", filename) or not isinstance(patch, dict):
                raise ValueError("invalid patch")
        runtime_patches = runtime.get("applications", {}).get(app_name, {})
        if not isinstance(runtime_patches, dict) or set(runtime_patches) - set(patches):
            raise ValueError("invalid runtime patches")
        patches = {name: [runtime_patches.get(name, {}), patch] for name, patch in patches.items()}
        saved = {k: env[k] for k in protected if k in env}
        env.update(values)
        env.update(saved)
        return env, patches
    except (ValueError, KeyError, TypeError):
        raise SystemExit("Invalid cluster runtime configuration or missing application policy; refusing deployment") from None


def apply_cluster_policy(directory, patches):
    for filename, sequence in patches.items():
        path = directory / filename
        if not path.is_file():
            raise SystemExit(f"Policy refers to missing manifest {filename}")
        for patch in sequence:
            # Sensitive runtime patches use a private file, never process arguments.
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as patch_file:
                json.dump(patch, patch_file)
                patch_file.flush()
                result = subprocess.run(
                    ["kubectl", "patch", "--local", "-f", str(path), "--type=strategic", "--patch-file", patch_file.name, "-o", "json"],
                    capture_output=True, text=True, timeout=30,
                )
            if result.returncode:
                raise SystemExit(f"Cannot merge deployment policy for {filename}")
            path.write_text(result.stdout, encoding="utf-8")
            path.chmod(0o600)
