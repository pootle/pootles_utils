"""
This module provides classes that support observers, smart value handling and debug functions

All changes to values nominate an agent, and observers nominate the agent making changes they
are interested in.

It supercedes the pvars module
"""
import logging, sys, threading, pathlib, math, json
from enum import Enum, auto as enumauto, Flag

class loglvls(Enum):
    """
    A class for logging levels so data is self identfying
    """
    VAST    = logging.DEBUG-1 
    DEBUG   = logging.DEBUG
    INFO    = logging.INFO
    WARN    = logging.WARN
    ERROR   = logging.ERROR
    FATAL   = logging.FATAL
    NONE    = 0

class myagents(Flag):
    NONE    = 0
    app     = enumauto()
    user    = enumauto()

class wflags(Flag):
    NONE        = 0
    DISABLED    = enumauto()

class watchable():
    """
    provides a 'smart' object that provides basic observer functionality around an object.
    
    Changes to the value can be policed, and updates have to provide an agent that is 
    performing the update. Observers can then request to be notified when the value is changed
    by specific agents.
    """
    def __init__(self, value, app, flags=wflags.NONE, loglevel=loglvls.INFO):
        """
        creates a new watchable. Initialises the internal value and sets an empty observers list
        
        value: the initial value for the object. Not validated!
        
        app  : the app instance for this. Used for logging and for validating agents
        """
        self._val=value
        self.app=app
        self.observers=None
        self.oblock=threading.Lock()
        self.flags=flags
        self.loglevel=loglevel
        self.log(loglvls.DEBUG, 'watchable type %s setup with value %s' % (type(self).__name__, self._val))

    def setValue(self, value, agent):
        """
        Updates the value of a watchable or the loglevel.
        
        if not a loglevel, this validates and converts (if relevant) the requested value.
        
        If the value is valid and different from the current value, checks for and calls
        any observers interested in changes by the given agent.
        """
        if isinstance(value, loglvls):
            self.loglevel = value
            return False
        if isinstance(value, wflags):
            self.flags=value
            return False
        assert isinstance(agent, self.app.agentclass), 'unexpected value %s of type %s in setValue' % (value, type(value).__name__)
        newvalue=self.validValue(value, agent)
        if newvalue != self._val:
            self.notify(newvalue, agent)
            return True
        else:
            self.log(loglvls.DEBUG,'value unchanged (%s)' % self._val)
            return False

    def getValue(self):
        return self._val

    def validValue(self, value, agent=None):
        """
        validates the given value and returns the canonical value which will be stored.
        
        Raise an exception if the value is invalid
        
        'Real' classes must implement this
        """
        raise NotImplementedError()

    def notify(self, newvalue, agent):
        if self.observers:
            clist=None
            with self.oblock:
                if agent in self.observers:
                    clist=self.observers[agent].copy()
            oldvalue=self._val
            self._val=newvalue
            if clist:
                for ob in clist:
                    ob(oldValue=oldvalue, newValue=newvalue, agent=agent, watched=self)
            self.log(loglvls.DEBUG,'value changed (%s)- observers called' % self._val)
        else:
            self._val=newvalue
            self.log(loglvls.DEBUG,'value changed (%s)- no observers' % self._val)

    def addNotify(self, callback, agent):
        assert callable(callback)
        assert isinstance(agent, self.app.agentclass)
        self.log(loglvls.DEBUG,'added watcher %s' % callback.__name__)
        with self.oblock:
            if self.observers is None:
                self.observers={agent:[callback]}
            elif agent in self.observers:
                self.observers[agent].append(callback)
            else:
                self.observers[agent]=[callback]
        
    def dropNotify(self, callback, agent):
        with self.oblock:
            aglist=self.observers[agent]
            ix = aglist.index(callback)
            aglist.pop(ix)

    def log(self, loglevel, *args, **kwargs):
        """
        request a logging operation. This does nothing if the given loglevel is < the loglevel set in the object
        """
        if loglevel.value >= self.loglevel.value:
            self.app.log(loglevel, *args, **kwargs)

class textWatch(watchable): 
    """
    A refinement of watchable for text strings.
    """
    def validValue(self, value, agent):
        """
        value   : the requested new value for the field, can be anything that str() takes, but None will fail.
        
        agent   : who asked for then change (ignored here)
        
        returns : the valid new value (this is always a str)
        
        raises  : Any error that str() can raise
        """
        if value is None:
            raise ValueError('None is not a valid textVar value')
        return str(value)

