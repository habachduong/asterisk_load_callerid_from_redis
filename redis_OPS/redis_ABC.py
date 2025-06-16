# Import required libraries
import redis
import json
from datetime import datetime
import redis_lock

# Import Redis search and JSON path modules
from redis.commands.json.path import Path
import redis.commands.search.aggregation as aggregations
import redis.commands.search.reducers as reducers
from redis.commands.search.field import TextField, NumericField, TagField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import NumericFilter, Query
import time
import logging
from configparser import ConfigParser, NoOptionError

# Custom ConfigParser class to preserve case sensitivity
class MyConfigParser(ConfigParser):
    def optionxform(self, optionstr):
        return optionstr

# Read configuration from file
config = MyConfigParser()
config.read('/etc/ABC.conf')

# Get Redis connection parameters from config
redis_host = config.get('global', 'redis_host')     
redis_port = config.get('global', 'redis_port')

# Initialize Redis connection
conn  = redis.Redis(host=redis_host, port=redis_port)

# Define index name for caller ID information
index_callerid="callerid_infor"

# Example of PSTN caller ID structure
###########################
###pstn callerid
    # callerid1 = {
    #     "callerid":{
    #         "name": "9988271882",
    #         "route_number": "",
    #         "calls_count": 42,
    #         "status":0,
    #         "lastcall":"",
    #         "TRUNK_NAME": "ABC_TRUNK",
    #     }
    # }
###########################

# Define Redis search index and schema
index="callerid_infor"
schema = (TextField("$.callerid.name", as_name="name"), 
        NumericField("$.callerid.calls_count", as_name="calls_count"),
        NumericField("$.callerid.failed_count", as_name="failed_count"), 
        NumericField("$.callerid.busy_count", as_name="busy_count"), 
        NumericField("$.callerid.status", as_name="status"),
        TagField("$.callerid.TRUNK_NAME", as_name="TRUNK_NAME"))

# Create Redis search index if it doesn't exist
try:
    index_info= conn.ft(index).info();
except:
    conn.ft(index).create_index(schema, definition=IndexDefinition(prefix=["callerid:"], index_type=IndexType.JSON))

# Function to add caller ID information to Redis
def add_callerid_to_redis(conn, index, callerid, callerid_infor):
    try:
        key = f"{index}:{callerid}"
        conn.set(key, json.dumps(callerid_infor))
        return True
    except Exception as e:
        print(f"Error adding callerid to redis: {e}")
        return False

# Function to add default caller ID to Redis
def add_callerid_default_redis(conn, callerid, route_number, trunk_name):
    try:
        key = f"callerid_infor:{callerid}"
        info = {
            "callerid": {
                "name": callerid,
                "route_number": route_number,
                "calls_count": 0,
                "failed_count": 0,
                "busy_count": 0,
                "status": 1,
                "lastcall": "",
                "TRUNK_NAME": trunk_name,
            }
        }
        conn.set(key, json.dumps(info))
        return True
    except Exception as e:
        print(f"Error adding default callerid to redis: {e}")
        return False

# Function to get default caller ID information from Redis
def get_default_callerid_redis(conn):
    default_trunk_name=conn.get("default_trunk_name")
    default_callerid=conn.get("default_callerid")
    default_route_number=conn.get("default_route_number")
    result={
            "default_trunk_name":default_trunk_name,
            "default_callerid":default_callerid,
            "default_route_number":default_route_number
    }
    return result;

# Function to delete all PSTN caller IDs by trunk name
def del_pstn_callerid_all_by_trunk(conn,index,TRUNK_NAME):
    try:
        pattern = f"{index}:*"
        keys = [k for k in conn.keys(pattern) if TRUNK_NAME in str(conn.get(k))]
        for k in keys:
            conn.delete(k)
        return 1
    except Exception as e:
        print(f"Error deleting callerids by trunk: {e}")
        return -1
