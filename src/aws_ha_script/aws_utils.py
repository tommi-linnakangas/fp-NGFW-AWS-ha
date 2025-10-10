import functools
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import boto3
import requests
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError as BotoClientError
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.exceptions import HAScriptError
from aws_ha_script.log_utils import logger
from aws_ha_script.smc_events import send_error_to_smc

EC2_METADATA_URL_BASE = "http://169.254.169.254/latest"


# aliases for typing
EC2ResourceType = Any


def configure_ca_cert():
    """Set environment variable REQUESTS_CA_BUNDLE needed by 'requests' library.

    see https://docs.python-requests.org/en/latest/user/advanced/#ssl-cert-verification
    """
    openssl_ca_cert_file = "/data/config/policy/latest/inspection/ca-bundle.pem"
    if not os.path.exists(openssl_ca_cert_file):  # noqa: PTH110
        openssl_ca_cert_file = "/data/config/tls/ca-bundle.pem"
        assert os.path.exists(openssl_ca_cert_file)  # noqa: PTH110
    logger.info("PEM bundle found: %s", openssl_ca_cert_file)
    os.environ["REQUESTS_CA_BUNDLE"] = openssl_ca_cert_file


def get_ec2_resource() -> EC2ResourceType:
    region = get_aws_region_name()
    if not region:
        logger.critical("Failed to get AWS region metadata.")
        sys.exit(1)
    ec2 = boto3.resource("ec2", region_name=region, api_version="2016-09-15")
    return ec2


@functools.lru_cache(maxsize=1)
def aws_auth_token(cache_key):  # noqa: ARG001
    resp = requests.put(
        EC2_METADATA_URL_BASE + "/api/token",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "3600"},
        timeout=10)
    resp.raise_for_status()
    return resp.text


def aws_headers():
    return {
        # New authentication token on every hour
        "X-aws-ec2-metadata-token": aws_auth_token(time.monotonic() / 3600),
    }


def get_metadata(url: str) -> str:
    return requests.get(url, headers=aws_headers(), timeout=10).text


def get_metadata_value(key: str) -> str:
    return get_metadata(f"{EC2_METADATA_URL_BASE}/meta-data/{key}")


def get_instance_id() -> str:
    return get_metadata_value("instance-id")


def get_aws_region_name() -> Optional[str]:
    dyn_doc_url = f"{EC2_METADATA_URL_BASE}/dynamic/instance-identity/document"
    text_result = get_metadata(dyn_doc_url)
    json_result = json.loads(text_result) if text_result else None
    region = json_result.get("region") if json_result else None
    logger.debug("AWS region: %s", region)
    return region


