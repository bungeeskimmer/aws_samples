import boto3
import botocore
import time
import datetime
import click

from botocore.errorfactory import ClientError

COMMAND_TIME_OUT = 120
DEFAULT_INSTANCE_ROLE_PRO = "bfgAutomationInstanceProfile"

def wait_for_command(command_id, wait_forever=False):
    """
        Run a command using AWS SSM and wait for either forever or COMMAND_TIME_OUT time for a ssm command to execute
    :param command_id: Id of ssm command to wa
    :param wait_forever:
    :return:
    """
    result = check_command(command_id)

    if wait_forever:
        while True:
            if result and result['Commands'][0]['Status'] in ['Pending', 'InProgress']:
                time.sleep(1)
                result = check_command(command_id)
            else:
                break
    else:
        for i in range(0, COMMAND_TIME_OUT):
            if result and result['Commands'][0]['Status'] in ['Pending', 'InProgress']:
                time.sleep(1)
                result = check_command(command_id)
            else:
                break
    return result


def check_command(command_id):
    """
        Call for the status of a AWS SSM command or return False if the command is not registered
    :param command_id: ssm command id
    :return: the command object or False if not found
    """
    ssm = boto3.client('ssm')
    response = ssm.list_commands(CommandId=command_id)
    if "Commands" in response and response['Commands']:
        return response
    else:
        return False


def run_command(instance_ids, command, s3bucket, s3key= "ssm-commands"):
    """

    http://boto3.readthedocs.io/en/latest/reference/services/ssm.html#SSM.Client.send_command

        Send a Run SSM api command and log stuff about it
    :param instance_ids: Instance ids to run command on
    :param command: the command string
    :param s3bucket: the s3bucket to log command output to. Needs to exist or it will fail
    :return:
    """

    if not s3_bucket_exists(s3bucket):
        click.echo("Warning s3 bucket " + s3bucket + " not found, command output going to default-ssm-output")
        s3bucket = "default-ssm-output"

    thetime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    click.echo(thetime +": Running -\n'")
    click.secho('\t'+command, fg='green')
    click.secho("'\n\ton: " + str(instance_ids), fg='blue')

    wait_for_ssm_hosts(instance_ids)
    command_response = None
    ssm = boto3.client('ssm')

    for i in range(30):
        try:
            command_response = ssm.send_command(
                InstanceIds=instance_ids,
                DocumentName='AWS-RunShellScript',
                Comment=command[-100:],
                OutputS3BucketName=s3bucket,
                OutputS3KeyPrefix ="commands",
                Parameters={
                    "commands": [command]
                }
            )
        except ClientError, e:

            if e.response["Error"]["Code"] == u'InvalidInstanceId':
                click.echo("Waiting for ssm")
                time.sleep(2)
                continue
            else:
                break;
        break;

    return command_response


def cancel_command(command_id, instance_ids):
    ssm = boto3.client('ssm')

    response = ssm.cancel_command(
        CommandId=command_id,
        InstanceIds=instance_ids
    )

    return response

def expand_ebs(ebs_id, gigs):
    """
    :param ebs_id: list of ebss to expand
    :param gigs: number of gigs to expand to
    :return:
    """
    client = boto3.client('ec2')
    client.modify_volume(VolumeId=ebs_id, Size=gigs)


def find_policy(name):
    """
        Look to see if a policy exists in AWS for this region
    :param name: Name of policy to find
    :return: The policy object of False if not found
    """
    iam_client = boto3.client('iam')
    response = iam_client.list_policies(
        Scope='Local',
        OnlyAttached=False
    )
    for p in response['Policies']:
        if p['PolicyName'] == name:
            return p
    return False


def find_role(name):
    """
    Look to see if a Role exists in AWS for this region
    :param name: Name of role to find
    :return: The role object of False if not found
    """
    iam_client = boto3.client('iam')
    try:
        response = iam_client.list_role_policies(
            RoleName=name
        )
    except:
        return False
    return True


def find_instance_profiles(name):
    """
    Look to see if a instance profile exists in AWS for this region
    :param name: Name of role to find
    :return: The role object of False if not found
    """
    iam_client = boto3.client('iam')
    response = iam_client.list_instance_profiles(
    )

    for p in response['InstanceProfiles']:
        if p['InstanceProfileName'] == name:
            return p
    return False


def find_vpc(vpc_name ='tsung_vpc'):
    ec2_client = boto3.client('ec2')
    vpc = ec2_client.describe_vpcs()
    # only want tsung_vpcs
    res = ec2_client.describe_vpcs(Filters=[{"Name": "tag-key", "Values": [vpc_name]}])

    if res['Vpcs']:
        return res['Vpcs'][0]['VpcId']
    else:
        return None


