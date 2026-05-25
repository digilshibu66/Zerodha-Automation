import logging
import psutil

logger = logging.getLogger(__name__)

try:
    import pygetwindow as gw
    HAVE_PYGW = True
except (ImportError, NotImplementedError):
    HAVE_PYGW = False
    logger.info("pygetwindow not available; window title listing disabled")


def chrome_running():
    for process in psutil.process_iter():
        try:
            if "chrome" in process.name().lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False


def list_chrome_windows():
    if not HAVE_PYGW:
        logger.warning("Cannot list windows: pygetwindow unavailable")
        return []
    titles = gw.getAllTitles()
    return [t for t in titles if "chrome" in t.lower()]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if chrome_running():
        print("Chrome is running")
        windows = list_chrome_windows()
        if windows:
            print("Chrome windows:")
            for w in windows:
                print(f"  - {w}")
    else:
        print("Chrome is not running")