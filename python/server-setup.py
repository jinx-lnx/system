#!/usr/bin/python

import sys
sys.path.append('/opt/gwn/python')


from dialog import Dialog
from ipaddr import IPv4Address,IPv4Network,AddressValueError
from config import ServerConfig
from socket import gethostbyname, create_connection
import re
import subprocess
import time
import apt
import os


__revision__ = r'$Revision: 126 $'


def ask_full_hostname(domain_stub):

	full_hostname = ''

	while not full_hostname:

		dlg_full_hostname = None

		if (not domain_stub):
			prompt = "This server is not going to be part of a facility deployment, so\n"
			prompt += "we need to know the full hostname.\nPlease enter the FULL host name\n"
			prompt += "('mailrelay.hq', 'something.cloud'):"
		else:
			canned_servertypes = {
				'1': 'appserver',
				'2': 'apptest',
				'3': 'ras1',
				'4': 'ras2',
				'5': 'vls1',
				'6': 'vls2',
				'7': 'vls3',
				'8': 'vls4',
				'9': 'other (vls5+, etc.)'
			}
			(exit_value, canned_id) = d.menu("What type of server are you installing?",
				16, 60, 9, sorted(canned_servertypes.items())
				, nocancel=1, backtitle=dialog_title)
			if int(canned_id) < 9:
				dlg_full_hostname = canned_servertypes[canned_id]
			else:
				prompt = "This server is going to be part of a facility deployment, so we\n"
				prompt += "already know the domain name: {0}\n".format(domain_stub)
				prompt += "Please enter ONLY the hostname here (without '.{0}')".format(domain_stub)


		if dlg_full_hostname is None:
			(exit_value, dlg_full_hostname) = d.inputbox(prompt, 10, 70, nocancel=1,
				backtitle=dialog_title)

		if (not domain_stub and re.match('^[-\w]{2,}(\.[-\w]{2,})+$', dlg_full_hostname)):
			full_hostname = dlg_full_hostname.lower()
		elif (domain_stub and re.match('^[-\w]{2,}$', dlg_full_hostname)):
			full_hostname = dlg_full_hostname.lower() + '.' + domain_stub
		else:
			d.msgbox("Invalid host name!\n"
				"Entered host name: " + dlg_full_hostname, 7, 60, backtitle=dialog_title)

	return full_hostname



def ask_ip_address(d, prompt, allow_empty=False, suggested_ip=""):

	ip_address = None

	while not ip_address:
		try:
			(exit_value, dlg_ip_address) = d.inputbox(prompt, 10, 60, suggested_ip, nocancel=1,
				backtitle=dialog_title)
			if allow_empty and len(dlg_ip_address)<1:
				return None
			ip_address = IPv4Address(dlg_ip_address)
		except AddressValueError:
			d.msgbox("Invalid IP address: " + dlg_ip_address, 7, 60, backtitle=dialog_title)

	return ip_address



def ask_ip_settings(d):

	ip_address = ask_ip_address(d, "Please enter IP address for the server:")
	ip_netmask = None
	ip_gateway = None
	ip_dns = None


	while not ip_netmask:

		try:
			(exit_value, dlg_ip_netmask) = d.inputbox(
				"Please enter the netmask for the server:\n"
				"(for example: 255.255.248.0)", 10, 60,
				"255.255.255.0", nocancel=1, backtitle=dialog_title)
			ip_netmask = IPv4Network(ip_address.compressed + '/' + dlg_ip_netmask)
		except ValueError:
			d.msgbox("Invalid netmask: " + dlg_ip_netmask, 7, 60, backtitle=dialog_title)

	while not ip_gateway:

		try:
			suggested_gw = str(ip_netmask.network + 1)
			(exit_value, dlg_ip_gateway) = d.inputbox(
				"Please enter IP of the default gateway:", 10, 60,
				suggested_gw, nocancel=1, backtitle=dialog_title)
			ip_gateway = IPv4Address(dlg_ip_gateway)

			if not ip_gateway in ip_netmask:
				d.msgbox("Gateway IP " + str(ip_gateway)
				+ " is not in the entered network\n" +
				str(ip_netmask.network) + "/" + str(ip_netmask.netmask), 7, 60, backtitle=dialog_title)
				ip_gateway = None

		except AddressValueError:
			d.msgbox("Invalid gateway IP address: " + dlg_ip_gateway, 7, 60, backtitle=dialog_title)

	while not ip_dns:

		try:
			(exit_value, dlg_ip_dns) = d.inputbox(
				"Please enter IP of the DNS server to use during install:", 10, 60,
				'10.1.1.20', nocancel=1, backtitle=dialog_title)
			ip_dns = IPv4Address(dlg_ip_dns)

		except AddressValueError:
			d.msgbox("Invalid DNS server IP address: " + dlg_ip_dns, 7, 60, backtitle=dialog_title)


	return (ip_address,ip_netmask,ip_gateway,ip_dns)



