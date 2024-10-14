import re
import subprocess
import sys
from typing import Optional
from aws_ha_script.aws_utils import EC2ResourceType, get_config_tag_value, get_metadata_value
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.log_utils import logger
from aws_ha_script.smc_events import send_error_to_smc


def is_primary(config) -> bool:
    """Check if this engine is primary.

    check if this engine is primary by comparing its own instance-id
    with the primary_instance_id defined in config.
    """
    instance_id = get_metadata_value("instance-id")
    primary_instance_id = config.primary_instance_id
    if not primary_instance_id:
        logger.critical("Config error: missing primary_instance_id")
        sys.exit(1)
    return primary_instance_id == instance_id


def is_secondary(config) -> bool:
    """Check if this engine is secondary.

    check if this engine is secondary by comparing its own instance-id
    with the primary_instance_id defined in config.
    """
    return not is_primary(config)


def set_local_status(new_status: str) -> bool:
    """Change the node status ("offline" or "online")

    :param new_status: "offline" or "online"
    :return: True if successful, False otherwise.
    :raises: None
    """
    assert new_status == "online" or new_status == "offline"

    try:
        exit_status = subprocess.call(
            ["/usr/sbin/sg-cluster", new_status]  # noqa: S603
        )
        is_success = exit_status == 0
    except OSError:
        logger.exception("Failed to change node status to %s", new_status)
        is_success = False

    return is_success


def get_local_status() -> Optional[str]:
    """Return local status.

    Possible values are 'online', 'offline' and None on failure
    """
    status = None
    try:
        process = subprocess.Popen(
            ["/usr/sbin/sg-cluster", "status"], stdout=subprocess.PIPE  # noqa: S603
        )
        output = process.communicate()[0].decode("utf8")
        pattern = re.compile(r"Current status: (.)", re.DOTALL)
        match_obj = pattern.search(output)
        if match_obj:
            status = "online" if match_obj.group(1) == "+" else "offline"
        else:
            logger.error("Failed to parse result from sg-cluster: %s", output)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to get online/offline status.")
    return status


def get_primary_status(config: HAScriptConfig, ec2: EC2ResourceType) -> str:
    """get status from tag 'FP_HA_status' of primary instance.

    this is called from secondary because it requires the config
    parameter 'primary_instance_id'. On the primary get_local_status

    return 'online', 'offline' or 'unknown'
    """
    primary_instance_id = config.primary_instance_id
    if primary_instance_id is None:
        send_error_to_smc(config, "HA not working. Config issue: " + "missing primary_instance_id")
        sys.exit(1)
    status = get_config_tag_value(ec2, "status", primary_instance_id)
    return status if status is not None else "unknown"
