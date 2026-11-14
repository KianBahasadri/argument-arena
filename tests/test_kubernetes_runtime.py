import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml

from argument_arena.config import Config
from argument_arena.health import write_health

spec = importlib.util.spec_from_file_location(
    "render", Path(__file__).resolve().parents[1] / "scripts/render_manifests.py"
)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def deployment():
    return next(
        resource
        for resource in yaml.safe_load_all(renderer.render("bot:1", "123"))
        if resource["kind"] == "Deployment"
    )["spec"]["template"]["spec"]


def test_kubernetes_environment_and_secret_mount_match_installed_runtime(tmp_path):
    pod = deployment()
    container = pod["containers"][0]
    env = {item["name"]: item["value"] for item in container["env"]}
    config = Config.from_env(env)
    assert config.guild_id == 123
    assert config.llm_endpoint.startswith("https://opencode.ai/inference/go/")
    assert config.llm_model == "claude-haiku-5-5"
    assert config.llm_judge_model == "gemini-4-argon"
    mounts = {item["name"]: item for item in container["volumeMounts"]}
    assert Path(mounts["data"]["mountPath"]) == config.data_dir
    assert mounts["credentials"]["readOnly"]
    for path in (config.token_file, Path(config.llm_key_file), Path(config.search_key_file)):
        assert str(path.parent) == mounts["credentials"]["mountPath"]
    volume = next(item for item in pod["volumes"] if item["name"] == "credentials")
    assert volume["secret"]["secretName"] == "bot-credentials"
    assert volume["secret"]["defaultMode"] == 0o440
    assert pod["securityContext"]["fsGroup"] == pod["securityContext"]["runAsGroup"]
    token = tmp_path / config.token_file.name
    token.write_text("offline-test-token\n")
    assert Config.from_env(env | {"AA_DISCORD_TOKEN_FILE": str(token)}).read_token() == (
        "offline-test-token"
    )


def test_rendered_probes_run_the_installed_cli_and_distinguish_readiness(tmp_path):
    container = deployment()["containers"][0]
    for ready in (False, True):
        write_health(tmp_path, ready=ready)
        for name in ("startupProbe", "livenessProbe", "readinessProbe"):
            command = container[name]["exec"]["command"]
            assert command[0] == "argument-arena"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "argument_arena",
                    "--data-dir",
                    str(tmp_path),
                    *command[1:],
                ],
                capture_output=True,
                timeout=container[name]["timeoutSeconds"],
                check=False,
            )
            expected = 1 if name == "readinessProbe" and not ready else 0
            assert result.returncode == expected, result.stderr


def test_healthcheck_runs_without_loading_the_gateway_runtime(tmp_path):
    write_health(tmp_path, ready=True)
    script = """
import runpy
import sys

sys.modules["argument_arena.runtime"] = None
sys.modules["discord"] = None
sys.argv = ["argument-arena", "--data-dir", sys.argv[1], "healthcheck"]
runpy.run_module("argument_arena", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        timeout=deployment()["containers"][0]["readinessProbe"]["timeoutSeconds"],
        check=False,
    )
    assert result.returncode == 0, result.stderr