class floatWatch(watchable):
    """
    A refinement of watchable that restricts the value to numbers - simple floating point.
    """
    def __init__(self, *, maxv=sys.float_info.max, minv=-sys.float_info.max, clamp=False, allowNaN=True, **kwargs):
        """
        Makes a float given min and max values. The value can be set clamped to prevent failures 
        
        minv        : the lowest allowed value - use 0 to allow only positive numbers
        
        maxv        : the highest value allowed

        clamp       : if True all values that can float() are accepted for updating, but are restricted to be between minv and maxv
        """
        self.maxv=float(maxv)
        self.minv=float(minv)
        self.clamp=clamp==True
        self.allowNaN=allowNaN
        super().__init__(**kwargs)

    def validValue(self, value, agent):
        """
        value   : the requested new value for the field, can be anything that float(x) can handle that is between minv and maxv
                    - or if clamp is True, any value
        
        agent   : who asked for then change (ignored here)

        returns : the valid new value (this is always a float)
        
        raises  : ValueError if the provided value is invalid
        """
        av=float(value)
        if math.isnan(av) and self.allowNaN:
            return av
        if self.clamp:
            return self.minv if av < self.minv else self.maxv if av > self.maxv else av
        if self.minv <= av <= self.maxv:
            return av
        raise ValueError('value {} is outside range {} to {}'.format(value, self.minv, self.maxv))

class intWatch(watchable):
    """
    A refinement of watchable that restricts the field value to integer numbers optionally within a range.
    """
    def __init__(self, maxv=None, minv=None, clamp=False, **kwargs):
        """
        creates an integer var
        
        maxv: None if unbounded maximum else anything that int() accepts
        
        minv: None if unbounded minimum else anything that int() accepts
        
        clamp: if True then value is clamped to maxv and minv (either can be None for unbounded in either 'direction'
        """
        self.maxv=maxv if maxv is None else int(maxv)
        self.minv=minv if minv is None else int(minv)
        self.clamp=clamp==True
        super().__init__(**kwargs)
 
    def validValue(self, value, agent):
        """
        value   : the requested new value for the field, can be anything that int() can handle that is between minv and maxv
                    - or if clamp is True, any value
        
        agent   : who asked for then change (ignored here)

        returns : the valid new value (this is always an int)
        
        raises  : ValueError if the provided value is invalid
        """
        av=int(value)
        if self.clamp:
            if not self.minv is None and av < self.minv:
                return self.minv
            if not self.maxv is None and av > self.maxv:
                return self.maxv
            return av
        if (self.minv is None or av >= self.minv) and (self.maxv is None or av <= self.maxv):
            return av
        raise ValueError('value {} is outside range {} to {} for watchable'.format(value, self.minv, self.maxv))

    def increment(self, agent, count=1):
        incer=int(count)
        newval=self.getValue()+incer
        self.setValue(newval, agent)
        return newval

class enumWatch(watchable):
    """
    a watchable that can only take a specific set of values, and can wrap / clamp values.
    
    It also allows values to be cycled through
    """
    def __init__(self, vlist, wrap=True, clamp=False, **kwargs):
        self.wrap=wrap == True
        self.clamp=clamp == True
        self.vlist=vlist
        super().__init__(**kwargs)

    def validValue(self, value, agent):
        if not value in self.vlist:
            raise ValueError('value (%s) not valid' % value)
        return value

    def getIndex(self):
        return self.vlist.index(self._val)

    def increment(self, agent, inc=1):
        newi=self.getIndex()+inc
        if 0 <= newi < len(self.vlist):
            return self.setValue(self.vlist[newi], agent)
        elif self.wrap:
            if newi < 0:
                useval = self.vlist[-1]
            else:
                useval = self.vlist[0]
        elif self.clamp:
            if newi < 0:
                useval = self.vlist[0]
            else:
                useval = self.vlist[-1]
        else:
            raise ValueError('operation exceeds list boundary')
        self.setValue(useval, agent)

    def setIndex(self, ival, agent):
        if 0 <= ival < len(self.vlist):
            return self.setValue(self.vlist[ival], agent)
        else:
            raise ValueError('index out of range')
        
class btnWatch(watchable):
    """
    For simple click buttons that always notify
    """
    def setValue(self, value, agent):
        if isinstance(value, loglvls):
            self.loglevel = value
            return False
        if isinstance(value, wflags):
            self.flags=value
            return False
        assert isinstance(agent, self.app.agentclass)
        self.notify(self._val, agent)
        return True

