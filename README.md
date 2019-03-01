# EC2 VOLUME ENCRYPTION SCRIPT

This python3 code encrypts ec2 volumes instances.

## Requirements

* AWS CLI configured with needed permissions under profile (https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-install.html)
* python 3 installed (https://www.python.org/downloads/)
* boto3 AWS SDK  

if you don't have boto3 installed, use pip:
```bash
pip3 install -r requirements.txt
```

## Use

python3 ec2_encrypt_volumes.py [profile name] [region name] [operation mode]

arguments:
profile name:   the profile name to use. ex: 'default'
region_name:    the region to operate in.  us-east-1/us-east-2/us-west-1/us-west-2
operation mode: all|instance id

### example

```bash
python3 ec2_encrypt_volumes.py my_profile us-east-2 i-01abd353e

python3 ec2_encrypt_volumes.py default us-east-1 all
```
