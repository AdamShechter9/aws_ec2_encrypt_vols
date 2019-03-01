# Author Adam Shechter
# adam@at1security.com
# at1security LLC
#
# instance_list:            contains a list of all instances in region
# encryption_list:          contains a list of the unencrypted volume objects
# snapshot_list:            contains a list of all unencrypted snapshot objects
# encrypted_snapshot_list:  contains a list of all encrypted snapshot objects
#
# Tags on Snapshots
# {'Key': 'Name', 'Value': volumename},
# {'Key': 'Device', 'Value': volume['Attachments'][0]['Device']},
# {'Key': 'VolumeId', 'Value': volume['VolumeId']},
# {'Key': 'InstanceName', 'Value': instance_name},
# {'Key': 'InstanceId', 'Value': instance['InstanceId']},
# {'Key': 'createdDate', 'Value': create_fmt},
#
#
# Copyright 2019 At1 LLC
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

import datetime
import time
import os
import sys
import boto3
import json


def get_instances(work_instance_id):
    try:
        if work_instance_id != "all":
            local_response = ec2_client.describe_instances(
                InstanceIds=[work_instance_id]
            )
        else:
            local_response = ec2_client.describe_instances()
    except Exception as e:
        print(e)
        sys.exit(1)
    return local_response['Reservations']


def get_volume(volume_id):
    local_response = None
    try:
        local_response = ec2_client.describe_volumes(
            VolumeIds=[volume_id]
        )
    except Exception as e:
        print(e)
    vol = local_response['Volumes'][0]
    return vol


def create_snapshot(vol, source_instance):
    try:
        instance_name = [tag['Value'] for tag in source_instance['Tags'] if tag['Key'] == 'Name'][0]
    except KeyError:
        instance_name = ""
    create_time = datetime.datetime.now()
    create_fmt = create_time.strftime('%Y-%m-%d %H-%M-%S')
    print("Backing up volume %s of instance id %s %s in %s" % (vol['VolumeId'], source_instance['InstanceId'], instance_name, vol['AvailabilityZone']))
    volume_name = 'Snapshot Unencrypted'
    # Find name tag for volume if it exists
    if 'Tags' in vol:
        for tags in vol['Tags']:
            if tags["Key"] == 'Name':
                volume_name = volume_name + " " + tags["Value"]
    local_response = None
    try:
        local_response = ec2_client.create_snapshot(
            VolumeId=vol['VolumeId'],
            Description='Temporary Snapshot of instance {}'.format(source_instance['InstanceId']),
            TagSpecifications=[
                {
                    'ResourceType': 'snapshot',
                    'Tags': [
                        {'Key': 'Name', 'Value': volume_name},
                        {'Key': 'Device', 'Value': vol['Attachments'][0]['Device']},
                        {'Key': 'VolumeId', 'Value': vol['VolumeId']},
                        {'Key': 'InstanceName', 'Value': instance_name},
                        {'Key': 'InstanceId', 'Value': source_instance['InstanceId']},
                        {'Key': 'createdDate', 'Value': create_fmt},
                    ]
                },
            ],
        )
    except Exception as e:
        print(e)
    return local_response


def copy_snapshot_encrypt(original_snapshot_result):
    local_response = None
    try:
        local_response = ec2_client.copy_snapshot(
            Description='Encrypted Snapshot',
            Encrypted=True,
            # KmsKeyId='string',
            SourceRegion=region_name,
            SourceSnapshotId=original_snapshot_result['SnapshotId'],
        )
    except Exception as e:
        print(e)
    return local_response


def create_encrypted_snapshot_tags(snapshot_id, tags):
    local_response = None
    for tag in tags:
        if tag['Key'] == 'Name':
            tag['Value'] = "Snapshot Encrypted" + tag['Value'][20:]
    try:
        local_response = ec2_client.create_tags(
            Resources=[
                snapshot_id,
            ],
            Tags=tags
        )
    except Exception as e:
        print(e)
    return local_response


def create_new_volume(encrypted_snapshot, old_snapshot, vol):
    try:
        volume_tags = vol['Tags']
    except KeyError:
        volume_tags = [{'Key': 'Name', 'Value': 'Anonymous Volume'}]
    volume_tags.extend([x for x in old_snapshot['Tags'] if x['Key'] == 'Device'])
    volume_tags.extend([x for x in old_snapshot['Tags'] if x['Key'] == 'InstanceId'])
    local_response = None
    try:
        local_response = ec2_client.create_volume(
            AvailabilityZone=vol['AvailabilityZone'],
            SnapshotId=encrypted_snapshot['SnapshotId'],
            VolumeType=vol['VolumeType'],
            Size=vol['Size'],
            TagSpecifications=[
                {
                    'ResourceType': 'volume',
                    'Tags': volume_tags
                },
            ]
        )
    except Exception as e:
        print(e)
    return local_response


