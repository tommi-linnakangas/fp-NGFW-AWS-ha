---
title:  AWS HA Script Documentation
geometry:
- margin=1cm
---

## Introduction

The script is used by a pair of Single FlexEdge Secure SD-WAN Engines
(formerly Next Generation Firewall) on Amazon Web Services (AWS) to act a
primary and secondary pair. One of the SD-WAN Engines acts as
the **primary** and always processes the traffic under normal circumstances.
The second Engine acts as the **secondary** and constantly monitors the primary:

- It checks the state of the AWS route table from the internal network to
  the pair of firewalls.
- It periodically tries to open a TCP connection on a well-known port (SSH
  by default) on the NIC referenced by the route table.
- It checks the operational status of the primary (online/offline), which
  the primary stores in an EC2 instance tag value.

When the secondary detects an abnormal situation regarding one of these
criteria, it takes action to become active and receive the traffic:

- It modifies the AWS route table from the internal network(s) to point to
  the secondary

## Operation

The diagram below shows how the HA script operates:

- On the primary NGFW instance, the script monitors a remote host (TCP
  remote probing). If such probing fails, the primary gives control to the
  secondary by going offline and storing its offline state to EC2 instance tag.
- On the secondary NGFW instance, the script monitors the primary instance
  (TCP probing). If such probing fails, the secondary takes over by
  re-routing traffic to itself.

![](./aws_ha_script-operations.png)

## The Script Configuration

This script requires a set of configuration properties, which can be set in
two different ways:

- Specify settings as a **Custom Properties Profile** in the Engine properties
  in the SMC. They will appear in the file <b>{se_script_path}_allow</b> on the
  Engine.
- Specify properties as **AWS EC2 instance tags** of the EC2 instance. The tags
  must have prefix **FP_HA_**, e.g. FP_HA_route_table_id.

The script will merge the two sources of configuration. This allows
specifying attributes where it's convenient for the administrator.

**Note** In case the same key is defined in both sources, the AWS tags source
takes precedence.

### Mandatory Properties

The following configuration properties are mandatory:

| Property              | Example                                                         | Default | Description                                                                                                             |
|-----------------------|-----------------------------------------------------------------|---------|-------------------------------------------------------------------------------------------------------------------------|
| route_table_id        | rtb-xxxxxxxxxxxxxxxx                                            |         | Route table that sends the traffic from subnet(s) to the SD-WAN Engine.                                                 |
| internal_nic_idx      | 0                                                               | 0       | Internal NIC index that receives the traffic from the route table.                                                      |
| primary_instance_id   | i-xxxxxxxxxxxxxxxx                                              |         | Primary instance ID (AWS identifier). **Note** Must be declared on both primary and secondary.                          |
| secondary_instance_id | i-xxxxxxxxxxxxxxxx                                              |         | Secondary instance ID (AWS identifier). **Note** Must be declared on both primary and secondary.                        |
| se_script_path        | /data/config/hooks/policy-applied/99_aws_ha_script_installer.py |         | Path on the engine were the installation script is going to be delivered. **Note** Must be a property declared via SMC. |

### Optional properties

The following configuration properties are optional.

#### Probing from Secondary to Primary

| Property          | Example                 | Default | Description                                                                                                                                                                           |
|-------------------|-------------------------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| probe_enabled     | true                    | true    | Specifies whether TCP probing mechanism is enabled. Possible values are "true" or "false".                                                                                            |
| probe_ip [1]      | 10.101.0.254,10.0.0.254 |         | A comma-separated list of private IP addresses of the Primary Engine used for probing.                                                                                                |
| probe_port        | 2222                    | 22      | The TCP port used by the Secondary to probe the Primary. **Note** TCP connections to this port must be allowed in the policy of the Primary.                                          |
| probe_timeout_sec | 2                       | 2       | Timeout in seconds after an attempt by the Secondary to connect to the Primary is declared as failed.                                                                                 |
| probe_max_fail    | 10                      | 10      | The number of consecutive failed attempts by the Secondary to connect to the Primary before starting the switchover procedure (the time will be probe_max_fail * check_interval_sec). |

[1] Comma-separated list of private IP addresses of the Primary SD-WAN
Engine used for probing. If unspecified, the first IP address of the Primary
ENIs will be used. If none of these addresses respond to the probe, the
Secondary will take over by changing the AWS route table to the local
protected network. The assumption is that if the Primary could not respond
to probe, it is dead (network failure between the Primary and the Secondary
is not considered).

#### Probing from Primary to the Remote Host

