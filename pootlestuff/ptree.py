#!/usr/bin/python3
"""
This module provides a class for node based trees, the class provided can be used as a base or mixin
for hierarchical object trees.

The primary class inherits from OrderedDict, so child nodes can be selected using standard dict notation.
In addition __getitem__ is redefined to allow filesystem like navigation using '..' and '/'. This does mean
nodenames are expected to be strings and that '/'  and '..' can't be used as part of node names.

In addition (because it is based on OrderedDict) slices of the node's children can be extracted. Note though that
this returns a straight OrderedDict of the children, not a new instance of the originating class (trying to 
return a new treeob would imply nodes having multiple parents which is a whole new level of complexity!)

Examples:
    node['childx']      - returns the child node named 'childx' of the current node.
    node['../siblingx'] - returns the sibling node named 'siblingx' of the current node - that is the 
                          child node 'siblingx' of the parent of the current node.
    node[1:-3]          returns an OrderedDict of the second to (last-3) children of this node
"""

from collections import Hashable
from collections import OrderedDict

class treeob(OrderedDict):
    """
    A class that places an object within a tree. Each node is basically a dict (empty for leaf nodes)
    """
    hiernamesep='/'
    
    def __init__(self, *, name, parent, app, childdefs=None): # * forces all args to be used as keywords
        """
        Creates a node and links it from the parent (if present)

        name        : a hashable name for the node
        
        parent      : if not None, then the child will be added as an offspring of this parent
        
        app         : the top parent (root node) of the tree, can hold various tree constant info, None only
                      for the root node itself.
        
        childdefs   : iterable of definitions for child nodes, each to be the kwargs for calling makeChild

        raises ValueError is the parent already has a child with this name, or if the name is not Hashable
        """
        assert isinstance(name, Hashable), 'the name given for variable {} is not hashable'.format(name)
        self.name=name
        self.parent=parent
        self.app=self if app is None else app
        super().__init__()
        if not parent is None:
            parent[self.name]=self
        if not childdefs is None:
            for cdef in childdefs:
                self.makeChild(**cdef)

    def makeChild(self, _cclass, **kwargs):
        """
        default makeChild creates a child with parent and app defined automatically.
        
        Its parent will be the 'self' calling makeChild and app will be replicated from 'self'
        
        _cclass defines the type of object to be created (presumably inheriting from treeob)
        
        All other arguments are passed through to _cclass' constructor.
        """
        try:
            return _cclass(parent=self, app=self.app, **kwargs)
        except:
            print('makeChild failed with params', cdef, 'in', self.getHierName())
            raise

    def __getitem__(self, nname):
        """
        redefine __getitem_- to parse use slices or a string for filesystem like syntax.
        """
        if isinstance(nname, slice): # first handle the slice case
            keys=list(self.keys())
            kl=len(keys)
            if nname.start is None:
                start = 0 if nname.step is None or nname.step > 0 else kl-1
            else:
                start = nname.start if nname.start >=0 else nname.start+kl
                if start < 0:
                    start=0
                elif start >= kl:
                    start=kl
            if nname.stop is None:
                stop=kl if nname.step is None or nname.step > 0 else -1
            else:
                stop=nname.stop if nname.stop >=0 else nname.stop+kl
                if stop < 0:
                    stop=0
                elif stop >= kl:
                    stop=kl
            rr=range(start, stop) if nname.step is None else range(start,stop,nname.step)
            return OrderedDict(((keys[ix], self[keys[ix]]) for ix in rr))

        if hasattr(nname, 'split'):  # do a simple test to see if nname is string like
            splitname=nname.split(self.hiernamesep)
            if len(splitname)==1:
                try:
                    return super().__getitem__(nname)
                except KeyError:
                    raise KeyError('key %s not found in %s' % (nname, str(self.keys())))
            cnode=self
            for pname in splitname:
                if pname=='':
                    cnode=self.app
                elif pname=='..':
                    cnode=cnode.parent
                else:
                    try:
                        cnode=cnode.__getitem__(pname)
                    except KeyError:
                        raise KeyError('key %s not found in %s' % (pname, str(cnode.keys())))
            return cnode

        return super().__getitem__(nname)   # if all else fails, treat as a simple key

    def getHierName(self):
        """
        returns the hierarchic name of this variable.
        
        Returns a string using hiernamesep to separate each ancestor's name. 
        """
        if self.parent is None:
            return ''
        else:
            return self.parent.getHierName()+self.hiernamesep+self.name

    def __repr__(self):
        """
        A simple version of __repr__ that tends to be a bit recursive.
        """
        if len(self.keys()) == 0:
            return "{} name={}".format(self.__class__.__name__, self.name)
        else:
            return "{} name={}, children {}".format(self.__class__.__name__, self.name, list(self.keys()))