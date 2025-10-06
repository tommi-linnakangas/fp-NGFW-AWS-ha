import logging

import pytest
from conftest import Ec2Conf
from mock import MagicMock, Mock, patch
from mypy_boto3_ec2.type_defs import RouteTypeDef

from aws_ha_script.aws_utils import RouteInfo, update_route_table
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.context import HAScriptContext
from aws_ha_script.mainloop import primary_main_loop_handler


@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.update_route_table")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
@patch("aws_ha_script.mainloop.get_route_table_info")
def test_online(
    get_route_table_info,
    get_local_status,
    get_primary_status,
    tcp_probe,
    update_route_table,
    send_notification_to_smc,
    set_config_tag,
    caplog,
):
    """basic case: primary was active/online and still is"""
    caplog.set_level(logging.INFO)

    primary_ip = "10.0.1.37"
    config = HAScriptConfig(
        route_table_id="rtb-0869eb690cef8c3a6",
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )
    ctx = HAScriptContext(
        prev_local_status="online", prev_local_active=True, display_info_needed=True
    )

    ec2 = MagicMock()
    eni = MagicMock(private_ip_address=primary_ip)

    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", eni, "rtb-0869eb690cef8c3a6")
    ]
    get_local_status.return_value = "online"

    primary_main_loop_handler(config, ec2, "eni-0007a7ea295a24c9b", primary_ip, ctx)

    logmsgs = [r.message for r in caplog.records]
    assert logmsgs == [
        "route_table_id: rtb-0869eb690cef8c3a6, route_dest: 0.0.0.0/0, "
        "route_state: active, private_ip_address: 10.0.1.37, local_ip: 10.0.1.37, "
        "primary_status: online, primary: active",
    ]

    # make sure no rerouting takes place
    assert len(send_notification_to_smc.mock_calls) == 0
    assert len(update_route_table.mock_calls) == 0
    assert len(set_config_tag.mock_calls) == 0

    assert ctx.prev_local_status == "online"
    assert ctx.prev_local_active
    assert not ctx.display_info_needed


