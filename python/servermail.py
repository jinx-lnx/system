#!/usr/bin/python2

# $Id$

# Generate an email to 'root'

# Include GWN packages
import sys
sys.path.append("/opt/gwn/python")

import argparse
import socket
import smtplib
import time
from email.mime.text import MIMEText
from subprocess import Popen, PIPE, STDOUT


# If this server was primed by a PLS stick, we can read the facility code, etc.
try:
	from config import ServerConfig
	have_config = True
except:
	have_config = False


try:
	parser = argparse.ArgumentParser(description='Send an email to root')
	parser.add_argument("-s", "--subject", help="Subject for the email", required=True)
	parser.add_argument("-r", "--raw", help="Just generate and print the raw mail message. Do not send.",
		required=False, action="store_true")
	parser.add_argument("-c", "--cc", help="Send a carbon copy of the email to this recipient.",
		required=False)
	args = parser.parse_args()

	# Read the message from stdin
	body = sys.stdin.read()
	sys.stdin.close()
	body = body.strip()

	# Skip empty emails
	if (len(body.strip()) < 1):
		exit (1)

	# Attach a local timestamp of the server's time to the beginning of the mail
	now = time.strftime('%c %Z')
	body = "Server timestamp: " + now + "\n-----\n\n" + body
	
	# Try to import the encryption module
	try:
		import gnupg
		gpg = gnupg.GPG(gnupghome='/root/.gnupg/')
		dudes = [
			'rcavanaugh@getwellnetwork.com',
			'jlynch@getwellnetwork.com',
			'aspagnolo@getwellnetwork.com',
			'bborter@getwellnetwork.com',
			'bnigmann@getwellnetwork.com',
			'dgassen@getwellnetwork.com'
		]

		crypt = gpg.encrypt(body, dudes)
		if not crypt.ok:
			body = '### REDACTED DUE TO ENCRYPTION ERROR: {0} ###\n\nIntended recipients: {1}'.format(crypt.status, dudes)
		else:
			body = crypt.data
	except:
		pass

	# Assemble the mail message
	msg = MIMEText(body)

	if have_config == True:
		s = ServerConfig()
		facility_code = s.get_string('facility_code')
	else:
		facility_code = None

	host_name =  socket.getfqdn()
	sender = 'root@' + host_name
	recipient = 'root'
	prefix = ''

	if(facility_code):
		prefix = facility_code + ": "

	msg['Subject'] = prefix + args.subject
	msg['From'] = sender
	msg['To'] = recipient
	if args.cc is not None:
		msg['CC'] = args.cc

	msg_str = msg.as_string()

	if args.raw == True:
		print msg_str
		exit(0)

	# Prefer to use the '/usr/sbin/sendmail' command for queueing
	# email locally. This even works if Postfix is not up at the moment.
	try:
		p = Popen(['/usr/sbin/sendmail', '-t'], stdout=PIPE, stdin=PIPE, stderr=STDOUT)
		p.communicate(input=msg_str)
		exit(0)
	except Exception, e:
		pass

	# Fall back to manual delivery to localhost. Try up to 3 times
	success = False
	for i in range(1,3):
		try:
			s = smtplib.SMTP('localhost', timeout=3)
			s.sendmail(sender, recipient, msg_str)
			s.quit()
			success = True
			break
		except:
			time.sleep(5)

	if (not success):
		print "Sending server mail failed three times"
		exit (1)

except Exception as e:
	print "Sending server mail failed:", e

