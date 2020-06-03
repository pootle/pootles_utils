#!/usr/bin/python3
"""
This module provides 2 classes derived from http.server.HTTPServer and http.server.BaseHTTPRequestHandler

Together they provide a simple web server capability that can be used for local network access. The underlying
packages are not robust for direct access from the internet.
"""
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs
import http.server
import json, time, errno, threading, logging, pathlib
from pagelink import pageupdatelist

pageid=972

def makepageref():
    """
    returns a unique id that can be used for each page
    """
    global pageid
    pageid +=1
    return str(pageid)

class httpserver(ThreadingMixIn, http.server.HTTPServer):
    """
    http server class based on standard python server.HTTPserver with threading mixin (so we can handle
    multiple concurrent requests) plus specific additional functionality
    
    It allows queues of status messages to be setup which are served up as event streams on request. No session control etc. here though
    
    The overall operation is controlled by a 
    """
    def __init__(self, *args, config, **kwargs):
        self.config=config
        self.logger=logging.getLogger(__loader__.name+'.'+type(self).__name__)
        self.loglvl=logging.DEBUG
        self.logger.setLevel(self.loglvl)
        self.serverrunning=True
        self.activeupdates={}
        self.slock=threading.Lock()
        th=threading.Thread(name='listchecker', target=self.runner)
        th.start()
        super().__init__(*args, **kwargs)

    def close(self):
        try:
            self.config['app'].close()
            self.log(logging.INFO, 'app closed')
        except:
            self.log(logging.ERROR, 'app close crashed', exc_info=True, stack_info=True)
        self.serverrunning=False
        self.shutdown()

    def runner(self):   # watcher to discard unused active update lists
        while self.serverrunning:
            with self.slock:
                deadlist = [k for k, l in self.activeupdates.items() if l.hasexpired()]
                for k in deadlist:
                    uplist=self.activeupdates.pop(k)
                    uplist.closelist()
            time.sleep(5)

    def addupdatelist(self, ulist):
        with self.slock:
            self.activeupdates[ulist.pageid]=ulist
            
    def log(self, level, *args, **kwargs):
        if level >= self.loglvl:
            self.logger.log(level, *args, **kwargs)

    def getupdates(self, qp, pp):
        updid=qp['updatename'][0]
        if updid in self.activeupdates:
            return self.activeupdates[updid].getupdates()
        else:
            return 'kwac'