class folderWatch(watchable):
    """
    Internally. the value is a pathlib path to a folder (subfolders are created automatically).
    """
    def __init__(self, value, **kwargs):
        super().__init__(value=self.validValue(value, None), **kwargs)

    def validValue(self, value, agent):
        tp=pathlib.Path(value).expanduser()
        if tp.exists():
            if tp.is_dir():
                return tp
            else:
                raise ValueError('%s is not a folder' % str(tp))
        else:
            tp.mkdir(parents=True, exist_ok=True)
            return tp

    def getValue(self):
        return str(self._val)

    def getFolder(self):
        return self._val

    def currentfilenames(self, includes=None, excludes=None):
        """
        returns names of files currently in this folder
        """
        return [pp.name for pp in self.getValue().iterdir() if pp.is_file() and 
                    (True if includes is None else [1 for x in includes if pp.name.endswith(x)]) and 
                    (True if excludes is None else [1 for x in excludes if not pp.name.endswith(x)])]

class watchablegroup(object):
    def __init__(self, value, wabledefs, loglevel=None):
        """
        value    : dict of preferred values for watchables in this activity (e.g. from saved settings file)
        
        wabledefs: a list of 5-tuples that define each watchable with the following entries:
            0:  name of the watchable
            1:  class of the watchable
            2:  default value of the watchable
            3:  True if the watchable is returned by fetchsettings (as a dict member)
            4:  kwargs to use when setting up the watchable
        """
        self.perslist=[]
        self.loglevel=loglvls.INFO if loglevel is None else loglevel
        for awable in wabledefs:
            ch=self.makeChild(defn=awable, value=awable[2] if value is None else value.get(awable[0], awable[2]))
            if ch is None:
                raise ValueError('child construction failed - see log')
            setattr(self, awable[0], ch)
            if awable[3]:
                self.perslist.append(awable[0])

    def makeChild(self, value, defn):
        """
        returns a new object with this object as the app using a definition list
        
        value    : value for the 
        
        defn: a list of 5-tuples that define each watchable with the following entries:
            0:  name of the watchable   - not used
            1:  class of the watchable
            2:  default value of the watchable - only used if value is None
            3:  True if then watchable is returned by fetchsettings (as a dict member) - not used
            4:  kwargs to use when setting up the watchable
        """
        deflen=len(defn)
        if deflen==4:
            params={}
        elif deflen==5:
            params=defn[4]
        else:
            raise ValueError('there are not 4 or 5 entries in this definition for class %s: %s' % (type(self).__name__, defn))
        try:
            vv=defn[2] if value is None else value
            return defn[1](app=self, value=vv, **params)
        except:
            print('input values:', value)
            self.log(loglvls.ERROR,'class %s exception making variable %s' % (type(self).__name__, defn[0]), exc_info=True, stack_info=True)
        return None

    def fetchsettings(self):
        return {kv: getattr(self,kv).getValue() for kv in self.perslist}

    def applysettings(self, settings, agent):
        for k,v in settings:
            if k in self.perslist:
                getattr(self, k).setValue(v, agent)

