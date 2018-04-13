#!/usr/bin/python2

# -------------------------------------------------------------------
# MANAGED BY SALT
# -------------------------------------------------------------------

#
# Collects a few pieces of information and sends it to Colossus
#
# $Id: server-report 39 2012-10-16 21:49:20Z bnigmann $
#

import httplib
import urllib
import subprocess
import os
import re
import time
import random
import sys
import getopt
import json

from sysinf import Sysinf
from socket import timeout


REVISION = 50


# -------------------------------------------------------------------
# Read the first line of the given file
# -------------------------------------------------------------------

def read_line_from_file(filename): 

	line = None
	try:
		line = open(filename, 'r').readline()
	except:
		line = None

	return line.strip()



# -------------------------------------------------------------------
# Execure a shell command and capture the output
# -------------------------------------------------------------------

def run_process(cmd):

	p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
	result = []

	running = True	
	while(running):
		retcode = p.poll() #returns None while subprocess is running
		if(retcode is not None):
			running = False

		# Running or not, read all the output from the script that's left
		line_count = 0;
		line = p.stdout.readline()
		while(line):
			line_count = line_count + 1
			if(line_count>1000):
				raise Exception, "Infinite loop in run_rocess()?"

			if(len(line)>0):
				result.append(line.strip())
			line=p.stdout.readline()

	return result



# -------------------------------------------------------------------
# Calculate a unique server identifier.
# For now, simply the MAC address of eth0.
# -------------------------------------------------------------------

def calculate_server_id():

	return read_line_from_file('/sys/class/net/eth0/address')




# -------------------------------------------------------------------
# Script starts here
# -------------------------------------------------------------------

# Were there any command line options given?
try:
	opts, args = getopt.getopt(sys.argv[1:], 'u')
	for o, a in opts:
		if (o == '-u'):
			print "Server ID:", calculate_server_id()
			sys.exit(0)
except Exception, e:
	print "Error parsing command line options:", e


# Initialize the array for the collected data
info = {}


# 'Calculate' the script revision from SVN keyword. This is auto-updated by svn!
# Only add it to the result parameters if it was successful. We need the strange
# chop-up, so svn doesn't replace the regex as well
try:
	info['script_revision'] = REVISION
except:
	pass



# Gather the MAC address of eth0 as the unique server ID
# ------------------------------------------------------

try:
	info['mac_eth0'] = calculate_server_id()
except:
	pass



# Is this a VM or real hardware?
# ------------------------------

try:
	info['server_type'] = 'baremetal'

	if (os.path.exists('/sys/hypervisor/type')):
		info['server_type'] = read_line_from_file('/sys/hypervisor/type')
	elif (os.path.exists('/sys/class/dmi/id/sys_vendor')):
		vendor = read_line_from_file('/sys/class/dmi/id/sys_vendor')
		if (re.search('^VMware', vendor)):
			info['server_type'] = 'vmware'
	elif (os.path.exists('/proc/ide/ide1/hdc/model')):
		vendor = read_line_from_file('/proc/ide/ide1/hdc/model')
		if (re.search('^VMware', vendor)):
			info['server_type'] = 'vmware'
	elif (os.path.exists('/usr/bin/imvirt')):
		info['server_type'] = run_process('/usr/bin/imvirt')[0]
except:
	info['server_type'] = 'unknown'
		


# Gather Facility code
# --------------------

try:
	if (os.path.exists('/etc/FacilityCode.txt')):
		# Old-school A3 servers
		info['facility_code'] = read_line_from_file('/etc/FacilityCode.txt')
	else:
		# New S4 servers
		sys.path.append('/opt/gwn/python')
		from config import ServerConfig
		config = ServerConfig()
		info['facility_code'] = config.get_string('facility_code')
except:
	pass


# Gather the server build version
# -------------------------------

try:
	info['build_version'] = read_line_from_file('/etc/GWNBuild.txt')
except:
	pass


# Gather the server's uptime
# --------------------------

