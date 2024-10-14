import ctypes
import os
import subprocess
import sys
from contextlib import suppress
from glob import glob
from signal import SIGINT, SIGTERM, signal
from aws_ha_script.log_utils import logger

running = True

ACTUAL_SCRIPT_NAME = "aws_ha_script"


def signal_handler(signal_received, frame):  # noqa: ARG001
    logger.info("Signal received: %d", signal_received)
    global running
    running = False


def disable_service_and_exit(exit_status):
    logger.info("Disabling script 'user_hook' from msvc")
    subprocess.call(["/bin/msvc", "-d", "user_hook"])  # noqa: S603
    sys.exit(exit_status)


def install_signal_handlers():
    signal(SIGINT, signal_handler)
    signal(SIGTERM, signal_handler)


def write_pid():
    pid_file = f"/var/run/{ACTUAL_SCRIPT_NAME}.pid"
    pid = os.getpid()
    with open(pid_file, "w") as fp:  # noqa: PTH123
        fp.write(str(pid))
    logger.info("pid=%d in file %s", pid, pid_file)


def cleanup_pid():
    pid_file = f"/var/run/{ACTUAL_SCRIPT_NAME}.pid"
    with suppress(Exception):
        os.remove(pid_file)  # noqa: PTH107


def die_with_parent():
    """make the script receive a SIGTERM when the parent dies.

    This is needed because apparently 'user_hook' does not terminate the
    run-at-boot script when 'msvc -d' is called
    """
    libc_path = glob("/lib/x86_64-linux-gnu/libc.so.*")  # noqa: PTH207

    if not libc_path or len(libc_path) != 1:
        logger.error("Cannot find libc. msvc -d/-r will not work correctly.")
        return

    libc = ctypes.CDLL(libc_path.pop())
    pr_set_pdeathsig = 1
    libc.prctl(pr_set_pdeathsig, SIGTERM)


def is_running():
    return running
