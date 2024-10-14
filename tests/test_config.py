import logging

from mock import Mock, patch

from aws_ha_script.config import load_config


def test_load_config_success(caplog):
    caplog.set_level(logging.INFO)

    with patch(
        "aws_ha_script.config._read_custom_properties_file"
    ) as read_custom_properties_file:
        # probe_port and probe_timeout_sec default values are overriden
        read_custom_properties_file.return_value = dict(
            probe_enabled="false",
            probe_port=1234,
            probe_timeout_sec="7",
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

        assert len(caplog.records) == 1

        # in this example route_table_id is not set, validation fails
        # with pytest.raises(HAScriptConfigError) as e_info:
        #     conf_module.config = config
        #     validate_config()
        # assert str(e_info.value) == "Mandatory config entry 'route_table_id' missing"


# todo need failure cases
