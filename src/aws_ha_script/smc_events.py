import subprocess

from aws_ha_script.config import HAScriptConfig
from aws_ha_script.log_utils import logger


class SMCEventFacility:
    USER_DEFINED = 16


class SMCEventType:
    EMERGENCY = 1
    SYSTEM_ALERT = 2
    CRITICAL_ERROR = 3
    ERROR = 4
    WARNING = 5
    NOTIFICATION = 6
    INFORMATIONAL = 7


class SMCEventNumber:
    UNDEFINED = 0
    INTERNAL_ERROR = 1
    NOTICE = 500


#   0 - Undefined
#   1 - Internal error
#   6 - Invalid argument
#   8 - Network is unreachable
#   9 - No route to host
#   10 - Connection refused
#   100 - I/O error
#   308 - Failed to set configuration
#   500 - Notice


def send_event_to_smc(config: HAScriptConfig, message: str,
                      event_type: int = SMCEventType.NOTIFICATION, facility: int = -1,
                      event_number: int = SMCEventNumber.NOTICE,
                      alert: bool = False):
    """Send an event to the SMC.

    :param config: the configuration from the main program
    :param message: the message associated with the event
    :param event_type: the type of the event
    :param facility: the facility associated with the event
    :param event_number: the event number
    :param alert: indicates whether the event is an alert
    """
    log_facility = config.log_facility if config.log_facility is not None else -1
    if facility < 0:
        facility = SMCEventFacility.USER_DEFINED if log_facility < 0 else log_facility

    cmd_args = [
        "/usr/sbin/sg-logger", "-f", str(facility), "-t", str(event_type),
        "-i", message.encode("utf8"), "-e", str(event_number)
    ]

    if alert:
        cmd_args.append("-a")

    try:
        exit_status = subprocess.call(cmd_args)  # noqa: S603
        if exit_status != 0:
            logger.error("Failed to send event: exit status=%d", exit_status)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send event.")


def send_notification_to_smc(config, message, alert: bool = False):
    logger.info(message)
    send_event_to_smc(config, "AWS-HA: " + message, alert=alert)


def send_error_to_smc(config, message):
    logger.error(message)
    send_event_to_smc(config, "AWS-HA: " + message, SMCEventType.CRITICAL_ERROR, alert=True)
