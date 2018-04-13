#!/usr/bin/python

import os
import argparse
import yaml
import syslog
import shutil
import datetime
import os
import getpass

# Config File
CONF='/etc/gwn/server.conf'

parser = argparse.ArgumentParser(description='Utility for Adding/Removing Trusted Issuers')
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument('-a', nargs=2, metavar=('hash', 'descriptive_name'), help='Add Trusted Issuer')
group.add_argument('-r', metavar='hash', help='Remove Trusted Issuer')
group.add_argument('-v', action='store_true', help='Show Trusted Issuers')
args = parser.parse_args()

# Read Config
conf = yaml.load(open(CONF))
issuers = conf['grains']['gwn'].setdefault('trusted_issuers',{})

# Log the fact that we are trying to change something
syslog.openlog(logoption=syslog.LOG_PID, facility=syslog.LOG_LOCAL0)
syslog.syslog(syslog.LOG_NOTICE,"%s script called by %s to modify %s" % (
	os.path.basename(__file__), 
	os.environ["SUDO_USER"] if "SUDO_USER" in os.environ else getpass.getuser(), 
	CONF))

if 'v' in args and args.v is True:
    """ List the trusted issuers """
    print "Currently Trusted Issuers:"
    for h in issuers:
        print "\t%s: %s" % (h,issuers[h])
elif 'a' in args and args.a is not None:
	""" Add the trusted issuer to the set"""
	if (args.a[0] in issuers and issuers[args.a[0]] != args.a[1]) or args.a[0] not in issuers:
		syslog.syslog(syslog.LOG_INFO,"Adding Trusted Issuer %s (%s) to server configuration" % (args.a[1], args.a[0]))
		issuers[args.a[0]] = args.a[1]
		shutil.copyfile(CONF,"%s.%s" % (CONF,datetime.datetime.now().strftime("%Y%m%d%H%M%S")))
		yaml.dump(conf, file(CONF, 'w'), indent=2,default_flow_style=False);
	else:
		syslog.syslog(syslog.LOG_INFO,"Issuer %s (%s) already trusted - no action taken" % (args.a[1], args.a[0]))
elif 'r' in args and args.r is not None:
	""" Drop the trusted issuer from the set"""
	if args.r in issuers:
		syslog.syslog(syslog.LOG_INFO,"Removing Trusted Issuer %s to server configuration" % args.r)
		del issuers[args.r]
		shutil.copyfile(CONF,"%s.%s" % (CONF,datetime.datetime.now().strftime("%Y%m%d%H%M%S")))
		yaml.dump(conf,file(CONF, 'w'), indent=2,default_flow_style=False);
	else:
		syslog.syslog(syslog.LOG_INFO,"Issuer %s not trusted - no action taken" % args.r)
