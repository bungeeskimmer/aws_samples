requires boto3 and the click python lib

to run add awslib to your python path and run python kafka


export PYTHONPATH=$PYTHONPATH:$(dirname $(dirname $(pwd)));python __init__.py 

or

example you check out this project in /home/myname/workspace/awslib
Run:
export PYTHONPATH=$PYTHONPATH:/home/myname/workspace
cd  /home/myname/workspace/awslib/kafka/
python __init__.py