def ask_custom_nat(d, dialog_title):
	# Clear previous NAT mappings, if any
	subprocess.call([ 'sed', '-i', '-e', '/# --INSTALLER--/,$d', '/etc/hosts' ])
	if d.yesno('Does this site require custom NAT mappings for HQ servers?', 10, 60, backtitle=dialog_title, defaultno=True) == 0:
		nat_needed = { 'salt-master.hq' : None, 'apt.hq' : None, 'services.hq' : None, 'dc0.ad.gwn': None }
		for n in nat_needed.keys():
			(exit_value, dlg_nat) = d.inputbox(
				"Please enter the NAT address for '{0}'".format(n), 10, 60,
				nocancel=1, backtitle=dialog_title)
			nat_needed[n] = dlg_nat
		with open('/etc/hosts', 'a') as h:
			h.write('# --INSTALLER--\n')
			for k in nat_needed.keys():
				if nat_needed[k] is not None:
					h.write('{0}\t{1}\n'.format(nat_needed[k], k))
			


def try_again_prompt(d, message, height, width, backtitle=None):
	exit_status = -1
	while (exit_status != 0):
		(exit_status, selection) = d.menu(message, height, width, 4,
			choices=[('1','Try again now'), ('2','Shut down server'), ('3', 'Login to console'), ('4', 'Ignore (Linux Admin only!)')],
			nocancel=1, backtitle=dialog_title)

		# Successful selection and shutdown requested:
		if(exit_status==0 and selection=='2'):
			subprocess.call(['clear'])
			print "Shutting down..."
			time.sleep(1)
			subprocess.call(['poweroff'])

		# Successful selection and console login requested:
		if(exit_status==0 and selection=='3'):
			subprocess.call(['clear'])
			time.sleep(1)
			exit(0)

		# Successful selection and 'Ignore' selected. Must me supported by calling code!
		if(exit_status==0 and selection=='4'):
			raise Exception('Ignoring the Problem')


def update_package_repository(d, apt_cache):
	d.infobox("Updating package repository...", 5, 60, backtitle=dialog_title)
	apt_cache.update()
	apt_cache.open()


