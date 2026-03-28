"""Application configuration — loaded from config.yaml with env var overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


def _data_dir() -> Path:
    return Path(os.environ.get("IPMILINK_DATA_DIR", "/data" if os.name != "nt" else "./data"))


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 3000
    https: bool = False
    cert_file: str | None = None
    key_file: str | None = None


@dataclass
class AuthConfig:
    enabled: bool = True
    session_expiry: str = "24h"
    max_login_attempts: int = 5
    lockout_duration: str = "15m"


@dataclass
class IPMIConfig:
    poll_interval: int = 5
    power_poll_interval: int = 10
    command_timeout: int = 10
    backend: str = "ipmitool"


@dataclass
class DataConfig:
    db_path: str = ""
    retention_days: int = 365
    cleanup_interval: str = "24h"

    def __post_init__(self):
        if not self.db_path:
            self.db_path = str(_data_dir() / "ipmilink.db")


@dataclass
class LoggingConfig:
    level: str = "info"
    file: str | None = None


@dataclass
class ModuleConfig:
    enabled: bool = True


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    ipmi: IPMIConfig = field(default_factory=IPMIConfig)
    data: DataConfig = field(default_factory=DataConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    demo: bool = False
    modules: dict[str, ModuleConfig] = field(default_factory=dict)


def _apply_env_overrides(config: AppConfig) -> None:
    """Apply IPMILINK_ prefixed env vars to config."""
    env_map = {
        "IPMILINK_SERVER_HOST": ("server", "host"),
        "IPMILINK_SERVER_PORT": ("server", "port", int),
        "IPMILINK_AUTH_ENABLED": ("auth", "enabled", lambda v: v.lower() in ("true", "1", "yes")),
        "IPMILINK_AUTH_SESSION_EXPIRY": ("auth", "session_expiry"),
        "IPMILINK_IPMI_POLL_INTERVAL": ("ipmi", "poll_interval", int),
        "IPMILINK_DATA_DB_PATH": ("data", "db_path"),
        "IPMILINK_DATA_RETENTION_DAYS": ("data", "retention_days", int),
        "IPMILINK_LOGGING_LEVEL": ("logging", "level"),
        "IPMILINK_DEMO": ("demo", None, lambda v: v.lower() in ("true", "1", "yes")),
    }
    for env_key, mapping in env_map.items():
        value = os.environ.get(env_key)
        if value is None:
            continue
        if mapping[1] is None:
            # top-level attribute
            converter = mapping[2] if len(mapping) > 2 else str
            setattr(config, mapping[0], converter(value))
        else:
            section = getattr(config, mapping[0])
            converter = mapping[2] if len(mapping) > 2 else str
            setattr(section, mapping[1], converter(value))


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML file, then apply env var overrides."""
    config = AppConfig()

    if config_path is None:
        config_path = _data_dir() / "config.yaml"

    path = Path(config_path)
    if path.exists():
        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        if "server" in raw:
            config.server = ServerConfig(**{k: v for k, v in raw["server"].items() if k in ServerConfig.__dataclass_fields__})
        if "auth" in raw:
            config.auth = AuthConfig(**{k: v for k, v in raw["auth"].items() if k in AuthConfig.__dataclass_fields__})
        if "ipmi" in raw:
            config.ipmi = IPMIConfig(**{k: v for k, v in raw["ipmi"].items() if k in IPMIConfig.__dataclass_fields__})
        if "data" in raw:
            config.data = DataConfig(**{k: v for k, v in raw["data"].items() if k in DataConfig.__dataclass_fields__})
        if "logging" in raw:
            config.logging = LoggingConfig(**{k: v for k, v in raw["logging"].items() if k in LoggingConfig.__dataclass_fields__})
        if "demo" in raw:
            config.demo = bool(raw["demo"])
        if "modules" in raw and isinstance(raw["modules"], dict):
            for mod_id, mod_conf in raw["modules"].items():
                if isinstance(mod_conf, dict):
                    config.modules[mod_id] = ModuleConfig(**mod_conf)

    _apply_env_overrides(config)
    return config


def save_default_config(config_path: str | Path) -> None:
    """Write a default config.yaml if it doesn't exist."""
    path = Path(config_path)
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    default = {
        "server": {"host": "0.0.0.0", "port": 3000, "https": False},
        "auth": {"enabled": True, "session_expiry": "24h", "max_login_attempts": 5},
        "ipmi": {"poll_interval": 5, "power_poll_interval": 10, "command_timeout": 10},
        "data": {"retention_days": 365, "cleanup_interval": "24h"},
        "logging": {"level": "info"},
        "modules": {
            "sensors": {"enabled": True},
            "fanpilot": {"enabled": True},
            "power": {"enabled": True},
            "sel": {"enabled": True},
            "fru": {"enabled": True},
        },
    }
    with open(path, "w") as f:
        yaml.dump(default, f, default_flow_style=False, sort_keys=False)