try:
	uptime_str = read_line_from_file('/proc/uptime')
	uptime = uptime_str.split(' ')
	info['uptime_system'] = float(uptime[0])
	info['uptime_idle'] = float(uptime[1])
except:
	pass


# Gather the server's distribution
# --------------------------------

try:
	if (os.path.exists('/etc/portage')):
		info['server_os'] = 'Gentoo'
	elif (os.path.exists('/usr/bin/lsb_release')):
		info['server_os'] = run_process(['/usr/bin/lsb_release', '-s', '-d'])[0]
except:
	pass


# If supported, count number of upgradable packages
# -------------------------------------------------

try:
	if (os.path.exists('/usr/lib/update-notifier/apt-check')):
		lines = run_process(['/usr/lib/update-notifier/apt-check'])
		(update_pkg, update_sec) = lines[0].split(';')
		info['update_pkg'] = int(update_pkg)
		info['update_sec'] = int(update_sec)

	if (os.path.exists('/var/run/reboot-required')):
		info['reboot_required'] = True
except:
	pass



# Gather Kernel version and installed Kernels
# -------------------------------------------

try:
	lines = run_process(['uname', '-r'])
	info['kernel_version'] = lines[0]

        lines = run_process(['dpkg', '-l', 'linux-image-*'])
        installed = re.compile('^ii[\s]+(\S+)')
        info['installed_kernels'] = []
        for l in lines:
            m = installed.match(l)
            if m is not None:
                info['installed_kernels'].append(m.group(1))
except:
	pass



# Gather the full host name
# -------------------------

try:
	lines = run_process(['hostname', '-f'])
	info['host_name'] = lines[0]
except:
	pass



# Gather IP information
# ---------------------

try:
	lines = run_process(['ifconfig', 'eth0'])
	info['mac_eth0'] = re.search('HWaddr (.*)$', lines[0]).group(1).strip()
	s = re.search('inet addr:(.*) Bcast:(.*) Mask:(.*)$', lines[1])
	info['ip_address'] = s.group(1).strip()
	info['ip_netmask'] = s.group(3).strip()
except:
	pass



# Gather BIOS information
# -----------------------

try:
	lines = run_process(['smbios-sys-info-lite'])

	for line in lines:
		s = None
		s = re.search('Service Tag:(.*)$', line)
		if (s):
			info['service_tag'] = s.group(1).strip()
			continue

		s = re.search('Product Name:(.*)$', line)
		if (s):
			sx = s.group(1).strip()
			if len(sx) > 0:
				info['server_model'] = sx
			continue

		# For newer servers, Product Name is blank. Send OEM ID instead if Product Name is blank.
		s = re.search('OEM System ID:(.*)$', line)
		if ('server_model' not in info and s is not None):
			info['server_model'] = s.group(1).strip()
			# For a few well-known OEM IDs, translate to model
			if info['server_model'] == '0x8127':
				info['server_model'] += ' (R420)'
			elif info['server_model'] == '0x8162':
				info['server_model'] += ' (R430)'
			continue

		s = re.search('BIOS Version:(.*)$', line)
		if (s):
			info['bios_version'] = s.group(1).strip()
			continue
except:
	pass


# Dump server.conf
# ----------------

try:
	import yaml
	with open('/etc/gwn/server.conf', 'r') as config:
		data = yaml.load(config)
		info['server_conf'] = data['grains']['gwn']
except BaseException as e:
	info['server_conf'] = "ERROR: {0}".format(e)


# Using full disk encryption?
# ---------------------------

try:
	crypt = read_line_from_file('/etc/crypttab')
	if re.search('luks', crypt) is not None:
		info['has_fde'] = 1
except:
	info['has_fde'] = 0


# The server's system time zone
# -----------------------------

try:
	info['timezone'] = time.strftime("%Z", time.gmtime())
except:
	info['timezone'] = '?'


# The last time a Salt highstate was run
# --------------------------------------

try:
	if os.path.exists('/etc/salt/last-highstate.txt'):
		info['last_highstate'] = int(os.path.getmtime('/etc/salt/last-highstate.txt'))
except:
    pass