def perform_sanity_check(dialog):

	all_passed = True
	with open('/tmp/sanity-check.txt', 'w') as san:
		san.write('\n============================================================\n')
		san.write('Network Sanity Check\n')
		san.write('============================================================\n\n')
		p = 0
		d.gauge_start('Performing Network Sanity Check...', 6, 60, backtitle=dialog_title)

		# Resolve a few required hosts
		for h in [ 'services.hq', 'apt.hq', 'salt-master.hq', 'security.ubuntu.com' ]:
			p += 5
			try:
				ip = gethostbyname(h)
			except BaseException:
				ip = 'UNKNOWN'
				all_passed = False
			d.gauge_update(p, text='Checking IP: {0}'.format(h))
			san.write('IP for {0}'.format(h).ljust(45) + ': ' + ip + '\n')

		# Try connecting to HTTP port on a few critical hosts
		san.write('\n')
		for h in [ 'apt.hq','security.ubuntu.com' ]:
			p += 5
			test_result = '[SUCCESS]'
			try:
				c = create_connection( (h, 80), 10 )
				c.close()
			except BaseException as b:
				test_result = '[FAIL]' + str(b)
				all_passed = False
			d.gauge_update(p, text='Checking HTTP connection: {0}'.format(h))
			san.write('Direct HTTP to {0}'.format(h).ljust(45) + ': ' + test_result + '\n')

		# Try connecting to Salt
		san.write('\n')
		p += 5
		test_result = '[SUCCESS]'
		try:
			c = create_connection( ('salt-master.hq', 4505), 10 )
			c.close()
			c = create_connection( ('salt-master.hq', 4506), 10 )
			c.close()
		except BaseException as b:
			test_result = '[FAIL]' + str(b)
			all_passed = False
		d.gauge_update(p, text='Checking Salt connection')
		san.write('Salt connectivity (4505 and 4506)'.format(h).ljust(45) + ': ' + test_result + '\n')

		# Try 5 pings to services.hq
		san.write('\n')
		hq_reachable = False
		test_result = '[FAIL]'
		for i in range(0,5):
			p += 10
			d.gauge_update(p, text='Pinging services.hq')
			ping_result = subprocess.call(['ping','-c','1','-w','5','services.hq'], stdout=devnull, stderr=subprocess.STDOUT)
			if ping_result == 0:
				hq_reachable = True
				test_result = '[SUCCESS]'
				break
		if not hq_reachable:
			all_passed = False
		san.write('Ping services.hq'.ljust(45) + ': ' + test_result + '\n')

		
	# Show the result
	d.gauge_update(100)
	d.gauge_stop()
	dialog.textbox('/tmp/sanity-check.txt', 30, 75)
	return all_passed




# -------------------------------------------------------------------
# Script starts here:
# -------------------------------------------------------------------

