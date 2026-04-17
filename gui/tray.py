import pystray
from PIL import Image, ImageDraw


def create_image():
    width = 64
    height = 64
    
    image = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    
    draw.ellipse((10, 20, 30, 40), fill=(100, 150, 255))
    draw.ellipse((25, 15, 45, 35), fill=(120, 170, 255))
    draw.ellipse((40, 20, 60, 40), fill=(100, 150, 255))
    draw.rectangle((20, 35, 50, 45), fill=(100, 150, 255))
    
    return image


def on_quit(icon, item):
    icon.stop()


def on_open(icon, item):
    print("Открыть папку")


def on_notifications(icon, item):
    print("уведомление")


def run_tray():
    menu = pystray.Menu(
        pystray.MenuItem("Отключить уведомления", on_notifications),
        pystray.MenuItem("Открыть Redisk", on_open),
        pystray.MenuItem("Закрыть", on_quit)
    )
    
    icon = pystray.Icon(
        name="discohack",
        icon=create_image(),
        title="DiscoHack",
        menu=menu
    )
    
    icon.run()


if __name__ == "__main__":
    run_tray()