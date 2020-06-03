# pootles_utils

Various utility modules to do stuff I find useful in different projects.

* watchables        - managed variables with an observer like capability to build dynamic apps (particularly web based) - supercedes pvars and ptree
* webserv           - a command line parser that runs up a web server controlled by a config file and based on basichttpserver (see next line)
* basichttpserver   - derived from http.server provides a simple web server capability with page serving (static and dynamic), live streaming, file streaming
                      and ability to dynamically update web pages. Provides clean separation of application code from user interface code.
* ptree - a hierarchic tree of named nodes where children ore an ordered dict and can be referenced using filesystem like syntax and slicing
* netinf - pure python to extract info about network interfaces on linux boxes
* pvars - managed variables for apps using tree structuring (from ptree) and with functionailty to help with abstracting gui from app logic

## installation

Once downloaded switch to the new directory and 

> sudo python3 setup.py install

The various modules can then be used in python modules like this:

> from pootlestuff import xxx