if __name__ == '__main__':


	devnull = open('/dev/null','w')

	# Initialize a few constants
	dialog_title = "GetWellNetwork Server Installation        {0}".format(__revision__)

	# Initialize the server configuration, created by this bootstrap script
	config = ServerConfig()

	# Initialize the dialog object
	d = Dialog()

	d.msgbox("GetWellNetwork Server Installation\n\n"
		"The following steps will walk you through the setup of "
		"this server. Please read the options and instructions carefully.",
		10, 60, backtitle=dialog_title)

	# Input: Facility Code
	# --------------------

	facility_code = None

	while facility_code is None:
		(exit_value, dlg_facility_code) = d.inputbox(
			"If this server is part of a facility deployment, enter the "
			"facility code here. If it is not part of a facility deployment, "
			"leave this blank.\n"
			"Please enter the facility code for the server:", 10, 60, nocancel=1,
			backtitle=dialog_title)

		if re.match('^([a-zA-Z][a-zA-Z0-9-]{2,})?$', dlg_facility_code):
			facility_code = dlg_facility_code.upper()
		else:
			d.msgbox("Invalid facility code!\n"
				"Entered code: " + dlg_facility_code, 7, 60, backtitle=dialog_title)
			facility_code = None



	# Input: Full host name
	# ---------------------

	full_host_name = ""

	if facility_code:
		full_host_name = ask_full_hostname(facility_code + '.gwn')
	else:
		full_host_name = ask_full_hostname('')


	# Input: IP Settings
	# ------------------

	ip_address = None
	ip_netmask = None
	ip_gateway = None
	ip_dns = None

	exit_value = 1
	while (exit_value!=0):
		(ip_address,ip_netmask,ip_gateway,ip_dns) = ask_ip_settings(d)
		exit_value = d.yesno("Are the following settings correct?\n\n" +
			"Full Host Name..: " + full_host_name + "\n" +
			"Facility Code...: " + facility_code + "\n" +
			"Server IP.......: " + str(ip_address) + "\n" +
			"Netmask.........: " + str(ip_netmask.network) + "/" + str(ip_netmask.netmask) + "\n" +
			"Gateway.........: " + str(ip_gateway) + "\n" +
			"DNS Server......: " + str(ip_dns) + "\n" +
			"Possible IPs....: " + str(ip_netmask.numhosts),
			15, 60, backtitle=dialog_title)

	ask_custom_nat(d, dialog_title)

	# Write the generated config file
	d.infobox("Writing configuration to disk", 5, 60, backtitle=dialog_title)
	time.sleep(1)
	config.set_string('is_production', False)
	if facility_code:
		config.set_string('facility_code', facility_code)
	config.set_string('full_host_name', full_host_name)
	config.set_string('offsite_backup', 's3')

	config.set_string('ip_address', str(ip_address))
	config.set_string('ip_netmask', str(ip_netmask.netmask))
	config.set_string('ip_gateway', str(ip_gateway))
	# Note: we don't write ip_dns to server.conf; only used during initial install!

	config.save()


	# Stop the network interfaces using the old settings
	d.infobox("Stopping Network Interfaces", 5, 60, backtitle=dialog_title)
	subprocess.call(['/etc/init.d/networking', 'stop'], stdout=devnull, stderr=subprocess.STDOUT)
	time.sleep(2)

	if os.path.exists('/usr/bin/killall'):
		d.infobox("Terminating DHCP client", 5, 60, backtitle=dialog_title)
		subprocess.call(['/usr/bin/killall', '-9', 'dhclient3'], stdout=devnull, stderr=subprocess.STDOUT)
		time.sleep(1)

	# Write the network configuration (MUST happen after interfaces are down,
	# or you might end up with a left-over dhcp client!)
	with open('/etc/network/interfaces', 'w') as interfaces:
		interfaces.write('# Generated by GWN server config script\n#\n')
		interfaces.write('auto lo\n  iface lo inet loopback\n\n')
		interfaces.write('auto eth0\n')

		# Write the initial IP configuration
		interfaces.write('  iface eth0 inet static\n')
		interfaces.write('  name Primary Interface\n')
		interfaces.write('  address ' + str(ip_address) + '\n')
		interfaces.write('  netmask ' + str(ip_netmask.netmask) + '\n')
		interfaces.write('  gateway ' + str(ip_gateway) + '\n')
		interfaces.write('  dns-nameservers ' + str(ip_dns) + '\n\n')

		interfaces.write('\n  # Add static routes to the appropriate interface\n')
		interfaces.write('  #post-up route add -net a.b.c.d netmask e.f.g.h gw i.j.k.l\n\n')

		interfaces.write('\n\n# Include separate configuration files for other interfaces\n')
		interfaces.write('source /etc/network/interfaces.d/*.cfg\n')



	# Restart the network with the new settings	
	d.infobox("Starting Network Interfaces", 5, 60, backtitle=dialog_title)
	subprocess.call(['/etc/init.d/networking', 'start'], stdout=devnull, stderr=subprocess.STDOUT)
	time.sleep(2)

        # Offer to use an SSH tunnel to bypass network limitations to the Salt-Master
	# DISABLED: no longer needed, but let's keep the code for now...
	if (False and d.yesno("Do you need to establish an SSH tunnel "
			"to HQ for Salt access?", 10, 60, backtitle=dialog_title) == 0):
		try:
			from port_forwarder import PortForwarder

			(exit_value, ad_user) = d.inputbox("Please enter your AD username:",
				nocancel=1, backtitle=dialog_title)
			(exit_value, ad_pwd) = d.passwordbox("Please enter your AD password:\n"
				"(note: it will not show in the text field)",
				nocancel=1, backtitle=dialog_title)
			d.infobox("Starting SSH tunnel...", 5, 60, backtitle=dialog_title)
			time.sleep(1)
			pfw = PortForwarder(ssh_host='services.hq', username=ad_user, password=ad_pwd)
			pfw.start_port_forward(local_port=4506, target_host=salt_master, target_port=4506,
				local_address='127.0.0.1', abort_transfer_on_exit=True)
			time.sleep(2)
			salt_master = 'localhost'

		except Exception, e:
			d.msgbox("SSH tunnel failed. Falling back to direct connection "
				"(which might not work).\n"
				"{0}".format(e), 7, 60, backtitle=dialog_title)

	# Perform a network sanity check for required components
	sanity_check_passed = False
	while (sanity_check_passed == False):
		sanity_check_passed = perform_sanity_check(d)

		if (sanity_check_passed == False):
			try:
				try_again_prompt(d, "Network Sanity Check Failed.",
					15, 75, backtitle=dialog_title)
			except Exception:
				# If 'Ignore' is selected, allow to continue at own risk.
				sanity_check_passed = True

	if (devnull):
		devnull.close()

	# Offer full package upgrade before installing the rest
	d.infobox("Opening package manager cache", 5, 60, backtitle=dialog_title)
	apt_cache = apt.cache.Cache()
	cache_update_done = False

	if (d.yesno("Would you like to upgrade all packages to the latest "
			"version first (recommended)?", 10, 60, backtitle=dialog_title) == 0):
		update_package_repository(d, apt_cache)
		cache_update_done = True
		apt_cache.upgrade(dist_upgrade=True)
		with open('/tmp/upgrade.txt', 'w') as upg:
			upg.write("\n============================================================\n")
			upg.write("{0} packages will be upgraded:\n".format(len(apt_cache.get_changes())))
			upg.write("============================================================\n\n")
			for p in sorted(apt_cache.get_changes()):
				upg.write("{0}-{1}\n".format(p.shortname, p.candidate.version))

		d.textbox('/tmp/upgrade.txt', 30, 75)
		os.system('clear')
		print "----------------------------------------------------------------------"
		print "Updating packages now. Depending on the available Internet bandwidth,"
		print "there might not be any output on the screen for several minutes..."
		print "----------------------------------------------------------------------\n"
		apt_cache.commit(fetch_progress=apt.progress.text.AcquireProgress(),
			install_progress=apt.progress.base.InstallProgress())
		apt_cache.open()

	# Is the Salt package known at all?
	if (not apt_cache.has_key('salt-minion')):
		if not cache_update_done:
			update_package_repository(d, apt_cache)

		# If Salt is still unknown, we're in trouble
		if (not apt_cache.has_key('salt-minion')):
			d.msgbox("ERROR: Cannot locate the Salt package.\n"
				"Please contact the Linux system administrator.", 12, 60, backtitle=dialog_title)
			exit(1)

	# Is the Salt Minion installed yet?	
	d.infobox("Checking for Salt Minion...", 5, 60, backtitle=dialog_title)
	minion = apt_cache['salt-minion']
	if (not minion.is_installed):
		d.infobox("Installing Salt Minion...", 5, 60, backtitle=dialog_title)
		time.sleep(2)
		os.system('clear')
		minion.mark_install()
		apt_cache.commit()

	# Stop the Minion service
	d.infobox("Stopping Salt Minion service...", 5, 60, backtitle=dialog_title)
	subprocess.call(['service', 'salt-minion', 'stop'])

	# Confirm the salt-master host
	(exit_value, salt_master) = d.inputbox("Enter the Salt-Master host to connect to.\n"
			"In almost all cases, the default value is what you need. Change this "
			"only if you have been instructed to do so.",
			12, 60, "salt-master.hq", nocancel=1, backtitle=dialog_title)

	d.infobox("Configuring Salt Minion...", 5, 60, backtitle=dialog_title)
	with open('/etc/salt/minion', 'w') as mcfg:
		mcfg.write("# Salt Minion configuration\n")
		mcfg.write("master: " + salt_master + "\n")
		mcfg.write("id: " + full_host_name + "\n")
		mcfg.write("include:\n")
		mcfg.write("  - /etc/gwn/server.conf\n")
		mcfg.write("state_verbose: False\n")

	# Loop to get the Minion certified
	master_success = False
	while (not master_success):
		d.infobox("Attempting to contact Salt Master.\n\n"
			"If this hangs for more than a minute, please reach out to a Linux Admin "
			"and have them approve the Salt Minion key for {0}.".format(full_host_name),
			9, 60, backtitle=dialog_title)
		ret = subprocess.call(['salt-call', '-l', 'quiet', 'cmd.run', '"uptime"'])

		if (ret == 2):
			try_again_prompt(d, "The Salt Master has been contacted, "
				"but this server is not registered yet.\n"
				"Please contact the Linux system administrator, ask them to sign the "
				"Salt Minion key for '" + full_host_name + "' and try again.",
				15, 75, backtitle=dialog_title)
		elif (ret == 42):
			try_again_prompt(d, "The Salt Master has been contacted, "
				"but is has rejected this server's public key.\n"
				"Please contact the Linux system administrator, ask them to clear the "
				"Salt Minion key for '" + full_host_name + "' and try again.",
				15, 75, backtitle=dialog_title)
		elif (ret == 0):
			master_success = True
		else:
			d.msgbox("ERROR: Unexpected error, ret={0}".format(ret), 5, 60, backtitle=dialog_title)

	d.msgbox("Ready to configure the server.\n\n"
		"This process will run several minutes. Please do not abort it and do not "
		"disconnect the network during the process!", 12, 60, backtitle=dialog_title)

	salt_success = False

	while not salt_success:

		# Run the salt-call script manually
		with os.tmpfile() as pout:
			subprocess.call(['salt-call', '-l', 'info', '--out', 'raw', 'state.highstate'], stdout=pout)
			pout.flush()
			pout.seek(0)

			# Look in the output for the result hash and parse that into Python
			salt_result = None
			for l in pout:
				try:
					salt_result = eval(l)
					break
				except:
					pass

			salt_report = []

			if (salt_result):

				# We got a parsable salt response, so let's flip the flag
				salt_success = True

				# Also save it to the /tmp folder for debugging
				with open('/tmp/salt-result.txt', 'w') as sres:
					sres.write(str(salt_result))

				# If there are 'local' items, append them to the root (Salt bug)
				if 'local' in salt_result:
					# If the 'local' value is a list, something went wrong
					if isinstance(salt_result['local'], list):
						salt_report.append( ('Salt Initialization failed', "\n".join(salt_result['local'])) )
						salt_success = False
					else:
						salt_result = dict(salt_result.items() + salt_result['local'].items())

				for (key, val) in salt_result.items():
					if 'result' in val:
						if val['result'] == False:
							salt_success = False
							entry = ( "FAILED: " + str(key), "REASON: " + str(val['comment']) )
							salt_report.append(entry)

		if not salt_success:
			with open('/tmp/salt-report.txt', 'w') as rep:
				rep.write("===================================================================\n")
				rep.write("ERROR(S) DURING INSTALLATION\n")
				rep.write("===================================================================\n\n")
				for (failed, reason) in salt_report:
					rep.write("---------------------------\n" + failed + "\n" + reason + "\n")

			d.textbox('/tmp/salt-report.txt', 30, 75)
			try_again_prompt(d, "Initializing this server failed. Please choose from the following "
				"options:", 15, 75, backtitle=dialog_title)		


	# We will only reach here if Salt was successful
	# (The user also could have terminated the script)

	# We cannot remove the temporary setup user while it's in use, so we'll lock it.
	# Salt will later remove it.
	subprocess.call(['usermod', '--lock', '--expiredate', '1', 'setup'])

	# Since Salt might not run for a while, change the root password now
	subprocess.call(['usermod', '--password', '$6$kRYw34T6ui98I$LS2yWTLzHjHm9hFvXL.cF7AX9y0Qkvp2OQkppHU10eUJw3Ir9qvUgYRFBAOSsgTlaGyhcHMm3J4eqWDwRwKSK0', 'root'])

	# Remove temporary helper files
	os.remove('/opt/gwn/launch-gwn-setup')
	os.remove('/etc/sudoers.d/gwn-setup')

	d.msgbox("Installation complete.\nServer will now reboot.", 12, 60, backtitle=dialog_title)
	subprocess.call(['reboot'])

