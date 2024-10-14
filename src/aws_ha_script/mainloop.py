import sys
import time
from typing import List
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError as BotoClientError
from aws_ha_script.aws_utils import (
    EC2ResourceType,
    get_eni,
    get_instance_ip_addresses,
    get_route_table_info,
    set_config_tag,
    update_route_table,
)
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.context import HAScriptContext
from aws_ha_script.daemon import is_running
from aws_ha_script.exceptions import HAScriptError
from aws_ha_script.log_utils import logger
from aws_ha_script.ngfw_utils import (
    get_local_status,
    get_primary_status,
    is_primary,
    set_local_status,
)
from aws_ha_script.smc_events import send_notification_to_smc
from aws_ha_script.tcp_probing import tcp_probe


def get_primary_probe_ip_addresses(config: HAScriptConfig, ec2: EC2ResourceType) -> List[str]:
    """Get the IP addresses for probing the primary engine.

    The IP addresses are taken either from the user config or by taking the first ip address
    of each ENI attached to the primary engine.

    :param config: HAScriptConfig object
    :param ec2: boto3 EC2 resource
    :return: list of IP addresses for probing the primary engine
    """
    ip_addresses = (
        config.probe_ip.split(",")
        if config.probe_ip else get_instance_ip_addresses(ec2, config.primary_instance_id)
    )
    return ip_addresses


def primary_check_remote_hosts(config: HAScriptConfig, ctx: HAScriptContext) -> bool:
    """Probe remote hosts to make sure VPN tunnel is still up.

    :param config: HAScriptConfig object
    :param ctx: HAScriptContext object
    :return: True if primary engine was able to connect to at least one remote host
             or the probing is disabled.
    """
    if not config.remote_probe_enabled:
        return True

    ip_addresses = config.remote_probe_ip.split(",")
    if tcp_probe(config, ip_addresses, config.remote_probe_port, ctx):
        return True

    return False


def primary_main_loop_handler(config: HAScriptConfig, ec2: EC2ResourceType,
                              local_eni_id: str, local_ip: str, ctx: HAScriptContext):
    """Mainloop for the primary engine.

    Logic:
    - Notifies the secondary engine when the primary goes offline or online (via AWS EC2 tags).
    - Goes offline if all the remote IP addresses are unreachable.
    - Always tries to re-route traffic to itself, if it is online.

    :param config: HAScriptConfig object
    :param ec2: boto3 EC2 resource
    :param local_eni_id: id of the Elastic Network Interface that permits
     reaching the internal network(s), needed to update the route table.
    :param local_ip: private IP address corresponding to the local ENI, needed to know
     if the engine is active.
    :param ctx: HAScriptContext object
     Track changes since the last iteration:
       - prev_local_status: Last known admin status ("online"/"offline").
       - prev_local_active: Boolean. True if this engine was active at the previous iteration.
     Global access to config:
       - route_table_id
     Deprecated:
       - primary_engine_name, secondary_engine_name
    """
    local_status = get_local_status()
    if not local_status:
        logger.error("Failed to get local status. HA script is not working properly.")
        return

    if ctx.prev_local_status != local_status:
        logger.info("Notify secondary engine about status change: %s -> %s",
                    ctx.prev_local_status, local_status)
        # We change the previous status only in case of success, so that if we fail to set
        # the tag, it has a chance to succeed on the next iteration.
        if set_config_tag(ec2, "status", local_status):
            ctx.prev_local_status = local_status
            ctx.display_info_needed = True

    if local_status == "online" and not primary_check_remote_hosts(config, ctx):
        # We failed to reach all the configured remote IP addressed several times
        # (see config.probe_max_fail). We set the primary offline so that the secondary takes
        # over.
        local_status = "offline"
        set_local_status(local_status)
        send_notification_to_smc(
            config,
            f"Primary '{config.primary_instance_id}' changed to offline because "
            f"remote probe failed to reach hosts '{config.remote_probe_ip}'.",
            alert=True)
        ctx.display_info_needed = True
        return

    # Iterate only over routes that use NGFW.
    ngfw_instance_ids = [config.primary_instance_id, config.secondary_instance_id]

    for route_info in get_route_table_info(ec2, config.route_table_id, ngfw_instance_ids):
        local_is_active = route_info.eni.private_ip_address == local_ip

        if local_is_active != ctx.prev_local_active:
            if local_status == "online" and not local_is_active:
                # Change detected: primary was active, (i.e. processing traffic) and secondary
                # took over. This happens for instance because the TCP probe from the secondary
                # failed too many times.
                #
                # We turn the primary engine offline so that:
                # - The VPN tunnel is closed and VPN traffic goes to secondary
                #   (for engine version >= 6.10).
                # - The primary engine does not attempt to get back the traffic on next tick
                #   (ping-pong effect).
                #
                # Setting the node online requires human intervention
                # (from the smc or using "sg-cluster" command).
                local_status = "offline"
                set_local_status(local_status)
                send_notification_to_smc(
                    config,
                    f"Primary '{config.primary_instance_id}' address '{local_ip}' "
                    f"is no longer active, state changed to offline.",
                    alert=True)
            ctx.prev_local_active = local_is_active
            ctx.display_info_needed = True

        need_reroute = local_status == "online" and not local_is_active

        logger.debug(
            "Primary mainloop, route_table_id: %s, route_dest: %s, local_status: %s, "
            "local_is_active: %s, route_state: %s",
            route_info.route_table_id, route_info.route_dest, local_status, local_is_active,
            route_info.route_state)

        if ctx.display_info_needed or need_reroute:
            logger.info("route_table_id: %s, route_dest: %s, route_state: %s, "
                        "private_ip_address: %s, local_ip: %s, primary_status: %s, primary: %s",
                        route_info.route_table_id, route_info.route_dest, route_info.route_state,
                        route_info.eni.private_ip_address, local_ip, local_status,
                        "active" if local_is_active else "not active")
            ctx.display_info_needed = False

        if not need_reroute:
            continue

        ctx.display_info_needed = True

        if update_route_table(config, ec2, route_info.route_table_id, route_info.route_dest,
                              local_eni_id):
            send_notification_to_smc(
                config,
                f"Route table '{route_info.route_table_id}' changed route to "
                f"'{route_info.route_dest}' via primary '{local_ip}'.",
                alert=True)


