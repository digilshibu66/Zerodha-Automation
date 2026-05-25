import logging
import sys

logger = logging.getLogger(__name__)

try:
    import pygetwindow as gw
    HAVE_PYGW = True
except (ImportError, NotImplementedError):
    HAVE_PYGW = False
    if sys.platform == "linux":
        logger.info("pygetwindow not available on Linux; Zerodha window check disabled")


def check_zerodha_open():
    if not HAVE_PYGW:
        logger.warning("Cannot check Zerodha window: pygetwindow unavailable")
        return False
    titles = gw.getAllTitles()
    for title in titles:
        lower = title.lower()
        if "kite" in lower or "zerodha" in lower:
            logger.info("Zerodha/Kite window detected: %s", title)
            return True
    logger.warning("No Zerodha/Kite window found")
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if check_zerodha_open():
        print("Zerodha/Kite window is open")
    else:
        print("No Zerodha/Kite window detected")