def create_lb(name, subnets, sgs, listeners):
    """

    :param name:
    :param subnets:
    :param sgs:
    :param listeners:
    :return:

    Listeners=[
        {
            'InstancePort': 80,
            'InstanceProtocol': 'HTTP',
            'LoadBalancerPort': 80,
            'Protocol': 'HTTP',
        }

    """
    client = boto3.client('elb')

    response = client.create_load_balancer(Name=name, Listeners=listeners, Subnets=subnets, SecurityGroups=sgs)

    return response


def delete_lb(lb_name):

    client = boto3.client('elb')
    response = client.delete_load_balancer(
        LoadBalancerName=lb_name,
    )

    return response


def create_launch_config(lcn, sg_id, ami_id, keypair, userdata, instance_type ):
    client = boto3.client('autoscaling')
    response = client.create_launch_configuration(
        LaunchConfigurationName=lcn,
        ImageId=ami_id,
        KeyName=keypair,
        UserData=userdata,
        SecurityGroups=[
            sg_id
        ],
        InstanceType=instance_type,
        InstanceMonitoring={
            'Enabled': True
        },
        IamInstanceProfile="ecsInstanceRole",
        AssociatePublicIpAddress=True
    )
    return response


def create_autoscaling_group(agn, minCount, maxCount, lcn, subnet, tags):
    client = boto3.client('autoscaling')
    response = client.create_auto_scaling_group(
        AutoScalingGroupName=agn,
        LaunchConfigurationName=lcn,
        MinSize=minCount,
        MaxSize=maxCount,
        VPCZoneIdentifier=subnet.subnet_id.id,
        Tags=[tags]
    )

def create_ec2_instances(ami_id,
                         keypair,
                         instance_type,
                         subnet_id,
                         sg_id,
                         userdata="",
                         max_count=1,
                         min_count=1,
                         tags=[{ 'Key': 'createdByAutomation',
                                 'Value': 'True'}],
                         instance_profile_name=DEFAULT_INSTANCE_ROLE_PRO
                         ):
    """

    http://boto3.readthedocs.io/en/latest/reference/services/ec2.html#EC2.Client.run_instances

            'Tags': [
                {
                    'Key': 'string',
                    'Value': 'string'
                },
            ]

    :param ami_id:
    :param keypair:
    :param instance_type:
    :param subnet_id:
    :param sg_id:
    :param userdata:
    :param max_count:
    :param min_count:
    :param tags:
    :param instance_profile_name:
    :return:
    """
    """

    :param subnet_id:
    :param sg_id:
    :return: a tuple where first element is a list with master instance id and second is
    """
    ec2_client = boto3.client('ec2')

    #check to see if the default instance profile exists otherwise create it
    if instance_profile_name == DEFAULT_INSTANCE_ROLE_PRO:
        create_default_iam_stuff()

    started_instances = ec2_client.run_instances(

        NetworkInterfaces=[
            {
                'DeviceIndex': 0,
                'SubnetId': subnet_id,
                'AssociatePublicIpAddress': True,
                'Groups': [sg_id]
            },
        ],
        ImageId=ami_id,
        InstanceType=instance_type,
        KeyName=keypair,
        MaxCount=max_count,
        MinCount=min_count,
        TagSpecifications=[{"ResourceType": "instance", "Tags": tags}],
        UserData=userdata,
        IamInstanceProfile={
            "Name": instance_profile_name
        }
    )

    return started_instances


def terminate_instances(ids):
    """
        Teminate the ec2 instances specified by ids
    :param ids: ec2 instance ids to terminate
    :return:
    """
    client = boto3.client('ec2')
    return client.terminate_instances(InstanceIds=ids)


def create_security_group(vpc_id, from_port, to_port, group_name='', description='', cidr_ip="0.0.0.0/0"):
    """

    :param vpc_id:
    :param from_port:
    :param to_port:
    :param cidr_ip:
    :param group_name:
    :param description:
    :return:
    """
    ec2_resource = boto3.resource('ec2')
    vpc = ec2_resource.Vpc(vpc_id)

    sg = vpc.create_security_group(GroupName=group_name,
                                   Description=description,
                                   VpcId=vpc.id
                                   )

    # sg = ec2_resource.SecurityGroup(sg_response['GroupId'])
    sg.authorize_ingress(
        CidrIp=cidr_ip,
        FromPort=from_port,
        GroupId=sg.group_id,
        IpProtocol="-1",
        ToPort=to_port
    )

    return sg


