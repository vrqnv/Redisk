import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yadisk  # type: ignore[import-not-found]
from webdav3.client import Client as WebDAVClient  # type: ignore[import-untyped]


class CloudAPI:
    def __init__(self, config: dict | None = None):
        self.yandex: Any | None = None
        self.nextcloud: Any | None = None
        self.config = config or {}

        disks = self.config.get("disks", {})

        yandex_cfg = disks.get("yandex", {})
        if yandex_cfg.get("enabled") and yandex_cfg.get("token"):
            self.connect_yandex(yandex_cfg["token"])

        nc_cfg = disks.get("nextcloud", {})
        if nc_cfg.get("enabled") and nc_cfg.get("url"):
            self.connect_nextcloud(nc_cfg)

    @staticmethod
    def _normalize_remote_path(path: str) -> str:
        normalized = "/" + path.strip("/")
        if normalized == "/":
            return normalized
        return normalized.replace("//", "/")

    @staticmethod
    def _ensure_parent(path: str) -> str:
        remote = CloudAPI._normalize_remote_path(path)
        parent = str(Path(remote).parent)
        if not parent.startswith("/"):
            parent = "/" + parent
        return parent

    def connect_yandex(self, token: str) -> bool:
        try:
            client = yadisk.YaDisk(token=token)
            if client.check_token():
                self.yandex = client
                print("Яндекс.Диск: подключён")
                return True
            print("Яндекс.Диск: токен недействителен")
        except Exception as exc:
            print(f"Яндекс.Диск: ошибка подключения — {exc}")
        self.yandex = None
        return False

    def connect_nextcloud(self, cfg: dict) -> bool:
        try:
            parsed = urlsplit(cfg["url"])
            hostname = f"{parsed.scheme}://{parsed.netloc}"
            root = parsed.path if parsed.path else "/"
            if not root.endswith("/"):
                root += "/"
            client = WebDAVClient(
                {
                    "webdav_hostname": hostname,
                    "webdav_root": root,
                    "webdav_login": cfg["login"],
                    "webdav_password": cfg["password"],
                }
            )
            # Some WebDAV setups restrict LIST but allow lightweight checks.
            # Try multiple probes to avoid false-negative "cannot connect".
            ok = False
            for probe in (lambda: client.check("/"), lambda: client.list("/")):
                try:
                    probe()
                    ok = True
                    break
                except Exception:
                    continue
            if not ok:
                raise RuntimeError("WebDAV endpoint is not reachable with provided credentials")
            self.nextcloud = client
            print("NextCloud: подключён")
            return True
        except Exception as exc:
            print(f"NextCloud: ошибка подключения — {exc}")
        self.nextcloud = None
        return False

    def disconnect(self, disk_id: str):
        if disk_id == "yandex":
            self.yandex = None
        elif disk_id == "nextcloud":
            self.nextcloud = None

    def is_connected(self, disk_id: str) -> bool:
        if disk_id == "yandex":
            return self.yandex is not None
        if disk_id == "nextcloud":
            return self.nextcloud is not None
        return False

    def list_dir(self, disk_id: str, path: str = "/") -> list[dict]:
        remote = self._normalize_remote_path(path)

        if disk_id == "yandex" and self.yandex:
            result = []
            try:
                for item in self.yandex.listdir(remote):
                    item_type = getattr(item, "type", None) or ""
                    is_dir = str(item_type).lower() == "dir"
                    raw_path = getattr(item, "path", "") or ""
                    clean_path = raw_path.replace("disk:", "", 1) if raw_path.startswith("disk:") else raw_path
                    name = getattr(item, "name", None) or clean_path.rstrip("/").split("/")[-1]
                    if not name:
                        continue
                    result.append({"name": name, "path": clean_path, "is_dir": is_dir})
            except Exception as exc:
                print(f"Яндекс.Диск: ошибка листинга {remote} — {exc}")
            return result

        if disk_id == "nextcloud" and self.nextcloud:
            result = []
            try:
                try:
                    items = self.nextcloud.list(remote, get_info=True)
                except TypeError:
                    items = self.nextcloud.list(remote)

                for item in items:
                    if isinstance(item, dict):
                        name = item.get("name", "").rstrip("/")
                        if not name or name in (".", ".."):
                            continue
                        item_path = f"{remote.rstrip('/')}/{name}".replace("//", "/")
                        result.append(
                            {
                                "name": name,
                                "path": item_path,
                                "is_dir": bool(item.get("isdir", False)),
                            }
                        )
                    elif isinstance(item, str):
                        name = item.strip("/").split("/")[-1]
                        if not name or name in (".", ".."):
                            continue
                        is_dir = item.endswith("/")
                        item_path = f"{remote.rstrip('/')}/{name}".replace("//", "/")
                        result.append({"name": name, "path": item_path, "is_dir": is_dir})
            except Exception as exc:
                print(f"NextCloud: ошибка листинга {remote} — {exc}")
            return result

        return []

    def download_file(self, disk_id: str, remote_path: str, local_path: str) -> bool:
        remote = self._normalize_remote_path(remote_path)
        try:
            os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
            if disk_id == "yandex" and self.yandex:
                self.yandex.download(remote, local_path)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                self.nextcloud.download_file(remote, local_path)
                return True
        except Exception as exc:
            print(f"Ошибка скачивания [{disk_id}] {remote}: {exc}")
        return False

    def upload_file(self, disk_id: str, local_path: str, remote_path: str) -> bool:
        remote = self._normalize_remote_path(remote_path)
        try:
            parent = self._ensure_parent(remote)
            if parent != "/":
                self.create_folder(disk_id, parent)
            if disk_id == "yandex" and self.yandex:
                self.yandex.upload(local_path, remote, overwrite=True)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                # webdavclient3 expects (remote_path, local_path)
                self.nextcloud.upload_file(remote, local_path)
                return True
        except Exception as exc:
            print(f"Ошибка загрузки [{disk_id}] {remote}: {exc}")
        return False

    def create_folder(self, disk_id: str, remote_path: str) -> bool:
        remote = self._normalize_remote_path(remote_path)
        if remote == "/":
            return True
        try:
            if disk_id == "yandex" and self.yandex:
                if not self.yandex.exists(remote):
                    self.yandex.mkdir(remote)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                if not self.nextcloud.check(remote):
                    self.nextcloud.mkdir(remote)
                return True
        except Exception as exc:
            print(f"Ошибка создания папки [{disk_id}] {remote}: {exc}")
        return False

    def delete_path(self, disk_id: str, remote_path: str) -> bool:
        remote = self._normalize_remote_path(remote_path)
        try:
            if disk_id == "yandex" and self.yandex:
                if self.yandex.exists(remote):
                    self.yandex.remove(remote, permanently=True)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                if self.nextcloud.check(remote):
                    self.nextcloud.clean(remote)
                return True
        except Exception as exc:
            print(f"Ошибка удаления [{disk_id}] {remote}: {exc}")
        return False

    def move_path(self, disk_id: str, src_path: str, dst_path: str) -> bool:
        src = self._normalize_remote_path(src_path)
        dst = self._normalize_remote_path(dst_path)
        try:
            if disk_id == "yandex" and self.yandex:
                self.yandex.move(src, dst, overwrite=True)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                self.nextcloud.move(src, dst)
                return True
        except Exception as exc:
            print(f"Ошибка перемещения [{disk_id}] {src} → {dst}: {exc}")
        return False
