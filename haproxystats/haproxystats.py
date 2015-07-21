import json
import logging
from datetime import datetime
from requests import Request, Session

log = logging.getLogger(__name__)

def to_utf(s):
    return s.encode('utf8')

class HAProxyStatsException(Exception):
    """ Generic HAProxyStats exception """

class HAProxyService(object):
    """
    Generic service object representing a proxy component
    params:
     - fields(list): Fieldnames as read from haproxy stats export header
     - values(list): Stats for corresponding fields given above for this 
                     frontend, backend, or listener
    """
    def __init__(self,fields,values,proxy_name=None):
        self.proxy_name = proxy_name

        #zip field names and values
        self.__dict__ = dict(zip(fields, self._read(values)))

        if self.svname == 'FRONTEND' or self.svname == 'BACKEND':
            self.name = self.pxname
        else:
            self.name =  self.svname

    def _read(self,values):
        """
        Read stat str, convert unicode to utf and string to int where needed
        and return as list
        """
        ret = []

        for v in values:
            if v.isdigit():
                v = int(v)
            if isinstance(v,unicode):
                v = to_utf(v)
            ret.append(v)
    
        return ret

class HAProxyServer(object):
    """
    HAProxyServer object is created for each haproxy server we poll along with
    corresponding frontend, backend, and listener services.
    """
    def __init__(self,base_url,auth=None):
        self._auth = auth
        self.failed = False

        self.name = base_url.split(':')[0]
        self.url = 'http://' +  base_url + '/;csv;norefresh'

    def fetch_stats(self):
        """
        Fetch and parse stats from this Haproxy instance
        """
        self.frontends = []
        self.backends = []
        self.listeners = []

        csv = [ l for l in self._get(self.url).strip(' #').split('\n') if l ]
        if not csv:
            self.failed = True
            return

        #read fields header to create keys
        fields = [ to_utf(f) for f in csv.pop(0).split(',') if f ]
    
        #add frontends and backends first
        for line in csv:
            service = HAProxyService(fields, line.split(','), proxy_name=self.name)

            if service.svname == 'FRONTEND':
                self.frontends.append(service)
            elif service.svname == 'BACKEND':
                service.listener_names = []
                self.backends.append(service)
            else:
                self.listeners.append(service)
    
        #now add listener  names to corresponding backends
        for listener in self.listeners:
            for backend in self.backends:
                if backend.iid == listener.iid:
                    backend.listener_names.append(listener.name)

        self.stats = { 'frontends': [ s.__dict__ for s in self.frontends ],
                       'backends': [ s.__dict__ for s in self.backends ],
                       'listeners': [ s.__dict__ for s in self.listeners ] }

        self.last_update = datetime.utcnow()
    
    def _get(self,url):
        s = Session()
        if None in self._auth:
            req = Request('GET',url)
        else:
            req = Request('GET',url,auth=self._auth)

        try:
            r = s.send(req.prepare(),timeout=10)
        except Exception as e:
            raise HAProxyStatsException(
                    'Error fetching stats from %s:\n%s' % (url,e)
                    )
            return ''

        return r.text

class HaproxyStats(object):
    """
    params:
     - servers(list) - List of haproxy instances defined as
       hostname:port or ip:port
     - user(str) -  User to authenticate with via basic auth(optional)
     - user_pass(str) -  Password to authenticate with via basic auth(optional)
    """
    def __init__(self,servers,user=None,user_pass=None):
        self.servers = [ HAProxyServer(s,auth=(user,user_pass)) for s in servers ]

        self.update()

    def update(self):
        start = datetime.utcnow()

        for s in self.servers:
            s.fetch_stats()

        duration = (datetime.utcnow() - start).total_seconds()
        log.info('Polled stats from %s servers in %s seconds' % \
                (len(self.servers),duration))

        if self.get_failed():
            return False

        return True

    def all_stats(self):
        return { s.name : s.stats for s in self.servers }

    def to_json(self):
        return json.dumps(self.all_stats())

    def get_failed(self):
        return [ s for s in self.servers if s.failed ]
