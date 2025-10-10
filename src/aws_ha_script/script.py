"""script to provide ha for a pair of ngfw instances firewall on aws"""
import argparse
import logging
import sys
from datetime import datetime

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
from aws_ha_script.ngfw_utils import is_primary
from aws_ha_script.smc_events import send_error_to_smc, send_notification_to_smc

__VERSION__ = "1.1.4-rc2"


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

    script_info = f"{ACTUAL_SCRIPT_NAME}, file: {__file__}, version: {__VERSION__}"

    args = parse_args()
    if args.version:
        print(script_info)
        sys.exit(1)

    configure_logging(log_file, args.console, args.debug)
    logger.info(f"Script started: {script_info}")

    die_with_parent()
    write_pid()
    install_signal_handlers()
    configure_ca_cert()

    ec2, config, role, tags = None, None, None, {}

    try:
        ec2 = get_ec2_resource()
        tags = get_config_tags(ec2)
    except Exception as exc:  # noqa: BLE001
        logger.exception("HA not starting. Failed with exception.", exc_info=True)
        send_error_to_smc(config, f"HA not starting. Failed to get aws tags: {exc}")
        disable_service_and_exit(1)

    try:
        config = load_config(tags)
        role = "primary" if is_primary(config) else "secondary"
    except OSError as io_error:
        send_error_to_smc(config, f"HA not starting. Failed to read config: {io_error}")
        disable_service_and_exit(1)
    except HAScriptConfigError as config_error:
        send_error_to_smc(config, f"HA not starting. Invalid config: {config_error}")
        disable_service_and_exit(1)
    except Exception as exc:  # noqa: BLE001
        logger.exception("HA not starting. Failed with exception.", exc_info=True)
        send_error_to_smc(config, f"HA not starting. Script exited: {exc}")
        disable_service_and_exit(1)

    send_notification_to_smc(config, f"Script started: {script_info}, role: {role}")

    if config.dry_run:
        logger.warning("DRY-RUN: No changes will be made to the system.")

    if config.disabled:
        logger.info("Script 'run-at-boot' is disabled. Exiting.")
        disable_service_and_exit(0)

    if config.debug:
        logger.setLevel(logging.DEBUG)

    try:
        mainloop(config, ec2)
    except KeyboardInterrupt:
        logger.warning("Leaving script.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("HA not working. Failed with exception.", exc_info=True)
        send_error_to_smc(config, f"HA not working. Script exited: {exc}")

    cleanup_pid()
    send_notification_to_smc(config, f"Script terminated: {script_info}, role: {role}")


if __name__ == "__main__":
    main()