| Property             | Example                 | Default | Description                                                                                                                                                                          |
|----------------------|-------------------------|---------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| remote_probe_enabled | true                    | false   | Specifies whether TCP probing mechanism from the Primary to the Remote host(s) is enabled (e.g. to make sure SD-WAN is working properly). Possible values are "true" or "false".     |
| remote_probe_ip [2]  | 10.100.0.10,10.101.0.10 |         | A comma-separated list of private IP addresses of remote host(s).                                                                                                                    |
| remote_probe_port    | 8080                    | 80      | Remote port to probe.                                                                                                                                                                |
| probe_timeout_sec    | 2                       | 2       | Timeout in seconds after an attempt by the Primary to connect Remote hosts is declared as failed.                                                                                    |
| probe_max_fail       | 10                      | 10      | The number of consecutive failed attempts by the Primary to connect to Remote hosts before starting the switchover procedure (the time will be probe_max_fail * check_interval_sec). |

[2] A comma-separated list of Remote hosts (accessible via the SD-WAN)
private IP addresses that the Primary Engine probes periodically to make
sure the SD-WAN tunnel is still up. If none of these addresses responds to
the probe, the Primary will hand off to the Secondary by putting itself
offline. This property is mandatory if **remote_probe_enabled** is set to
**true**.

#### Other Properties

| Property           | Example | Default | Description                                                                                                                                                   |
|--------------------|---------|---------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| log_facility       | -1      | -1      | The facility used by this script to send events to the SMC. Type 'sg-logger -s' to get the list of facilities. **Note** If not set, defaults to USER_DEFINED. |
| check_interval_sec | 1       | 1       | A periodic interval in seconds for both Primary and Secondary to check the status.                                                                            |

## How to Create Configuration in SMC

The sections below show how to create the configuration in SMC.

### Create the Custom Properties Profile Element

The first step is to create the Custom Properties Profile element that will
be used for both Engines:

1. Login to SMC with the Management Client
2. Navigate to **Configuration** > **Engine** > **Other Elements** >
   **Engine Properties** > **Custom Properties Profiles**
3. Click the **New** button > **Custom Properties Profile**
4. Configure the Custom Properties Profile with attributes to have the
   Secondary Engine monitor the Primary Engine, to have the Primary Engine
   monitor the Remote host (optional) and click OK. Here is an example
   configuration (see *The Script Configuration* section for parameter
   descriptions):

![](smc_properties.png)

**Note** If you prefer, you can create a separate Custom Properties Profile for
each Engine.

### Select the Custom Properties Profile in Each Engine Properties

Now that the Custom Properties Profile element has been created, it need to
be added to the Engine properties:

1. In the Management Client, navigate to **Configuration** > **Engine** >
   **Engines**
2. Right-click the Secondary Engine element and open it for editing
3. Navigate to **Advanced Settings** > **Custom Properties Profiles**
4. Click the **Add** button > select the custom properties profile you
   created for the Secondary Engine > **Select**
5. Click the **Save** button to save the changes
6. Add the Custom Properties Profile for the Primary Engine similarly and save the Engine

### Add Access Rules to Allow Probing Connections and Install the Policy

The Engine Access Rules will not allow probing connections by default, so
rules need to be added to allow them. Let's first add rules to the Primary
Engine:

1. In the Management Client, right-click the Primary Engine >
   **Current Policy** > **Edit**
2. Find a suitable location for the rules and right-click the **ID** field of
   the rule below > **Add Rule Before**
3. Configure the rule to allow probing traffic from Secondary Engine to the
   Primary
4. (Optional) If you wish to have the Primary monitor the Remote host status,
   add another rule that allows these connections
5. Click the **Save and Install** button to install the configuration to the
   Primary Engine

![](se-policy.png)

A rule need to added also to the Secondary Engine policy:

1. In the Management Client, right-click the Secondary Engine > **Current
   Policy** > **Edit**
2. Find a suitable location for the rules and right-click the **ID** field of
   the rule below > **Add Rule Before**
3. Configure the rule to allow probing traffic from Secondary Engine to the
   Primary
4. Click the **Save and Install** button to install the configuration to the
   Secondary Engine

## Create the AWS EC2 Instance Tag Configuration

