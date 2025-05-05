#!/usr/bin/python3

from asterisk.agi import *
from redis_OPS import *

agi = AGI()

agi_callerid = agi.env['agi_callerid'] if "agi_callerid" in agi.env else ""
agi.verbose("agi_callerid:"+str(agi_callerid))

agi_accountcode= agi.env['agi_accountcode'] if "agi_accountcode" in agi.env else ""
agi.verbose("agi_accountcode:"+str(agi_accountcode))

uniqueid=agi.env['agi_uniqueid'] if "agi_uniqueid" in agi.env else ""
agi.verbose("uniqueid:"+str(uniqueid))

result=get_default_callerid_redis(conn)
new_cid_number=result["default_callerid"]
trunk_name=result["default_trunk_name"]
route_number=result["default_route_number"]

# callerid_json=get_pstn_callerid_last(conn,"callerid_infor", 'OPS_TRUNK')
agi.verbose("### python agi started ###")

# if callerid_json!=-1:
# 	callerid_info=json.loads(callerid_json)
	# new_cid_number=callerid_info['callerid']['name']
	# trunk_name=callerid_info['callerid']["TRUNK_NAME"]
	# route_number=callerid_info['callerid']["route_number"]

if(new_cid_number==''):
	new_cid_number='02473002556';
if(trunk_name==''):
	trunk_name='OPS_TRUNK';
if(route_number==""):
	route_number="0";

#agi.verbose("TRUNK_NAME:"+str(trunk_name))
#agi.verbose("route_number:"+str(route_number))
#agi.verbose("new_cid_number:"+str(new_cid_number))
#agi.verbose("callerid:"+str(callerid))

agi.execute('SET VARIABLE TRUNK_NAME '+trunk_name)
agi.execute('SET VARIABLE route_number '+route_number)
agi.execute('SET VARIABLE new_cid_number '+new_cid_number)
agi.execute('SET VARIABLE src_number '+agi_callerid)


agi.verbose("### python agi ended ###")

