import sys
import tempfile
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QAction
from PIL import Image, ImageDraw


def create_icon_path():
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 20, 54, 60), fill=(100, 150, 255))
    
    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
    image.save(temp_file.name)
    return temp_file.name


def on_open():
    print("Открыт Redisk")


def on_notifications():
    print("Уведомления отключены")


def on_quit(tray_icon, app):
    print("Программа закрыта")
    tray_icon.hide()
    app.quit()


def run_tray():
    app = QApplication(sys.argv)
    icon_path = create_icon_path()
    tray_icon = QSystemTrayIcon(QIcon(icon_path), parent=app)
    
    menu = QMenu()
    
    open_action = QAction("Открыть Redisk")
    open_action.triggered.connect(on_open)
    menu.addAction(open_action)
    
    notifications_action = QAction("Отключить уведомления")
    notifications_action.triggered.connect(on_notifications)
    menu.addAction(notifications_action)
    
    menu.addSeparator()
    
    quit_action = QAction("Закрыть")
    quit_action.triggered.connect(lambda: on_quit(tray_icon, app))
    menu.addAction(quit_action)

    tray_icon.setContextMenu(menu)
    tray_icon.show()
    
    tray_icon.showMessage("DiscoHack", "Программа запущена")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    run_tray()