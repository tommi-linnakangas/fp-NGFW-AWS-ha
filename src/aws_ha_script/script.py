"""script to provide ha for a pair of ngfw instances firewall on aws"""
import argparse
import logging
import sys
from datetime import datetime

from botocore.exceptions import ClientError as BotoClientError

from aws_ha_script.aws_utils import configure_ca_cert, get_config_tags, get_ec2_resource
from aws_ha_script.config import load_config
from aws_ha_script.daemon import (
    ACTUAL_SCRIPT_NAME,
    cleanup_pid,
    die_with_parent,
    disable_service_and_exit,
    install_signal_handlers,
    write_pid,
)
from aws_ha_script.exceptions import HAScriptConfigError
from aws_ha_script.log_utils import configure_logging, logger
from aws_ha_script.mainloop import mainloop
from aws_ha_script.smc_events import send_error_to_smc

__VERSION__ = "1.1.3"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments of the script.

    :return: parsed arguments
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawTextHelpFormatter, description="aws ha script"
    )
    parser.add_argument(
        "-v", "--version", action="store_true", help="show script version"
    )
    parser.add_argument(
        "-c",
        "--console",
        action="store_true",
        help="run as normal app instead of daemon",
    )
    parser.add_argument("-d", "--debug", action="store_true", help="debug logs")
    args = parser.parse_args()
    return args


def main() -> None:
    """Entry point of the script."""
    now = datetime.now()
    date_time = now.strftime("%Y%m%d")
    log_file = f"/data/diagnostics/aws-ha-{date_time}.log"

    args = parse_args()
    if args.version:
        print(f"this is {ACTUAL_SCRIPT_NAME} version {__VERSION__}")
        sys.exit(1)

    configure_logging(log_file, args.console, args.debug)
    logger.info(
        "%s started as %s (version %s)", ACTUAL_SCRIPT_NAME, __file__, __VERSION__
    )

    die_with_parent()
    write_pid()
    install_signal_handlers()
    configure_ca_cert()

    ec2 = get_ec2_resource()

    config = None

    try:
        tags = get_config_tags(ec2)
        config = load_config(tags)
    except OSError as io_error:
        send_error_to_smc(config, f"HA not working. failed to read config: {io_error}")
        disable_service_and_exit(1)
    except HAScriptConfigError as exc:
        send_error_to_smc(config, f"HA not working. Invalid config: {exc}")
        disable_service_and_exit(1)
    except BotoClientError as exc:
        send_error_to_smc(config, f"HA not working. Failed to get aws tags: {exc}")
        disable_service_and_exit(1)
    except Exception as exc:  # noqa: BLE001
        logger.error("HA not working. Failed with exception: %s", exc)
        disable_service_and_exit(1)

    if config.disabled:
        logger.info("Script 'run-at-boot' is disabled. Exiting.")
        disable_service_and_exit(0)

    if config.debug:
        logger.setLevel(logging.DEBUG)

    try:
        mainloop(config, ec2)
    except KeyboardInterrupt:
        logger.warning("Leaving script.")
    except Exception:  # noqa: BLE001
        logger.critical("Unknown exception. Exiting", exc_info=True)
        send_error_to_smc(config, "HA not working. Script exited.")

    cleanup_pid()
    logger.info("%s terminated", __file__)


if __name__ == "__main__":
    main()
