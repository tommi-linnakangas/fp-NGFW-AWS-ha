import logging
import sys
from logging.handlers import RotatingFileHandler

logger = logging.getLogger(__name__)

LOGGER_MAX_BYTES = 1000000
LOGGER_MAX_FILES = 5


def configure_logging(log_file_name, console=False, debug=False):
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s", "%Y-%m-%dT%H:%M:%S%z")
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    file_handler = RotatingFileHandler(
        log_file_name, maxBytes=LOGGER_MAX_BYTES, backupCount=LOGGER_MAX_FILES)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
