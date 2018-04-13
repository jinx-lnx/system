#!/usr/bin/python2

# Include GWN packages
import sys
sys.path.append("/opt/gwn/python")

from config import ServerConfig

try:
	s = ServerConfig()
	print s.get_string('facility_code')
except:
	print 'UNKNOWN'
