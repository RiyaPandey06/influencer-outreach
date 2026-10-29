"""Configuration loading (config.yaml + .env)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(path: str = "config.yaml") -> dict:
    load_dotenv()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with p.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    for key in ("campaign", "discovery", "filter", "categories"):
        if key not in cfg:
            raise ValueError(f"config.yaml is missing the '{key}' section")
    return cfg


def env(name: str, default: str | None = None) -> str | None:
    val = os.getenv(name)
    return val if val not in (None, "") else default
