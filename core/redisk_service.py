import os
import shutil
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
from watchdog.observers import Observer  # type: ignore[import-not-found]

from cache import CacheManager
from cloud.api import CloudAPI
from utils.config import load_config, save_config


DISK_TITLES = {
    "yandex": "Яндекс.Диск",
    "nextcloud": "NextCloud",
}

TITLE_TO_DISK = {v: k for k, v in DISK_TITLES.items()}


class RediskService:
    def __init__(self):
        self.root_dir = Path.home() / "Redisk"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._add_bookmark(self.root_dir)

        self.config = load_config()
        self.config.setdefault("disks", {})
        self.config.setdefault("cache", {})

        self.api = CloudAPI(config=self.config)
        cache_size_mb = int(self.config["cache"].get("max_size_mb", 5120))
        self.cache = CacheManager(max_size_mb=cache_size_mb)
        self._pause_depth = 0

        self.observer = Observer()
        self.handler = RediskWatchHandler(self)
        self.observer.schedule(self.handler, str(self.root_dir), recursive=True)
        self.observer.start()

        for disk_id in self.get_connected_disks():
            self.ensure_disk_local_dir(disk_id)
            self.start_sync(disk_id)

    # ------------------------------------------------------------------ #
    # Pause context                                                        #
    # ------------------------------------------------------------------ #

    @property
    def events_paused(self) -> bool:
        return self._pause_depth > 0

    def _pause(self):
        self._pause_depth += 1

    def _resume(self):
        self._pause_depth = max(0, self._pause_depth - 1)

    # ------------------------------------------------------------------ #
    # Bookmarks (GTK3 / GTK4 file manager sidebar)                        #
    # ------------------------------------------------------------------ #

    def _add_bookmark(self, path: Path):
        uri = path.as_uri()
        name = path.name
        line = f"{uri} {name}\n"
        for gtk_ver in ("gtk-3.0", "gtk-4.0"):
            bm_file = Path.home() / ".config" / gtk_ver / "bookmarks"
            bm_file.parent.mkdir(parents=True, exist_ok=True)
            existing = bm_file.read_text(encoding="utf-8") if bm_file.exists() else ""
            if uri not in existing:
                with open(bm_file, "a", encoding="utf-8") as f:
                    f.write(line)

    # ------------------------------------------------------------------ #
    # Disk management                                                      #
    # ------------------------------------------------------------------ #

    def get_connected_disks(self) -> list[str]:
        disks = self.config.get("disks", {})
        result = []
        for disk_id in ("yandex", "nextcloud"):
            if disks.get(disk_id, {}).get("enabled") and self.api.is_connected(disk_id):
                result.append(disk_id)
        return result

    def ensure_disk_local_dir(self, disk_id: str):
        (self.root_dir / DISK_TITLES[disk_id]).mkdir(parents=True, exist_ok=True)

    def _save(self):
        save_config(self.config)

    def connect_yandex(self, token: str) -> bool:
        ok = self.api.connect_yandex(token)
        if not ok:
            return False
        self.config["disks"].setdefault("yandex", {})
        self.config["disks"]["yandex"]["token"] = token
        self.config["disks"]["yandex"]["enabled"] = True
        self._save()
        self.ensure_disk_local_dir("yandex")
        return True

    def connect_nextcloud(self, url: str, login: str, password: str) -> bool:
        cfg = {"url": url, "login": login, "password": password}
        ok = self.api.connect_nextcloud(cfg)
        if not ok:
            return False
        self.config["disks"].setdefault("nextcloud", {})
        self.config["disks"]["nextcloud"].update(cfg)
        self.config["disks"]["nextcloud"]["enabled"] = True
        self._save()
        self.ensure_disk_local_dir("nextcloud")
        return True

    def disconnect_disk(self, disk_id: str):
        self.config["disks"].setdefault(disk_id, {})
        self.config["disks"][disk_id]["enabled"] = False
        self._save()
        self.api.disconnect(disk_id)

        local_dir = self.root_dir / DISK_TITLES[disk_id]
        if local_dir.exists():
            self._pause()
            try:
                shutil.rmtree(local_dir)
            finally:
                self._resume()

    def shutdown(self):
        self.observer.stop()
        self.observer.join(timeout=2)
        self.cache.close()

    def get_cache_stats(self) -> dict:
        return self.cache.get_stats()

    def clear_cache(self) -> int:
        return self.cache.clear_all()

    # ------------------------------------------------------------------ #
    # Sync                                                                 #
    # ------------------------------------------------------------------ #

    def start_sync(self, disk_id: str, on_done=None) -> threading.Thread:
        def _run():
            self.pull_from_cloud(disk_id)
            if on_done:
                try:
                    on_done(disk_id)
                except Exception as exc:
                    print(f"on_done callback error: {exc}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def pull_from_cloud(self, disk_id: str):
        if not self.api.is_connected(disk_id):
            return
        disk_root = self.root_dir / DISK_TITLES[disk_id]
        disk_root.mkdir(parents=True, exist_ok=True)
        self._pause()
        try:
            self._sync_dir_from_cloud(disk_id, "/", disk_root)
        except Exception as exc:
            print(f"Ошибка синхронизации [{disk_id}]: {exc}")
        finally:
            self._resume()

    def _sync_dir_from_cloud(self, disk_id: str, remote_path: str, local_dir: Path):
        items = self.api.list_dir(disk_id, remote_path)
        for item in items:
            name = item["name"]
            if not name:
                continue
            if item["is_dir"]:
                child_local = local_dir / name
                child_local.mkdir(parents=True, exist_ok=True)
                self._sync_dir_from_cloud(disk_id, item["path"], child_local)
            else:
                target_file = local_dir / name
                cache_key = self._cache_key(disk_id, item["path"])
                if target_file.exists():
                    # Локальный файл уже есть: используем его как источник кэша.
                    try:
                        self.cache.cache_local_file(cache_key, str(target_file), file_id=cache_key)
                    except Exception as exc:
                        print(f"Cache update skipped for {target_file}: {exc}")
                    continue

                if self.cache.restore_to_local(cache_key, str(target_file)):
                    continue

                if self.api.download_file(disk_id, item["path"], str(target_file)):
                    try:
                        self.cache.cache_local_file(cache_key, str(target_file), file_id=cache_key)
                    except Exception as exc:
                        print(f"Cache store skipped for {target_file}: {exc}")

    # ------------------------------------------------------------------ #
    # Watchdog handlers                                                    #
    # ------------------------------------------------------------------ #

    def _disk_and_relative_from_path(self, path: str):
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.root_dir.resolve())
        except ValueError:
            return None, None
        parts = relative.parts
        if not parts:
            return None, None
        disk_id = TITLE_TO_DISK.get(parts[0])
        if not disk_id:
            return None, None
        rel = Path(*parts[1:]) if len(parts) > 1 else Path(".")
        return disk_id, rel

    def handle_created_or_modified(self, path: str, is_dir: bool):
        disk_id, rel = self._disk_and_relative_from_path(path)
        if not disk_id or rel is None:
            return
        remote = "/" if str(rel) == "." else "/" + str(rel).replace("\\", "/")
        if is_dir:
            self.api.create_folder(disk_id, remote)
        elif os.path.exists(path):
            self.api.upload_file(disk_id, path, remote)
            cache_key = self._cache_key(disk_id, remote)
            try:
                self.cache.cache_local_file(cache_key, path, file_id=cache_key)
            except Exception as exc:
                print(f"Cache update skipped for {path}: {exc}")

    def handle_deleted(self, path: str):
        disk_id, rel = self._disk_and_relative_from_path(path)
        if not disk_id or rel is None or str(rel) == ".":
            return
        remote = "/" + str(rel).replace("\\", "/")
        self.api.delete_path(disk_id, remote)
        cache_key = self._cache_key(disk_id, remote)
        try:
            self.cache.evict(cache_key)
        except Exception:
            pass

    def handle_moved(self, src_path: str, dest_path: str, is_dir: bool):
        src_disk, src_rel = self._disk_and_relative_from_path(src_path)
        dst_disk, dst_rel = self._disk_and_relative_from_path(dest_path)

        if (
            src_disk and dst_disk
            and src_disk == dst_disk
            and src_rel and dst_rel
            and str(src_rel) != "."
            and str(dst_rel) != "."
        ):
            src_remote = "/" + str(src_rel).replace("\\", "/")
            dst_remote = "/" + str(dst_rel).replace("\\", "/")
            if self.api.move_path(src_disk, src_remote, dst_remote):
                return

        # Fallback for cross-disk moves or failed renames
        self.handle_deleted(src_path)
        self.handle_created_or_modified(dest_path, is_dir=is_dir)

    def _cache_key(self, disk_id: str, remote_path: str) -> str:
        normalized = "/" + remote_path.strip("/")
        return f"{disk_id}:{normalized}"


class RediskWatchHandler(FileSystemEventHandler):
    def __init__(self, service: RediskService):
        self.service = service

    def on_created(self, event):
        if self.service.events_paused:
            return
        self.service.handle_created_or_modified(event.src_path, is_dir=event.is_directory)

    def on_modified(self, event):
        if self.service.events_paused or event.is_directory:
            return
        self.service.handle_created_or_modified(event.src_path, is_dir=False)

    def on_deleted(self, event):
        if self.service.events_paused:
            return
        self.service.handle_deleted(event.src_path)

    def on_moved(self, event):
        if self.service.events_paused:
            return
        self.service.handle_moved(
            src_path=event.src_path,
            dest_path=event.dest_path,
            is_dir=event.is_directory,
        )