class watchablesmart(watchablegroup):
    """
    This class can act as a complete app, or as a part of an app.
    
    For a complete app:
        sets up logging for the app
    
    for a component of an app:
        passes logging calls up to the app.
    """
    def __init__(self, value, app=None, loglevel=loglvls.INFO, **kwargs):
        if app==None: # this is the real (top level) app
            if loglevel is None or loglevel is loglvls.NONE:
                self.logger=None
                print('%s no logging' % type(self).__name__)
            else:
                self.agentclass=myagents
                self.logger=logging.getLogger(__loader__.name+'.'+type(self).__name__)
                chandler=logging.StreamHandler()
                chandler.setFormatter(logging.Formatter(fmt= '%(asctime)s %(levelname)7s (%(process)d)%(threadName)12s  %(module)s.%(funcName)s: %(message)s', datefmt= "%M:%S"))
                self.logger.addHandler(chandler)
                self.logger.setLevel(loglevel.value)
                self.log(loglvls.INFO,'logging level is %s' % loglevel)
            if isinstance(value, str):
                spath=pathlib.Path(value).expanduser()
                if spath.is_file():
                    try:
                        with spath.open('r') as spo:
                            self.startsettings=json.load(spo)
                        self.log(loglvls.INFO,'app settings loaded from file %s' % spath)
                    except:
                        self.log(loglvls.ERROR,'failed to load settings from %s - default values used' % spath, exc_info=True, stack_info=True)
                        self.startsettings={}
                else:
                    self.log(loglvls.INFO,'app settings file %s not found - default values used' % spath)
                    self.startsettings={}
            elif hasattr(value,'keys'):
                self.startsettings=value
                self.log(loglvls.INFO,'using settings from passed object')
            elif value is None:
                self.log(loglvls.INFO,'settings not specified, default values used')
                self.startsettings={}
            else:
                self.log(loglvls.INFO,'setings not processed from passed %s' % type(values).__name__)
                self.startsettings={}
        else:
            self.app=app
            self.agentclass=app.agentclass
            self.startsettings=value
        super().__init__(value=self.startsettings, loglevel=loglevel, **kwargs)

    def log(self, level, msg, *args, **kwargs):
        if hasattr(self,'app'):
            if self.loglevel.value <= level.value:
                self.app.log(level, msg, *args, **kwargs)
        else:
            if self.logger:
                self.logger.log(level.value, msg, *args, **kwargs)
            elif level.value >= loglvls.WARN:
                print(msg) 

    def savesettings(self, oldValue, newValue, agent, watched):
        if hasattr(self, 'app'):
            raise ValueError('only the app level can save settings')
        try:
            setts = self.fetchsettings()
        except:
            self.log(loglvls.WARN,'fetchsettings failed', exc_info=True, stack_info=True)
            setts = None
        if not setts is None:
            try:
                settstr=json.dumps(setts, indent=4)
            except:
                self.log(loglvls.WARN,'json conversion of these settings failed', exc_info=True, stack_info=True)
                self.log(loglvls.WARN,str(setts))
                settstr=None
        if not settstr is None:
            try:
                with self.settingsfrom.open('w') as sfo:
                    sfo.write(settstr)
            except:
                self.log(loglvls.WARN,'save settings failed to write file', exc_info=True, stack_info=True)
                return
            self.log(loglvls.INFO,'settings saved to file %s' % str(self.settingsfrom))

class watchablepigpio(watchablesmart):
    """
    a root class that adds in pigpio setup to watchablesmart
    """
    def __init__(self, app=None, **kwargs):
        """
        if the app has a pio attribute, (an instance of pigpio.pi), that is used otherwise one is set up.
        """
        if not app is None and hasattr(app,'pio'):
            self.pio=app.pio
            self.mypio=False
        else:
            import pigpio
            ptest=pigpio.pi()
            if not ptest.connected:
                raise ValueError('pigpio failed to initialise')
            self.pio=ptest
            self.mypio=True
        if not self.pio.connected:
            raise ValueError('pigpio is not connected')
        super().__init__(app=app, **kwargs)

    def close(self):
        if self.mypio:
            self.pio.stop()
            self.mypio=False
        self.pio=None

class watchableAct(watchablegroup):
    """
    An app can have a number of optional activities (that can have their own threads, watched vars etc.
    
    This class provides useful common bits for such activities. It provides:
        
        A way to set up the watchable variables for the class, using passed in values (for saved settings for example)
        with defaults if a value isn't passed.
        
        A way to automatically retrieve values for a subset of watchable variables (e.g. to save values as a known config)
        
        logging via the parent app using Python's standard logging module
    """
    def __init__(self, app, **kwargs):
        self.app=app
        self.agentclass=app.agentclass
        super().__init__(**kwargs)

    def log(self, loglevel, *args, **kwargs):
        """
        request a logging operation. This does nothing if the given loglevel is < the loglevel set in the object
        """
        if self.loglevel.value <= loglevel.value:
            self.app.log(loglevel, *args, **kwargs)

class watchableApp(object):
    def __init__(self, agentclass=myagents, loglevel=None):
        self.agentclass=agentclass
        if loglevel is None or loglevel is loglvls.NONE:
            self.logger=None
            print('%s no logging' % type(self).__name__)
        else:
            self.logger=logging.getLogger(__loader__.name+'.'+type(self).__name__)
            chandler=logging.StreamHandler()
            chandler.setFormatter(logging.Formatter(fmt= '%(asctime)s %(levelname)7s (%(process)d)%(threadName)12s  %(module)s.%(funcName)s: %(message)s', datefmt= "%M:%S"))
            self.logger.addHandler(chandler)
            self.logger.setLevel(loglevel.value)

    def log(self, level, msg, *args, **kwargs):
        if self.logger:
            self.logger.log(level.value, msg, *args, **kwargs)