class httprequh(http.server.BaseHTTPRequestHandler):
    """
    added functionality for handling individual requests.
    
    A new instance of this class is created to process each incoming request to the service, which (if the server
    uses the Threading Mixin) will also be running in a new thread.
    """
    
    def _do_action(self, f, **kwargs):
        """
        internal function that wraps a call to app code in try / except checks the response and sends appropriate
        data back to the client.
        
        If there is an exception in the app code, info is logged and an error response is sent
        
        params:
            f: the funcion to call
            
            all other (keyword) arguments are passed on to f
        
        f should return a dict with the following keys:
            'resp'      : the response code (typically 200)
            'headers'   : a list of 2-tuples, each 2-tuple sent as a header
            'data'      : a string (which will be encoded and sent) or bytes (which will be sent)
        """
        try:
            response=f(**kwargs)
        except:
            response={'resp':500, 'msg':'what could possibly go wring'}
            self.server.log(logging.CRITICAL,'request %s failed' % self.path, exc_info=True, stack_info=True)
        if response['resp']==200:
            self.send_response(200)
            for h in response.get('headers',{}):
                self.send_header(*h)
            rdata=response['data']
            if isinstance(rdata,str):
                rdata=rdata.encode()
            self.send_header('Content-Length', len(rdata))
            self.end_headers()
            self.wfile.write(rdata)
        else:
            self.send_error(response['resp'], response['msg'])

    def _do_datafetch(self, f, **kwargs):
        """
        a very simple wrapper round a function call that passes through the result from the function or
        (if there is an exception), logs the exceotion info and returns None)
        """
        try:
            return f(**kwargs)
        except:
            self.server.log(logging.CRITICAL,'request %s failed' % self.path, exc_info=True)
            return None

    def do_GET(self):
        """
        parses various info about the request runs the code appropriate for the request
        """
        serverconfig=self.server.config     # put the config in a convenient place
        parsedpath=urlparse(self.path)      # and do 1st level parse on the request
        if parsedpath.path.startswith('/static'):                           #if the path starts with static - serve a fixed file
            self.servestatic(statfile=parsedpath.path[len('/static/'):])
            return
        try:
            validrequs=serverconfig['GET']
        except:
            self.server.log(logging.INFO,'config has no GET list')
            self.send_error(501, 'no GET list specified for this server')
            return
        pathlookup=parsedpath.path[1:]      # ditch the leading slash
        if pathlookup in validrequs:
            try:
                requtype, requdata = validrequs[pathlookup]
            except:
                self.server.log(logging.INFO,'GET entry for %s in config failed >%s<' % (self.path, validrequs[pathlookup])) 
                self.send_error(404, 'server config error for the page you have requested! (%s)' %pathlookup)
                return
        else:
            self.server.log(logging.INFO,'no GET entry for %s in config' % self.path) #look for the path ( without the leading '/') in GET dict
            self.send_error(404, 'I know nothing of the page you have requested! (%s)' %pathlookup)
            return
        queryparams={} if parsedpath.query=='' else parse_qs(parsedpath.query)  # and parse the query params (if present) - cos lots will want these
        if requtype=='makestaticpage':
            self._do_action(f=requdata[0], qp=queryparams, pp=parsedpath, **requdata[1])
        elif requtype=='updatewv':
            # user changed a value on web page; this updates the watchables's value by calling the wwlink's webset method.
            # it returns the value as interpreted by the app if successful
            if 't' in queryparams and 'v' in queryparams and 'p' in queryparams and queryparams['p'][0] in self.server.activeupdates:
                updatelist=self.server.activeupdates[queryparams['p'][0]]
                try:
                    resp=updatelist.applyUpdate(queryparams['t'], queryparams['v']) # we expect a dict with 'OK' and 'fail' or 'value'
                except:
                    self.server.log(logging.CRITICAL,'updatewv request %s failed' % self.path, exc_info=True)
                    self.send_error(500, 'update failed!')
                    return
            elif 't' in queryparams and 'v' in queryparams and 'p' in queryparams:
                print('================================================================================================')
                print('invalid pageid in request %s' % queryparams['p'][0])
                self.server.log(logging.ERROR, 'invalid pageid in request %s' % queryparams['p'][0])
                self.send_error(410, 'unknown update list key')
                return
            else:
                self.server.log(logging.WARN, 'missing params in request %s' % list(queryparams.keys()))
                self.send_error(400, 'missing request params')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())

        elif requtype=='makedynampage':
            pagelist=pageupdatelist(pageid=makepageref())
            self._do_action(f=requdata[0], qp=queryparams, pp=parsedpath, pagelist=pagelist, **requdata[1])
            if pagelist.haslinks():
                self.server.addupdatelist(pagelist)

        elif requtype=='updatestream':
            if requdata[0]=='serv':
                func=getattr(self.server, requdata[1])
                print('func is', func)
                kwargs={}
            else:
                func=requdata[0]
                kwargs=requdata[1]
            newdata=self._do_datafetch(f=func, qp=queryparams, pp=parsedpath, **kwargs)
            if not newdata is None:
                running=True
                while running:
                    datats=json.dumps(newdata)
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                    try:
                        self.end_headers()
                        self.wfile.write(('data: %s\n\n' % datats).encode())
                    except Exception as e:
                        running=False
                        if e.errno!=errno.EPIPE:
                            raise
                        else:
                            print(type(e).__name__)
                            print('genstream client %s terminated' % str(self.client_address))
                    time.sleep(3)
                    if not self.server.serverrunning:
                        running=False
                    newdata=self._do_datafetch(f=func, qp=queryparams, pp=parsedpath, **kwargs)
            else:
                self.server.log(logging.INFO, 'request fails with parsedpath >%s<' % str(parsedpath))
                self.send_error(500)
        elif requtype=='camstream':
            print('setup with', requdata)
            try:
                camstreaminfo=requdata()
            except StopIteration:
                self.send_error(402, 'no source for stream')
                return
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            running=True
            self.server.log(30, 'camstreamhandler client %s starts using %s' %   (str(self.client_address), camstreaminfo))
            try:
                while running and not camstreaminfo is None and self.server.serverrunning:
                    try:
                        frame, conttype, datalen=camstreaminfo.nextframe()
                    except StopIteration:
                        running=False
                        self.server.log(30, 'camstreamhandler got StopIteration %s terminated' %   str(self.client_address))
                    if running:
                        try:
                            self.wfile.write(b'--FRAME\r\n')
                            self.send_header('Content-Type', conttype)
                            self.send_header('Content-Length', datalen)
                            self.end_headers()
                            self.wfile.write(frame)
                            self.wfile.write(b'\r\n')
                        except BrokenPipeError:
                            running=False
                self.server.log(30, 'camstreamhandler client %sterminated' %   str(self.client_address))
            except ConnectionError as ce:
                self.server.log(30, 'camstreamhandler client connection lost %s' %  str(self.client_address))
            except Exception as e:
                self.server.log(30, 'camstreamhandler client %s crashed' %   (str(self.client_address)), exc_info=True, stack_info=True)
            if not camstreaminfo is None:
                camstreaminfo.streamends()
        elif requtype=='vidstream':
            tp=requdata['resolve'](qp=queryparams)
            if tp.exists():
                tsize=tp.stat().st_size
                if True:
                    rbits=self.headers.get('Range').strip().split('=')
                    if rbits[0]=='bytes':
                        rstarts, rends=rbits[1].split('-')
                        start=0 if len(rstarts)==0 else int(rstarts)
                        end=tsize-1 if len(rends)==0 else int(rends)
                        if end >=tsize:
                            end=tsize-1
                        if end-start > 65535:
                            end=start+65535
                        with tp.open('rb') as tpo:
                            if start != 0:
                                tpo.seek(start)
                            self.send_response(206)
                            self.send_header(*self.mimetypeforfile('.mp4'))
                            self.send_header('Content-Length', str(end-start+1))
                            self.send_header('Content-Range', 'bytes %s-%s/%s' % (start, end, tsize))
                            self.send_header('Accept-Ranges','bytes')
                            self.end_headers()
                            rdat=tpo.read(end-start)
                            if rdat:
                                self.wfile.write(rdat)
                        return
                    else:
                        print('nobytes!')
            else:
                print('fileooops', str(tp))
                self.send_error(502, 'video would be nice')
        elif requtype=='redirect':
            self.send_response(301)
            self.send_header('Location', requdata)
            self.end_headers()
        elif requtype=='query': # a generic query that calls the func defined in requdata with the params from the http request and returns jsonized response
            if 'fixed' in requdata:
                queryparams.update(requdata['fixed'])
            resp = self._do_datafetch(requdata['func'],**queryparams)
            if resp is None:
                self.send_error(502, "That didn't go well")
            else:
                jdat=json.dumps(resp).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', len(jdat))
                self.end_headers()
                self.wfile.write(jdat)
                print('--------------', jdat)
        else:
            self.server.log(logging.INFO, 'request fails with parsedpath >%s<' % str(parsedpath))
            self.send_error(404)
        return

    def do_POST(self):
        serverconfig=self.server.config    # put the config in a convenient place
        try:
            validrequs=serverconfig['POST']
        except:
            self.send_error(501, 'no POST list specified for this server')
            return
        th=self.headers['Content-Type']
        print('+++++++++++++', self.path)
        if th.startswith('application/json'):
            dlength=int(self.headers['Content-Length'])
            ddata=self.rfile.read(dlength)
            if len(ddata) != dlength:
                print("HELEPELPELPELEPLEPELEPLE")
                self.send_error(501,'oops')
                return
            parsedpath=urlparse(self.path)
            pathlookup=parsedpath.path[1:]      # ditch the leading slash
            if pathlookup in validrequs:
                pathinf=validrequs[pathlookup]
                jdata=json.loads(ddata.decode('utf-8'))
                print(jdata.keys())
                result=pathinf[0](pathinf[1], **jdata)
                # result is a dict with:
                #   resp: the response code - if 200 then good else bad
                #   rdata: (only if resp==200) data (typically a dict) to json encode and return as the data
                #   rmsg: (only if resp != 200) the message to return with the fail code
                if result['resp']==200:
                    datats=json.dumps(result['rdata'])
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(datats.encode('utf-8'))
                else:
                    self.send_error(result['resp'], result['rmsg'])
            else:
                self.send_error(404, ('no page for %s' % self.path[1:]))
        else:
            self.send_error(500,'what is ' + th) 

    def servestatic(self, statfile):
        staticinf=self.server.config['staticroot']
        staticfile=staticinf['path']/statfile
        if staticfile.is_file():
            try:
                sfx=self.mimetypeforfile(staticfile.suffix)
            except:
                self.send_error(501, "no mime type found in server config['mimetypes'] for %s" % staticfile.suffix)
                return
            self.send_response(200)
            self.send_header(*sfx)
            with staticfile.open('rb') as sfile:
                cont=sfile.read()
                self.send_header('Content-Length', len(cont))
                self.end_headers()
                self.wfile.write(cont)
        else:
            self.send_error(404, 'file %s not present or not a file' % str(staticfile))

    def mimetypeforfile(self, fileext):
        return {
        '.css' :('Content-Type', 'text/css; charset=utf-8'),
        '.html':('Content-Type', 'text/html; charset=utf-8'),
        '.js'  :('Content-Type', 'text/javascript; charset=utf-8'),
        '.ico' :('Content-Type', 'image/x-icon'),
#        '.py'  :('Content-Type', 'text/html; charset=utf-8'),   # python template files we assume return html for now
        '.jpg' :('Content-Type', 'image/jpeg'),
        '.png' :('Content-Type', 'image/png'),
        '.mp4' :('Content-Type', 'video/mp4'),
        '.svg' :('Content-Type', 'image/svg+xml'),
        }[fileext]
