import logging

import pytest
from conftest import Ec2Conf
from mock import MagicMock, Mock, patch
from mypy_boto3_ec2.service_resource import Route
from mypy_boto3_ec2.type_defs import RouteTypeDef

from aws_ha_script.aws_utils import RouteInfo
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.context import HAScriptContext
from aws_ha_script.mainloop import secondary_main_loop_handler


@pytest.mark.parametrize(
    "takeover_reason", ["probe_fails", "prim_offline", "route_blackhole"]
)
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
    caplog,
    takeover_reason,
):
    """ """
    ec2 = MagicMock()

    secondary_eni_id = "eni-0007a7ea295a24c9c"
    primary_ip = "10.0.1.37"
    secondary_ip = "10.0.1.38"
    route_table_id = "rtb-0869eb690cef8c3a6"
    caplog.set_level(logging.INFO)

    config = HAScriptConfig(
        route_table_id=route_table_id,
        primary_instance_id='i-1234',
        secondary_instance_id='i-2345',
        probe_port=12345, probe_ip=primary_ip
    )

    # for now the primary (10.0.1.37) has the traffic
    active_eni = MagicMock(private_ip_address=primary_ip)
    get_route_table_info.return_value = [
        RouteInfo("active", "0.0.0.0/0", active_eni, route_table_id)
    ]
    get_local_status.return_value = "online"

    if takeover_reason == "route_blackhole":
        get_route_table_info.return_value = [
            RouteInfo("blackhole", "0.0.0.0/0", active_eni, route_table_id)
        ]

    elif takeover_reason == "prim_offline":
        get_primary_status.return_value = "offline"

    elif takeover_reason == "probe_fails":
        tcp_probe.return_value = False

    ctx = HAScriptContext(
        prev_local_status="online",
        prev_primary_status="online",
        prev_local_active=False,
        display_info_needed=False,
    )

    # --- ACTUAL TEST ---
    secondary_main_loop_handler(config, ec2, secondary_eni_id, secondary_ip, ctx)

    tcp_probe.assert_called_once_with(config, [primary_ip], config.probe_port, ctx)

    update_route_table.assert_called_once_with(
        config, ec2, "rtb-0869eb690cef8c3a6", "0.0.0.0/0", secondary_eni_id
    )

    # make sure the smc is notified
    send_notification_to_smc.assert_called_once_with(
        config,
        "Route table 'rtb-0869eb690cef8c3a6' changed route to '0.0.0.0/0' "
        "via secondary '10.0.1.38'.",
        alert=True)


@pytest.mark.parametrize("takeover_reason", ["probe_fails", "prim_offline"])
@patch("aws_ha_script.mainloop.send_notification_to_smc")
@patch("aws_ha_script.mainloop.tcp_probe")
@patch("aws_ha_script.mainloop.get_primary_status")
@patch("aws_ha_script.mainloop.get_local_status")
def test_secondary_takeover_moto(
    get_local_status,
    get_primary_status,
    tcp_probe,
    send_notification_to_smc: Mock,
    ec2conf: Ec2Conf,
    caplog,
    takeover_reason,
):
    """same test using moto. Verifies that only routes via ngfw are modified"""
    caplog.set_level(logging.INFO)

    primary_eni_id = ec2conf.enis[0].id
    secondary_eni_id = ec2conf.enis[1].id
    eni3_id = ec2conf.enis[2].id
    secondary_ip = ec2conf.enis[1].private_ip_address

    config = HAScriptConfig(
        route_table_id=ec2conf.protected_route_table.id,
        primary_instance_id=ec2conf.instances[0].id,
        secondary_instance_id=ec2conf.instances[1].id,
        probe_port=12345,
    )

    # make sure default route goes initially via the primary
    ec2conf.protected_route_table.reload()
    default_route = ec2conf.protected_route_table.routes_attribute[1]
    assert default_route.get("NetworkInterfaceId") == primary_eni_id

    # make sure 'other_route' goes via eni3
    other_route = ec2conf.protected_route_table.routes_attribute[2]
    assert other_route.get("NetworkInterfaceId") == eni3_id

    get_local_status.return_value = "online"
    tcp_probe.return_value = True

    if takeover_reason == "prim_offline":
        get_primary_status.return_value = "offline"
    elif takeover_reason == "probe_fails":
        tcp_probe.return_value = False

    ctx = HAScriptContext(
        prev_local_status="online",
        prev_primary_status="online",
        prev_local_active=False,
        display_info_needed=False,
    )

    # --- ACTUAL TEST ---
    secondary_main_loop_handler(config, ec2conf.ec2, secondary_eni_id, secondary_ip, ctx)

    # make sure the default route now points to eni of secondary
    ec2conf.protected_route_table.reload()
    default_route: RouteTypeDef = ec2conf.protected_route_table.routes_attribute[1]
    assert default_route.get("NetworkInterfaceId") == secondary_eni_id

    # make sure 'other_route' still goes via eni3
    other_route = ec2conf.protected_route_table.routes_attribute[2]
    assert other_route.get("NetworkInterfaceId") == eni3_id

    # make sure the smc is notified
    send_notification_to_smc.assert_called_once_with(
        config,
        f"Route table '{ec2conf.protected_route_table.id}' changed route to '0.0.0.0/0' "
        f"via secondary '{secondary_ip}'.",
        alert=True)
