# OPS_Kamailio CallerID Management System
# This system provides APIs for managing CallerIDs in Redis and MySQL database
# Main functionalities include: deleting all CallerIDs, syncing from DB, and replacing CallerIDs

# Required imports for the system
import os
import os.path
import sys
import re
import time
import logging
import optparse
import base64
import urllib
import threading
import requests
from redis_OPS import *  # Custom Redis operations module
import base64 as __b
import logging as __l
import sys as __s
from datetime import datetime as __d
from configparser import ConfigParser, NoOptionError
from datetime import datetime

# Import Twisted framework for web server functionality
try:
    from twisted.python import failure
    from twisted.internet import reactor, task, defer
    from twisted.internet import error as tw_error
    from twisted.web import server as TWebServer
    from twisted.web import resource
except ImportError:
    print ("REST_API ERROR: Module twisted not found.")
    print ("You need twisted matrix 10.1+ to run REST_API. Get it from http://twistedmatrix.com/")
    sys.exit(1)

# Import MySQL connector for database operations
try:
    import mysql.connector
except ImportError:
    print ("REST_API ERROR: Mysql not found.")
    print ("You need Mysql connector")
    sys.exit(1)
    
# Import JSON handling
try:
    import json
except ImportError:
    import simplejson as json

# System configuration constants
HTTP_SESSION_TIMEOUT        = 60  # Session timeout in seconds
AMI_RECONNECT_INTERVAL      = 10  # AMI reconnection interval
TASK_CHECK_STATUS_INTERVAL  = 10  # Status check interval
TASK_QUEUE_CALL_INTERVAL    = 20  # Queue call interval

REST_API_CALLERID = "REST_API"  # API identifier

# Device states mapping for Asterisk
AST_DEVICE_STATES = {
    '0': 'Unknown',
    '1': 'Not In Use',
    '2': 'In Use',
    '3': 'Busy',
    '4': 'Invalid',
    '5': 'Unavailable',
    '6': 'Ringing',
    '7': 'Ring, In Use',
    '8': 'On Hold'
}

# Logging configuration
log                 = None
logging.DUMPOBJECTS = False
logging.FORMAT      = "[%(asctime)s] %(levelname)-8s :: %(message)s" 
logging.NOTICE      = 60
logging.addLevelName(logging.NOTICE, "NOTICE")

# Generic object class for dynamic attribute handling
class GenericObject(object):
    def __init__(self, objecttype = "Generic Object"):
        self.objecttype = objecttype
    def __setattr__(self, key, value):
        self.__dict__[key] = value
    def __getattr__(self, key):
        return self.__dict__.get(key)
    def __delattr__(self, key):
        del self.__dict__[key]
    def __str__(self):
        out = [
            "",
            "##################################################",
            "# Object Type: %s" % self.objecttype,
            "##################################################"
        ]
        keys = sorted(self.__dict__.keys())
        pad  = sorted([len(k) for k in keys])[-1]
        
        for key in keys:
            format = "%%%ds : %s" % (pad, '%s')
            value  = self.__dict__.get(key)
            out.append(format % (key, value))
        
        out.append("##################################################")
        
        return "\n".join(out)

# Custom ConfigParser class that preserves case sensitivity
class MyConfigParser(ConfigParser):
    def optionxform(self, optionstr):
        return optionstr