def create_subnet(vpc_id, cidr_block, tags=[]):
    """
     Tags=[
        {
            'Key': 'tsung_route_table',
            'Value': 'True'
        }
    ]

    :param vpc_id:
    :param cidr_block:
    :param tags:
    :return:
    """
    ec2_resource = boto3.resource('ec2')

    vpc = ec2_resource.Vpc(vpc_id)

    subnet = vpc.create_subnet(CidrBlock=cidr_block)
    subnet.create_tags(Tags=tags)

    return subnet


def create_default_iam_stuff():
    """
    Create the role, role policy and instance profiles needed for tsung.
    If they don not all ready exist.
    :return:
    """
    iam_client = boto3.client('iam')

    if not find_role('bfgAutomationRole'):
        roleResponse = iam_client.create_role(
            RoleName='bfgAutomationRole',
            AssumeRolePolicyDocument ='''{
                                  "Version": "2012-10-17",
                                  "Statement": [
                                    {
                                      "Effect": "Allow",
                                      "Principal": {
                                        "Service": "ec2.amazonaws.com"
                                      },
                                      "Action": "sts:AssumeRole"
                                    }
                                  ]
                                }''',
            Description='ec2 automation policy for general bfg stuff'
        )

    if not find_policy('bfgAutomationRolePolicy'):

        response = iam_client.create_policy(
            PolicyName='bfgAutomationRolePolicy',
            PolicyDocument='''{
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:*",
                        "cloudtrail:LookupEvents"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ssm:DescribeAssociation",
                        "ssm:GetDeployablePatchSnapshotForInstance",
                        "ssm:GetDocument",
                        "ssm:GetManifest",
                        "ssm:GetParameters",
                        "ssm:ListAssociations",
                        "ssm:ListInstanceAssociations",
                        "ssm:PutInventory",
                        "ssm:PutComplianceItems",
                        "ssm:PutConfigurePackageResult",
                        "ssm:UpdateAssociationStatus",
                        "ssm:UpdateInstanceAssociationStatus",
                        "ssm:UpdateInstanceInformation"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2messages:AcknowledgeMessage",
                        "ec2messages:DeleteMessage",
                        "ec2messages:FailMessage",
                        "ec2messages:GetEndpoint",
                        "ec2messages:GetMessages",
                        "ec2messages:SendReply"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "cloudwatch:PutMetricData"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ec2:DescribeInstanceStatus"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ds:CreateComputer",
                        "ds:DescribeDirectories"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:DescribeLogGroups",
                        "logs:DescribeLogStreams",
                        "logs:PutLogEvents"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "s3:PutObject",
                        "s3:GetObject",
                        "s3:AbortMultipartUpload",
                        "s3:ListMultipartUploadParts",
                        "s3:ListBucket",
                        "s3:ListBucketMultipartUploads"
                    ],
                    "Resource": "*"
                },
                {
                    "Effect": "Allow",
                    "Action": [
                        "ecr:BatchCheckLayerAvailability",
                        "ecr:BatchGetImage",
                        "ecr:DescribeRepositories",
                        "ecr:GetAuthorizationToken",
                        "ecr:GetDownloadUrlForLayer",
                        "ecr:GetRepositoryPolicy",
                        "ecr:ListImages",
                        "ecs:CreateCluster",
                        "ecs:DeregisterContainerInstance",
                        "ecs:DiscoverPollEndpoint",
                        "ecs:Poll",
                        "ecs:RegisterContainerInstance",
                        "ecs:StartTask",
                        "ecs:StartTelemetrySession",
                        "ecs:SubmitContainerStateChange",
                        "ecs:SubmitTaskStateChange"
                    ],
                    "Resource": [
                        "*"
                    ]
                }
            ]
        }''',
            Description='ec2 automation role policy for general bfg stuff'
        )

        response = iam_client.attach_role_policy(
            RoleName="bfgAutomationRole",
            PolicyArn=response['Policy']['Arn']
        )

    if not find_instance_profiles("bfgAutomationInstanceProfile"):
        response = iam_client.create_instance_profile(
            InstanceProfileName='bfgAutomationInstanceProfile'
        )
        response = iam_client.add_role_to_instance_profile(
            InstanceProfileName='bfgAutomationInstanceProfile',
            RoleName="bfgAutomationRole"
        )


