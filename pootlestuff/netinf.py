import subprocess
"""
A little bit of Python that returns info about available network interaces and key IP4
info for each.

Includes a simple utility function that returns just a list of (non loopback) IP4 adresses
"""
def netinf():
    """
    parses the output from ifconfig' and returns key info.
    
    returns a dict with keys being the name of the interface and each value being a list of dicts:
    
        each dict with possible entries:
            'peer'      : ip4 host address (if there is one)
            'netmask'   : mask for this subnet
            'broadcast' : broadcast address
            'mac_addr'  : mac address
            plus any other parts found on the inet line as key / value pairs
    """
    co = subprocess.Popen(['ifconfig'], stdout = subprocess.PIPE)
    ifaces={}
    aline=co.stdout.readline()
    while len(aline) > 0:
        if aline[0] in (32,10):
            print('unexpected line:', aline)
            aline=co.stdout.readline()
        else:
            inameb, rest = aline.split(b':', maxsplit=1)
            iname=inameb.decode()
            ifaceinfo={}
            ifaces[iname] = ifaceinfo
            aline=co.stdout.readline()
            while aline[0] == 32:
                lparts = [p.strip() for p in aline.strip().split(b' ') if not p.strip() == b'']
                if lparts[0]==b'inet':
                    _sectadd(ifaceinfo,'IP4',_ip4parse(lparts))
                elif lparts[0]==b'inet6':
                    pass
                elif lparts[0] == b'ether':
                    _sectadd(ifaceinfo, 'mac_addr', lparts[1].decode())
                elif lparts[0] in (b'loop', b'RX', b'TX'):
                    pass
                else:
                    print('???', lparts)
                    print(lparts[0])
                aline=co.stdout.readline()
            if len(aline) == 0:
                pass # loop will exit - we're done
            elif aline[0]== 10:
                aline=co.stdout.readline() # skip to next interface
    return ifaces

def _sectadd(dd, key, val):
    if not key in dd:
        dd[key]=[val]
    else:
        dd[key].append(val)

def _ip4parse(lparts):
    ip4inf = {'peer': lparts[1].decode()}
    for x in range(2, len(lparts)-1, 2):
        ip4inf[lparts[x].decode()] = lparts[x+1].decode()
    return ip4inf

def allIP4():
    """
    returns a list of all the IP4 addresses available (excluding loopback)
    """
    return  [e['peer'] for x in netinf().values() if 'IP4' in x for e in x['IP4'] if 'peer' in e and e['peer'] != '127.0.0.1']