def stop_instance(stop_instance_id):
    try:
        response = ec2_client.stop_instances(
            InstanceIds=[
                stop_instance_id,
            ],
            Force=True
        )
    except Exception as e:
        print(e)
        return {"error": {"statusCode": 400, "body": str(e)}}
    return response


def start_instance(start_instance_id):
    local_response = None
    try:
        local_response = ec2_client.start_instances(
            InstanceIds=[
                start_instance_id,
            ],
        )
    except Exception as e:
        print(e)
    return local_response


def detach_volume(detach_vol):
    # instance_id = [x['Value'] for x in volume['Tags'] if x['Key'] == 'InstanceId'][0]
    try:
        response = ec2_client.detach_volume(
            Force=True,
            # InstanceId=instance_id,
            VolumeId=detach_vol['VolumeId'],
        )
    except Exception as e:
        print(e)
        sys.exit(1)
    print("volume detached {}".format(detach_vol['VolumeId']))
    return response


def attach_volume(vol):
    tries = 0
    attach_instance_id = [x['Value'] for x in vol['Tags'] if x['Key'] == 'InstanceId'][0]
    device_name = [x['Value'] for x in vol['Tags'] if x['Key'] == 'Device'][0]
    local_response = None
    while tries < 10:
        try:
            local_response = ec2_client.attach_volume(
                Device=device_name,
                InstanceId=attach_instance_id,
                VolumeId=vol['VolumeId']
            )
            break
        except Exception as e:
            print(e)
            if tries < 9:
                tries += 1
            else:
                print("failed.  action incomplete.")
                return {"error": {"statusCode": 400, "body": str(e)}}
            # sleeps 1 second first try, 2 seconds second try, etc
            time.sleep(tries)

    print("volume {} attached to instance {} as {}".format(vol['VolumeId'], attach_instance_id, device_name))
    return local_response


def delete_volume(vol):
    print("Starting Delete on Volume ID {0}".format(vol['VolumeId']))
    try:
        response = ec2_client.delete_volume(
            VolumeId=vol['VolumeId'],
        )
        print(response)
    except Exception as e:
        print(e)
        print("Failed to delete unencrypted volumes!")
    return


# function takes an instance object,
# iterates through all its attached EBS volumes,
# if volume is not encrypted it adds to encryption list
def collect_instances_volumes(source_instance):
    temp_encryption_list = []
    print()
    print('*' * 100)
    print("\nInstance Id: {}".format(source_instance['InstanceId']))
    for instance_vol in source_instance['BlockDeviceMappings']:
        print('-' * 50)
        print("Volume Id: {}".format(instance_vol['Ebs']['VolumeId']))
        vol = get_volume(instance_vol['Ebs']['VolumeId'])
        print("Encrypted: {}".format(vol['Encrypted']))
        for attachment in vol['Attachments']:
            print("Device Name: {}".format(attachment['Device']))
        if not vol['Encrypted']:
            temp_encryption_list.append(vol)
    return temp_encryption_list


# stops instances with volumes that need encryption
def step1():
    print()
    print('*' * 100)
    print("1. Stopping Instances")
    for vol in vol_encryption_list:
        response = stop_instance(vol['Attachments'][0]['InstanceId'])
        print(response)
    return


# iterates through encryption list,
# waits to see if instance is stopped,
# and creates unencrypted snapshot of volume
def step2():
    print()
    print('*' * 100)
    print("2. Taking Snapshots")
    # snapshot_list contains a list of all unencrypted snapshot objects
    temp_snapshots_list = []
    for vol in vol_encryption_list:
        for work_instance in instance_list:
            if work_instance['InstanceId'] == vol['Attachments'][0]['InstanceId']:
                is_stopped = False
                while not is_stopped:
                    response = get_instances(work_instance['InstanceId'])
                    print('{} is {}'.format(work_instance['InstanceId'], response[0]['Instances'][0]['State']['Name']))
                    if response[0]['Instances'][0]['State']['Name'] != 'stopped':
                        time.sleep(20)
                    else:
                        is_stopped = True
                response = create_snapshot(vol, work_instance)
                temp_snapshots_list.append(response)
                break
    return temp_snapshots_list


