#!/usr/bin/python3
"""
provides a number of classes (called xxVar) to abstract between application variables and the rest of the world.

Updates are policed and a change notification mechanism is provided.

When a var is updated, the agent param identifies the source of the change and notifications can identify the sources
they are interested in

This base set of Var classes provide core functionality.

Vars form a tree structure (single parent nodes), so each Var has a parent except the top of the tree which has no parent.
"""
import logging, sys, pathlib
from collections import OrderedDict
from enum import Enum
from inspect import signature
from pootlestuff import ptree

class loglvls(Enum):
    VAST    = logging.DEBUG-1 
    DEBUG   = logging.DEBUG
    INFO    = logging.INFO
    WARN    = logging.WARN
    ERROR   = logging.ERROR
    FATAL   = logging.FATAL
    NONE    = 0

class groupVar(ptree.treeob):
    """
    the base for all things made of multiple fields
    """
    def __init__(self, value={}, loglvl=loglvls.NONE, **kwargs):
        """
        For non-leaf nodes of the tree, handles setup and access to groups of Vars

        value           : a dict with the initial values for the fields, the dict keys should be a (sub)set of the childdefs names
        """
        if loglvl is None or loglvl is loglvls.NONE:
            self.loglvl=1000
        else:
            self.loglvl=loglvl.value if isinstance(loglvl, loglvls) else loglvl
        if not value is None and len(value) > 0:
            self.prevals=value
        super().__init__(**kwargs)
        if hasattr(self, 'prevals'):
            del self.prevals

    def makeChild(self, _cclass, name, value=None, **kwargs):
        if hasattr(self, 'prevals') and name in self.prevals and not value is None:
            print('WARNING preval is %s value is %s for child %s' % (self.prevals[name], value, name)) 
        try:
            if issubclass(_cclass, (groupVar, baseVar)) and hasattr(self,'prevals') and name in self.prevals:
                return _cclass(name=name, parent=self, app=self.app, value=self.prevals[name], **kwargs)
            else:
                return _cclass(name=name, parent=self, app=self.app, value=value, **kwargs)
        except:
            print('child constructor fails for xxVar (%s) in (%s), with params %s' % (name, self.getHierName(), kwargs))
            raise

    def getValue(self):
        """
        returns a dict with the values for all children
        """
        return OrderedDict([(n, v.getValue()) for n,v in self.items()])

    def getFiltered(self, filter):
        """
        returns a dict with the values for all children with the given filter.
        
        Note groupvars always cascade this down the tree, the filter property only applies to baseVar
        derived classes.
        """
        dlist={}
        for n,v in self.items():
            if  hasattr(v, 'getFiltered'):
                vdict=v.getFiltered(filter)
                if not vdict is None:
                    dlist[n] = vdict
            elif hasattr(v, 'filters') and filter in v.filters:
                dlist[n] = str(v.getValue())
        return dlist if len(dlist) > 0 else None

    def setValue(self, value, agent):
        """
        uses the value dict to update the value of all children, value can contain a subset of the children
        """
        if agent in self.app.agents:
            if isinstance(value, loglvls):
                self.loglvl=value.value
            for n, v in value.items():
                assert n in self
                self.setValue(v, agent)
        else:
            raise RuntimeError('agent {} not known in setting var {}'.format(agent, self.name))

    def __repr__(self):
        return "{} is a {}".format(self.name, type(self).__name__)

    def log(self, level, *args, **kwargs):
        if (isinstance(level,loglvls) and level.value >= self.loglvl) or level >= self.loglvl:
            self.app.log(level, *args, **kwargs)

class rootVar(groupVar):
    """
    the root of the tree has a couple of extras
    """
    def __init__(self, *, agentlist, logformat, loglvl, **kwargs):
        if len(agentlist) == 0:
            raise ValueError('agent list cannot be empty')
        self.agents=agentlist
        self.logformat=logformat
        if loglvl is None or loglvl is loglvls.NONE:
            self.loglvl=1000
        else:
            self.logger=logging.getLogger(__loader__.name+'.'+type(self).__name__)
            self.loglvl=loglvl.value if isinstance(loglvl, loglvls) else loglvl
            self.logger.setLevel(self.loglvl)
        super().__init__(**kwargs)

    def log(self, level, msg, *args, **kwargs):
        if self.logger:
            self.logger.log(level, msg, *args, **kwargs)

