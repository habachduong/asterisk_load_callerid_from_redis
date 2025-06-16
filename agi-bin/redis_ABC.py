import redis

from redis.commands.json.path import Path
import redis.commands.search.aggregation as aggregations
import redis.commands.search.reducers as reducers
from redis.commands.search.field import TextField, NumericField, TagField
from redis.commands.search.indexDefinition import IndexDefinition, IndexType
from redis.commands.search.query import NumericFilter, Query
import redis_lock
from datetime import datetime
import time
try:#non sql
    import json
except ImportError:
    import simplejson as json

from configparser import ConfigParser, NoOptionError

class MyConfigParser(ConfigParser):
    def optionxform(self, optionstr):
        return optionstr
config = MyConfigParser()
config.read('/etc/OPS.conf')



redis_host = config.get('global', 'redis_host')     
redis_port = config.get('global', 'redis_port')

conn  = redis.Redis(host=redis_host, port=redis_port)#, username='asterisk_user', password='asterisk_pass' )


index_callerid="callerid_infor"


###########################
###pstn callerid
    # callerid1 = {
    #     "callerid":{
    #         "name": "9988271882",
    #         "route_number": "",
    #         "calls_count": 42,
    #         "status":0,
    #         "lastcall":"",
    #         "TRUNK_NAME": "OPS_TRUNK",
    #     }
    # }
###########################
index="callerid_infor"
schema = (TextField("$.callerid.name", as_name="name"), 
        NumericField("$.callerid.calls_count", as_name="calls_count"),
        NumericField("$.callerid.failed_count", as_name="failed_count"), 
        NumericField("$.callerid.busy_count", as_name="busy_count"), 
        NumericField("$.callerid.status", as_name="status"),
        TagField("$.callerid.TRUNK_NAME", as_name="TRUNK_NAME"))
try:
    index_info= conn.ft(index).info();
    #print(index_info)

except:
    conn.ft(index).create_index(schema, definition=IndexDefinition(prefix=["callerid:"], index_type=IndexType.JSON))


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
