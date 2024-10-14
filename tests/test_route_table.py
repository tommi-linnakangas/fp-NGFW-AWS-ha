from botocore.exceptions import ClientError as BotoClientError
from mock import MagicMock, patch

from aws_ha_script.aws_utils import set_config_tag


def test_set_config_tag_success():
    with patch("aws_ha_script.aws_utils.get_metadata_value") as get_metadata_value:
        ec2 = MagicMock()
        instance_id = MagicMock()
        get_metadata_value.return_value = instance_id

        assert set_config_tag(ec2, "status", "online")
        assert len(ec2.mock_calls) == 1
        ec2.create_tags.assert_called_once_with(
            Resources=[instance_id], Tags=[{"Value": "online", "Key": "FP_HA_status"}]
        )


def test_set_config_tag_fails(caplog):
    with patch("aws_ha_script.aws_utils.get_metadata_value") as get_metadata_value:
        ec2 = MagicMock()
        instance_id = MagicMock()
        get_metadata_value.return_value = instance_id
        ec2.create_tags.side_effect = BotoClientError(MagicMock(), "create_tags")
        assert not set_config_tag(ec2, "status", "online")
        assert len(ec2.mock_calls) == 1
        ec2.create_tags.assert_called_once_with(
            Resources=[instance_id], Tags=[{"Value": "online", "Key": "FP_HA_status"}]
        )

        assert len(caplog.records) == 1
        assert caplog.records[0].message == "set_config_tag failed."
