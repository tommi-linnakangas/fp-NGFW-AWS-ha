import re
import subprocess
from typing import Optional
from aws_ha_script.aws_utils import EC2ResourceType, get_config_tag_value, get_metadata_value
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.exceptions import HAScriptConfigError
from aws_ha_script.log_utils import logger


def is_instance_type(config, instance_id_type: str) -> bool:
    instance_id = get_metadata_value("instance-id")
    if not config.primary_instance_id:
        raise HAScriptConfigError("Missing primary_instance_id")
    if not config.secondary_instance_id:
        raise HAScriptConfigError("Missing secondary_instance_id")
    if instance_id not in [config.primary_instance_id, config.secondary_instance_id]:
        raise HAScriptConfigError(f"Instance id not configured correctly: {instance_id}")
    if instance_id_type == "primary" and instance_id == config.primary_instance_id:
        return True
    if instance_id_type == "secondary" and instance_id == config.secondary_instance_id:
        return True
    return False


def is_primary(config) -> bool:
    """Check if this engine is primary.

    check if this engine is primary by comparing its own instance-id
    with the primary_instance_id defined in config.

    :param config: configuration from the main program
    """
    return is_instance_type(config, "primary")


def is_secondary(config) -> bool:
    """Check if this engine is secondary.

    check if this engine is secondary by comparing its own instance-id
    with the primary_instance_id defined in config.

    :param config: configuration from the main program
    """
    return is_instance_type(config, "secondary")


def set_local_status(config, new_status: str) -> bool:
    """Change the node status ("offline" or "online")

    :param config: configuration from the main program
    :param new_status: "offline" or "online"
    :return: True if successful, False otherwise.
    :raises: None
    """
    assert new_status == "online" or new_status == "offline"

    if config.dry_run:
        logger.warning("DRY-RUN: Do not change node status to %s.", new_status)
        return True

    try:
        exit_status = subprocess.call(
            ["/usr/sbin/sg-cluster", new_status]  # noqa: S603
        )
        is_success = exit_status == 0
    except OSError:
        logger.exception("Failed to change node status to %s.", new_status, exc_info=True)
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
        logger.exception("Failed to get online/offline status.", exc_info=True)
    return status


def get_primary_status(config: HAScriptConfig, ec2: EC2ResourceType) -> str:
    """get status from tag 'FP_HA_status' of primary instance.

    this is called from secondary because it requires the config
    parameter 'primary_instance_id'. On the primary get_local_status

    :param config: configuration from the main program
    :return: 'online', 'offline' or 'unknown'
    """
    primary_instance_id = config.primary_instance_id
    if primary_instance_id is None:
        raise HAScriptConfigError("Config issue: missing primary_instance_id")
    status = get_config_tag_value(ec2, "status", primary_instance_id)
    return status if status is not None else "unknown"
