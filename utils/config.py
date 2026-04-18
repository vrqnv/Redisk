"""Config helpers for DiscoHack."""

import json
from pathlib import Path


def get_config_dir():
    """Return config dir and ensure it exists."""
    config_dir = Path.home() / ".config" / "discohack"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _default_config():
    # Плейсхолдеры: user заполнит client_id вручную.
    return {
        "oauth": {
            "yandex": {
                "client_id": "8ccbfa30fe5d4a68a3b4b1f4a8c34765",
                "redirect_uri": "http://127.0.0.1:8085/callback",
            },
        },
        "disks": {
            "yandex": {"enabled": False},
            "nextcloud": {"enabled": False},
        },
    }


def load_config():
    """Load config file, creating it with defaults if missing."""
    config_file = get_config_dir() / "config.json"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = _default_config()
        save_config(cfg)

    # Мягко домерживаем дефолты,
    # чтобы обновления структуры не ломали старые конфиги.
    defaults = _default_config()
    cfg.setdefault("oauth", {})
    cfg["oauth"].setdefault("yandex", {})
    cfg["oauth"]["yandex"].setdefault(
        "client_id",
        defaults["oauth"]["yandex"]["client_id"],
    )
    cfg["oauth"]["yandex"].setdefault(
        "redirect_uri",
        defaults["oauth"]["yandex"]["redirect_uri"],
    )
    if not cfg["oauth"]["yandex"].get("client_id"):
        cfg["oauth"]["yandex"]["client_id"] = defaults["oauth"]["yandex"][
            "client_id"
        ]
        save_config(cfg)
    cfg.setdefault("disks", {})
    cfg["disks"].setdefault("yandex", defaults["disks"]["yandex"])
    cfg["disks"].setdefault("nextcloud", defaults["disks"]["nextcloud"])
    return cfg


def save_config(config):
    """Persist config to ~/.config/discohack/config.json."""
    config_file = get_config_dir() / "config.json"
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
