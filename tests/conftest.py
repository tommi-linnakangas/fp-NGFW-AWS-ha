from collections import namedtuple
from dataclasses import dataclass
from typing import Any, List, Tuple

import boto3
import pytest
from moto import mock_ec2
from mypy_boto3_ec2.client import EC2Client
from mypy_boto3_ec2.service_resource import (
    EC2ServiceResource,
    Instance,
    NetworkInterface,
    RouteTable,
    _RouteTable,
)


@dataclass
class Ec2Conf:
    ec2: EC2ServiceResource
    ec2_client: EC2Client
    instances: List[Instance]
    enis: List[NetworkInterface]
    vpc: Any
    protected_route_table: RouteTable

    @property
    def primary_instance(self) -> Instance:
        return self.instances[0]

    @property
    def primary_instance_id(self) -> str:
        return self.primary_instance.id


@pytest.fixture
def ec2_resource_client() -> Any:
    with mock_ec2():
        ec2_resource: EC2ServiceResource = boto3.resource("ec2", "us-west-1")
        ec2_client: EC2Client = boto3.client("ec2", "us-west-1")
        yield ec2_resource, ec2_client


@pytest.fixture
def ec2conf(ec2_resource_client: Tuple[EC2ServiceResource, EC2Client]):
    """ """
    ec2, ec2_client = ec2_resource_client

    resp = ec2_client.describe_availability_zones()
    zones = resp["AvailabilityZones"]
    assert len(zones) == 2  # us-west-1a and us-west-1b
    zoneId1 = zones[0].get("ZoneId")
    zoneId2 = zones[1].get("ZoneId")

    assert zoneId1
    assert zoneId2
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")

    # these are the subnets containing the ngfws (one per az)
    primary_subnet11 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.11.0/24", AvailabilityZoneId=zoneId1
    )
    primary_subnet12 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.12.0/24", AvailabilityZoneId=zoneId1
    )

    primary_subnet21 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.21.0/24", AvailabilityZoneId=zoneId2
    )
    primary_subnet22 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.22.0/24", AvailabilityZoneId=zoneId2
    )

    # these are the customer subnets
    protected_subnet1 = ec2.create_subnet(
        VpcId=vpc.id, CidrBlock="10.0.1.0/24", AvailabilityZoneId=zoneId1
    )
    # protected_subnet2 = ec2.create_subnet(
    #     VpcId=vpc.id, CidrBlock="10.0.2.0/24", AvailabilityZoneId=zoneId2
    # )
    subnets = []

    # each ngfw has 2 interfaces (one to the public and one to the protected)
    eni11 = ec2.create_network_interface(SubnetId=primary_subnet11.id)
    eni12 = ec2.create_network_interface(SubnetId=primary_subnet12.id)
    eni21 = ec2.create_network_interface(SubnetId=primary_subnet21.id)
    eni22 = ec2.create_network_interface(SubnetId=primary_subnet22.id)

    # this extra interface is not connected to any ngf: its purpose is
    # to test that only routes via the ngfw are modified
    eni1 = ec2.create_network_interface(SubnetId=protected_subnet1.id)

    enis = [eni11, eni21, eni1]
    primary_instance = ec2.create_instances(
        ImageId="ami-123456",
        NetworkInterfaces=[
            {"NetworkInterfaceId": eni11.id, "DeviceIndex": 0},
            {"NetworkInterfaceId": eni12.id, "DeviceIndex": 1},
        ],
        MinCount=1,
        MaxCount=1,
    )
    secondary_instance = ec2.create_instances(
        ImageId="ami-12c6146b",
        NetworkInterfaces=[
            {"NetworkInterfaceId": eni21.id, "DeviceIndex": 0},
            {"NetworkInterfaceId": eni22.id, "DeviceIndex": 1},
        ],
        MinCount=1,
        MaxCount=1,
    )

    instances = primary_instance + secondary_instance

    protected_route_table: RouteTable = ec2.create_route_table(VpcId=vpc.id)

    association_id1 = ec2_client.associate_route_table(
        RouteTableId=protected_route_table.id,
        SubnetId=protected_subnet1.id,
    )

    # see https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Route_Tables.html
    # and https://boto3.amazonaws.com/v1/documentation/api/latest/
    #        reference/services/ec2/routetable/create_route.html
    protected_default_route = protected_route_table.create_route(
        DestinationCidrBlock="0.0.0.0/0",
        NetworkInterfaceId=eni11.id,
    )

    another_route = protected_route_table.create_route(
        DestinationCidrBlock="192.168.0.0/24",
        NetworkInterfaceId=eni1.id,
    )
    return Ec2Conf(ec2, ec2_client, instances, enis, vpc, protected_route_table)
