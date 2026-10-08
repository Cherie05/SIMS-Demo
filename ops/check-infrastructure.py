"""Validate merged Compose configurations using synthetic credentials, without starting services."""

import base64
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def configuration(files: list[str], environment: dict[str, str]) -> dict:
    command = ["docker", "compose", "--env-file", "production.env.example"]
    for file in files:
        command.extend(["-f", file])
    result = subprocess.run(
        [*command, "config", "--format", "json"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"Compose validation failed for {', '.join(files)}: {result.stderr.strip()}"
        )
    return json.loads(result.stdout)


def main() -> None:
    # Explicit overrides and an example env file prevent reading a developer's production secrets.
    environment = os.environ.copy()
    for name in (
        "MYSQL_ROOT_PASSWORD",
        "MYSQL_PASSWORD",
        "MYSQL_APP_PASSWORD",
        "MYSQL_BACKUP_PASSWORD",
        "MYSQL_RESTORE_PASSWORD",
        "REDIS_PASSWORD",
        "JWT_SECRET_KEY",
        "BACKUP_ENCRYPTION_KEY",
        "GRAFANA_ADMIN_PASSWORD",
        "METRICS_TOKEN",
    ):
        environment[name] = f"validation_only_{name.lower()}_0123456789_0123456789"
    environment.update(
        {
            "DATA_ENCRYPTION_KEYS": base64.urlsafe_b64encode(bytes(range(32))).decode(),
            "PUBLIC_URL": "https://sims.example.com",
            "SITE_ADDRESS": "sims.example.com",
            "OTP_DELIVERY": "email",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_STARTTLS": "true",
            "SMTP_SSL": "false",
            "SMTP_USER": "validation",
            "SMTP_PASSWORD": "validation_only",
            "MAIL_FROM": "no-reply@example.com",
            "EDGE_PROXY_IP": "172.30.250.10",
            "EDGE_SUBNET": "172.30.250.0/24",
            "SIGNUP_ENABLED": "false",
            "BACKUP_DIR": "./backups",
            "COMPOSE_PROFILES": "",
            "COMPOSE_PROJECT_NAME": "sims-config-check",
        }
    )
    base = ["docker-compose.yml"]
    demo = configuration(base, environment)
    assert demo["services"]["migrate"]["environment"]["SEED_DEMO_DATA"] == "true"
    production = configuration([*base, "docker-compose.prod.yml"], environment)
    services = production["services"]
    assert production["networks"]["app"]["internal"]
    assert production["networks"]["data"]["internal"]
    for name in (
        "mysql",
        "backend",
        "worker",
        "frontend",
        "redis",
        "migrate",
        "db-init",
        "backup",
    ):
        assert not services[name].get("ports"), (
            f"{name} must have no production host ports"
        )
        assert services[name]["read_only"], (
            f"{name} must have a read-only root filesystem"
        )
    assert "mailpit" not in services, "Development inbox must be inactive in production"
    for name in ("backend", "worker", "migrate"):
        settings = services[name]["environment"]
        assert settings["ENVIRONMENT"] == "production"
        assert settings["DATABASE_TLS"] == "required"
        assert settings["OTP_DELIVERY"] == "email"
        assert settings["FRONTEND_URL"].startswith("https://")
    assert services["migrate"]["environment"]["SEED_DEMO_DATA"] == "false"
    assert "sims_app@" in services["backend"]["environment"]["DATABASE_URL"]
    assert "sims@" in services["migrate"]["environment"]["DATABASE_URL"]
    assert services["db-init"]["environment"]["MYSQL_SSL_MODE"] == "REQUIRED"
    assert services["backup"]["environment"]["MYSQL_SSL_MODE"] == "REQUIRED"
    monitored = configuration(
        [*base, "docker-compose.prod.yml", "docker-compose.observability.yml"],
        environment,
    )
    for name in ("prometheus", "grafana"):
        service = monitored["services"][name]
        assert service["read_only"] and service["healthcheck"]
        assert all(port["host_ip"] == "127.0.0.1" for port in service["ports"])
    assert not monitored["networks"]["monitoring"].get("internal", False), (
        "Monitoring dashboards need a bridge that supports loopback host publishing"
    )
    assert monitored["networks"]["app"]["internal"]
    assert monitored["networks"]["data"]["internal"]
    assert (
        monitored["services"]["prometheus"]["environment"]["METRICS_TOKEN"]
        == environment["METRICS_TOKEN"]
    )
    print("Compose checks passed: development, production, production with monitoring.")


if __name__ == "__main__":
    main()
