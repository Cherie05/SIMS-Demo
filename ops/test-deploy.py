"""Exercise deployment and finite rollback using fake commands in a temporary checkout."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST = "a" * 64
BACKEND = f"ghcr.io/example/sims/backend@sha256:{DIGEST}"
FRONTEND = f"ghcr.io/example/sims/frontend@sha256:{DIGEST}"
FAKE_COMMAND = """#!/usr/bin/env python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
release = os.getenv("APP_VERSION", "")
with open(os.environ["FAKE_LOG"], "a") as output:
    output.write(json.dumps({"name": name, "args": args, "release": release}) + "\\n")
phase = os.getenv("FAIL_PHASE", "")
if name == "docker" and phase == "all_runtime" and "up" in args and "backend" in args:
    sys.exit(1)
if release == "v2.0.0":
    if name == "docker" and phase == "runtime" and "up" in args and "backend" in args:
        sys.exit(1)
    if name == "sh" and phase == "smoke":
        sys.exit(1)
sys.exit(0)
"""


@unittest.skipUnless(
    os.name == "posix",
    "Run deployment tests on Linux (CI or a temporary Python container).",
)
class DeploymentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.checkout = self.directory / "checkout"
        (self.checkout / "ops").mkdir(parents=True)
        shutil.copyfile(ROOT / "ops/deploy.sh", self.checkout / "ops/deploy.sh")
        self.binaries = self.directory / "bin"
        self.binaries.mkdir()
        for name in ("git", "docker", "sh"):
            command = self.binaries / name
            command.write_text(FAKE_COMMAND)
            command.chmod(0o700)
        self.state = self.directory / "state"
        self.state.mkdir()
        self.log = self.directory / "calls.jsonl"
        self.environment = {
            **os.environ,
            "PATH": f"{self.binaries}:{os.environ['PATH']}",
            "STATE_DIR": str(self.state),
            "PUBLIC_URL": "https://sims.example.com",
            "FAKE_LOG": str(self.log),
            "FAIL_PHASE": "",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, name: str, release: str) -> None:
        (self.state / name).write_text(
            f"RELEASE={release}\nBACKEND_IMAGE={BACKEND}\nFRONTEND_IMAGE={FRONTEND}\n"
        )

    def deploy(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["/bin/sh", str(self.checkout / "ops/deploy.sh"), *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def calls(self) -> list[dict]:
        return (
            [json.loads(line) for line in self.log.read_text().splitlines()]
            if self.log.exists()
            else []
        )

    def test_success_runs_schema_steps_and_records_release(self) -> None:
        self.record("current", "v1.0.0")
        result = self.deploy("v2.0.0", BACKEND, FRONTEND)
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls()
        releases = [
            call["args"][-1]
            for call in calls
            if call["name"] == "docker" and "run" in call["args"]
        ]
        self.assertEqual(releases, ["db-init", "migrate"])
        self.assertIn("RELEASE=v2.0.0", (self.state / "current").read_text())
        self.assertIn("RELEASE=v1.0.0", (self.state / "previous").read_text())
        self.assertFalse((self.state / "lock").exists())
        self.assertEqual((self.state / "current").stat().st_mode & 0o777, 0o600)

    def test_startup_and_smoke_failure_roll_back_once_without_migrations(self) -> None:
        for phase in ("runtime", "smoke"):
            with self.subTest(phase=phase):
                self.record("current", "v1.0.0")
                self.environment["FAIL_PHASE"] = phase
                self.log.unlink(missing_ok=True)
                result = self.deploy("v2.0.0", BACKEND, FRONTEND)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("deploy.rolled_back", result.stdout)
                self.assertIn("RELEASE=v1.0.0", (self.state / "current").read_text())
                rollback_calls = [
                    call for call in self.calls() if call["release"] == "v1.0.0"
                ]
                self.assertFalse(
                    any("migrate" == call["args"][-1] for call in rollback_calls)
                )
                self.assertEqual(
                    sum(call["name"] == "sh" for call in rollback_calls), 1
                )

    def test_manual_rollback_uses_previous_and_skips_migration(self) -> None:
        self.record("current", "v2.0.0")
        self.record("previous", "v1.0.0")
        result = self.deploy("--rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RELEASE=v1.0.0", (self.state / "current").read_text())
        self.assertFalse(any(call["args"][-1] == "migrate" for call in self.calls()))

    def test_failed_rollback_stops_and_retains_successful_state(self) -> None:
        self.record("current", "v1.0.0")
        self.environment["FAIL_PHASE"] = "all_runtime"
        result = self.deploy("v2.0.0", BACKEND, FRONTEND)
        self.assertEqual(result.returncode, 1)
        self.assertIn("deploy.rollback_failed", result.stdout)
        self.assertIn("RELEASE=v1.0.0", (self.state / "current").read_text())
        self.assertEqual(
            sum(
                call["name"] == "docker"
                and "up" in call["args"]
                and "backend" in call["args"]
                for call in self.calls()
            ),
            2,
        )

    def test_mutable_image_or_invalid_tag_is_rejected_before_remote_calls(self) -> None:
        for arguments in (
            ("v2.0.0", "backend:latest", FRONTEND),
            ("v2.0.0;bad", BACKEND, FRONTEND),
        ):
            with self.subTest(arguments=arguments):
                result = self.deploy(*arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls())

    def test_state_file_is_data_and_never_executes_shell_text(self) -> None:
        marker = self.directory / "unwanted-command"
        (self.state / "previous").write_text(
            f"RELEASE=$(touch {marker})\nBACKEND_IMAGE={BACKEND}\nFRONTEND_IMAGE={FRONTEND}\n"
        )
        result = self.deploy("--rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(marker.exists())
        self.assertFalse(self.calls())


if __name__ == "__main__":
    unittest.main(verbosity=2)