def create_network_stuff():
    """
     This function creates all the necessary networking stuff for tsung to operate
    :return:
    """
    ec2_resource = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    # find out if we need to make a network
    tsung_vpcId = find_vpc()

    if tsung_vpcId:

        vpc = ec2_resource.Vpc(tsung_vpcId)
        subnet = [ec2_resource.Subnet(s) for s in vpc.subnets.all()][0]
        route_table = [ec2_resource.RouteTable(r) for r in vpc.route_tables.all()][0]
        gateway = [ec2_resource.InternetGateway(g) for g in vpc.internet_gateways.all()][0]
        sg = [ec2_resource.SecurityGroup(s) for s in vpc.security_groups.all()][0]
        sg_id = sg.id.id
        subnet_id = subnet.id.id
    else:
        vpc = ec2_resource.create_vpc(
            CidrBlock="10.0.0.0/16"
        )

        # Configure the VPC to support DNS resolution and hostname assignment
        vpc.modify_attribute(
            EnableDnsHostnames={
                'Value': True
            }
        )

        vpc.modify_attribute(
            EnableDnsSupport={
                'Value': True
            }

        )
        vpc.create_tags(Tags=[
            {
                'Key': 'tsung_vpc',
                'Value': 'True'
            },
        ])

        netacl = ec2_client.create_network_acl(
            VpcId=vpc.vpc_id
        )

        ec2_client.create_network_acl_entry(
            Egress=False,
            NetworkAclId=netacl['NetworkAcl']['NetworkAclId'],
            Protocol="-1",
            RuleAction="allow",
            RuleNumber=1,
            PortRange={
                "To": 65535,
                "From": 0
            },
            CidrBlock="10.0.0.0/16"
        )

        # Create an Internet Gateway
        gateway = ec2_resource.create_internet_gateway()

        gateway.create_tags(Tags=[
            {
                'Key': 'tsung_gateway',
                'Value': 'True'
            },
        ])

        # Attach the Internet Gateway to our VPC
        vpc.attach_internet_gateway(InternetGatewayId=gateway.id)

        # Create a Route Table
        route_table = vpc.create_route_table()

        route_table.create_tags(Tags=[
            {
                'Key': 'tsung_route_table',
                'Value': 'True'
            },
        ])
        # Create a size /16 subnet
        subnet = vpc.create_subnet(CidrBlock='10.0.0.0/16')
        subnet.create_tags(Tags=[
            {
                'Key': 'tsung_route_table',
                'Value': 'True'
            }
        ])

        # Associate Route Table with our subnet
        ec2_client.associate_route_table(RouteTableId=route_table.id, SubnetId=subnet.id)

        # Create a Route from our Internet Gateway to the internet
        route = ec2_client.create_route(RouteTableId=route_table.id,
                                        DestinationCidrBlock='0.0.0.0/0',
                                        GatewayId=gateway.id)

        # Create a new VPC security group
        sg = vpc.create_security_group(GroupName='wide open',
                                       Description='A group for tsung - all tcp ports',
                                       VpcId=vpc.id
                                       )

        # sg = ec2_resource.SecurityGroup(sg_response['GroupId'])
        sg.authorize_ingress(
            CidrIp="0.0.0.0/0",
            FromPort=0,
            GroupId=sg.group_id,
            IpProtocol="-1",
            ToPort=65535
        )

        sg_id = sg.id
        subnet_id = subnet.id

    return subnet_id, route_table, gateway, sg_id, vpc


def wait_for_ssm_hosts(instance_ids):
    """
    No known waiter
    :param instance_ids:
    :return:
    """
    ssm_client = boto3.client('ssm')

    for i in range(1, 60):
        try:

            results = ssm_client.describe_instance_information(InstanceInformationFilterList=[
                {'key': 'InstanceIds', 'valueSet': instance_ids}])

            online_ids = [instance["InstanceId"] for instance in results['InstanceInformationList']
                          if instance['PingStatus'] == 'Online']

            if set(online_ids) == set(instance_ids):
                break

        except ClientError:
            click.secho("Waiting for ssm to be ready", fg='red')
            time.sleep(2)

    time.sleep(5)


def s3_bucket_exists(bucket_name):

    client = boto3.client('s3')
    buckets = client.list_buckets()

    return any(b['Name'] == bucket_name for b in buckets["Buckets"])


def download_file(bucket, key, local_path):
    resource = boto3.resource('s3')
    my_bucket = resource.Bucket(bucket)
    my_bucket.download_file(key, local_path)

   # client = boto3.client('s3')
   # with open(local_path, 'wb') as data:
   #     client.download_fileobj(bucket, key, data)


def s3_object_exists(bucket, key):
    s3 = boto3.resource('s3')

    for i in range(0, COMMAND_TIME_OUT):
        try:
            s3.Object(bucket, key).load()
            return True
        except botocore.exceptions.ClientError as e:
            if e.response['Error']['Code'] == "404":
                time.sleep(1)
    return False


def upload_file(localfile, bucket, key):
    s3 = boto3.client('s3')
    s3.upload_file(localfile, bucket, key)

