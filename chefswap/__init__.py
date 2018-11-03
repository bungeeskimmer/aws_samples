import click
import config
import boto3
import time
import os
import awslib

# Global to track instance ids in case of exception
INSTANCE_IDS = []
COMMAND_IDS = []
NOW = str(int(time.time()))

os.environ["AWS_ACCESS_KEY_ID"] = config.ACCESS_KEY_ID
os.environ["AWS_SECRET_ACCESS_KEY"] = config.SECRET_KEY
os.environ["AWS_DEFAULT_REGION"] = config.REGION_NAME

jmeter_cmd = """cd /home/ec2-user/test/testbin;jmeter/bin/jmeter.sh -n -t FHLoad.jmx -Jtarget_level=%d -Jramp_up=%d -Jhold%d -Jsteps=%d -Jusers_file=fh_rave_users%d.csv -l results.txt"""


@click.command()
@click.option('--ec2_type', default=config.INSTANCE_TYPE)
@click.option('--num_instances', default=8, help="Number of instances")
@click.option('--target_level', default=50)
@click.option('--ramp_up', default=50)
@click.option('--steps', default=50)
@click.option('--hold', default=3000)
@click.option('--test_file', default="", help="Optional jmeter testfile to override on image")
def run(ec2_type, num_instances, target_level, ramp_up, steps, hold, test_file):
    global INSTANCE_IDS
    global COMMAND_IDS
    global NOW
    global TEST_STARTED
    ec2_client = boto3.client('ec2')

    if test_file != "":

        assert os.path.exists(test_file)
        click.echo("Testfile found to override on s3")
        awslib.upload_file(test_file, "chefswapjmeter-test", "testbin/FHLoad.jmx")

        awslib.s3_object_exists("chefswapjmeter-test", "testbin/FHLoad.jmx")


    INSTANCE_IDS = [inst["InstanceId"] for inst in
                    awslib.create_ec2_instances(ami_id=config.AMI_ID,
                                                keypair=config.KEYPAIR_NAME,
                                                instance_type=ec2_type,
                                                subnet_id="subnet-e9deec8f",
                                                sg_id="sg-78b67c06",
                                                min_count=num_instances,
                                                max_count=num_instances
                                                )["Instances"]
                    ]

    click.echo("Waiting for instances to spin up...")
    waiter = ec2_client.get_waiter('instance_running')

    waiter.wait(InstanceIds=INSTANCE_IDS)

    awslib.wait_for_ssm_hosts(INSTANCE_IDS)


    COMMAND_IDS = [awslib.run_command([inID], "aws s3 sync s3://chefswapjmeter-test/testbin /home/ec2-user/test/testbin/",
                                      "chefswapjmeter-test")['Command']["CommandId"]
                   for inID in INSTANCE_IDS ]

    COMMAND_IDS = [awslib.run_command([inID], "rm /home/ec2-user/test/testbin/results* /home/ec2-user/test/testbin/jmeter.log ",
                                      "chefswapjmeter-test")['Command']["CommandId"]
                   for inID in INSTANCE_IDS
                   ]


    if test_file != "":
        click.echo("Testfile found copying to instances ")

        COMMAND_IDS = [awslib.run_command([inID], "aws s3 cp s3://chefswapjmeter-test/testbin/FHLoad.jmx /home/ec2-user/test/testbin/FHLoad.jmx",
                                          "chefswapjmeter-test")['Command']["CommandId"]
                       for inID in INSTANCE_IDS
                       ]

    COMMAND_IDS = [awslib.run_command([inID[0]], jmeter_cmd % (target_level, ramp_up, hold, steps, inID[1]),
                                      "chefswapjmeter-test")['Command']["CommandId"]
                   for inID in zip(INSTANCE_IDS, range(1, len(INSTANCE_IDS) + 1))
                   ]

    click.echo("Test running, hit ctl-c to stop em and record the results - once!")

    while True:
        time.sleep(1)


def clean_up():
    global INSTANCE_IDS
    global COMMAND_IDS
    global NOW

    if INSTANCE_IDS:
        click.echo("Collecting results")
        try:
            # try to cancel commands
            [awslib.cancel_command(cmds[0], [cmds[1]]) for cmds in zip(COMMAND_IDS, INSTANCE_IDS)]
    
            # copy results
            copy_cmd_ids = [awslib.run_command([inID],
                                               "cd /home/ec2-user/test/testbin;aws s3 mv results.txt s3://chefswapjmeter-test/results/result-" + inID + "/"+NOW+".txt",
                                               "chefswapjmeter-test"
                                               )['Command']["CommandId"]
                            for inID in INSTANCE_IDS
                            ]
    
            copy_cmd_ids = [awslib.run_command([inID],
                                               "cd /home/ec2-user/test/testbin;aws s3 mv jmeter.log s3://chefswapjmeter-test/results/jmeterlog-" + inID + "/"+NOW+".log",
                                               "chefswapjmeter-test"
                                               )['Command']["CommandId"]
                            for inID in INSTANCE_IDS
                            ]
    
            click.echo("Copying results locally")

            # copy results locally
            [awslib.s3_object_exists("chefswapjmeter-test", "results/result-" + inID + "/" + NOW + ".txt")
             for inID in INSTANCE_IDS]
    
            [awslib.download_file("chefswapjmeter-test", "results/result-" + inID + "/" + NOW + ".txt",
                                  os.path.join("results", "result-" + inID + "_" + NOW + ".txt"))
             for inID in INSTANCE_IDS]
    
            [awslib.s3_object_exists("chefswapjmeter-test", "results/jmeterlog-" + inID + "/" + NOW + ".log")
             for inID in INSTANCE_IDS]
    
            [awslib.download_file("chefswapjmeter-test", "results/jmeterlog-" + inID + "/" + NOW + ".log",
                                  os.path.join("results", "jmeterlog-" + inID + "_" + NOW + ".txt"))
             for inID in INSTANCE_IDS]
        
        finally:
            click.echo("Terminating instances")
            awslib.terminate_instances(INSTANCE_IDS)


if __name__ == "__main__":
    try:
        run()
    except Exception, e:
        click.echo(e.message)
    except KeyboardInterrupt:
        pass
    finally:
        clean_up()