def get_config_tags(ec2: EC2ResourceType, instance_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a dictionary of config properties from EC2 instance tags.

    Configuration properties are taken from the tags of the given ec2 instance
    (by default, local instance). Only tags starting with 'FP_HA_' are considered.

    For example, if tag "FP_HA_route_table_id" has value "rtb-0f713d2bd5363d74f",
    the dictionary will contain the following value:

    {"route_table_id": "rtb-0f713d2bd5363d74f"}

    :param ec2: boto3 EC2 resource
    :param instance_id: EC2 instance id
    :return: dictionary of config properties
    """
    if not instance_id:
        instance_id = get_metadata_value("instance-id")
    instance = ec2.Instance(instance_id)
    filtered_tags = {}
    for tag in instance.tags:
        if tag["Key"].startswith("FP_HA_"):
            key = tag["Key"].replace("FP_HA_", "")
            filtered_tags[key] = tag["Value"]
    return filtered_tags


def get_config_tag_value(ec2: EC2ResourceType, tag: str,
                         instance_id: Optional[str] = None) -> Optional[str]:
    """Get value of a config property from EC2 instance tags.

    :param ec2: boto3 EC2 resource
    :param tag: config property name
    :param instance_id: EC2 instance id
    :return: config property value or None, if property is not found
    """
    tags = get_config_tags(ec2, instance_id)
    if tag in tags:
        return tags[tag]
    logger.debug("EC2 instance tag not found, instance_id: %s, tag: %s", instance_id, tag)
    return None


def set_config_tag(config: HAScriptConfig, ec2: EC2ResourceType, tag: str, value: str,
                   instance_id: Optional[str] = None) -> bool:
    """Add a tag to the EC2 instance.

    :param config: configuration from the main program
    :param ec2: boto3 EC2 resource
    :param tag: tag name
    :param value: value to set
    :param instance_id: EC2 instance id
    :return: True if the tag was added, False otherwise

    The `tag` parameter will be prefixed with when set to the instance `FP_HA_`.
    """
    if config.dry_run:
        logger.warning("DRY-RUN: Do not modify instance tag, key: FP_HA_%s, value: %s", tag, value)
        return True

    try:
        if not instance_id:
            instance_id = get_metadata_value("instance-id")
        ec2.create_tags(Resources=[instance_id], Tags=[{"Key": f"FP_HA_{tag}", "Value": value}])
        return True
    except (BotoClientError, BotoCoreError) as boto_error:
        send_error_to_smc(config, f"Failed to set AWS EC2 tag: {boto_error}")
        return False


def get_eni(ec2: EC2ResourceType, device_index: int,
            instance_id: Optional[str] = None) -> Tuple[str, str]:
    """Get the Elastic Network Interface (ENI) of the given EC2 instance.

    :param ec2: boto3 EC2 resource
    :param device_index: index of the device in EC2 instance
    :param instance_id: EC2 instance id
    :return: tuple of Elastic Network Interface (ENI) of the given EC2 instance and IP address
    :raises HAScriptError: if the EC2 instance does not have an Elastic Network Interface
     with the given device index
    """
    if not instance_id:
        instance_id = get_metadata_value("instance-id")
    instance = ec2.Instance(instance_id)

    for interface in instance.network_interfaces_attribute:
        attachment = interface.get("Attachment")
        status = attachment.get("Status")
        attachment_device_index = int(attachment.get("DeviceIndex"))
        logger.debug("instance_id: %s, status: %s, device_index: %d, attachment_device_index: %d",
                     instance_id, status, device_index, attachment_device_index)
        if attachment and status == "attached" and attachment_device_index == device_index:
            eni_id = interface["NetworkInterfaceId"]
            eni_ip_address = interface["PrivateIpAddress"]
            logger.info("eni_id: %s, eni_ip_address: %s", eni_id, eni_ip_address)
            return eni_id, eni_ip_address
    raise HAScriptError(f"Failed to get local ENI, device_index: {device_index}")


@dataclass
class RouteInfo:
    # AWS route state (e.g. "active" or "blackhole").
    route_state: str

    # AWS route destination cidr (e.g. "0.0.0.0/0").
    route_dest: str

    # AWS EC2 elastic network interface (an instance of ec2.NetworkInterface)
    # (see https://boto3.amazonaws.com/v1/documentation/api/latest/reference
    #     /services/ec2/networkinterface/index.html).
    eni: Any

    # AWS route table ID.
    route_table_id: str


def get_route_table_info(ec2: EC2ResourceType, route_table_ids: str,
                         ngfw_instance_ids: List[str]) -> Any:
    """Iterates over all routes via NGFWs from the specified route tables.

    :param ec2: boto3 EC2 resource
    :param route_table_ids: comma-separated list of route table ids
    :param ngfw_instance_ids: comma-separated list of NGFW instance ids
    """
    for route_table_id in route_table_ids.split(","):
        route_table = ec2.RouteTable(route_table_id)
        route_table.reload()
        for route in route_table.routes_attribute:
            # route not going to an eni, skipping
            if "NetworkInterfaceId" not in route:
                continue
            current_eni = ec2.NetworkInterface(route["NetworkInterfaceId"])

            # eni not attached to an ec2 instance, skipping
            if not current_eni.attachment:
                continue

            # eni not attached to an ngfw. skipping
            instance_id = current_eni.attachment.get("InstanceId")
            if not instance_id or instance_id not in ngfw_instance_ids:
                continue

            yield RouteInfo(
                route["State"],
                route["DestinationCidrBlock"],
                current_eni,
                route_table_id,
            )


def update_route_table(config: HAScriptConfig, ec2: EC2ResourceType, route_table_id: str,
                       dest: str, eni_id: str) -> bool:
    """Update the aws route table.

    Update the route table to use the given Elastic Network Interface
    (ENI) for the specified destination.

    :param config: configuration from the main program
    :param ec2: boto3 EC2 resource
    :param route_table_id: route table id
    :param dest: destination for the route, e.g. "0.0.0.0/0"
    :param eni_id: ENI id to be associated with the route
    :return: True if the update is successful, False otherwise.
    """
    if config.dry_run:
        logger.warning("DRY-RUN: Do not modify route, dest: %s, eni_id: %s", dest, eni_id)
        return True

    try:
        route_obj = ec2.Route(route_table_id, dest)
        logger.info("Modifying route, dest: %s, eni_id: %s", dest, eni_id)
        route_obj.replace(DestinationCidrBlock=dest, NetworkInterfaceId=eni_id)
        logger.info("Modifying route done.")
        return True
    except (BotoClientError, BotoCoreError) as boto_error:
        send_error_to_smc(config, f"Failed to update route: {boto_error}")
        return False


def get_instance_ip_addresses(ec2: EC2ResourceType, instance_id: str) -> List[str]:
    """Get IP addresses from the given EC2 instance.

    :param ec2: boto3 EC2 resource
    :param instance_id: EC2 instance id
    """
    instance = ec2.Instance(instance_id)
    # instance.reload()
    ip_list = [eni.private_ip_address for eni in instance.network_interfaces]
    return ip_list
