import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yadisk  # type: ignore[import-not-found]
from yadisk.exceptions import WrongResourceTypeError  # type: ignore[import-not-found]
from webdav3.client import Client as WebDAVClient  # type: ignore[import-untyped]

class CloudAPI:
    def __init__(self, config: dict | None = None):
        self.yandex: Any | None = None
        self.nextcloud: Any | None = None
        self.config = config or {}

        # Не автоподключаемся при старте.
        # Подключение происходит только когда пользователь явно вводит данные в tray.

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

    @staticmethod
    def _yandex_item_is_dir(item: Any) -> bool:
        is_dir_attr = getattr(item, "is_dir", None)
        if callable(is_dir_attr):
            try:
                return bool(is_dir_attr())
            except Exception:
                pass
        if isinstance(is_dir_attr, bool):
            return is_dir_attr
        item_type = getattr(item, "type", None)
        if isinstance(item_type, str):
            return item_type.lower() == "dir"
        return False

    def connect_yandex(self, token: str) -> bool:
        try:
            client = yadisk.YaDisk(token=token)
            if client.check_token():
                self.yandex = client
                return True
        except Exception as exc:
            print(f"Яндекс.Диск: ошибка - {exc}")
        self.yandex = None
        return False

    def connect_nextcloud(self, cfg: dict) -> bool:
        try:
            parsed = urlsplit(cfg["url"])
            hostname = f"{parsed.scheme}://{parsed.netloc}"
            root = parsed.path if parsed.path else "/"
            client = WebDAVClient(
                {
                    "webdav_hostname": hostname,
                    "webdav_root": root,
                    "webdav_login": cfg["login"],
                    "webdav_password": cfg["password"],
                }
            )
            client.list("/")
            self.nextcloud = client
            return True
        except Exception as exc:
            print(f"NextCloud: ошибка - {exc}")
        self.nextcloud = None
        return False

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
                items = self.yandex.listdir(remote)
            except WrongResourceTypeError:
                # Иногда API может вернуть путь к файлу там, где ожидалась папка.
                # В таком случае считаем, что дочерних элементов нет.
                return []
            for item in items:
                result.append(
                    {
                        "name": item.name,
                        "path": item.path.replace("disk:", "", 1),
                        "is_dir": self._yandex_item_is_dir(item),
                    }
                )
            return result

        if disk_id == "nextcloud" and self.nextcloud:
            try:
                items = self.nextcloud.list(remote, get_info=True)
            except TypeError:
                items = self.nextcloud.list(remote)

            result = []
            for item in items:
                if isinstance(item, dict):
                    name = item.get("name", "").rstrip("/")
                    if not name or name in (".", ".."):
                        continue
                    item_path = f"{remote.rstrip('/')}/{name}".replace(
                        "//",
                        "/",
                    )
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
                    item_path = f"{remote.rstrip('/')}/{name}".replace(
                        "//",
                        "/",
                    )
                    result.append(
                        {"name": name, "path": item_path, "is_dir": is_dir}
                    )
            return result

        return []

    def download_file(
        self,
        disk_id: str,
        remote_path: str,
        local_path: str,
    ) -> bool:
        remote = self._normalize_remote_path(remote_path)
        try:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            # После предыдущих неудачных синков на месте файла
            # мог остаться каталог с таким же именем.
            if os.path.isdir(local_path):
                try:
                    os.rmdir(local_path)
                except OSError:
                    print(
                        f"Пропуск файла {disk_id} {remote}: "
                        f"локальный путь уже занят каталогом {local_path}",
                    )
                    return False
            if disk_id == "yandex" and self.yandex:
                self.yandex.download(remote, local_path)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                self.nextcloud.download_file(remote, local_path)
                return True
        except Exception as exc:
            print(f"Ошибка скачивания {disk_id} {remote}: {exc}")
        return False

    def upload_file(
        self,
        disk_id: str,
        local_path: str,
        remote_path: str,
    ) -> bool:
        remote = self._normalize_remote_path(remote_path)
        try:
            self.create_folder(disk_id, self._ensure_parent(remote))
            if disk_id == "yandex" and self.yandex:
                self.yandex.upload(local_path, remote, overwrite=True)
                return True
            if disk_id == "nextcloud" and self.nextcloud:
                self.nextcloud.upload_file(local_path, remote)
                return True
        except Exception as exc:
            print(f"Ошибка загрузки {disk_id} {remote}: {exc}")
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
            print(f"Ошибка создания папки {disk_id} {remote}: {exc}")
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
            print(f"Ошибка удаления {disk_id} {remote}: {exc}")
        return False
