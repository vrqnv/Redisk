import os
import subprocess
import sys
import tempfile
import webbrowser

from PIL import Image, ImageDraw  # type: ignore[import-not-found]
from PyQt6.QtGui import QAction, QIcon  # type: ignore[import-not-found]
from PyQt6.QtWidgets import (  # type: ignore[import-not-found]
    QApplication,
    QMenu,
    QSystemTrayIcon,
)


DISK_TITLES = {
    "yandex": "Яндекс.Диск",
    "nextcloud": "NextCloud",
}

DISK_AUTH_URLS = {
    "yandex": "https://oauth.yandex.ru/authorize",
    "nextcloud": "https://nextcloud.com/sign-up/",
}


class TrayController:
    def __init__(self, app: QApplication, tray_icon: QSystemTrayIcon):
        self.app = app
        self.tray_icon = tray_icon
        self.notifications_enabled = True
        self.connected_disks: set[str] = set()
        self.menu = QMenu()
        self.notifications_action = QAction("Отключить уведомления")
        self.notifications_action.triggered.connect(self.toggle_notifications)

    def show_notification(self, title: str, message: str):
        if self.notifications_enabled:
            self.tray_icon.showMessage(title, message)

    def open_redisk(self):
        mount_dir = os.path.expanduser("~/Redisk")
        os.makedirs(mount_dir, exist_ok=True)

        try:
            subprocess.Popen(["xdg-open", mount_dir])
        except Exception as exc:
            print(f"Не удалось открыть файловый менеджер: {exc}")
            self.show_notification(
                "DiscoHack",
                "Не удалось открыть файловый менеджер",
            )
            return

        print(f"Открыт Redisk: {mount_dir}")

    def connect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]
        auth_url = DISK_AUTH_URLS[disk_id]

        webbrowser.open(auth_url, new=2)
        print(f"Открыта авторизация: {disk_title}")

        # Для прототипа считаем, что авторизация успешна после перехода.
        self.connected_disks.add(disk_id)
        self.show_notification("DiscoHack", f"{disk_title} подключен")
        self.open_redisk()
        self.rebuild_menu()

    def disconnect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]
        if disk_id in self.connected_disks:
            self.connected_disks.remove(disk_id)
            self.show_notification("DiscoHack", f"{disk_title} отключен")
            print(f"Отключен диск: {disk_title}")
            self.rebuild_menu()

    def toggle_notifications(self):
        self.notifications_enabled = not self.notifications_enabled
        if self.notifications_enabled:
            print("Уведомления включены")
            self.notifications_action.setText("Отключить уведомления")
            self.show_notification("DiscoHack", "Уведомления включены")
        else:
            print("Уведомления отключены")
            self.notifications_action.setText("Включить уведомления")

    def add_disconnect_menu(self):
        if not self.connected_disks:
            return

        if len(self.connected_disks) == 1:
            disk_id = next(iter(self.connected_disks))
            action = QAction(f"Отключить {DISK_TITLES[disk_id]}")
            action.triggered.connect(lambda: self.disconnect_disk(disk_id))
            self.menu.addAction(action)
            return

        disconnect_menu = QMenu("Отключить диск")
        for disk_id in sorted(self.connected_disks):
            action = QAction(f"Отключить {DISK_TITLES[disk_id]}")
            action.triggered.connect(lambda _, d=disk_id: self.disconnect_disk(d))
            disconnect_menu.addAction(action)
        self.menu.addMenu(disconnect_menu)

    def add_add_disk_menu(self):
        add_menu = QMenu("Добавить диск")
        available = [
            disk_id
            for disk_id in ("yandex", "nextcloud")
            if disk_id not in self.connected_disks
        ]

        if not available:
            disabled_action = QAction("Все диски уже подключены")
            disabled_action.setEnabled(False)
            add_menu.addAction(disabled_action)
        else:
            for disk_id in available:
                action = QAction(DISK_TITLES[disk_id])
                action.triggered.connect(lambda _, d=disk_id: self.connect_disk(d))
                add_menu.addAction(action)

        self.menu.addMenu(add_menu)

    def rebuild_menu(self):
        self.menu.clear()
        self.add_disconnect_menu()
        self.add_add_disk_menu()

        open_action = QAction("Открыть Redisk")
        open_action.triggered.connect(self.open_redisk)
        self.menu.addAction(open_action)
        self.menu.addAction(self.notifications_action)

        self.menu.addSeparator()
        quit_action = QAction("Закрыть")
        quit_action.triggered.connect(self.quit_app)
        self.menu.addAction(quit_action)

    def quit_app(self):
        print("Программа закрыта")
        self.tray_icon.hide()
        self.app.quit()


def create_icon_path():
    width = 64
    height = 64
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 20, 54, 60), fill=(100, 150, 255))

    temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    image.save(temp_file.name)
    return temp_file.name


def run_tray():
    app = QApplication(sys.argv)
    icon_path = create_icon_path()
    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)

    controller = TrayController(app=app, tray_icon=tray_icon)
    controller.rebuild_menu()

    tray_icon.setContextMenu(controller.menu)
    tray_icon.show()
    controller.show_notification("DiscoHack", "Программа запущена")

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray()