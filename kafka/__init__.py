from config import *
import sys
sys.path.append("/Users/narayan.pallipamu")
import awslib
import boto3
import click
import time

awslib.COMMAND_TIME_OUT = 240

ec2_client = boto3.client('ec2')
ec2_resource = boto3.resource('ec2')
ssm_client = boto3.client('ssm')

log_client = boto3.client('logs')

zookeeper_docker_compose_cmd = """#!/bin/bash
sudo mkdir -p /opt/zookeeper
sudo echo 'version: "2"
services:
  zookeeper:
    image: zookeeper
    ports:
      - "2181:2181"
      - "2888:2888"
      - "3888:3888"
    logging:
      driver: "awslogs"
      options:
        awslogs-region: "us-west-2"
        awslogs-group: "kafka-cluster"
        awslogs-stream: "zookeeper-%s"
    environment:
      ZOO_MY_ID: %d
      ZOO_PORT: 2181
      ZOO_SERVERS: %s
    network_mode: bridge'>>/opt/zookeeper/docker-compose.yaml
"""

kafka_docker_compose_cmd = """#!/bin/bash
sudo mkdir -p /opt/kafka
sudo echo 'version: "2"
services:
  kafka:
    image: wurstmeister/kafka:0.11.0.1
    ports:
      - "9092:9092"
      - "1099:1099"
    logging:
      driver: "awslogs"
      options:
        awslogs-region: "us-west-2"
        awslogs-group: "kafka-cluster"
        awslogs-stream: "broker-%s"
    environment:
      KAFKA_ZOOKEEPER_CONNECTION_TIMEOUT_MS: 60000
      KAFKA_LOG_RETENTION_HOURS: 168
      KAFKA_NUM_RECOVERY_THREADS_PER_DATA_DIR: 4
      KAFKA_NUM_PARTITIONS: 120
      KAFKA_DELETE_TOPIC_ENABLE: "true"
      KAFKA_ZOOKEEPER_CONNECT: %s
      KAFKA_BROKER_ID: %d
      KAFKA_ADVERTISED_PORT: "9092"
      KAFKA_PORT: 9092
      HOSTNAME_COMMAND: "wget -t3 -T2 -qO-  http://169.254.169.254/latest/meta-data/local-ipv4"
      KAFKA_JMX_OPTS: "-Dcom.sun.management.jmxremote -Dcom.sun.management.jmxremote.authenticate=false -Dcom.sun.management.jmxremote.ssl=false -Djava.rmi.server.hostname=%s -Dcom.sun.management.jmxremote.rmi.port=1099"
      JMX_PORT: 1099
    network_mode: bridge'>>/opt/kafka/docker-compose.yaml
"""

if __name__ == "__main__":

    # Create kafka instances and store instance info response
    kafka_instances_response = awslib.create_ec2_instances(ami_id=AMI_ID,
                                                           keypair=KEYPAIR_NAME,
                                                           instance_type=KAFKA_INSTANCE_TYPE,
                                                           subnet_id="subnet-e9deec8f",
                                                           sg_id="sg-a774bcd9",
                                                           min_count=3,
                                                           max_count=3,
                                                           tags=[{'Key': 'Kafka',
                                                           'Value': 'True'}]
                                                           )
    # Store instance ids
    kafka_instance_ids = [k["InstanceId"] for k in kafka_instances_response["Instances"]]
    # Store instance dicts
    kafka_instances_response = ec2_client.describe_instances(InstanceIds=kafka_instance_ids)["Reservations"][0]["Instances"]

    # Create zookeeper instances and store instance info response
    zoo_instance_response = awslib.create_ec2_instances(ami_id=AMI_ID,
                                                        keypair=KEYPAIR_NAME,
                                                        instance_type=KAFKA_INSTANCE_TYPE,
                                                        subnet_id="subnet-e9deec8f",
                                                        sg_id="sg-869668f8",
                                                        min_count=3,
                                                        max_count=3,
                                                        tags=[{
                                                    'Key': 'Zookeeper',
                                                    'Value': 'True'}]
                                                        )
    # Store instance ids
    zoo_instance_ids = [z["InstanceId"] for z in zoo_instance_response["Instances"]]
    # Store instance dicts
    zoo_instance_response = ec2_client.describe_instances(InstanceIds=zoo_instance_ids)["Reservations"][0]["Instances"]

    click.secho("zoo instanceId: ")
    click.secho("\t" + ','.join(zoo_instance_ids), fg='blue')

    #  wait for instances to start
    click.secho("kafka instanceIds: ")
    click.secho("\t" + ','.join(kafka_instance_ids), fg='blue')

    click.echo("Waiting for instances to spin up...")
    waiter = ec2_client.get_waiter('instance_running')
    waiter.wait(InstanceIds=zoo_instance_ids + kafka_instance_ids)

    awslib.wait_for_ssm_hosts(zoo_instance_ids + kafka_instance_ids)

    #create logstreams
    [log_client.create_log_stream(logGroupName="kafka-cluster", logStreamName="broker-"+kid) for kid in kafka_instance_ids]

    [log_client.create_log_stream(logGroupName="kafka-cluster", logStreamName="zookeeper-"+kid) for kid in zoo_instance_ids]

    # make sure they have public ips
    while not all("PublicIpAddress" in z for z in zoo_instance_response):
        zoo_instance_response = ec2_client.describe_instances(InstanceIds=zoo_instance_ids)["Reservations"][0]["Instances"]

    while not all("PublicIpAddress" in k for k in kafka_instances_response):
        kafka_instances_response = ec2_client.describe_instances(InstanceIds=kafka_instance_ids)["Reservations"][0]["Instances"]

    # Construct kafka bootstrap connect string
    zookeeper_connect = ",".join([z["PublicIpAddress"] + ":2181" for z in zoo_instance_response])

    # Kafka bootstrap string

    kafka_bootstrap = ",".join([z["PublicIpAddress"] + ":9092" for z in kafka_instances_response])

    # Construct zookeeper connect string - need to replace each servers respective ip with 0.0.0.0 later in docker cmd
    zookeeper_server_connect = " ".join(["server." + str(k[1]) + "=" + k[0]["PublicIpAddress"] + ":2888:3888"
                                         for k in zip(zoo_instance_response, range(len(zoo_instance_response)))]
                                        )

    # replace the docker file cmd str with pertinent data
    # each zookeeper connect need to have its server be 0.0.0.0 in connect string or election listener w
    commands = [awslib.run_command([z[0]["InstanceId"]],
                                   (zookeeper_docker_compose_cmd % (z[0]["InstanceId"],
                                                                    z[1],
                                                                    zookeeper_server_connect)
                                    ).replace(z[0]['PublicIpAddress'], "0.0.0.0"),
                                   "zookeepers"
                                   )['Command']['CommandId'] for z in zip(zoo_instance_response,
                                                                          range(len(zoo_instance_response))
                                                                          )
                ]

    [awslib.wait_for_command(c) for c in commands]

    # replace the docker file cmd str with pertinent data
    commands = [awslib.run_command([z[0]["InstanceId"]],
                                   kafka_docker_compose_cmd % (
                                       z[0]["InstanceId"],
                                       zookeeper_connect,
                                       z[1],
                                       z[0]["PublicIpAddress"]),
                                    "kafka-brokers"
                                   )['Command']['CommandId'] for z in zip(kafka_instances_response,
                                                                          range(len(kafka_instances_response))
                                                                          )

                ]

    [awslib.wait_for_command(c)for c in commands]

    commands = [
                awslib.run_command([zid],
                                   "cd /opt/zookeeper;docker-compose up -d", "zookeepers")['Command']['CommandId']
                for zid in zoo_instance_ids
                ]

    awslib.wait_for_command(c)

    commands = [
        awslib.run_command([kid],
                           "cd /opt/kafka;docker-compose up -d", "kafka-brokers")['Command']['CommandId']
        for kid in kafka_instance_ids
    ]

    [awslib.wait_for_command(c) for c in commands]

    click.echo("zookeeper-connect " + zookeeper_server_connect)
    click.echo("kafka-connect " + zookeeper_connect)
    click.echo("kafka-bootstrap " + kafka_bootstrap)