# List the mounted SquashFS images
# --------------------------------

try:
	squashfs = []
	for line in run_process('/bin/mount'):
		s = re.search('^([^ ]+) .*squashfs', line)
		if s is not None:
			squashfs.append(s.group(1))
	if len(squashfs)>0:
		info['mounted_squashfs'] = squashfs
except:
	pass


# What web server is installed? Nginx or lighttpd?
# ------------------------------------------------

try:
	info['web_server'] = 'UNKNOWN'
	release = run_process(['/usr/bin/lsb_release', '-rs'])[0]
	if release == '12.04' or release == '14.04':
		# Using upstart
		lines = run_process(['/usr/sbin/service', '--status-all'])
		for line in lines:
			s = re.search('\[ \+ \]  (nginx|lighttpd)', line)
			if s is not None:
				info['web_server'] = s.group(1)
				break
	else:
		# Using systemd
		lines = run_process(['/bin/systemctl', 'list-unit-files', '--type=service'])
		for line in lines:
			s = re.search('^(nginx|lighttpd).*enabled', line)
			if s is not None:
				info['web_server'] = s.group(1)
				break
except:
	pass


# If lighttpd is installed, collect the ways PLS was accessed from the previous log
# ---------------------------------------------------------------------------------

try:
	if os.path.exists('/var/log/lighttpd/access.log.1'):
		with open('/var/log/lighttpd/access.log.1') as log:
			first_line = log.readline()
			m = re.search('\[(.*?)\]', first_line)
			log_date = m.group(1)
			log.seek(0)
			lighttpd_access = {
				'log_date': log_date,
				'access': {}
			}
			access = {}
			for line in log:
				m = re.search('<(.*?)> \[(.*?)\]$', line)
				if m is not None:
					k = '{0}__{1}'.format(m.group(1), m.group(2))
					if k not in access:
						access[k] = 0
					access[k] += 1

		# Need to replace any dots in the host names, so MongoDB does not choke
		for k in access:
			lighttpd_access['access'][k.replace('.', '_')] = access[k]

		info['lighttpd_access'] = lighttpd_access
except: 
	pass


# Is Wildfly or JBoss currentpy running on this server?
# -----------------------------------------------------

# To determine this quickly and easily while both application servers are still out there,
# we need to look what's actually _running_ at the moment. If PLS happens to be down, we'll
# just say "UNKNOWN".

try:
	if os.path.exists('/opt/jboss7') or os.path.exists('/opt/wildfly'):
		info['pls'] = { 'server': 'UNKNOWN' }
		lines = run_process(['/usr/bin/jps', '-v'])
		for line in lines:
			s = re.search('/opt/(jboss7|wildfly)', line)
			if s is not None:
				info['pls'] = { 'server': s.group(1) }
				break;
except:
	pass



# Do we have a local JBoss installed? Try to fetch the PLS version and such
# -------------------------------------------------------------------------

try:
	if 'pls' in info and info['pls']['server'] == 'jboss7':
		# Quiescent video controllers
		if os.path.exists('/opt/jboss7/standalone/deployments/assets.war/WEB-INF/config/Configuration.xml'):
			info['pls']['quiescent_controllers'] = []
			with open('/opt/jboss7/standalone/deployments/assets.war/WEB-INF/config/Configuration.xml', 'r') as c:
				for l in c:
					s = re.search('>([\.\w-]+)</quiescent-controller>', l)
					if s is not None:
						srv = s.group(1)
						if srv != 'VLC-X' and srv != 'VLC-Y':
							info['pls']['quiescent_controllers'].append(srv)
		# Deployed PLS version
		info['pls']['version'] = 'unknown'
		pls = httplib.HTTPConnection('localhost', 8080, timeout=10)
		pls.request('GET', '/Admin/sysinfo/Sysinfo.action?runCheck=com.gwn.plife.sysinfo.checks.AppVersionCheck&authUserName=gwnreporter&authUserPassword=ixNq^4nJJeX1')
		res = pls.getresponse()
		if res.status == 200:
			m = re.search('<app-version>(.*)</app-version>', res.read())
			if m is not None:
				info['pls']['version'] = m.group(1)
