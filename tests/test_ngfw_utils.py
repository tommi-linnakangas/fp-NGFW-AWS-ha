import logging

from mock import Mock, patch

from aws_ha_script.ngfw_utils import get_local_status


def test_get_local_status_failed(caplog):
    """fails because /usr/sbin/sg-cluster does not exist"""
    caplog.set_level(logging.INFO)
    assert not get_local_status()

    logmsgs = [r.message for r in caplog.records]
    assert logmsgs == ["Failed to get online/offline status."]


@patch("aws_ha_script.ngfw_utils.subprocess")
def test_get_local_status_success_online(subprocess, caplog):
    caplog.set_level(logging.INFO)

    process = Mock()
    process.communicate.return_value = [b"Current status: +"]

    subprocess.Popen.return_value = process

    assert get_local_status() == "online"

    logmsgs = [r.message for r in caplog.records]
    assert logmsgs == []


@patch("aws_ha_script.ngfw_utils.subprocess")
def test_get_local_status_success_offile(subprocess, caplog):
    caplog.set_level(logging.INFO)

    process = Mock()
    process.communicate.return_value = [b"Current status: -"]

    subprocess.Popen.return_value = process

    assert get_local_status() == "offline"

    logmsgs = [r.message for r in caplog.records]
    assert logmsgs == []


@patch("aws_ha_script.ngfw_utils.subprocess")
def test_get_local_status_failure_no_match(subprocess, caplog):
    caplog.set_level(logging.INFO)

    process = Mock()
    process.communicate.return_value = [b"some unexpected message"]

    subprocess.Popen.return_value = process

    assert get_local_status() is None

    logmsgs = [r.message for r in caplog.records]
    assert logmsgs == [
        "Failed to parse result from sg-cluster: some unexpected message"
    ]
