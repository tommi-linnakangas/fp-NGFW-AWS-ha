## AWS HA script

This repository provides AWS HA script for Forcepoint SD-WAN solution in AWS.

### User guide

User guide for the script can be found [here](./doc/user_guide.md).

### AWS IAM instance profile

AWS HA script makes various AWS boto3 API calls. In order to avoid hardcoded
credentials, the best practice is to use an AWS instance profile, that is
derived from an AWS IAM role. This IAM role must have the policy attached,
similar to the following:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "",
            "Effect": "Allow",
            "Action": [
                "ec2:ReplaceRoute",
                "ec2:DescribeTags",
                "ec2:DescribeRouteTables",
                "ec2:DescribeNetworkInterfaces",
                "ec2:DescribeInstances",
                "ec2:DescribeInstanceAttribute",
                "ec2:CreateTags"
            ],
            "Resource": "*"
        }
    ]
}
```

### Requirements

#### pyenv

The script is developed for Python 3.7, so you need to have pyenv installed (or any other
tool such as asdf).

Check Python version::

```
$ python --version
Python 3.7.17
```

#### pipenv

Python 3.7 is no longer supported by pipenv, which generates and error when using pipenv.
The temporary solution is to install older version of pipenv:

```
pip3 install pipenv==2023.9.8 --force
```

See: https://github.com/pypa/pipenv/issues/6020

### Source files

The source code is located in src directory.

### Building a deployment file

The problem with custom properties profile is the size limit is 32 KB. In order to counter
that limit, the script is delivered as a self-expanding zipapp file:

 - *zipapp* is used to make a Python executable zip file (sometimes found
   with extension .pyz), which is called installed as run-at-boot file on engine.
 - The script *utils/generate-script-installer.py* takes this appzip file and
   generates a python program *dist/aws_ha_script_installer.py*. It contains the
   zip as a BASE64 string and a function to extract it to the proper place.

This *dist/aws_ha_script_installer.py* needs to be provided to the customer to be
placed in the custom property 'se_script_path'
(see [user guide](./doc/user_guide.md) for details).

*dist/aws_ha_script_installer.py* will also attempt to copy a file
*aws_ha_script_installer.py_allow* to the installation target.

The file *aws_ha_script_installer.py_allow* is generated automatically
by the smc custom properties mechanism: see [here](http://help.stonesoft.com/onlinehelp/StoneGate/SMC/6.10.0/GUID-1FB9FE34-59C9-43D9-859B-C98312C172E6.html?hl=_allow)

### Delivery steps

The following steps must be done when releasing the new version of the script:

1. Change version in `ha-script/src/aws_ha_script/script.py`, e.g.:
   ```
   __VERSION__ = "1.1.4"
   ```
2. Run tests, build documents and deliverables.
   ```
   make all
   ```
3. Create new branch and commit the changes:
   ```
   git checkout wip/new-branch
   git add *
   git commit
   git push
   ```
4. Create pull-request and wait until the pull-request is approved.
5. Go to GitHub page and click *Create new release*.
6. Create new tag, e.g. `v1.1.4`.
7. Type *Release title* and *Description*.
8. Upload the deliveries.
  - `ha-script/dist/aws_ha_script_installer.py`
  - `ha-script/doc/user_guide.pdf`
