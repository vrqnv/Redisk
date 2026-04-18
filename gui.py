import sys
import os
import json
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QLabel,
    QDialog,
    QLineEdit,
    QInputDialog,
    QProgressBar,
    QStatusBar,
    QTextEdit,
    QTabWidget,
    QListWidget,
    QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap

from yandex import YandexDisk
from cache import FileCache
from sync import start_sync
from integration import mount_cloud, unmount_cloud, is_cloud_mounted


class DownloadThread(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(bool, str)

    def __init__(self, cloud, remote_path, local_path):
        super().__init__()
        self.cloud = cloud
        self.remote_path = remote_path
        self.local_path = local_path

    def run(self):
        try:

            def progress_callback(downloaded, total):
                self.progress.emit(downloaded, total)

            self.cloud.download_file(
                self.remote_path, self.local_path, progress_callback
            )
            self.finished.emit(True, "Скачивание завершено")
        except Exception as e:
            self.finished.emit(False, str(e))


class CloudFileListWidget(QListWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        paths = []
        for url in event.mimeData().urls():
            if url.isLocalFile():
                paths.append(url.toLocalFile())

        if paths:
            self.owner.upload_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class CloudExplorer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DiscoHack - Яндекс.Диск")
        self.setGeometry(100, 100, 700, 260)

        self.cfg_path = "config.json"
        self.cfg = self.load_config()
        self.cloud = None
        self.cache = FileCache(self.cfg.get("cache_dir", "/var/tmp/discohack_cache"))
        self.sync_worker = None

        self.setup_ui()
        self.setup_statusbar()
        self.setup_tray()
        self.init_cloud_from_config()
        self.update_mount_status()
        self.update_disk_ui()

    def load_config(self):
        if os.path.exists(self.cfg_path):
            with open(self.cfg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "service": "yandex",
            "yandex_token": "",
            "cache_dir": "/var/tmp/discohack_cache",
            "sync_enabled": False,
        }

    def save_config(self):
        with open(self.cfg_path, "w", encoding="utf-8") as f:
            json.dump(self.cfg, f, ensure_ascii=False, indent=4)

    def setup_ui(self):
        cloud_widget = self.create_cloud_tab()
        self.setCentralWidget(cloud_widget)

    def create_cloud_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.disk_status_label = QLabel("Диск не добавлен. Нажмите «Добавить диск».")
        self.mount_status = QLabel("Статус монтирования: неизвестно")
        self.mount_path_label = QLabel("Смонтированная папка: не определена")

        buttons_row = QHBoxLayout()
        btn_add_disk = QPushButton("Добавить диск")
        btn_add_disk.clicked.connect(self.add_disk_flow)
        btn_open_mounted = QPushButton("Открыть смонтированную папку")
        btn_open_mounted.clicked.connect(self.open_mounted_folder)
        btn_mount = QPushButton("Смонтировать")
        btn_mount.clicked.connect(self.mount_disk)
        btn_unmount = QPushButton("Размонтировать")
        btn_unmount.clicked.connect(self.unmount_disk)
        buttons_row.addWidget(btn_add_disk)
        buttons_row.addWidget(btn_open_mounted)
        buttons_row.addWidget(btn_mount)
        buttons_row.addWidget(btn_unmount)

        hint = QLabel(
            "Рабочий сценарий: Добавить диск -> Смонтировать -> Открыть смонтированную папку.\n"
            "После этого перенос файлов с диска на локальный ПК выполняется обычным drag-and-drop в файловом менеджере GNOME."
        )

        layout.addWidget(self.disk_status_label)
        layout.addWidget(self.mount_status)
        layout.addWidget(self.mount_path_label)
        layout.addLayout(buttons_row)
        layout.addWidget(hint)
        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def setup_statusbar(self):
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.statusbar.addPermanentWidget(self.progress_bar)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("folder-remote"))

        tray_menu = QMenu()
        show_action = QAction("Показать окно", self)
        show_action.triggered.connect(self.showNormal)

        hide_action = QAction("Скрыть окно", self)
        hide_action.triggered.connect(self.hide)

        add_disk_action = QAction("Добавить диск (авторизация)", self)
        add_disk_action.triggered.connect(self.add_disk_flow)

        mount_action = QAction("Добавить диск (mount)", self)
        mount_action.triggered.connect(self.mount_disk)

        unmount_action = QAction("Удалить диск (unmount)", self)
        unmount_action.triggered.connect(self.unmount_disk)

        open_mounted_action = QAction("Открыть смонтированную папку", self)
        open_mounted_action.triggered.connect(self.open_mounted_folder)

        quit_action = QAction("Выйти", self)
        quit_action.triggered.connect(self.quit_app)

        tray_menu.addAction(show_action)
        tray_menu.addAction(hide_action)
        tray_menu.addSeparator()
        tray_menu.addAction(add_disk_action)
        tray_menu.addAction(mount_action)
        tray_menu.addAction(unmount_action)
        tray_menu.addAction(open_mounted_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        self.tray_icon.showMessage(
            "DiscoHack",
            "Приложение запущено в tray. Нажмите по иконке для открытия.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.isVisible():
                self.hide()
            else:
                self.showNormal()
                self.activateWindow()

    def closeEvent(self, event):
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "DiscoHack",
            "Окно скрыто в tray. Для выхода используйте меню иконки.",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )

    def init_cloud_from_config(self):
        token = self.cfg.get("yandex_token", "").strip()
        if token and token != "ВАШ_ТОКЕН_ЯНДЕКСА":
            self.cloud = YandexDisk(token)
            self.disk_status_label.setText(
                "Диск добавлен. Можно монтировать и открывать папку."
            )
        else:
            self.cloud = None
            self.disk_status_label.setText("Диск не добавлен. Нажмите «Добавить диск».")

    def build_oauth_url(self):
        client_id = self.cfg.get("yandex_client_id", "").strip()
        if not client_id:
            client_id, ok = QInputDialog.getText(
                self,
                "Yandex OAuth Client ID",
                "Введите OAuth Client ID приложения:",
                QLineEdit.EchoMode.Normal,
            )
            if not ok or not client_id.strip():
                return None
            self.cfg["yandex_client_id"] = client_id.strip()
            self.save_config()

        params = {
            "response_type": "token",
            "client_id": self.cfg["yandex_client_id"],
            "force_confirm": "yes",
        }
        return "https://oauth.yandex.ru/authorize?" + urlencode(params)

    def parse_token_from_input(self, input_text):
        text = input_text.strip()
        if not text:
            return ""
        if "access_token=" in text:
            parsed = urlparse(text)
            fragment = parse_qs(parsed.fragment)
            query = parse_qs(parsed.query)
            token = (fragment.get("access_token") or query.get("access_token") or [""])[
                0
            ]
            return token.strip()
        return text

    def add_disk_flow(self):
        oauth_url = self.build_oauth_url()
        if not oauth_url:
            QMessageBox.warning(self, "Авторизация", "Не указан OAuth Client ID.")
            return

        webbrowser.open(oauth_url)
        input_text, ok = QInputDialog.getText(
            self,
            "Авторизация Яндекс.Диска",
            "После входа в Яндекс ID вставьте URL из браузера\nили сам access_token:",
            QLineEdit.EchoMode.Normal,
        )
        if not ok:
            return

        token = self.parse_token_from_input(input_text)
        if not token:
            QMessageBox.warning(self, "Авторизация", "Не удалось извлечь access_token.")
            return

        test_cloud = YandexDisk(token)
        try:
            test_cloud.list_files("/")
        except Exception as exc:
            QMessageBox.critical(
                self, "Авторизация", f"Токен не прошел проверку: {exc}"
            )
            return

        self.cfg["yandex_token"] = token
        self.save_config()
        self.cloud = test_cloud
        self.disk_status_label.setText("Диск добавлен и авторизован.")
        self.statusbar.showMessage("Авторизация успешна", 3000)

    def update_disk_ui(self):
        self.update_mount_status()
        mount_path = self.get_mounted_path()
        if mount_path:
            self.mount_path_label.setText(f"Смонтированная папка: {mount_path}")
        else:
            self.mount_path_label.setText("Смонтированная папка: не определена")

    def get_mounted_path(self):
        uid = str(os.getuid()) if hasattr(os, "getuid") else ""
        base_dir = f"/run/user/{uid}/gvfs" if uid else "/run/user"
        try:
            if not os.path.isdir(base_dir):
                return None
            for name in os.listdir(base_dir):
                lower_name = name.lower()
                if "webdav" in lower_name and "yandex" in lower_name:
                    return os.path.join(base_dir, name)
        except Exception:
            return None
        return None

    def open_mounted_folder(self):
        mount_path = self.get_mounted_path()
        if not mount_path:
            QMessageBox.information(
                self,
                "Смонтированная папка",
                "Папка не найдена. Сначала выполните «Смонтировать».",
            )
            return
        url = f"file://{mount_path}"
        ok, _ = mount_cloud("yandex") if not is_cloud_mounted("yandex") else (True, "")
        if not ok:
            QMessageBox.warning(self, "Открытие папки", "Не удалось подтвердить mount.")
            return
        try:
            webbrowser.open(url)
            self.statusbar.showMessage(
                "Открыта смонтированная папка в файловом менеджере", 4000
            )
        except Exception as exc:
            QMessageBox.warning(
                self, "Открытие папки", f"Не удалось открыть папку: {exc}"
            )

    def show_file_context_menu(self, pos):
        menu = QMenu(self)
        actions = [
            ("Обновить", self.load_cloud_files),
            ("Назад", self.go_back),
            ("Загрузить файл", self.upload_file),
            ("Скачать", self.download_selected),
            ("Удалить", self.delete_selected),
            ("Предпросмотр", self.preview_selected),
            ("Создать ссылку", self.share_selected),
            ("Переместить", self.move_selected),
        ]
        for title, callback in actions:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.exec(self.file_list.mapToGlobal(pos))

    def load_cloud_files(self):
        try:
            self.statusbar.showMessage(f"Загрузка {self.current_path}...")
            items = self.cloud.list_files(self.current_path)
            self.file_list.clear()

            folders = [item for item in items if item.get("type") == "dir"]
            files = [item for item in items if item.get("type") == "file"]

            for item in folders + files:
                name = item.get("name", "unknown")
                item_type = item.get("type", "file")
                size = item.get("size", 0)

                if item_type == "dir":
                    display_text = f"📁 {name}/"
                else:
                    if size < 1024:
                        size_str = f"{size} B"
                    elif size < 1024 * 1024:
                        size_str = f"{size/1024:.1f} KB"
                    else:
                        size_str = f"{size/(1024*1024):.1f} MB"
                    display_text = f"📄 {name} ({size_str})"

                self.file_list.addItem(display_text)

            self.path_label.setText(f"Текущий путь: {self.current_path}")
            self.statusbar.showMessage(f"Загружено {len(items)} элементов", 3000)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить файлы: {e}")
            self.statusbar.showMessage(f"Ошибка: {e}", 5000)

    def on_item_double_click(self, item):
        text = item.text()
        if text.startswith("📁 "):
            name = text[2:-1]
            next_path = self.current_path.rstrip("/") + "/" + name
            self.navigate_to(next_path, remember_current=True)
        elif text.startswith("📄 "):
            self.download_selected()

    def navigate_to(self, new_path, remember_current=True):
        if not new_path.startswith("/"):
            new_path = "/" + new_path
        if remember_current and self.current_path != new_path:
            self.path_history.append(self.current_path)
        self.current_path = new_path
        self.load_cloud_files()

    def go_back(self):
        if not self.path_history:
            self.statusbar.showMessage("Нет предыдущей папки", 2000)
            return
        self.current_path = self.path_history.pop()
        self.load_cloud_files()

    def go_to_path(self):
        path = self.path_input.text().strip()
        if path:
            self.navigate_to(path, remember_current=True)
            self.path_input.clear()

    def get_selected_name(self):
        current = self.file_list.currentItem()
        if not current:
            return None
        text = current.text()
        if text.startswith("📁 "):
            return text[2:-1]
        elif text.startswith("📄 "):
            name_with_size = text[2:]
            last_paren = name_with_size.rfind("(")
            if last_paren > 0:
                return name_with_size[:last_paren].strip()
            return name_with_size
        return text

    def remote_path_for_name(self, name):
        return self.current_path.rstrip("/") + "/" + name

    def download_selected(self, local_path=None):
        name = self.get_selected_name()
        if not name:
            QMessageBox.warning(self, "Внимание", "Выберите файл")
            return

        remote_path = self.remote_path_for_name(name)
        if local_path is None:
            local_path, _ = QFileDialog.getSaveFileName(self, "Сохранить как", name)

        if local_path:
            self.thread = DownloadThread(self.cloud, remote_path, local_path)
            self.thread.progress.connect(self.update_progress)
            self.thread.finished.connect(self.download_finished)
            self.thread.start()
            self.progress_bar.setVisible(True)

    def upload_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выберите файл")
        if file_path:
            self.upload_paths([file_path], ask_confirmation=True)

    def upload_paths(self, paths, ask_confirmation=False):
        if not paths:
            return
        all_files = []
        for path in paths:
            if os.path.isfile(path):
                all_files.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for filename in files:
                        all_files.append(os.path.join(root, filename))

        if not all_files:
            return

        if ask_confirmation:
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                f"Загрузить {len(all_files)} файл(ов)\nв {self.current_path}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )

            if reply != QMessageBox.StandardButton.Yes:
                return

        for file_path in all_files:
            try:
                filename = os.path.basename(file_path)
                remote_path = self.current_path.rstrip("/") + "/" + filename
                self.cloud.upload_file(file_path, remote_path)
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Не удалось загрузить {file_path}: {e}"
                )
                break

        self.load_cloud_files()

    def delete_selected(self):
        name = self.get_selected_name()
        if not name:
            QMessageBox.warning(self, "Внимание", "Выберите элемент")
            return

        remote_path = self.remote_path_for_name(name)
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить {name}?\nЭто действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                self.cloud.delete(remote_path)
                self.load_cloud_files()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def preview_selected(self):
        name = self.get_selected_name()
        if not name:
            QMessageBox.warning(self, "Внимание", "Выберите файл")
            return

        ext = os.path.splitext(name)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]:
            QMessageBox.warning(self, "Предупреждение", "Это не изображение")
            return

        remote_path = self.remote_path_for_name(name)
        try:
            preview_url = self.cloud.get_preview(remote_path, "300x300")
            import requests

            resp = requests.get(preview_url)
            if resp.status_code == 200:
                preview_dialog = QDialog(self)
                preview_dialog.setWindowTitle(f"Предпросмотр: {name}")
                layout = QVBoxLayout()
                pixmap = QPixmap()
                pixmap.loadFromData(resp.content)
                label = QLabel()
                label.setPixmap(
                    pixmap.scaled(400, 400, Qt.AspectRatioMode.KeepAspectRatio)
                )
                layout.addWidget(label)
                preview_dialog.setLayout(layout)
                preview_dialog.exec()
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось загрузить превью")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def share_selected(self):
        name = self.get_selected_name()
        if not name:
            QMessageBox.warning(self, "Внимание", "Выберите элемент")
            return

        remote_path = self.remote_path_for_name(name)
        try:
            link = self.cloud.publish(remote_path)
            self.links_text.append(f"{name}: {link}")
            QMessageBox.information(
                self, "Ссылка создана", f"Публичная ссылка:\n{link}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def move_selected(self):
        name = self.get_selected_name()
        if not name:
            QMessageBox.warning(self, "Внимание", "Выберите элемент")
            return

        from_path = self.remote_path_for_name(name)
        to_path, ok = QInputDialog.getText(
            self, "Переместить", f"Переместить {name}\nНовый путь в облаке:"
        )
        if ok and to_path:
            if not to_path.startswith("/"):
                to_path = "/" + to_path
            try:
                self.cloud.move(from_path, to_path)
                self.load_cloud_files()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))

    def configure_token(self):
        token, ok = QInputDialog.getText(
            self,
            "Обновить токен",
            "Введите OAuth токен Яндекс.Диска:",
            QLineEdit.EchoMode.Normal,
            self.cfg.get("yandex_token", ""),
        )
        if ok and token.strip():
            self.cfg["yandex_token"] = token.strip()
            self.save_config()
            self.cloud = YandexDisk(self.cfg["yandex_token"])
            QMessageBox.information(self, "Готово", "Токен обновлен.")

    def update_mount_status(self):
        mounted = is_cloud_mounted("yandex")
        if hasattr(self, "mount_status"):
            self.mount_status.setText(
                "Статус монтирования: смонтирован"
                if mounted
                else "Статус монтирования: не смонтирован"
            )

    def mount_disk(self):
        if not self.cloud:
            QMessageBox.information(
                self, "Монтирование", "Сначала выполните «Добавить диск» и авторизацию."
            )
            return
        ok, message = mount_cloud("yandex")
        if ok:
            self.statusbar.showMessage(message, 4000)
            self.tray_icon.showMessage(
                "DiscoHack", message, QSystemTrayIcon.MessageIcon.Information, 2500
            )
        else:
            QMessageBox.warning(self, "Монтирование", message)
        self.update_disk_ui()

    def unmount_disk(self):
        ok, message = unmount_cloud("yandex")
        if ok:
            self.statusbar.showMessage(message, 4000)
        else:
            QMessageBox.warning(self, "Размонтирование", message)
        self.update_disk_ui()

    def start_sync_folder(self):
        local_dir = self.sync_local_path.text().strip()
        remote_dir = self.sync_remote_path.text().strip()

        if not local_dir or not remote_dir:
            QMessageBox.warning(self, "Ошибка", "Укажите локальную и облачную папки")
            return

        if not os.path.exists(local_dir):
            try:
                os.makedirs(local_dir)
            except Exception as e:
                QMessageBox.critical(
                    self, "Ошибка", f"Не могу создать локальную папку: {e}"
                )
                return

        try:
            self.stop_sync()
            self.sync_worker = start_sync(
                self.cloud, local_dir, remote_dir, poll_interval=20
            )
            self.sync_status.setText(
                f"Синхронизация запущена: {local_dir} ↔ {remote_dir}"
            )
            self.statusbar.showMessage("Двусторонняя синхронизация запущена", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def stop_sync(self):
        if self.sync_worker:
            self.sync_worker.stop()
            self.sync_worker = None
            self.sync_status.setText("Синхронизация остановлена")

    def load_links(self):
        self.links_text.append("--- Ссылки хранятся в истории ---")

    def update_progress(self, downloaded, total):
        if total > 0:
            percent = int(downloaded / total * 100)
            self.progress_bar.setValue(percent)
            self.statusbar.showMessage(f"Скачивание: {percent}%")

    def download_finished(self, success, message):
        self.progress_bar.setVisible(False)
        if success:
            self.statusbar.showMessage(message, 3000)
        else:
            QMessageBox.critical(self, "Ошибка", message)

    def quit_app(self):
        if self.sync_worker:
            self.sync_worker.stop()
        self.tray_icon.hide()
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = CloudExplorer()
    window.hide()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
