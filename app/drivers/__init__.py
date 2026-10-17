from app.config import DRIVER
from app.drivers.mock_driver import MockDriver
from app.drivers.playwright_driver import PlaywrightDriver

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        if DRIVER == "mock":
            _driver = MockDriver()
        else:
            _driver = PlaywrightDriver()
    return _driver


__all__ = ["get_driver", "MockDriver", "PlaywrightDriver"]