class baseVar(ptree.treeob):
    """
    A base class for single named variables with additional info that enables forms to be easily assembled.
    
    The current value is held in a standard (for each type of var) single format which is always accessed via
    _getVar and setVar.
    """
    def __init__(self, *, value=None, fallbackValue=None,
                onChange=None, formatString='{value:}', enabled=True, filters=None,
                loglvl=loglvls.NONE, **kwargs):
        """
        value           : the initial value for the var (if invalid the fallbackValue is used)
        
        fallbackValue   : if, during initialisation, the value is invalid, this value is used
                          
        onChange        : notification function called when the var's value changes, the function is a callable
                          with four named parameters:
                            oldValue: previous value
                            newValue: new value
                            var     : this class instance
                            agent   : the agent that triggered the change
                          
                          A 2-tuple, first element is function to call, second is agent(s) which can cause notification
                          
                          Note agent can be a list or a single value.

        formatString    : This is used as the formatString for this Var when a string 
                            representation is required. Format is called with 2 named params
                            value:  Current canonical value (via _getVar)
                            var  : this object

        enabled         : if True, field is enabled (for the user), otherwise it is disabled

        loglvl          : set to a python logging value to get logging for this field.

        various Exceptions can be raised.
        """
        self.loglvl=1000 if loglvl is None or loglvl is loglvls.NONE else loglvl.value if isinstance(loglvl, loglvls) else int(loglvl)
        if not hasattr(self, '_lvvalue'):
            self._lvvalue=None           # this is the place we keep the value of the variable - always access
                                         # via _getVar / _setVar
        super().__init__(**kwargs)
        self.onChange={}                # setup empty notify set then set the value before adding notifications
        self.enabled=enabled
        self.setInitialValue(value, fallbackValue)
        if not filters is None:
            self.filters=filters
        if not onChange is None:
            self.addNotify(*onChange)
        self.formatString = formatString
        self.setupLogMsg()

    def setInitialValue(self, value, fallbackValue):
        """
        sets up the value during construction
        """
        try:
            self.setValue(value, agent=self.app.agents[0])
            return
        except:
            pass
        try:
            self.setValue(fallbackValue, agent=self.app.agents[0])
        except:
            self.app.criticalreport('setup var {}, fallbackValue {} failed'.format(self.getHierName(), fallbackValue))
            raise

    def addNotify(self, func, agents):
        """
        Adds a single notification function that will be called when the canonical value of the var is changed using the given view.
        
        func    : a callable with parameters 'var', 'agent', 'newValue' and 'oldValue', any other parameters must not be mandatory.
                  can also be a string in which case must be the name of a member function on the app.
        
        agents  : can can be a single item, or a list of items or a single '*' for all agents.
                    Only changes from this / these agents will trigger the callback.
        
        returns Nothing
        
        raises: ValueError for various inconsistencies in the parameters
        """
        if isinstance(agents,str):
            if agents=='*':
                self.addNotify(func, self.app.agents)
                return
            if not agents in self.app.agents:
                raise ValueError('the agent {} requested in addNotify for var of type {} is not known to this tree -{}'.format(
                    agents, type(self).__name__, self.app.agents))
            if isinstance(func,str):
                try:
                    f=getattr(self.app, func)
                except AttributeError:
                    raise ValueError('the function {} requested in addNotify for var of type {} is not a member of the app {}'.format(
                    func, type(self).__name__, type(self.app).__name__))
            else:
                f=func
            if callable(f):
                sig = signature(f)
                if 'var' in sig.parameters and 'agent' in sig.parameters and 'oldValue' in sig.parameters and 'newValue' in sig.parameters:
                    if agents in self.onChange:
                        self.onChange[agents].append(f)
                    else:
                        self.onChange[agents]=[f]
                else:
                    raise ValueError("the function {} does not have named parameters ('var' and/or  'agent') for of type {}".format(
                        f.__name__, type(self).__name__))
            else:
               raise ValueError("the 'func' parameter ({}) for var of type {} is not callable".format(f, type(self).__name__))
        else:
            for v in agents:
                self.addNotify(func, v)

    def removeNotify(self, func, agents):
        if agents=='*':
            self.removeNotify(func, self.app.agents)
            return
        if isinstance(agents, str):
            if not agents in self.app.agents:
                raise ValueError('the agent {} requested in removeNotify for var of type {} is not known to this tree -{}'.format(
                    agents, type(self).__name__, self.app.agents))
            if isinstance(func,str):
                try:
                    f=getattr(self.app, func)
                except AttributeError:
                    raise ValueError('the function {} requested in removeNotify for var of type {} is not a member of the app {}'.format(
                    func, type(self).__name__, type(self.app).__name__))
            else:
                f=func
            flist=self.onChange[agents]
            find=flist.index(f)
            flist.pop(find)
        else:
            for a in agents:
                self.removeNotify(func,a)

    def setupLogMsg(self):
        """
        log message generated when var created 
        """
        if self.loglvl <= logging.INFO:
            self.log(logging.INFO, 'setup var {}, with value {}'.format(self.name, self.getValue()))

    def __repr__(self):
        return "{}(value={}, loglvl={})".format(self.__class__.__name__, self.getValue(), self.loglvl)

    def __str__(self, view=None):
        try:
            return self.formatString.format(value=self.getValue(),var=self)
        except:
            emsg='FAIL in field {} of type {} using format string >{}< with  value={}'.format(self.getHierName(), type(self).__name__, self.formatString, self.getValue())
            if self.loglvl <= loglvlvs.FATAL:
                self.log(logging.FATAL, emsg)
            else:
                print(emsg)
            raise

    def getValue(self):
        """
        fetches the var's value.
        """
        return self._lvvalue

    def setValue(self, value, agent):
        """
        Sets the var's value after validating the value. Calls any onChange callbacks
        if the value changes.
        
        Uses function validValue to check the value is OK and do things like clamping or wrapping the value
        
        value: new value
        
        returns True if the value changes, else False
        
        raises ValueError if the value is not valid
        raises RuntimeError if the agent is not in the known list of agents
        """
        if agent in self.app.agents:
            oldValue=self.getValue()
            newValue=self.validValue(value, agent) # validates the value (raising ValueError if nasty) and returns a correct value
            if newValue==self._lvvalue:
                if self.loglvl <= logging.DEBUG:
                    self.log(10, 'var {} agent {} with value {} is unchanged as {}'.format(self.name, agent, value, oldValue))
                return False
            self._lvvalue=newValue
            if self.loglvl <= logging.DEBUG:
                self.log(10, 'var {} agent {} with value {} updated from {} to {}'.format(self.name, agent, value, oldValue, newValue))
            self.notify(agent=agent, oldValue=oldValue, newValue=newValue)
            return True
        else:
            raise RuntimeError('agent {} not known in setting var {}'.format(agent, self.name))

    def notify(self, agent, oldValue, newValue):
        if agent in self.onChange:
            for f in self.onChange[agent]:
                f(oldValue=oldValue, newValue=newValue, agent=agent, var=self)

    def validValue(self, value, agent):
        raise NotImplementedError()

    def log(self, level, *args, **kwargs):
        if level >= self.loglvl:
            self.app.log(level, *args, **kwargs)