If you wish to use EC2 tags to define custom properties, the configuration
is created in the Amazon Web Services Console. For configuration
instructions, see the [Tagging AWS Resources and Tag Editor User Guide](https://docs.aws.amazon.com/tag-editor/latest/userguide/tagging.html)
and the [Tag your resources](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Using_Tags.html)
section of the [Amazon EC2 User Guide](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/concepts.html).

## Configuration Examples

The sections below show example configuration from SMC and AWS.

### Example of Custom Properties Profile Created in SMC

Here is an example of the **Custom Properties Profile** configuration
created for the secondary Engine to monitor the state of the Primary Engine:

![](smc_properties.png)

### The Primary Engine AWS EC2 Instance Tag Configuration Example

Below is an example of AWS EC2 instance tag configuration created for the
primary SD-WAN Engine instance:

![](aws_properties_1.png)

### The Secondary Engine AWS EC2 Instance Tag Configuration Example

Below is an example of AWS EC2 instance tag configuration created for the 
secondary SD-WAN Engine instance:

![](aws_properties_2.png)

## Make Changes and Recover from the Failover

The sections below show how an administrator can update, disable or
uninstall the script, how to manage the script from the Engine command line,
and how to recover from the failover.

### Update the Script or Change the Configuration

In order to upload a new version of the script or change the configuration
in the SMC:

1. Login to SMC with the Management Client
2. Navigate to **Configuration** > **Engine** > **Engines**
3. Open the Engine element for editing
4. Navigate to **Advanced Settings** > **Custom Properties Profiles**
5. Right-click the custom properties profile element > **Properties**
6. (Optional) Update the script file by clicking **Browse** >
   locate the new script file and select it > **Open**
7. (Optional) Make changes to the attribute configuration as desired
8. Click **OK** to save the changes
9. Click the **Save and Refresh** button to install the updated
   configuration to the Engine

If you are using AWS instance tags, update the script and settings in the
existing tag element settings, and refresh the Engine policy via SMC.

**Note** You must refresh the policy via SMC even if you only changed AWS
instance tags in AWS configuration.

### Disable the Script

To disable the script:

1. Login to SMC with the Management Client
2. Navigate to **Configuration** > **Engine** > **Engines**
3. Open the Engine element for editing
4. Navigate to **Advanced Settings** > **Custom Properties Profiles**
5. Right-click the custom properties profile element > **Properties**
6. Add a custom property **disabled:true** and click **OK** to save the changes
7. Click the **Save and Refresh** button to refresh the Engine configuration

If using AWS instance tags, add an AWS tag **FP_HA_disabled:true** to the
tag configuration, and install the Engine configuration via SMC.

### Uninstall the Script

In order to completely uninstall the script do the following:

1. Login to SMC with the Management Client
2. Navigate to **Configuration** > **Engine** > **Engines**
3. Open the Engine element for editing
4. Navigate to **Advanced Settings** > **Custom Properties Profiles**
5. Right-click the custom properties profile element > **Properties**
6. Add a custom property **uninstall:true** and click **OK** to save the changes
7. Click the **Save and Refresh** button to refresh the Engine configuration

At this point `/data/run-at-boot` and `/data/run-at-boot_allow` files do not
exist any more. After this, open the custom properties profile element for
editing is SMC and click the **Clear** button next to the script, save the
element and refresh the Engine configuration. This will remove the script
from the `/data/config/hooks/policy-applied` directory.

### Manage the Script from the Engine Command Line

The script can be managed also from the Engine command line via a SSH
connection with these commands:

| Operation          | Command             |
|--------------------|---------------------|
| Start the script   | `msvc -u user_hook` |
| Stop the script    | `msvc -d user_hook` |
| Restart the script | `msvc -r user_hook` |

**Note** Stopping the script from the command line does not prevent the
script to be restarted at next reboot. You need to apply the *Uninstall the
Script* procedure described above.

### Recover from the Failover

If the AWS HA script performs a route failover, the Primary Engine goes
offline and the traffic is routed through the Secondary Engine. Once the
issue that caused the failover has been resolved, the system must be put to
HA ready state manually to recover back to the situation where the Primary
Engine is handling traffic. Perform the following steps:

1. Put the Primary Engine online to have the script update AWS route tables
   to point to the Primary Engine again
2. Make sure that VPNs work with both Engines
3. Make sure that remote probe hosts are accessible through VPNs
4. Make sure that the Primary Engine probe from the Secondary Engine is
   accessible

## Troubleshooting

Below you will find instructions how to troubleshoot issues with the HA
script operation.

### Script Installation

The script installation traces are written to the
`/data/diagnostics/aws-ha-install.log` file. View this file content when
experiencing issues with the script installation. The file can be viewed by
connecting to the Engine using SSH or by collecting sginfo from the Engine,
extracting the sginfo tarball and checking the `aws-ha-install.log` file.

### Verify the Script Is Running

To check that the script is running on the Engine, connect to the Engine via
SSH and run the command below:

`pgrep -af run-at-boot`

You should see output similar to this when the script is running:

`19418 /usr/bin/python3.9 /data/run-at-boot`

### Script Logs

The script writes logs to the `/data/diagnostics/aws-ha-<date>.log`file(s).
To view these logs, check them via a SSH connection or by collecting sginfo,
extracting the sginfo archive and checking the log file.

### Check Script Logs in SMC

The script logs are sent also to SMC. These messages can be viewed in the
SMC logs view by filtering logs with **Facility: User Defined** filter and
checking the Information Message field from the entries:

1. Login to SMC with the Management Client
2. Click the **Logs** button
3. On the **Query** pane **Filter** tab, add a new filter for the Facility
   field and select the **User Defined** value
4. Click **Apply** to filter the logs
5. Check the **Information Message** field for script operation messages

![](logs.png)

### Enable the Debug Mode

To get debug level logs for the script operation, the debug mode can be
enabled in the custom property profile settings. This is done by adding a
custom property **debug:True** to the custom properties profile, and installing
the policy.

**Note** The debug mode should be disable after the troubleshooting has been
done to avoid generating unnecessary debug level messages.