@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.update_route_table")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
@patch("aws_ha_script.mainloop.get_route_table_info")
def test_offline_to_online_success(
    get_route_table_info,
    get_local_status,
    get_primary_status,
    tcp_probe,
    update_route_table,
    send_notification_to_smc,
    set_config_tag,
    caplog,
):
    """primary was offline, becomes online. Needs to change the
    routing table to get the traffic again"""

    caplog.set_level(logging.INFO)
    ec2 = MagicMock()

    # since we were offline, the secondary (10.0.1.38) has the traffic
    active_eni = MagicMock(private_ip_address="10.0.1.38")
    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", active_eni, "rtb-0869eb690cef8c3a6")
    ]
    get_local_status.return_value = "online"

    config = HAScriptConfig(
        route_table_id="rtb-0869eb690cef8c3a6",
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    ctx = HAScriptContext(
        prev_local_status="offline",
        prev_local_active=False,
        display_info_needed=False,
    )

    primary_eni_id = "eni-0007a7ea295a24c9b"
    primary_ip = "10.0.1.37"

    # --- ACTUAL TEST ---
    primary_main_loop_handler(config, ec2, primary_eni_id, primary_ip, ctx)

    # logmsgs = [r.message for r in caplog.records]

    # make sure the standby is notified via tag change
    set_config_tag.assert_called_once_with(config, ec2, "status", "online")

    update_route_table.assert_called_once_with(
        config, ec2, "rtb-0869eb690cef8c3a6", "0.0.0.0/0", primary_eni_id
    )

    # make sure the smc is notified
    send_notification_to_smc.assert_called_once_with(
        config,
        "Route table 'rtb-0869eb690cef8c3a6' changed route to '0.0.0.0/0' "
        "via primary '10.0.1.37'.",
        alert=True)

    assert ctx.prev_local_status == "online"

    # the prev_local_active is still False: the reason is the
    # route change has been requested, but we have not yet checked
    # that it succeeded
    assert not ctx.prev_local_active


@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
def test_offline_to_online_success_moto(
    get_local_status: Mock,
    get_primary_status: Mock,
    tcp_probe: Mock,
    send_notification_to_smc: Mock,
    set_config_tag: Mock,
    ec2conf: Ec2Conf,
    caplog,
):
    """primary was offline, becomes online. Needs to change the
    routing table to get the traffic again. Same test as previous
    using moto"""

    caplog.set_level(logging.INFO)

    ec2 = ec2conf.ec2
    primary_eni_id = ec2conf.enis[0].id
    secondary_eni_id = ec2conf.enis[1].id
    eni3_id = ec2conf.enis[2].id
    primary_ip = ec2conf.enis[0].private_ip_address
    secondary_ip = ec2conf.enis[1].private_ip_address

    config = HAScriptConfig(
        route_table_id=ec2conf.protected_route_table.id,
        primary_instance_id=ec2conf.instances[0].id,
        secondary_instance_id=ec2conf.instances[1].id,
    )

    # the secondary has traffic initially
    update_route_table(
        config, ec2, ec2conf.protected_route_table.id, "0.0.0.0/0", secondary_eni_id
    )

    get_local_status.return_value = "online"

    ctx = HAScriptContext(
        prev_local_status="offline",
        prev_local_active=False,
        display_info_needed=False,
    )

    # --- ACTUAL TEST ---
    primary_main_loop_handler(config, ec2, primary_eni_id, primary_ip, ctx)

    # make sure the standby is notified via tag change
    set_config_tag.assert_called_once_with(config, ec2, "status", "online")

    # make sure route table updated
    ec2conf.protected_route_table.reload()
    default_route: RouteTypeDef = ec2conf.protected_route_table.routes_attribute[1]
    assert default_route.get("NetworkInterfaceId") == primary_eni_id

    # make sure 'other_route' still goes via eni3
    other_route = ec2conf.protected_route_table.routes_attribute[2]
    assert other_route.get("NetworkInterfaceId") == eni3_id

    # make sure the smc is notified
    send_notification_to_smc.assert_called_once_with(
        config,
        f"Route table '{ec2conf.protected_route_table.id}' changed route to '0.0.0.0/0' "
        f"via primary '{primary_ip}'.",
        alert=True)

    assert ctx.prev_local_status == "online"

    # the prev_local_active is still False: the reason is the
    # route change has been requested, but we have not yet checked
    # that it succeeded
    assert not ctx.prev_local_active


@patch("subprocess.call")
@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.update_route_table")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
@patch("aws_ha_script.mainloop.get_route_table_info")
def test_secondary_takeover(
    get_route_table_info,
    get_local_status,
    get_primary_status,
    tcp_probe,
    update_route_table,
    send_notification_to_smc,
    set_config_tag,
    subprocess_call,
    caplog,
):
    """primary was online, detects that secondary has taken over and goes
    offline
    """
    caplog.set_level(logging.INFO)

    subprocess_call.return_value = 0
    primary_eni_id = "eni-0007a7ea295a24c9b"
    primary_ip = "10.0.1.37"

    config = HAScriptConfig(
        route_table_id="rtb-0869eb690cef8c3a6",
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    ctx = HAScriptContext(
        prev_local_status="online", prev_local_active=True, display_info_needed=True
    )

    ec2 = MagicMock()
    # the secondary (10.0.1.38) has the traffic
    eni = MagicMock(private_ip_address="10.0.1.38")

    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", eni, "rtb-0869eb690cef8c3a6")
    ]
    get_local_status.return_value = "online"

    # --- ACTUAL TEST ---
    primary_main_loop_handler(config, ec2, primary_eni_id, primary_ip, ctx)

    subprocess_call.assert_called_once_with(["/usr/sbin/sg-cluster", "offline"])
    assert not ctx.prev_local_active
    assert ctx.prev_local_status == "online"  # will be set offline
    # on next iteration

    # make sure no rerouting takes place
    assert len(update_route_table.mock_calls) == 0

    send_notification_to_smc.assert_called_once_with(
        config,
        "Primary 'i-1234' address '10.0.1.37' is no longer active, "
        "state changed to offline.",
        alert=True)


@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.update_route_table")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
@patch("aws_ha_script.mainloop.get_route_table_info")
def test_online_to_offline_success(
    get_route_table_info,
    get_local_status,
    get_primary_status,
    tcp_probe,
    update_route_table,
    send_notification_to_smc,
    set_config_tag,
    caplog,
):
    """primary was online, becomes offline. Only action is to notify
    standby who will takeover
    """
    caplog.set_level(logging.INFO)

    primary_eni_id = "eni-0007a7ea295a24c9b"
    primary_ip = "10.0.1.37"

    config = HAScriptConfig(
        route_table_id="rtb-0869eb690cef8c3a6",
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    ctx = HAScriptContext(
        prev_local_status="online", prev_local_active=True, display_info_needed=True
    )

    ec2 = MagicMock()
    eni = MagicMock(private_ip_address=primary_ip)

    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", eni, "rtb-0869eb690cef8c3a6")
    ]
    get_local_status.return_value = "offline"

    # --- ACTUAL TEST ---
    primary_main_loop_handler(config, ec2, primary_eni_id, primary_ip, ctx)

    # logmsgs = [r.message for r in caplog.records]

    # make sure the standby is notified via tag change
    set_config_tag.assert_called_once_with(config, ec2, "status", "offline")

    # make sure no rerouting takes place
    assert len(send_notification_to_smc.mock_calls) == 0
    assert len(update_route_table.mock_calls) == 0

    assert ctx.prev_local_status == "offline"
    assert ctx.prev_local_active
    assert not ctx.display_info_needed


@patch("aws_ha_script.mainloop.set_config_tag")
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.update_route_table")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
@patch("aws_ha_script.mainloop.get_route_table_info")
def test_fail_to_change_status(
    get_route_table_info,
    get_local_status,
    get_primary_status,
    tcp_probe,
    update_route_table,
    send_notification_to_smc,
    set_config_tag,
    caplog,
):
    """primary was online, becomes offline. Changing the status tag fails.
    In this case, the prev_local_status is unchanged
    """
    caplog.set_level(logging.INFO)

    config = HAScriptConfig(
        route_table_id="rtb-0869eb690cef8c3a6",
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    primary_eni_id = "eni-0007a7ea295a24c9b"
    primary_ip = "10.0.1.37"

    ctx = HAScriptContext(
        prev_local_status="online", prev_local_active=True, display_info_needed=True
    )

    ec2 = MagicMock()
    eni = MagicMock(private_ip_address=primary_ip)

    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", eni, "rtb-0869eb690cef8c3a6")
    ]
    get_local_status.return_value = "offline"
    set_config_tag.return_value = False

    # --- ACTUAL TEST ---
    primary_main_loop_handler(config, ec2, primary_eni_id, primary_ip, ctx)

    # logmsgs = [r.message for r in caplog.records]

    # make sure the standby is notified via tag change
    set_config_tag.assert_called_once_with(config, ec2, "status", "offline")
    # this is the important part: prev status remains "online" so
    # that the
    assert ctx.prev_local_status == "online"
