import signal
import sys

from core.redisk_service import RediskService
from gui.tray import run_tray


def main():
    service = RediskService()

    def _handle_signal(signum, frame):
        service.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    run_tray(service)


if __name__ == "__main__":
    main()