class textVar(baseVar): 
    """
    A refinement of baseVar for text strings.
    """
    def validValue(self, value, agent):
        """
        value   : the requested new value for the field, can be anything that str() takes.
        
        agent   : who asked for then change (ignored here)
        
        returns : the valid new value (this is always a str)
        
        raises  : Any error that str() cam raise
        """
        if value is None:
            raise ValueError('None is not a valid textVar value for var %s' %self.getHierName())
        return str(value)

class folderVar(baseVar):
    """
    The value is a pathlib path to a folder (subfolders are created automatically).
    """
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

    def currentfilenames(self, includes=None, excludes=None):
        """
        returns names of files currently in this folder
        """
        return [pp.name for pp in self.getValue().iterdir() if pp.is_file() and 
                    (True if includes is None else [1 for x in includes if pp.name.endswith(x)]) and 
                    (True if excludes is None else [1 for x in excludes if not pp.name.endswith(x)])]

class floatVar(baseVar):
    """
    A refinement of baseVar that restricts the value to numbers - simple floating point.
    """
    def __init__(self, *, maxv=sys.float_info.max, minv=-sys.float_info.max, clamp=False, **kwargs):
        """
        Makes a float given min and max values. The value can be set to clamp
        
        minv        : the lowest allowed value - use 0 to allow only positive numbers
        
        maxv        : the highest value allowed

        clamp       : if True all values are accepted for updated, but are restricted to be between minv and maxv
        """
        self.maxv=float(maxv)
        self.minv=float(minv)
        self.clamp=clamp==True
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
        if self.clamp:
            return self.minv if av < self.minv else self.maxv if av > self.maxv else av
        if self.minv <= av <= self.maxv:
            return av
        raise ValueError('value {} is outside range {} to {} for var {}'.format(value, self.minv, self.maxv, self.name))

