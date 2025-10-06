import logging
import pytest

from mock import Mock, patch

from aws_ha_script.config import load_config
from aws_ha_script.exceptions import HAScriptConfigError


def test_load_config_success(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        # probe_port and probe_timeout_sec default values are overriden
        read_custom_properties_file.return_value = dict(
            probe_enabled="false",
            probe_port=1234,
            probe_timeout_sec="7",
            remote_probe_enabled="true",
            remote_probe_ip="1.2.3.4",
            remote_probe_port = 2222,
        )

        # ec2 tags take precedence
        config_tags = dict(
            route_table_id="rtb-1234",
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
        )

        config = load_config(config_tags)

        assert config.probe_max_fail == 10
        assert config.probe_port == 1234
        assert config.probe_timeout_sec == 7
        assert not config.probe_enabled
        assert config.remote_probe_enabled
        assert config.remote_probe_ip == "1.2.3.4"
        assert config.remote_probe_port == 2222

        assert len(caplog.records) == 1


def test_load_config_mandatory_property_missing(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        read_custom_properties_file.return_value = dict(
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
            probe_enabled="true",
            probe_port=1234,
            probe_timeout_sec="7",
        )
        with pytest.raises(HAScriptConfigError) as e_info:
            load_config({})
        assert str(e_info.value) == "Mandatory property is missing: route_table_id"


def test_load_config_mandatory_invalid_route_table_id(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        read_custom_properties_file.return_value = dict(
            route_table_id="1234",
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
            probe_enabled="true",
            probe_port=1234,
            probe_timeout_sec="7",
        )
        with pytest.raises(HAScriptConfigError) as e_info:
            load_config({})
        assert str(e_info.value) == "Value for 'route_table_id' should start with 'rtb-': 1234"


def test_load_config_invalid_probe_ip(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        read_custom_properties_file.return_value = dict(
            route_table_id="rtb-1234",
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
            probe_enabled="true",
            probe_port=1234,
            probe_timeout_sec="7",
            probe_ip="not an ip address",
        )
        with pytest.raises(HAScriptConfigError) as e_info:
            load_config({})
        assert str(e_info.value) == "Value for 'probe_ip' is not an IP address: not an ip address"


def test_load_config_invalid_remote_probe_ip(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        read_custom_properties_file.return_value = dict(
            route_table_id="rtb-1234",
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
            probe_enabled="true",
            probe_port=1234,
            probe_timeout_sec="7",
            remote_probe_ip="not an ip address",
        )
        with pytest.raises(HAScriptConfigError) as e_info:
            load_config({})
        assert str(e_info.value) == ("Value for 'remote_probe_ip' is not an IP address: "
                                     "not an ip address")


def test_load_config_missing_remote_probe_ip(caplog):
    caplog.set_level(logging.INFO)

    with patch("aws_ha_script.config._read_custom_properties_file") as read_custom_properties_file:
        read_custom_properties_file.return_value = dict(
            route_table_id="rtb-1234",
            primary_instance_id="i-1234",
            secondary_instance_id="i-4567",
            internal_nic_idx=1,
            probe_enabled="false",
            probe_port=1234,
            probe_timeout_sec="7",
            remote_probe_enabled="true",
        )
        with pytest.raises(HAScriptConfigError) as e_info:
            load_config({})
        assert str(e_info.value) == "Mandatory property is missing: remote_probe_ip"
