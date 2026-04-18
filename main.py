from cloud.api import CloudAPI
from gui.tray import run_tray


def main():
    # Инициализируем API облаков на старте, чтобы сразу проверить конфиг.
    CloudAPI()
    run_tray()


if __name__ == "__main__":
    main()
