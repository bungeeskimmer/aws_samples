### Requirements 

* [boto3](https://github.com/boto/boto3)
* [click](http://click.pocoo.org/5/) 

And add awslib to your python path and run python kafka


`export PYTHONPATH=$PYTHONPATH:$(dirname $(dirname $(pwd)));python __init__.py`

or

example you check out this project in /home/myname/workspace/awslib
Run:

`export PYTHONPATH=$PYTHONPATH:/home/myname/workspace`

`cd  /home/myname/workspace/awslib/chefswap/`

`python __init__.py`


### Options 

`export PYTHONPATH=$(dirname $(dirname $(pwd)));python __init__.py --help`

Usage:  `__init__.py`  [OPTIONS]


Options:

 *  --ec2_type TEXT default=t2.micro
 *  --num_instances INTEGER  default = 8
 *  --target_level INTEGER default = 50
 *  --ramp_up INTEGER defaul = 50 
 *  --steps INTEGER default = 50 
 *  --hold INTEGER default = 3000
 *  --test_file default is empty - specify path to a jmx testfile to override on S3 and hosts
 *  --help                   Show this message and exit.