# Main REST API HTTP server class
class REST_APIHTTP(resource.Resource):
    isLeaf   = True
    REST_API   = None
    sessions = {}
    # Redis index names for different data types
    index_campaign="campaign_infor"
    index_agent="agents_infor"
    index_callerid="callerid_infor"
    index_lead="leads_infor"

    # MySQL connection parameters
    mysql_conn = None
    mysql_host = ""    
    mysql_user = ""
    mysql_pass = ""
    mysql_database= ""     

    def __init__(self, host, port):
        log.log(logging.NOTICE,'Initializing REST_API HTTP Server at %s:%s...' % (host, port))
        # Define available API endpoints
        self.handlers = {
            '/API_Delete_ALL_CALLERID'        : self.API_Delete_ALL_CALLERID,
            '/API_SYNC_CALLERID_FROM_DB'      : self.API_SYNC_CALLERID_FROM_DB,
            '/API_REPLACE_CALLERID'           : self.API_REPLACE_CALLERID,
        }

    # Session management methods
    def _expireSession(self):
        expired = [sessid for sessid, session in self.sessions.items() if not self.REST_API.site.sessions.has_key(sessid)]
        for sessid in expired:
            log.log(logging.NOTICE,"Removing Expired Client Session: %s" % sessid)
            del self.sessions[sessid]
    
    def _addUpdate(self, **kw):
        session = self.sessions.get(kw.get('sessid'))
        if session:
            session.updates.append(kw)
        else:
            for sessid, session in self.sessions.items():
                session.updates.append(kw)
            
    def _onRequestFailure(self, reason, request):
        session = request.getSession()
        log.error("HTTP Request from %s:%s (%s) to %s failed: %s", request.client.host, request.client.port, session.uid, request.uri, reason.getErrorMessage())
        log.exception("Unhandled Exception on HTTP Request to %s" % request.uri)
        request.setResponseCode(500)
        request.finish()
        return 0;

    # Log API requests to MySQL database
    def API_log_request(self,**kw):
        if (self.mysql_conn is None) or (not self.mysql_conn.is_connected()):
            self.mysql_conn = mysql.connector.connect(user=self.mysql_user, password=self.mysql_pass, host=self.mysql_host, database=self.mysql_database)
        try:
            cursor_log = self.mysql_conn.cursor(buffered=True)
            query=("INSERT INTO API_log_request SET datecall=NOW(), path=%s, data_get=%s, user=%s, ipadd=%s, data_return=%s")
            cursor_log.execute(query,(kw.get('path'),kw.get('data'),kw.get('user'),kw.get('ipadd'),kw.get('data_return')))
            self.mysql_conn.commit()
            log.log(logging.NOTICE,"INSERT API CALL logs to DB")
        finally:
            log.log(logging.NOTICE,"finally 2")

    # Handle POST requests
    def render_POST(self, request):
        session = request.getSession()
        session.touch()
        session.data_send=request.content.read()
        user=request.getUser().decode("UTF-8")
        password=request.getPassword().decode("UTF-8")
        ipadd=request.client.host

        session.user_send=user
        session.ipadd_send=ipadd

        log.log(logging.NOTICE,"HTTP Request POST from %s:%s (%s) to %s", ipadd, request.client.port, session.uid, request.uri)
        log.log(logging.NOTICE,session.data_send)
        print(str(datetime.now())+" ## HTTP Request POST from %s:%s (%s) to %s", ipadd, request.client.port, session.uid, request.uri)
        print(session.data_send)
        if (user==self.request_api_user and password==self.request_api_pass):
            handler = self.handlers.get(request.path.decode("UTF-8"))
            if handler:
                d = task.deferLater(reactor, 0.001, lambda: request)
                d.addCallback(handler)
                d.addErrback(self._onRequestFailure, request)
                return TWebServer.NOT_DONE_YET
            return "ERROR :: Request Not Found"
        else:
            message_response= {"code": "1", "message": "Request Authentication Failed"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0

    # Handle GET requests
    def render_GET(self, request):
        session = request.getSession()
        session.touch()
        log.log(logging.NOTICE,"HTTP Request from %s:%s (%s) to %s", request.client.host, request.client.port, session.uid, request.uri)

        if not self.sessions.has_key(session.uid):
            log.log(logging.NOTICE,"New Client Session: %s" % session.uid)
            session._expireCall.cancel()
            session.sessionTimeout = HTTP_SESSION_TIMEOUT
            session.startCheckingExpiration()
            session.notifyOnExpire(self._expireSession)
            session.updates            = []
            session.isAuthenticated    = not self.REST_API.authRequired
            session.username           = None
            self.sessions[session.uid] = session
        handler = self.handlers.get(request.path)
        
        if handler:
            d = task.deferLater(reactor, 0.1, lambda: request)
            d.addCallback(handler)
            d.addErrback(self._onRequestFailure, request)
            return TWebServer.NOT_DONE_YET
        
        return "ERROR :: Request Not Found"

    # API to delete all CallerIDs for a specific trunk
    def API_Delete_ALL_CALLERID(self, request):
        session = request.getSession()
        user=session.user_send
        ipadd=session.ipadd_send
        try:
            data_json=json.loads(session.data_send)
        except ValueError as un:
            log.log(logging.NOTICE,"##API_Delete_ALL_CALLERID JSON error");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;
        try:
            trunk_name=data_json['trunk_name']
        except NameError:
            log.log(logging.NOTICE,"##API_Delete_ALL_CALLERID JSON error parameters");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;

        if(del_pstn_callerid_all_by_trunk(conn,self.index_callerid,trunk_name)!=-1):
            message_response= {"code": "0", "message": "DELETED ALL CALLERID IN: "+trunk_name}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()
            return 0;    
        else:
            message_response= {"code": "1", "message": "CALLERID IN "+ trunk_name +" CAN NOT DELETED!"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()
            return 0;    

    # API to sync CallerIDs from MySQL database to Redis
    def API_SYNC_CALLERID_FROM_DB(self, request):
        session = request.getSession()
        user=session.user_send
        ipadd=session.ipadd_send
        try:
            data_json=json.loads(session.data_send)
        except ValueError as un:
            log.log(logging.NOTICE,"##API_SYNC_CALLERID_FROM_DB JSON error");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;
        try:
            trunk_name=data_json['trunk_name']
        except NameError:
            log.log(logging.NOTICE,"##API_SYNC_CALLERID_FROM_DB JSON error parameters");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;

        if(del_pstn_callerid_all_by_trunk(conn,self.index_callerid,trunk_name)!=-1):
            if (self.mysql_conn is None) or (not self.mysql_conn.is_connected()):
                self.mysql_conn = mysql.connector.connect(user=self.mysql_user, password=self.mysql_pass, host=self.mysql_host, database=self.mysql_database)
            try:
                cursor_log = self.mysql_conn.cursor(buffered=True, dictionary=True)
                query_log=("SELECT * FROM pstn_callerid WHERE trunk=%s")
                log.log(logging.NOTICE,query_log,trunk_name)
                cursor_log.execute(query_log,(trunk_name,))
                result = cursor_log.fetchall()    
                if (result is not None) and (cursor_log.rowcount):
                    i=0;
                    for row in result:
                        i=i+1;
                        agent_id=str(row['callerid'])
                        route_number=str(row['route_number'])
                        status=int(row['active'])
                        trunk_name=str(row['trunk'])
                        if(i==1):
                            add_callerid_default_redis(conn, agent_id,route_number,trunk_name)

                        agent_infor =  {
                            "callerid":{
                                "name": agent_id,
                                "route_number": route_number,
                                "calls_count": 0,
                                "failed_count":0,
                                "busy_count":0,
                                "status":status,
                                "lastcall":"",
                                "TRUNK_NAME": trunk_name,
                            }
                        }
                        if not add_callerid_to_redis(conn, index, agent_id,agent_infor):
                            log.log(logging.NOTICE,"!!!!!FAILED ADD Callerid: "+agent_id)

            finally:
                log.log(logging.NOTICE,"finally 22")

            message_response= {"code": "0", "message": "SYNC SUCCESS ALL CALLERID FROM DB IN: "+trunk_name}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()
            return 0;    

    # API to replace CallerIDs in the system
    def API_REPLACE_CALLERID(self, request):
        session = request.getSession()
        user=session.user_send
        ipadd=session.ipadd_send
        try:
            data_json=json.loads(session.data_send)
        except ValueError as un:
            log.log(logging.NOTICE,"##API_REPLACE_CALLERID JSON error");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;
        try:
            for trunk in data_json:
                if trunk=='OPS_TRUNK':
                    route_number='92'
                if trunk=='OPS_TRUNK_DR':
                    route_number='';
                for callerid_index in data_json[trunk]:
                    callerid=data_json[trunk][callerid_index]
                    query_insert=f"INSERT IGNORE INTO pstn_callerid SET callerid='{callerid}', trunk_name='{trunk}', route_number='{route_number}'"
                    print(query_insert)

        except NameError:
            log.log(logging.NOTICE,"##API_REPLACE_CALLERID JSON error parameters");
            message_response= {"code": "1", "message": "JSON input Error"}
            log.log(logging.NOTICE,"##Response: %s",json.dumps(message_response))
            threading.Thread(target=self.API_log_request,kwargs={"path":request.path,"data":session.data_send,"user":user,"ipadd":ipadd,"data_return":json.dumps(message_response)}).start()
            request.write(json.dumps(message_response).encode('utf-8'))
            request.finish()    
            return 0;

# Main REST API class for server management
class REST_API:
    configFile         = None
    mysql_conn=None

    def __init__(self, configFile):
        log.log(logging.NOTICE, "Initializing REST_API LISTENER")
        self.configFile = configFile
        self.__parseREST_APIConfig()
        
    def __start(self):
        log.log(logging.NOTICE,"Starting REST_API LISTENER...")
    
    def onLoginSuccess(self, ami):
        log.log(logging.NOTICE, "LISTENER started...")
        
    def onLoginFailure(self, reason):
        log.error("LISTENER Failed to start, reason: %s" % (reason.getErrorMessage()))

    # Parse configuration file
    def __parseREST_APIConfig(self):
        log.log(logging.NOTICE, 'Parsing config file %s' % self.configFile)
        
        config = MyConfigParser()
        config.read(self.configFile)
        
        # Load MySQL configuration
        self.mysql_host = config.get('global', 'mysql_host')        
        self.mysql_user = config.get('global', 'mysql_user')
        self.mysql_pass = config.get('global', 'mysql_pass')
        self.mysql_database = config.get('global', 'mysql_database')

        # Load API authentication configuration
        self.request_api_user=config.get('global', 'request_api_user')        
        self.request_api_pass=config.get('global', 'request_api_pass')

        self.call_api_user=config.get('global', 'call_api_user')        
        self.call_api_pass=config.get('global', 'call_api_pass')
        self.call_api_link=config.get('global', 'call_api_link')
        self.call_api_link_finish=config.get('global', 'call_api_link_finish')

        self.RecordingLink=config.get('global', 'RecordingLink')

        # Configure HTTP server
        self.bindHost    = config.get('global', 'bind_host')
        self.bindPort    = int(config.get('global', 'bind_port'))
        self.http        = REST_APIHTTP(self.bindHost, self.bindPort)
        self.http.REST_API = self
        
        # Pass configuration to HTTP server
        self.http.mysql_host = config.get('global', 'mysql_host')        
        self.http.mysql_user = config.get('global', 'mysql_user')
        self.http.mysql_pass = config.get('global', 'mysql_pass')
        self.http.mysql_database = config.get('global', 'mysql_database')
        self.http.mysql_conn=self.mysql_conn;

        self.http.request_api_user=config.get('global', 'request_api_user')        
        self.http.request_api_pass=config.get('global', 'request_api_pass')

        self.http.call_api_user=config.get('global', 'call_api_user')        
        self.http.call_api_pass=config.get('global', 'call_api_pass')
        self.http.call_api_link=config.get('global', 'call_api_link')
        self.http.call_api_link_finish=config.get('global', 'call_api_link_finish')

        self.http.RecordingLink=config.get('global', 'RecordingLink')

        # License verification
        license=config.get('global', 'license_key')
        __a = __b.b64decode(license[1:-1]).decode().split("=")
        __k = 1
        if len(__a) > 1:
            __x = int(__a[1])
            __t = int(__d.timestamp(__d.now()))
            if __t > __x:
                __k = 0
                __l.info('License_key is expired!')
                __s.exit(1)
        
        # Start HTTP server
        self.site        = TWebServer.Site(self.http)
        reactor.listenTCP(self.bindPort, self.site, 50, self.bindHost)
        
        # Start server
        self.__start()

    # Log API calls to MySQL
    def API_log_call(self,**kw):
        if (self.mysql_conn is None) or (not self.mysql_conn.is_connected()):
            self.mysql_conn = mysql.connector.connect(user=self.mysql_user, password=self.mysql_pass, host=self.mysql_host, database=self.mysql_database)
        try:
            cursor_log = self.mysql_conn.cursor(buffered=True)
            query_log=("INSERT INTO API_log_call SET datecall=NOW(), path='"+(kw.get('path'))+"', data_send='"+kw.get('data_send')+"', status_code='"+kw.get('status_code')+"', data_return='"+str(kw.get('data_return').encode('ascii',errors='ignore'))+"'")
            log.log(logging.NOTICE,query_log)
            cursor_log.execute(query_log)
            self.mysql_conn.commit()
        finally:
            log.log(logging.NOTICE,"finally 22")

# Daemon process management
REST_API_PID_FILE = '/var/run/REST_API.pid'
def createDaemon():
    if os.fork() == 0:
        os.setsid()
        if os.fork() == 0:
            os.chdir(os.getcwd())
            os.umask(0)
        else:
            os._exit(0)
    else:
        os._exit(0)
    
    pid = os.getpid()
    print ('\nREST_API daemonized with pid %s' % pid)
    f = open(REST_API_PID_FILE, 'w')
    f.write('%s' % pid)
    f.close()

# Main function to run the REST API server
def RunREST_API(MM):
    global logging
    global log

    # Parse command line options
    opt = optparse.OptionParser()
    opt.add_option('--config',
        dest    = "configFile",
        default = '/etc/OPS.conf',
        help    = "use this config file instead of /etc/OPS.conf"
    )
    opt.add_option('--info',
        dest   = "info",
        action = "store_true",
        help   = "display INFO messages"
    )
    opt.add_option('--debug',
        dest   = "debug",
        action = "store_true",
        help   = "display DEBUG messages"
    )
    opt.add_option('--debug-ami',
        dest = "debugAMI",
        action = "store_true",
        help = "display DEBUG messages for AMI Factory"
    )
    opt.add_option('--dump-objects',
        dest   = "dump_objects",
        action = "store_true",
        help   = "display DEBUG messages"
    )
    opt.add_option('--colored',
        dest   = "colored",
        action = "store_true",
        help   = "display colored log messages"
    )
    opt.add_option('--daemon',
        dest   = "daemon",
        action = "store_true",
        help   = "deamonize (fork in background)"
    )
    opt.add_option('--logfile',
        dest    = "logfile",
        default = "/data/logs/REST_API.log",
        help    = "use this log file instead of /var/log/REST_API.log"
    )
    opt.add_option('--stop',
        dest   = "stop",
        action = "store_true",
        help   = "stop REST_API (only in daemon mode)"
    )
    
    (options, args) = opt.parse_args()

    # Handle stop command
    if options.stop:
        if os.path.exists(REST_API_PID_FILE):
            pid = open(REST_API_PID_FILE, 'r').read()
            os.unlink(REST_API_PID_FILE)
            os.popen("kill -TERM %d" % int(pid))
            print ("REST_API stopped...")
            sys.exit(0)
        else:
            print ("REST_API is not running as daemon...")
            sys.exit(1)
        sys.exit(2)
    
    # Handle daemon mode
    if options.daemon:
        createDaemon()
        
    # Configure logging levels
    if options.info:
        logging.getLogger("").setLevel(logging.INFO)
    
    if options.debug:
        logging.getLogger("").setLevel(logging.DEBUG)
                
    if options.dump_objects:
        logging.DUMPOBJECTS = True
        
    if options.colored:
        logging.COLORED = True
        logging.FORMAT  = "[%(asctime)s] %(levelname)-19s :: %(message)s"
        
    # Configure log handler
    _logHandler     = None
    if options.debug:
        _logHandler = logging.StreamHandler(sys.stdout)    
    else:
        logfile = '/var/log/REST_API.log'
        _logHandler = logging.FileHandler(logfile)

    logging.getLogger("").addHandler(_logHandler)
    
    global log
    log = logging.getLogger("REST_API")
    
    # Check config file existence
    if not os.path.exists(options.configFile):
        print ('  Config file "%s" not found.' % options.configFile)
        print ('  Run "%s --help" for help.' % sys.argv[0])
        sys.exit(1)
        
    # Start REST API server
    REST_API = MM(options.configFile)
    reactor.run()
    
    _logHandler.close()

# Entry point
if __name__ == '__main__':
    RunREST_API(REST_API)