def secondary_main_loop_handler(config: HAScriptConfig, ec2: EC2ResourceType,
                                local_eni_id: str, local_ip: str, ctx: HAScriptContext):
    """Monitors the primary engine.

    Logic:
     - Checks the primary admin status (online/offline) shared via EC2 tags.
     - Checks health via periodic attempts to connect to the SSH port of the primary.
     - Checks routing status reported by AWS.

    It will re-route traffic from protected network to itself, if the primary is
    unreachable or offline. This involves changing the AWS route table to itself.

    :param config: HAScriptConfig object
    :param ec2: boto3 EC2 resource
    :param local_eni_id: id of the Elastic Network Interface that permits
     reaching the internal network(s), needed to update the route table.
    :param local_ip: private IP address corresponding to the local ENI, needed to know
     if the engine is active.
    :param ctx: HAScriptContext object
    """
    local_status = get_local_status()
    if not local_status:
        logger.error("Failed to get local status. HA script not working properly.")
        return

    if ctx.prev_local_status != local_status:
        ctx.prev_local_status = local_status
        ctx.display_info_needed = True

    primary_status = get_primary_status(config, ec2)
    # Fails to get primary status? No action needed:
    # - "primary_status" value is "unknown" (logged if value has changed).
    # - We can continue to check at least for health of the primary.

    if ctx.prev_primary_status != primary_status:
        ctx.prev_primary_status = primary_status
        ctx.display_info_needed = True

    # "tcp_probe_fails" will be set to True if the SSH connection to
    # primary on port 22 fails 10 times in a row.

    # We evaluate this SSH probe to primary only for the first route
    # (assuming all the routes have the same primary).

    # The evaluation is done in the loop because at this point we do
    # not have the address of the primary.
    primary_ip_addresses = get_primary_probe_ip_addresses(config, ec2)

    tcp_probe_fails = config.probe_enabled and not tcp_probe(
        config, primary_ip_addresses, config.probe_port, ctx)

    ngfw_instance_ids = [config.primary_instance_id, config.secondary_instance_id]

    # Iterate only over routes that use NGFW.
    for route_info in get_route_table_info(ec2, config.route_table_id, ngfw_instance_ids):
        # The active engine is the one processing traffic (i.e. the engine that
        # the route table points to).
        local_is_active = route_info.eni.private_ip_address == local_ip

        if ctx.prev_local_active != local_is_active:
            ctx.display_info_needed = True
            ctx.prev_local_active = local_is_active

        need_reroute = (
            local_status == "online"
            and not local_is_active
            and (
                tcp_probe_fails
                or route_info.route_state == "blackhole"
                or primary_status == "offline"
            )
        )

        logger.debug(
            "Secondary mainloop, route_table_id: %s, route_dest: %s, local_status: %s, "
            "local_is_active: %s, tcp_probe_fails: %s, route_state: %s, primary_status: %s",
            route_info.route_table_id, route_info.route_dest, local_status, local_is_active,
            tcp_probe_fails, route_info.route_state, primary_status)

        if ctx.display_info_needed or need_reroute:
            logger.info("route_table_id: %s, route_dest: %s, route_state: %s, "
                        "private_ip_address: %s, local_ip: %s, primary_status: %s, "
                        "secondary_status: %s, secondary: %s",
                        route_info.route_table_id, route_info.route_dest, route_info.route_state,
                        route_info.eni.private_ip_address, local_ip, primary_status, local_status,
                        "active" if local_is_active else "not active")
            ctx.display_info_needed = False

        if not need_reroute:
            continue

        ctx.display_info_needed = True

        if update_route_table(config, ec2, route_info.route_table_id, route_info.route_dest,
                              local_eni_id):
            send_notification_to_smc(
                config,
                f"Route table '{route_info.route_table_id}' changed route to "
                f"'{route_info.route_dest}' via secondary '{local_ip}'.",
                alert=True)


def mainloop(config: HAScriptConfig, ec2: EC2ResourceType):
    """Loop forever

    Expected exceptions (e.g. boto3) are caught and do not exit the mainloop.
    Unexpected exceptions must be handled by the caller.
    """
    main_loop_handler = (
        primary_main_loop_handler if is_primary(config) else secondary_main_loop_handler
    )

    logger.info("Role is '%s'", "primary" if is_primary(config) else "secondary")

    try:
        (local_eni_id, local_ip) = get_eni(ec2, config.internal_nic_idx)
    except HAScriptError as exc:
        logger.critical("%s", exc)
        sys.exit(1)

    ctx = HAScriptContext()

    while is_running():
        try:
            main_loop_handler(config, ec2, local_eni_id, local_ip, ctx)
        except (HAScriptError, BotoClientError, BotoCoreError) as error:
            logger.exception("Unexpected exception, error: %s", error)
        finally:
            time.sleep(config.check_interval_sec)
