from botocore.exceptions import ClientError as BotoClientError
from conftest import Ec2Conf
from mock import MagicMock, patch

from aws_ha_script.config import HAScriptConfig

from aws_ha_script.aws_utils import (
    RouteInfo,
    get_config_tag_value,
    get_config_tags,
    get_eni,
    get_instance_ip_addresses,
    get_route_table_info,
    set_config_tag,
    update_route_table,
)


def test_set_config_tag_success() -> None:
    with patch("aws_ha_script.aws_utils.get_metadata_value") as get_metadata_value:
        config = HAScriptConfig(
            route_table_id="rtb-0869eb690cef8c3a6",
            primary_instance_id="i-1234",
            secondary_instance_id="i-2345"
        )
        ec2 = MagicMock()
        instance_id = MagicMock()
        get_metadata_value.return_value = instance_id

        assert set_config_tag(config, ec2, "status", "online")
        assert len(ec2.mock_calls) == 1
        ec2.create_tags.assert_called_once_with(
            Resources=[instance_id], Tags=[{"Value": "online", "Key": "FP_HA_status"}]
        )


def test_set_config_tag_fails(caplog) -> None:
    with patch("aws_ha_script.aws_utils.get_metadata_value") as get_metadata_value:
        config = HAScriptConfig(
            route_table_id="rtb-0869eb690cef8c3a6",
            primary_instance_id="i-1234",
            secondary_instance_id="i-2345"
        )
        ec2 = MagicMock()
        instance_id = MagicMock()
        get_metadata_value.return_value = instance_id
        ec2.create_tags.side_effect = BotoClientError(MagicMock(), "create_tags")
        assert not set_config_tag(config, ec2, "status", "online")
        assert len(ec2.mock_calls) == 1
        ec2.create_tags.assert_called_once_with(
            Resources=[instance_id], Tags=[{"Value": "online", "Key": "FP_HA_status"}]
        )

        assert len(caplog.records) == 2
        assert caplog.records[0].message.startswith("Failed to set AWS EC2 tag")


def test_get_config_tags_success(ec2conf: Ec2Conf) -> None:
    ec2 = ec2conf.ec2
    instance = ec2conf.instances[0]

    config = HAScriptConfig(
        route_table_id=ec2conf.protected_route_table.id,
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    assert instance.id
    set_config_tag(config, ec2, "tag1", "value1", instance_id=instance.id)

    ec2conf.ec2.create_tags(
        Resources=[instance.id],
        Tags=[
            {"Key": "FP_HA_tag2", "Value": "value2"},
            {"Key": "not_a_config_tag", "Value": "value3"},
        ],
    )

    assert get_config_tags(ec2, instance.id) == {"tag1": "value1", "tag2": "value2"}
    assert get_config_tag_value(ec2, "tag2", instance.id) == "value2"


def test_get_eni_success(ec2conf: Ec2Conf) -> None:
    ec2 = ec2conf.ec2
    instance = ec2conf.instances[1]

    eni_id, ip = get_eni(ec2, device_index=0, instance_id=instance.id)
    assert ip.startswith("10.0.")
    assert eni_id == ec2conf.enis[1].id


def test_get_route_table_info_success(ec2conf: Ec2Conf) -> None:
    """get route info. Only routes using ngfw instances are considered"""
    ec2 = ec2conf.ec2
    primary_eni = ec2conf.enis[0]
    other_eni = ec2conf.enis[2]
    protected_route_table = ec2conf.protected_route_table

    route_table_info = list(
        get_route_table_info(
            ec2,
            protected_route_table.id,
            [
                ec2conf.instances[0].id,
                ec2conf.instances[1].id,
            ],
        )
    )
    assert len(route_table_info) == 1
    assert route_table_info[0] == RouteInfo(
        "active",
        "0.0.0.0/0",
        primary_eni,
        ec2conf.protected_route_table.id,
    )


def test_update_route_table_info_success(ec2conf: Ec2Conf) -> None:
    """test route table for the given dest updated and the other route is untouched"""
    ec2 = ec2conf.ec2
    secondary_eni = ec2conf.enis[1]
    other_eni = ec2conf.enis[2]

    config = HAScriptConfig(
        route_table_id=ec2conf.protected_route_table.id,
        primary_instance_id="i-1234",
        secondary_instance_id="i-2345"
    )

    assert update_route_table(
        config, ec2, ec2conf.protected_route_table.id, "0.0.0.0/0", secondary_eni.id
    )

    protected_route_table = ec2conf.protected_route_table
    route_table_info = list(
        get_route_table_info(
            ec2,
            protected_route_table.id,
            [
                ec2conf.instances[0].id,
                ec2conf.instances[1].id,
            ],
        )
    )
    assert len(route_table_info) == 1
    assert route_table_info[0] == RouteInfo(
        "active",
        "0.0.0.0/0",
        secondary_eni,
        ec2conf.protected_route_table.id,
    )

    # note: there are 3 routes:
    # - local: 10.0.0.0/16
    # - default: 0.0.0.0/0
    # - 192.168.0.0/24
    # make sure the 3rd route has not been changed
    assert len(ec2conf.protected_route_table.routes) == 3
    assert (
        ec2conf.protected_route_table.routes[2].network_interface_id
        == ec2conf.enis[2].id
    )


def test_get_instance_ip_addresses_success(ec2conf: Ec2Conf) -> None:
    ec2 = ec2conf.ec2
    ip_list = get_instance_ip_addresses(ec2, ec2conf.primary_instance_id)
    assert len(ip_list) == 2
    assert ip_list[0].startswith("10.0.11.")
    assert ip_list[1].startswith("10.0.12.")
