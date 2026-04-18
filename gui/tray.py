import os
import subprocess
import sys
import tempfile
import webbrowser

from PIL import Image, ImageDraw  # type: ignore[import-not-found]
from PyQt6.QtGui import QAction, QIcon  # type: ignore[import-not-found]
from PyQt6.QtWidgets import (  # type: ignore[import-not-found]
    QApplication,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QSystemTrayIcon,
)

from core.redisk_service import DISK_TITLES, RediskService
from core.yandex_oauth import (
    yandex_exchange_code_for_token,
    yandex_start_oauth,
)
from utils.config import load_config, save_config

DISK_AUTH_URLS = {
    # ВАЖНО: oauth.yandex.ru/authorize требует client_id, иначе будет 400.
    # Поэтому для "просто перейти" открываем страницу Диска/логина.
    "yandex": "https://disk.yandex.ru/",
    "nextcloud": "https://nextcloud.com/sign-up/",
}


class TrayController:
    def __init__(
        self,
        app: QApplication,
        tray_icon: QSystemTrayIcon,
        service: RediskService,
    ):
        self.app = app
        self.tray_icon = tray_icon
        self.service = service
        self.notifications_enabled = True
        self.menu = self._create_menu()
        self.add_yandex_action = QAction("Добавить Яндекс.Диск")
        self.add_nextcloud_action = QAction("Добавить NextCloud")
        self.disconnect_yandex_action = QAction("Отключить Яндекс.Диск")
        self.disconnect_nextcloud_action = QAction("Отключить NextCloud")
        self.open_action = QAction("Открыть Redisk")
        self.notifications_action = QAction("Отключить уведомления")
        self.add_yandex_action.triggered.connect(self.add_yandex_flow)
        self.add_nextcloud_action.triggered.connect(
            lambda: self.connect_disk("nextcloud"),
        )
        self.disconnect_yandex_action.triggered.connect(
            lambda: self.disconnect_disk("yandex"),
        )
        self.disconnect_nextcloud_action.triggered.connect(
            lambda: self.disconnect_disk("nextcloud"),
        )
        self.open_action.triggered.connect(self.open_redisk)
        self.notifications_action.triggered.connect(self.toggle_notifications)

        self._log_path = os.path.expanduser("~/.cache/discohack/tray.log")
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    def _create_menu(self):
        # QMenu() иногда ведёт себя странно в разных DE,
        # поэтому создаём его в отдельном месте.
        from PyQt6.QtWidgets import QMenu  # type: ignore[import-not-found]

        return QMenu()

    def show_notification(self, title: str, message: str):
        if self.notifications_enabled:
            self.tray_icon.showMessage(title, message)

    def _log(self, message: str):
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(message.rstrip() + "\n")
        except Exception:
            pass

    def open_redisk(self):
        mount_dir = str(self.service.root_dir)
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

    def open_disk_site(self, disk_id: str):
        url = DISK_AUTH_URLS[disk_id]
        webbrowser.open(url, new=2)
        print(f"Открыт сайт: {DISK_TITLES[disk_id]} -> {url}")

    def add_yandex_flow(self):
        cfg = load_config()
        oauth_cfg = cfg.setdefault("oauth", {}).setdefault("yandex", {})
        client_id = (
            oauth_cfg.get("client_id")
            or os.environ.get("DISCOHACK_YANDEX_CLIENT_ID")
            or os.environ.get("YANDEX_CLIENT_ID")
        )
        redirect_uri = oauth_cfg.get("redirect_uri") or (
            "http://127.0.0.1:8085/callback"
        )
        oauth_cfg["redirect_uri"] = redirect_uri
        save_config(cfg)
        if not client_id:
            self._log("Yandex OAuth client_id missing.")
            self._log(
                "Set oauth.yandex.client_id in ~/.config/discohack/config.json "
                "or env DISCOHACK_YANDEX_CLIENT_ID.",
            )
            self.show_notification(
                "DiscoHack",
                (
                    "Не настроен Yandex client_id. "
                    "Заполни oauth.yandex.client_id в config.json "
                    "или DISCOHACK_YANDEX_CLIENT_ID."
                ),
            )
            return
        oauth_cfg["client_id"] = client_id
        save_config(cfg)

        # Запускаем OAuth (PKCE) с локальным callback.
        try:
            auth_url, _redirect_uri, verifier, result = yandex_start_oauth(
                client_id=client_id,
                scope="cloud_api:disk.read cloud_api:disk.write cloud_api:disk.info",
                redirect_uri=redirect_uri,
            )
        except OSError as exc:
            self._log(
                f"OAuth callback server error: {exc!r} "
                f"redirect_uri={redirect_uri}",
            )
            self.show_notification(
                "DiscoHack",
                f"OAuth callback не запустился (порт занят?): {redirect_uri}",
            )
            return
        webbrowser.open(auth_url, new=2)

        # Ждём callback (до 3 минут). В идеале это вынести в thread,
        # но для прототипа оставляем простое ожидание.
        ok = result.wait(timeout_s=180.0)
        if not ok or result.error or not result.code:
            QMessageBox.critical(
                None,
                "DiscoHack",
                f"Ошибка авторизации Яндекс: {result.error or 'timeout'}",
            )
            return

        try:
            token_data = yandex_exchange_code_for_token(
                client_id=client_id,
                code=result.code,
                code_verifier=verifier,
            )
        except Exception as exc:
            QMessageBox.critical(
                None,
                "DiscoHack",
                f"Не удалось получить токен: {exc}",
            )
            return

        access_token = token_data.get("access_token")
        if not access_token:
            QMessageBox.critical(
                None,
                "DiscoHack",
                "Не получен access_token от Яндекс OAuth",
            )
            return

        is_connected = self.service.connect_yandex(access_token)
        if not is_connected:
            QMessageBox.critical(
                None,
                "DiscoHack",
                "Не удалось подключить Яндекс.Диск через полученный токен",
            )
            return

        self.show_notification("DiscoHack", "Яндекс.Диск подключен")
        self.open_redisk()
        self.rebuild_menu()

    def connect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]
        if disk_id == "yandex":
            # Яндекс подключаем через add_yandex_flow (OAuth code flow).
            self.add_yandex_flow()
            return
        else:
            url, ok = QInputDialog.getText(
                None,
                "Подключение NextCloud",
                (
                    "URL WebDAV (например "
                    "https://.../remote.php/dav/files/<user>/):"
                ),
            )
            if not ok or not url.strip():
                return
            # Для удобства откроем страницу логина указанного сервера.
            base = url.strip().split("/remote.php", 1)[0].rstrip("/")
            if base.startswith("http"):
                webbrowser.open(f"{base}/login", new=2)
            login, ok = QInputDialog.getText(
                None,
                "Подключение NextCloud",
                "Логин:",
            )
            if not ok or not login.strip():
                return
            password, ok = QInputDialog.getText(
                None,
                "Подключение NextCloud",
                "Пароль / App Password:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not password:
                return
            is_connected = self.service.connect_nextcloud(
                url=url.strip(),
                login=login.strip(),
                password=password,
            )

        if not is_connected:
            QMessageBox.critical(
                None,
                "DiscoHack",
                f"Не удалось подключить {disk_title}. Проверьте данные.",
            )
            return

        self.show_notification("DiscoHack", f"{disk_title} подключен")
        self.open_redisk()
        self.rebuild_menu()

    def disconnect_disk(self, disk_id: str):
        disk_title = DISK_TITLES[disk_id]
        self.service.disconnect_disk(disk_id)
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

    def rebuild_menu(self):
        self.menu.clear()
        try:
            connected_disks = self.service.get_connected_disks()
            if "yandex" in connected_disks:
                self.menu.addAction(self.disconnect_yandex_action)
            if "nextcloud" in connected_disks:
                self.menu.addAction(self.disconnect_nextcloud_action)

            connected = set(connected_disks)
            if "yandex" not in connected:
                self.menu.addAction(self.add_yandex_action)
            if "nextcloud" not in connected:
                self.menu.addAction(self.add_nextcloud_action)
            self.menu.addAction(self.open_action)
            self.menu.addAction(self.notifications_action)
            self.menu.addSeparator()
            quit_action = QAction("Закрыть")
            quit_action.triggered.connect(self.quit_app)
            self.menu.addAction(quit_action)
            self.tray_icon.setContextMenu(self.menu)
        except Exception as exc:
            self._log(f"rebuild_menu error: {exc!r}")
            self.menu.clear()
            self.menu.addAction(self.notifications_action)
            quit_action = QAction("Закрыть")
            quit_action.triggered.connect(self.quit_app)
            self.menu.addAction(quit_action)
            self.tray_icon.setContextMenu(self.menu)

    def quit_app(self):
        print("Программа закрыта")
        self.service.shutdown()
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


def run_tray(service: RediskService):
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    icon_path = create_icon_path()
    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)

    controller = TrayController(app=app, tray_icon=tray_icon, service=service)
    controller.rebuild_menu()

    tray_icon.setContextMenu(controller.menu)
    tray_icon.show()
    controller.show_notification("DiscoHack", "Программа запущена")

    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray(RediskService())