# iterates through snapshots list
# waits for unencrypted snapshots to finish
# it then makes an encrypted copy of the snapshot
# adds it to encrypted snapshot list
# returns encrypted snapshot list
def step3():
    print()
    print('*' * 100)
    print("3. Creating Encrypted Snapshot Copy")
    # encrypted_snapshot_list contains a list of all encrypted snapshot objects
    temp_encrypted_snapshot_list = []
    for snapshot in snapshots_list:
        print(snapshot['SnapshotId'])
        is_pending = True
        snapshot_describe_response = None
        while is_pending:
            snapshot_describe_response = ec2_client.describe_snapshots(
                SnapshotIds=[
                    snapshot['SnapshotId']
                ]
            )
            print(snapshot_describe_response['Snapshots'][0]['Progress'])
            print(snapshot_describe_response['Snapshots'][0]['State'])
            if snapshot_describe_response['Snapshots'][0]['State'] != 'completed':
                time.sleep(10)
            else:
                is_pending = False
        print(snapshot_describe_response['Snapshots'][0]['Tags'])
        response1 = copy_snapshot_encrypt(snapshot)
        temp_encrypted_snapshot_list.append({'SnapshotId': response1['SnapshotId'], 'VolumeId': snapshot['VolumeId']})
        create_encrypted_snapshot_tags(response1['SnapshotId'], snapshot_describe_response['Snapshots'][0]['Tags'])
    return temp_encrypted_snapshot_list


# iterates through encrypted snapshot list
# creates a new encrypted volume from encrypted snapshot list
# returns list of encrypted volumes
def step4():
    print()
    print('*' * 100)
    print("4. Creating Encrypted Volumes from Encrypted Copies")
    # encrypted volumes list
    temp_encrypted_volume_list = []
    for encrypted_snapshot_obj in encrypted_snapshot_list:
        print(encrypted_snapshot_obj['SnapshotId'])
        is_pending = True
        while is_pending:
            snapshot_describe_response = ec2_client.describe_snapshots(
                SnapshotIds=[
                    encrypted_snapshot_obj['SnapshotId']
                ]
            )
            print(snapshot_describe_response['Snapshots'][0]['Progress'])
            print(snapshot_describe_response['Snapshots'][0]['State'])
            if snapshot_describe_response['Snapshots'][0]['State'] != 'completed':
                time.sleep(15)
            else:
                is_pending = False
        old_volume = [x for x in vol_encryption_list if x['VolumeId'] == encrypted_snapshot_obj['VolumeId']][0]
        old_snapshot = [x for x in snapshots_list if x['VolumeId'] == encrypted_snapshot_obj['VolumeId']][0]
        print(old_snapshot)
        print(old_volume)
        response = create_new_volume(encrypted_snapshot_obj, old_snapshot, old_volume)
        print(response)
        temp_encrypted_volume_list.append(response)
    return temp_encrypted_volume_list


# iterates through encryption list
# detaches the old volumes from instance
def step5():
    print()
    print('*' * 100)
    print("5. Detaching old volumes")
    for vol in vol_encryption_list:
        response = detach_volume(vol)
        print(response)
    return


# iterates through the encrypted volume list
# attaches the new encrypted volumes in place of the old ones
def step6():
    print()
    print('*' * 100)
    print("6. Attaching new encrypted volumes")
    for encrypted_vol in encrypted_volume_list:
        is_pending = True
        while is_pending:
            vol_describe_response = get_volume(encrypted_vol['VolumeId'])
            print(vol_describe_response['State'])
            if vol_describe_response['State'] != 'available':
                time.sleep(10)
            else:
                is_pending = False
        response = attach_volume(encrypted_vol)
        print(response)
    return


# starts up the instances
def step7():
    print()
    print('*' * 100)
    print("7. Starting Instances")
    for vol in vol_encryption_list:
        response = start_instance(vol['Attachments'][0]['InstanceId'])
        print(response)
    return


# Clean Up Old Volumes - erase unencrypted volumes from list
def step8():
    print()
    print('*' * 100)
    print("8. Clean Up Old Volumes")
    for vol in vol_encryption_list:
        delete_volume(vol)
    return


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args:
        print("This program encrypts volumes on EC2 instances.\narguments: profile_name region_name all|instance id")
        sys.exit(1)
    else:
        profile_name = args[0]
        region_name = args[1]
        try:
            instance_id = args[2]
        except IndexError:
            instance_id = "all"
    try:
        session = boto3.Session(profile_name=profile_name)
        ec2_client = session.client('ec2', region_name=region_name)
    except Exception as e:
        print(e)
        raise Exception("Error with AWS credentials")

    reservations = get_instances(instance_id)
    # instance list contains a list of instances in region
    instance_list = []
    # encryption list contains a list of the unencrypted volume objects
    vol_encryption_list = []
    # populate encryption list and instance list
    for reservation in reservations:
        for instance in reservation['Instances']:
            instance_list.append(instance)
            vol_encryption_list.extend(collect_instances_volumes(instance))
    print("\n\nVolumes To Encrypt:")
    for volume in vol_encryption_list:
        print(volume['VolumeId'])
    print("Initiating Drive Encryption Routine")

    step1()
    snapshots_list = step2()
    encrypted_snapshot_list = step3()
    encrypted_volume_list = step4()
    step5()
    step6()
    step7()
    step8()
    print("DONE")
    sys.exit(0)