class intVar(baseVar):
    """
    A refinement of baseVar that restricts the field value to integer numbers optionally within a range.
    """
    def __init__(self, maxv=None, minv=None, clamp=False, **kwargs):
        """
        creates an integer var
        
        maxv: None if unbounded maximum else anything that int() accepts
        
        minv: None if unbounded minimum else anythong that int() accepts
        
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
        raise ValueError('value {} is outside range {} to {} for var {}'.format(value, self.minv, self.maxv, self.name))

    def increment(self, agent, count=1):
        incer=int(count)
        self.setValue(self.getValue()+incer, agent)

class enumVar(baseVar):
    """
    a basevar with a list of possible values, which can be set, and cycled through.
    The internal value is the current index into the list
    """
    def __init__(self, name, vlist, fallbackValue=None, mode='wrap', **kwargs):
        """
        name        : name - passed to superclass used here for exception messages

        vlist       : the list of values the var can have

        mode        :
            'clamp' : add and subtract limit to first and last list entries respectively
            'wrap'  : add and subtract wrap around
            'abs'   : add and subtract raise ValueError at beyond list limits
        """
        if len(vlist)==0:
            raise ValueError('vlist must be some sort of list')
        if mode in ('clamp', 'wrap', 'abs'):
            self.mode=mode
            self.vlist=vlist
            self._lvvalue=vlist[0]
            super().__init__(name=name,  fallbackValue=vlist[0] if fallbackValue is None else fallbackValue, **kwargs)
        else:
            raise ValueError('mode {} not in ('','','') for var {}')

    def validValue(self, value, agent):
        """
        value   : the requested new value for the field, should be a value in the current list
        
        agent   : who asked for then change (ignored here)

        returns : the valid new value (this is always an int = the index into the list matching the value)
        
        raises  : ValueError if the provided value is invalid
        """
        return self.vlist.index(value)

    def getValue(self):
        try:
            return self.vlist[self._lvvalue]
        except TypeError:
            return self.vlist[0]

    def getIndex(self):
        if 0 <= self._lvvalue <= len(self.vlist):
            return self._lvvalue
        else:
            return 0

    def setIndex(self, index, agent):
        """
        Sets the var's value using the index in to vlist. Allows app code
        to remain independent of the text used for the various values
        """
        self.setValue(self.vlist[index], agent)

    def increment(self, incval, agent):
        newind=self._lvvalue+incval
        if newind < len(self.vlist):
            pass
        elif self.mode=='abs':
            raise ValueError('cannot increment var {} beyond end of list'.format(self.name))
        elif self.mode=='clamp':
            newind=len(self.vlist)-1
        else:
            newind=newind % len(self.vlist)
        return self.setValue(self.vlist[newind], agent)

    def setVlist(self, vlist, agent):
        """
        updates the underlying vlist and updates the value to match. If the old value is no longer in the list
        then resets to first entry
        """
        if vlist == self.vlist: # check if list has actually changed
            return False
        oldval=self.getValue()
        self.vlist=vlist
        try:
            newi=self.vlist.index(oldval)
        except ValueError:
            newi=0
        if not self.setValue(self.vlist[newi], agent):
            self.notify(agent=agent, oldValue=oldval, newValue=self.vlist[newi])
        return True