except:
	pass


# Do we have a local Wildfly installed? Try to fetch the PLS version and such
# ---------------------------------------------------------------------------

try:
	if 'pls' in info and info['pls']['server'] == 'wildfly':
		# Quiescent video controllers
		if os.path.exists('/opt/wildfly/standalone/deployments/assets.war/WEB-INF/config/Configuration.xml'):
			info['pls']['quiescent_controllers'] = []
			with open('/opt/wildfly/standalone/deployments/assets.war/WEB-INF/config/Configuration.xml', 'r') as c:
				for l in c:
					s = re.search('>([\.\w-]+)</quiescent-controller>', l)
					if s is not None:
						srv = s.group(1)
						if srv != 'VLC-X' and srv != 'VLC-Y':
							info['pls']['quiescent_controllers'].append(srv)
		# Deployed PLS version
		info['pls']['version'] = 'unknown'
		pls = httplib.HTTPConnection('localhost', 8080, timeout=20)
		pls.request('GET', '/Admin/sysinfo/Sysinfo.action?runCheck=com.gwn.plife.sysinfo.checks.AppVersionCheck&authUserName=gwnreporter&authUserPassword=ixNq^4nJJeX1')
		res = pls.getresponse()
		if res.status == 200:
			m = re.search('<app-version>(.*)</app-version>', res.read())
			if m is not None:
				info['pls']['version'] = m.group(1)
except Exception as e:
        if type(e) == timeout:
		info['pls']['version'] = 'timeout'
	pass


# If the server has PLC images and CurrentPLC symlink, capture it
# ---------------------------------------------------------------

try:
	if os.path.islink('/opt/plc-root/opt/images/CurrentPLC'):
		info['current_plc_link'] = os.readlink('/opt/plc-root/opt/images/CurrentPLC')
except:
	pass


# For appserververs: RAS or single server?
# ----------------------------------------

try:
	if re.match('^ras[0-9]\..*$', info['host_name']):
		info['appserver'] = { 'type': 'ras', 'node': 'slave' }
		for line in run_process(['/usr/sbin/crm_resource', '--resource', 'ms_StickyMaster', '--locate']):
			s = re.search(' (ras[0-9]) Master', line)
			if s is not None and re.match('^{0}'.format(s.group(1)), info['host_name']):
				info['appserver']['node'] = 'master'
	elif re.match('^appserver\.', info['host_name']):
		info['appserver'] = { 'type': 'standalone' }
	elif re.match('^apptest\.', info['host_name']):
		info['appserver'] = { 'type': 'test' }
except Exception as e:
	pass


# Report the size of the /boot partition
# --------------------------------------

try:
	lines = run_process(['df', '-B1', '/boot'])
        # Turn this:
	#  Filesystem     1B-blocks     Used Available Use% Mounted on
	#  /dev/sda1      270087168 80741376 175399936  32% /boot
        # into this: [ '/dev/sda1', '270087168', '80741376', ... ]
	values = lines[1].split()
	info['boot_partition'] = {
		'size_mb': int(values[1]) / 1048576,
		'available_mb': int(values[3]) / 1048576
	}
except:
	pass


# Total amount of RAM in the system
# ---------------------------------

try:
	import psutil
	mem = psutil.virtual_memory()
	info['total_ram_mb'] = mem.total / 1024**2
except:
	pass


# Which firewall is used? Ufw or iptables?
# ----------------------------------------

# To determine this quickly, we just check for the /usr/sbin/ufw binary.

try:
	if os.path.exists('/usr/sbin/ufw'):
		info['firewall'] = 'ufw'
        elif os.path.exists('/sbin/iptables'):
		info['firewall'] = 'iptables'
        else:
		info['firewall'] = 'UNKNOWN'
except:
	pass



# ------------------------------------------------------------------------
# SEND RESULT BACK:
# ------------------------------------------------------------------------

# "SysInf" is the new way to push server info.
Sysinf.send_server_info({'daily_status': info})

