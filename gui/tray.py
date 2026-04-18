import os
import subprocess
import sys
import tempfile
import threading
import webbrowser

from PIL import Image, ImageDraw  
from PyQt6.QtCore import QTimer 
from PyQt6.QtGui import QAction, QIcon  
from PyQt6.QtWidgets import ( 
    QApplication,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

from cloud.config import YANDEX_CLIENT_ID
from core.redisk_service import DISK_TITLES, RediskService


def _build_yandex_auth_url() -> str:
    if YANDEX_CLIENT_ID:
        return (
            "https://oauth.yandex.ru/authorize"
            f"?response_type=token"
            f"&client_id={YANDEX_CLIENT_ID}"
            "&force_confirm=yes"
            "&redirect_uri=https://oauth.yandex.ru/verification_code"
        )
    return "https://yandex.ru/dev/disk/poligon/"


DISK_AUTH_URLS = {
    "nextcloud": "https://nextcloud.com/install/",
}


class TrayController:
    def __init__(self, app: QApplication, tray_icon: QSystemTrayIcon, service: RediskService):
        self.app = app
        self.tray_icon = tray_icon
        self.service = service
        self.notifications_enabled = True
        self.menu = QMenu()
        self.notifications_action: QAction | None = None

        self._create_notifications_action()

        self._notif_queue: list[tuple[str, str]] = []
        self._notif_timer = QTimer()
        self._notif_timer.timeout.connect(self._flush_notifications)
        self._notif_timer.start(400)


    def _flush_notifications(self):
        while self._notif_queue:
            title, msg = self._notif_queue.pop(0)
            self.tray_icon.showMessage(title, msg)

    def show_notification(self, title: str, message: str):
        """Main-thread notification."""
        if self.notifications_enabled:
            self._notif_queue.append((title, message))

    def notify_from_thread(self, title: str, message: str):
        """Thread-safe notification (called from background threads)."""
        if self.notifications_enabled:
            self._notif_queue.append((title, message))
            

    def open_redisk(self):
        mount_dir = str(self.service.root_dir)
        os.makedirs(mount_dir, exist_ok=True)
        try:
            subprocess.Popen(["xdg-open", mount_dir])
        except Exception as exc:
            print(f"Не удалось открыть файловый менеджер: {exc}")
            self.show_notification("Redisk", "Не удалось открыть файловый менеджер")

    def connect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]

        if disk_id == "yandex":
            auth_url = _build_yandex_auth_url()
            webbrowser.open(auth_url, new=2)

            if YANDEX_CLIENT_ID:
                hint = (
                    "Браузер открыт на странице авторизации Яндекс.\n\n"
                    "После входа в аккаунт скопируйте значение access_token\n"
                    "из адресной строки браузера и вставьте его ниже."
                )
            else:
                hint = (
                    "Откройте страницу Яндекс.Диска в браузере.\n\n"
                    "Нажмите «Получить OAuth-токен», войдите в аккаунт,\n"
                    "скопируйте токен и вставьте его ниже.\n\n"
                    "Страница: https://yandex.ru/dev/disk/poligon/"
                )

            QMessageBox.information(None, "Авторизация Яндекс.Диска", hint)

            token, ok = QInputDialog.getText(
                None,
                "Подключение Яндекс.Диска",
                "OAuth-токен:",
            )
            if not ok or not token.strip():
                return

            is_connected = self.service.connect_yandex(token.strip())


        if not is_connected:
            QMessageBox.critical(
                None,
                "Redisk",
                f"Не удалось подключить {disk_title}.\nПроверьте данные и попробуйте снова.",
            )
            return

        self.show_notification("Redisk", f"{disk_title} подключён. Начинается синхронизация…")
        self.rebuild_menu()
        self.open_redisk()

        def on_sync_done(did: str):
            self.notify_from_thread("Redisk", f"{DISK_TITLES[did]}: синхронизация завершена")

        self.service.start_sync(disk_id, on_done=on_sync_done)

    def disconnect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]
        self.service.disconnect_disk(disk_id)
        self.show_notification("Redisk", f"{disk_title} отключён")
        self.rebuild_menu()

    def toggle_notifications(self):
        self.notifications_enabled = not self.notifications_enabled
        if self.notifications_enabled:
            if self.notifications_action:
                self.notifications_action.setText("Отключить уведомления")
            self.show_notification("Redisk", "Уведомления включены")
        else:
            if self.notifications_action:
                self.notifications_action.setText("Включить уведомления")


    def _add_disconnect_items(self):
        connected = self.service.get_connected_disks()
        if not connected:
            return

        for disk_id in connected:
            action = QAction(f"Отключить {DISK_TITLES[disk_id]}", self.menu)
            action.triggered.connect(lambda _, d=disk_id: self.disconnect_disk(d))
            self.menu.addAction(action)

    def _add_add_disk_menu(self):
        connected_set = set(self.service.get_connected_disks())
        available = [d for d in ("yandex", "nextcloud") if d not in connected_set]

        if not available:
            disabled = QAction("Все диски уже подключены", self.menu)
            disabled.setEnabled(False)
            self.menu.addAction(disabled)
        else:
            for disk_id in available:
                action = QAction(f"Подключить {DISK_TITLES[disk_id]}", self.menu)
                action.triggered.connect(lambda _, d=disk_id: self.connect_disk(d))
                self.menu.addAction(action)

    def _create_notifications_action(self):
        title = "Отключить уведомления" if self.notifications_enabled else "Включить уведомления"
        self.notifications_action = QAction(title, self.menu)
        self.notifications_action.triggered.connect(self.toggle_notifications)

    def rebuild_menu(self):
        self.menu = QMenu()

        self._create_notifications_action()
        self._add_disconnect_items()
        self._add_add_disk_menu()

        cache_stats_action = QAction("Статус кэша", self.menu)
        cache_stats_action.triggered.connect(self.show_cache_stats)
        self.menu.addAction(cache_stats_action)

        clear_cache_action = QAction("Очистить кэш", self.menu)
        clear_cache_action.triggered.connect(self.clear_cache)
        self.menu.addAction(clear_cache_action)

        open_action = QAction("Открыть Redisk", self.menu)
        open_action.triggered.connect(self.open_redisk)
        self.menu.addAction(open_action)

        if self.notifications_action:
            self.menu.addAction(self.notifications_action)

        self.menu.addSeparator()
        quit_action = QAction("Закрыть", self.menu)
        quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(quit_action)

        self.tray_icon.setContextMenu(self.menu)

    def show_cache_stats(self):
        try:
            stats = self.service.get_cache_stats()
            mb = 1024 * 1024
            total_mb = stats.get("total_size_bytes", 0) / mb
            max_mb = stats.get("max_size_bytes", 0) / mb
            free_mb = stats.get("free_bytes", 0) / mb
            msg = (
                f"Файлов в кэше: {stats.get('total_files', 0)}\n"
                f"Размер кэша: {total_mb:.2f} MB / {max_mb:.2f} MB\n"
                f"Свободно: {free_mb:.2f} MB\n\n"
                f"Cache hits: {stats.get('cache_hits', 0)}\n"
                f"Cache misses: {stats.get('cache_misses', 0)}\n"
                f"Downloads: {stats.get('downloads', 0)}\n"
                f"Evictions: {stats.get('evictions', 0)}"
            )
            QMessageBox.information(None, "Кэш Redisk", msg)
        except Exception as exc:
            print(f"Не удалось показать статус кэша: {exc}")
            QMessageBox.critical(None, "Кэш Redisk", f"Ошибка чтения статистики кэша:\n{exc}")

    def clear_cache(self):
        try:
            removed = self.service.clear_cache()
            self.show_notification("Redisk", f"Кэш очищен: удалено файлов {removed}")
            QMessageBox.information(None, "Кэш Redisk", f"Очищено файлов: {removed}")
        except Exception as exc:
            print(f"Не удалось очистить кэш: {exc}")
            QMessageBox.critical(None, "Кэш Redisk", f"Ошибка очистки кэша:\n{exc}")

    def quit_app(self):
        self.service.shutdown()
        self.tray_icon.hide()
        self.app.quit()


def _create_icon_path() -> str:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill=(70, 130, 230, 255))
    draw.ellipse((16, 16, 48, 48), fill=(255, 255, 255, 200))
    draw.ellipse((22, 22, 42, 42), fill=(70, 130, 230, 255))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return tmp.name


def run_tray(service: RediskService):
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(
            None,
            "Redisk",
            (
                "Системный трей недоступен."
            ),
        )
        sys.exit(1)

    icon_path = _create_icon_path()
    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)

    controller = TrayController(app=app, tray_icon=tray_icon, service=service)
    controller.rebuild_menu()

    tray_icon.setContextMenu(controller.menu)
    tray_icon.show()
    controller.show_notification("Redisk", "Приложение запущено")

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray(RediskService())
