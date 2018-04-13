#!/bin/bash

##########################################################################
## Collection of helper functions used in various scripts
##########################################################################
# Setup the lock functions needed
# Example usage: lock 9 "/tmp/cron-test.lock" "ipset_cron_update.sh is already running, killing"
# then you will run what you want. Once the script is done you will need to add
# clean_up function
function busy_script() {
	local mesg="${1}"; shift
	printf " ==> ${mesg}\n" >&2
	exit 1
}

# Print done
function stat_done() {
	printf "done\n" >&2
}

# Locking function
function lock() {
	eval "exec ${1}>"'"$2"'
	if ! flock -n "${1}"; then
		busy_script "${3}"
		flock "${1}"
	fi
}
# CLean up the lock function
clean_up() {
	rm -f "${1}"
	stat_done
	exit 0
}


# ------------------------------------------------------------------------
# Check if this server is a test server ("apptest").
#
# Return values:
#    0     : Server is a test server
#    1     : Server is not a test server
# ------------------------------------------------------------------------
function isTestServer() {
  # For now, just grep in the config file
  if hostname -f | grep -q "apptest" ; then
    return 0
  else
    return 1
  fi
}



# ------------------------------------------------------------------------
# Check if this server is marked for production usage.
# Note: this only applies to appservers. Videoservers will always be
#       "in production mode", because we have very few non-production
#       videoservers.
#
# Return values:
#    0     : Server is set to production mode
#    1     : Server is not set to production mode
# ------------------------------------------------------------------------
function isProduction() {
  hostname | egrep -qi "^vls"
  # Videoservers are always production mode
  if [ $? -eq 0 ] ; then
    return 0
  fi

  # For now, just grep in the config file
  if [ -z "$(grep -E "is_production:.*[Tt]rue" /etc/gwn/server.conf)" ] ; then
    return 1
  else
    return 0
  fi
}



# ------------------------------------------------------------------------
# Check if the script is running from cron or from a terminal
#
# Return values:
#    0      : The script is running from a shell session
#    1      : The script is running without terminal, like from cron
# ------------------------------------------------------------------------
function isInTerminal() {
	case "${TERM:-}" in
		dumb)		return 1 ;;
		unknown)	return 1 ;;
		*)		return 0 ;;
	esac
}



# ------------------------------------------------------------------------
# Wait a random amount of seconds between zero and the given parameter.
#
# Parameters:
#    $1     : The upper limit for the random wait in seconds
#
# ------------------------------------------------------------------------
function randomWait() {
  if [ -z "${1}" ] ; then
    echo "ERROR: Upper limit for randomWait missing"
    exit 1
  fi

  SLEEP=$(eval "expr $RANDOM % ${1}")
  if isInTerminal ; then
    echo "-- Random sleep of ${SLEEP} seconds..."
  fi
  sleep $SLEEP
}



# ------------------------------------------------------------------------
# Exit with printing out a message and a result code.
#
# Parameters:
#    $1     : Message to print
#    $2     : Result code to exit with (can be zero)
#
# ------------------------------------------------------------------------
function die() {
	local MSG="${1}" ; shift
	local RC=${1}    ; shift

	echo -e "${MSG}" \
		| ${FOLD} \
		>&2
	exit ${RC}
}

# ------------------------------------------------------------------------
# Check if $? is an error code and if so print a message and exit with
# that result code.
#
# Parameters:
#    $1     : Message to print if the $? was non-zero
#
# ------------------------------------------------------------------------
function dieIfError() {
	local RC=${?}
	[ ${RC} -eq 0 ] || die "${1}" ${RC}
}

# ------------------------------------------------------------------------
# Prints an error message, then calls "printHelp" (must be defined by the
# calling script)", then exits with the passed result code
#
# Parameters:
#    $1     : Message to print
#    $2     : Result code to exit with (can be zero)
#
# ------------------------------------------------------------------------
function dieWithHelp() {
	local MSG="${1}"  ; shift
	local RESULT=${1} ; shift

	echo -e "${MSG}" \
		| ${FOLD}
	printHelp
	exit ${RESULT}
}





# ------------------------------------------------------------------------
# Find a command. The function gets the command to search for as its first
# parameter, which then can optionally be followed by a list of paths to
# look into.
# If the command is found in any of these paths the full normalized path
# to the command in that path is printed to STDOUT.
# If the command is not found in any of the paths passed as parameters
# "which" is consulted. If "finds" it the normalized full path is printed
# to STDOUT.
# If the command is not found at all (not even with "which") nothing is
# printed and the function returns 1.
#
# Parameters:
#    $1      : Command to search for
#    $2 .. $n: Optional paths to look in for the command
#
# Return values:
#    0       : Command was found (and the normalized full path printed)
#    1       : Command was NOT found
#
# ------------------------------------------------------------------------
function findExe {
	local COMMAND="${1}"; shift
	local FOUND_PATH=

	FOUND_PATH=
	while [ ${#} -gt 0 ]; do
		if [ -x "${1}/${COMMAND}" ]; then
			FOUND_PATH="${1}/${COMMAND}"
			break
		fi
		shift
	done
	[ -z "${FOUND_PATH}" ] && FOUND_PATH="$( which "${COMMAND}" 2> /dev/null )"
	[ -z "${FOUND_PATH}" ] && return 0
	readlink -f "${FOUND_PATH}"
}



# ------------------------------------------------------------------------
# Shows a "delay" counter. This function shows an optional message
# and then waits for the specified number of seconds while showing
# a count-down timer.
#
# If no message is specified only the timer counts down.
#
# The function uses tput to overwrite the previous countdown
# value if tput is available (aka in a terminal). If tput is
# not available each countdown value is printed sequentially on
# the same line
#
# Parameters:
#    $1      : Delay time in seconds
#    $2      : Optional: a message to display
# ------------------------------------------------------------------------
function showDelayTimer() {
	local WAIT_TIME=${1} ; shift
	local WAIT_MSG=
	[ ${#} -gt 0 ] && WAIT_MSG="${1}" ; shift

	echo -en "${WAIT_MSG}"
	for WAIT in $( seq ${WAIT_TIME} -1 1 ); do
		${TPUT} sc
		echo -en " ${WAIT}"
		sleep 1
		${TPUT} rc
		${TPUT} el
	done
	showEndMarker "done" "${GOOD}"
}



# ------------------------------------------------------------------------
# Convenience function to show an end maker a la "[ok]" or "[failed]".
# If coloring is available the brackets are printed in bold and
# the message (e.g., "ok") is printed in the specified color.
#
# Parameters:
#    $1      : Message
#    $2      : Color for the message
# ------------------------------------------------------------------------
function showEndMarker() {
	local MSG="${1}"   ; shift
	local COLOR="${1}" ; shift

	echo -e " ${BOLD}[${NORMAL}${COLOR}${MSG}${NORMAL}${BOLD}]${NORMAL}"
}


# ------------------------------------------------------------------------
# Start a MySQL daemon that
#  - is only reachable via a socket,
#  - doesn't do password checks (!)
#  - ignores any "slave" configuration options
#  - only allows one concurrent connection at the same time
# The PID of the MySQL daemon is stored in the global variable
# $MYSQLD_PID.
#
# ------------------------------------------------------------------------
function startUnsecuredLocalMySql() {
	MYSQLD_PID=
	"${MYSQLD}" \
		--user=mysql \
		--skip-slave-start \
		--skip-networking \
		--skip-grant-tables \
		--max_connections=1 &
	MYSQLD_PID=$!

	# Ok, so, the *process* may have been started but we
	# still want to wait until mysqld is ready to process
	# queries. Now, let's loop until that happens *or*
	# until the started mysqld process disappears.
	for TRIAL in 1 2 3 4 5 6 7 8 9 10; do
		sleep 1 # Wait *first* then check (to ensure that the forked bash has
			# been replaced with the mysql binary
		# Check if the PID that we got back by starting mysqld in
		# the background is really a mysqld process
		if [ ! -L "/proc/${MYSQLD_PID}/exe" ]; then
			# PID doesn't exist (anymore?)
			return 1
		fi
		
		PID_EXE="$( readlink -f /proc/${MYSQLD_PID}/exe )"
		if [ "${PID_EXE}" != "${MYSQLD}" ]; then
			# PID doesn't exist (anymore?)
			return 2
		fi

		# Now try to connect to the mysql daemon.
		# This may fail if the daemon isn't ready yet.
		"${MYSQL}" ${MYSQL_OPTS} -e exit 2> /dev/null
		if [ ${?} -eq 0 ]; then
			# Everything ok... save the PID in our PID file and return
			return 0
		fi
	done
	kill ${MYSQLD_PID} 2> /dev/null
	return 3	# Could not start the mysql instance for some reason
			# (took too long)

}



# ------------------------------------------------------------------------
# Stops a MySQL daemon that was started by "startUnsecureMysqld".
# (if none was running this function quietly does nothing)
# ------------------------------------------------------------------------
stopUnsecuredLocalMysqld() {
        # Check if we have a mysqld daemon that we started earlier
        # Return if we don't
        [ -L "/proc/${MYSQLD_PID}/exe" ] || return # PID doesn't exist (anymore?)
        PID_EXE="$( basename $( readlink -f "/proc/${MYSQLD_PID}/exe" ) )"
        [ "${PID_EXE}" = "mysqld" ] || return # That PID is not a mysqld instance

        # Kill it and wait for it to disappear
        kill ${MYSQLD_PID}
        # Wait for mysqld to shut down
        while [ -L "/proc/${MYSQLD_PID}/exe" ]; do
                sleep .5
        done
}



# ------------------------------------------------------------------------
# Asks the question passed in as the first argument and then waits for the
# user to enter an answer. The answer must be
#  - "y" or "yes"
#  - "n" or "no"
# (case not important).
#
# If the variable $AUTO_ANSWER_YESNO is not empty then the question
# is not asked and this function simply sets YESNO to the
# contents of $AUTO_ANSWER_YESNO.
#
# Note: the contents of $AUTO_ANSWER_YESNO is NOT verified. If
#       this variable contains something else than "y", "yes", "no" or
#       "no" (case not important) the user will still be prompted to
#       answer the question.
#
# Parameters:
#    $1     : Question to ask
#
# Return values:
#    0      : User answered "yes" (or $AUTO_ANSWER_YESNO was set to "yes")
#    1      : User did answer with "no"
#
# ------------------------------------------------------------------------
function askYesNo() {
	local QUESTION="${1}"
	local YESNO=
	[ -z "${AUTO_ANSWER_YESNO:-}" ] || YESNO="${AUTO_ANSWER_YESNO}"
	while [ -z "${YESNO}" ]; do
		echo -en "${BOLD}${QUESTION}${NORMAL} [${GOOD}Yes${NORMAL}/${BAD}no${NORMAL}] "
		read -e YESNO
		case "${YESNO}" in
			""|y|Y|[yY][eE][sS]) YESNO=Y;;
			n|N|no|No|NO)        YESNO=N;;
			*)
				println "That I didn't understand."
				YESNO=
			;;
		esac
	done
	[ "${YESNO}" = "Y" ] && return 0
	return 1
}

# ------------------------------------------------------------------------
# Check whether the cluster is online.
#
# The current number of resources configured is stored in the global
# variable $CIB_RESOURCE_COUNT.
#
#
# Global variables changed:
#    $CIB_CURRENT_DC:     Current DC of the cluster (only if one is elected)
#    $CIB_RESOURCE_COUNT: Number of resources configured (extracted from
#                         from the cluster status)
#    $CIB_STATUS:         The full CIB status
#
# Return values:
#    0      : Cluster is up and running and has a DC
#    1      : Cluster is up and running and has a DC but no resources defined
#    2      : Cluster is up and running but no DC has been elected yet
#    3      : Could not connect to cluster/could not query cluster
#    4      : Could not extract who the DC is from the $CIB_STATUS
#             (an error message has been printed with the output of
#             "$CRM status")
#    5      : Could not extract the number of resources from the $CIB_STATUS
#             (an error message has been printed with the output of
#             "$CRM status")
#    6      : Cluster software is not running
#
# ------------------------------------------------------------------------
function checkClusterStatus() {
	# Check whether there is a heartbeat. No point trying to connect
	# if there is no such process running:
	[ $( pidof heartbeat corosync | wc -w ) -gt 0 ] \
		|| return 6 # No heartbeat running => cluster software not started

	CIB_CURRENT_DC=
	CIB_RESOURCE_COUNT=
	CIB_STATUS=$( "${CRM}" status 2>/dev/null )
	local RC=${?}
	case ${RC} in
		0)
			eval $(
				echo -e "${CIB_STATUS}" \
					| sed   -n \
						-e 's/^Current DC:  *\(.*\)$/CIB_CURRENT_DC="\1";/p' \
						-e 's/^\([0-9][0-9]*\) Resources configured.*/CIB_RESOURCE_COUNT=\1;/p'
			)
			case "${CIB_CURRENT_DC}" in
				"")
					return 4
					;;
				NONE)
					return 2
					;;
				*)
					# We have a DC... connected and rrrready :-)
					case "${CIB_RESOURCE_COUNT}" in
						"")
							return 5 # Resource count extraction failed
							;;
						0)
							return 1 # No resources defined
							;;
						*)
							return 0 # Some resources are defined
							;;
					esac
					;;
			esac
			;;
		*)
			return 3
			;;
	esac
}



# ------------------------------------------------------------------------
# Wait until the cluster is running and has a DC.
#
# The current number of resources configured is stored in the global
# variable $CIB_RESOURCE_COUNT.
#
#
# Parameters:
#    $1       : Initial message to be printed when waiting for the cluster
#               to start up (if this is an empty string, this function
#               doesn't print anything)
#    $2       : Initial message to be printed when waiting for the DC
#               to be elected (should be an empty string if this function
#               shouldn't print anything; see param $1)
#    $3 (opt) : maximum time to wait for the cluster
#
# Global variables changed:
#    $CIB_RESOURCE_COUNT: Number of resources configured (extracted from
#             from the cluster status)
#    $CIB_STATUS: The full CIB status
#
# Return values:
#    0      : Cluster is up and running and has a DC
#    1      : Cluster is up and running and has a DC but no resources defined
#    2      : Cluster is up and running but no DC has been elected yet after
#             max wait time has been exceeded
#    3      : Could not connect to cluster/could not query cluster within
#             max wait time
#    4      : Could not extract who the DC is from the $CIB_STATUS
#             (an error message has been printed with the output of
#             "$CRM status")
#    5      : Could not extract the number of resources from the $CIB_STATUS
#             (an error message has been printed with the output of
#             "$CRM status")
#    6      : Cluster software is not running
#    7      : Cluster software was running initially but disappeared
#
# ------------------------------------------------------------------------
function waitForCluster() {
	local WAITING_FOR_CLUSTER_MSG="${1}" ; shift
	local WAITING_FOR_DC_MSG="${1}"      ; shift
	local MAX_WAIT=
	local VERBOSE=true
	if [ ${#} -gt 0 ]; then
		MAX_WAIT=${1}
		shift
	fi
	if [ -z "${WAITING_FOR_CLUSTER_MSG}" ]; then
		VERBOSE=false
	else
		WAITING_FOR_CLUSTER_MSG="\n${WAITING_FOR_CLUSTER_MSG}.."
		WAITING_FOR_DC_MSG="\n${WAITING_FOR_DC_MSG}.."
	fi
	CIB_STATUS=
	WAIT_COUNT=0
	INITIAL_CHECK=true
	while true; do
		checkClusterStatus
		local RC=${?}
		case ${RC} in
			2) # Cluster is up and running but has no DC yet
				# Expected... the cluster needs more time to elect a DC
				if ${VERBOSE}; then
					echo -en "${WAITING_FOR_DC_MSG}."
					WAITING_FOR_DC_MSG=
				fi
				sleep 1
				;;
			3) # Could not connect to cluster (yet?)
				if ${VERBOSE}; then
					echo -en "${WAITING_FOR_CLUSTER_MSG}."
					WAITING_FOR_CLUSTER_MSG=
				fi
				sleep 1
				;;
			6)
				${INITIAL_CHECK} \
					&& return 6 # Initially cluster software not running
				return 7 # subsequent check => cluster software disappeared
				;;
			*) # Could not extract resource count
				return ${RC}
				;;
		esac
		INITIAL_CHECK=false
		if [ ! -z "${MAX_WAIT}" ]; then
			(( WAIT_COUNT++ ))
			[ ${WAIT_COUNT} -gt ${MAX_WAIT} ] && return ${RC}
		fi

	done
}



# ------------------------------------------------------------------------
# Print the current main IP to STDOUT
#
# ------------------------------------------------------------------------
function getCurrentIp() {
	sed     -n \
		-e '/\(allow-hotplug\|auto\) eth0/,/^$/s/[ \t]*address \([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)$/\1/p' \
		/etc/network/interfaces
}


					
# ------------------------------------------------------------------------
# Returns the current PLS version deployed as an integer in the form
# (MAJOR * 1000 + MINOR) * 1000) + REV
#
# Any non-digits following REV are being ignored.
#
# A PLS version like 7.03.01-SNAPSHOT-something would be returned as
# 7003001

# Return values:
#    0      : version successfully retrieved
#    1      : file with PLS version could not be found
#    2      : version could not be retrieved from version file
#
# ------------------------------------------------------------------------
function getPlsVersion() {
	local MAJOR=
	local MINOR=
	local REV=

	local VERSION_FILE=/opt/wildfly/standalone/deployments/pls.ear/ejb.jar/META-INF/maven/com.getwellnetwork/pls-core/pom.properties
	[ -f "${VERSION_FILE}" ] || VERSION_FILE=/opt/jboss/standalone/deployments/pls.ear/ejb.jar/META-INF/maven/com.getwellnetwork/pls-core/pom.properties
	[ -f "${VERSION_FILE}" ] || return 1
	eval $(
		sed	-n \
			-e 's/^version=0*\([0-9][0-9]*\)\.0*\([0-9][0-9]*\)\.0*\([0-9][0-9]*\).*/MAJOR=\1;MINOR=\2;REV=\3;/p' \
			"${VERSION_FILE}"
	)
	[ -z "${MAJOR}" ] && return 2
	[ -z "${MINOR}" ] && return 2
	[ -z "${REV}"   ] && return 2
	echo -n $(( (MAJOR * 1000 + MINOR) * 1000 + REV ))
	return 0
}

# ------------------------------------------------------------------------
# Print the JBoss PID to STDOUT if it is running on this host.
# (don't print anything if it is NOT running on this host.
# systems.
#
# NOTE: This function double checks if the PID is a java process.
#
# Return values:
#    0      : JBoss is running
#    1      : JBoss is NOT running
#
# ------------------------------------------------------------------------
function getJBossPid() {
	local JPID=$(ps -u jboss -f | grep "[o]rg\.jboss\.as\.standalone" | awk '{print $2}')
	[ -z "${JPID}" ] && return 1
	if [ $( basename $( readlink -f /proc/${JPID}/exe ) ) = "java" ]; then
		echo -n "${JPID}"
		return 0
	fi
	return 1
}

# ------------------------------------------------------------------------
# Tests if JBoss is running. Works on non-RAS-2.0 systems and on RAS-2.0
# systems.
#
# Return values:
#    0      : JBoss is running
#    1      : JBoss is NOT running
#
# ------------------------------------------------------------------------
function isJBossRunning() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# Old style check (look for PID on local system)
		getJBossPid > /dev/null
		return ${?}
	fi

	# Ask the cluster management software:
	"${CRM_RESOURCE}" --resource "${RSC_APPSERVER}" --locate 2>&1 | grep -v 'NOT running' > /dev/null
}



# ------------------------------------------------------------------------
# Prints the host name of the master node (Sticky Master) on STDOUT if
# it is assigned (should always be the case).
#
# Works on non-RAS-2.0 systems and on RAS-2.0 systems.
#
# Return values (NOTE: return values are REVERSED! Please check carefully):
#    0      : No master node (no StickyMaster has the role Master, unusual)
#    1      : The local node is the master node
#    2      : Another remote node is the master node
#
# ------------------------------------------------------------------------
function locateMasterNode() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# NOt RAS 2.0: Single S4 Appserver, we are always the master
		hostname
		return 1 # Running locally
	fi
	local MASTER_HOST=$(
		"${CRM_RESOURCE}" --resource ms_StickyMaster --locate 2>&1 \
			| sed -ne 's/.*is running on: \([^ ]*\) *Master$/\1/p'
	)
	[ -z "${MASTER_HOST}" ] && return 0
	echo -n "${MASTER_HOST}"
	[ "${MASTER_HOST}" = $( hostname ) ] && return 1
	return 2

}



# ------------------------------------------------------------------------
# Prints the host name on STDOUT if JBoss is running.
#
# Works on non-RAS-2.0 systems and on RAS-2.0 systems.
#
# Return values (NOTE: return values are REVERSED! Please check carefully):
#    0      : JBoss is NOT running
#    1      : JBoss is running locally
#    2      : JBoss is running remotely
#
# ------------------------------------------------------------------------
function locateJBoss() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# Old style check (look for PID on local system)
		if isJBossRunning ; then
			hostname
			return 1 # Running locally
		fi
		return 0 # Not running
	fi

	# Ask the cluster management software:
	local JBOSS_HOST=$(
		"${CRM_RESOURCE}" --resource "${RSC_APPSERVER}" --locate 2>&1 \
			| sed -ne 's/.*is running on: \([^ ]*\) *$/\1/p'
	)
	[ -z "${JBOSS_HOST}" ] && return 0
	echo -n "${JBOSS_HOST}"
	[ "${JBOSS_HOST}" = $( "${CRM_NODE}" -n ) ] && return 1
	return 2
}



# ------------------------------------------------------------------------
# Prints the host name on STDOUT that has the appserver IP address (if it
# is configured)
#
# Works on non-RAS-2.0 systems and on RAS-2.0 systems.
#
# Return values (NOTE: return values are REVERSED! Please check carefully):
#    0      : Appserver IP address is NOT configured
#    1      : Appserver IP address is configured locally
#    2      : Appserver IP address is configured remotely
#
# ------------------------------------------------------------------------
function locateAppserverIp() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# Standard appserver, most likely. It *must* have the
		# appserver IP address. The only alternative would be
		# midway in some RAS 2.0 conversion (or this script is
		# running on RAS 1.0 which should never be the case)
		hostname
		return 1 # Configured locally
	fi

	# Ask the cluster management software:
	local APPSERVER_IP_HOST=$(
		"${CRM_RESOURCE}" --resource AppserverIP --locate 2>&1 \
			| sed -ne 's/.*is running on: \([^ ]*\) *$/\1/p'
	)
	[ -z "${APPSERVER_IP_HOST}" ] && return 0
	echo -n "${APPSERVER_IP_HOST}"
	[ "${APPSERVER_IP_HOST}" = $( "${CRM_NODE}" -n ) ] && return 1
	return 2
}



# ------------------------------------------------------------------------
# Prints the host name on STDOUT that has a DB master running on it
#
# Works on non-RAS-2.0 systems and on RAS-2.0 systems.
#
# Return values (NOTE: return values are REVERSED! Please check carefully):
#    0      : No DB master is running
#    1      : DB master is running locally
#    2      : DB master is running remotely
#
# ------------------------------------------------------------------------
function locateDbMaster() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# Standard appserver, most likely. There is no master/slave
		# but we consider the only DB to be the "master".
		if [ $( pidof mysqld | wc -l ) -gt 0 ]; then
			hostname
			return 1
		fi
		return 0 # No DB running => no master
	fi
	local DB_MASTER_HOST=$(
		"${CRM_RESOURCE}" --resource ms_MariaDB --locate 2>&1 \
			| sed -ne 's/.*is running on: \([^ ]*\) *Master$/\1/p'
	)
	[ -z "${DB_MASTER_HOST}" ] && return 0
	echo -n "${DB_MASTER_HOST}"
	[ "${DB_MASTER_HOST}" = $( "${CRM_NODE}" -n ) ] && return 1
	return 2
}

# ------------------------------------------------------------------------
# Prints the host names of all working DB slaves.
#
# Works on non-RAS-2.0 systems and on RAS-2.0 systems.
#
# Return values (NOTE: return values are REVERSED! Please check carefully):
#    0      : No DB slave is running (no redundancy!)
#    1      : One DB slave is running locally (others could run on other
#             nodes)
#    2      : None of the slaves is running locally
#
# ------------------------------------------------------------------------
function locateDbSlaves() {
	if [ -z "${CRM_RESOURCE}" ]; then
		# Standard appserver, most likely. There are never any
		# slaves on standard appservers.
		return 0 # Std appservers don't have slaves
	fi
	local DB_SLAVE_HOSTS=$(
		"${CRM_RESOURCE}" --resource ms_MariaDB --locate 2>&1 \
			| sed	-n	\
				-e '/ Master$/d' \
				-e 's/.*is running on: \([^ ]*\) */\1/p' \
			| tr '\n' ' ' \
			| sed -e 's/  *$//'
	)
	[ -z "${DB_SLAVE_HOSTS}" ] && return 0 # No slave is running
	echo -n "${DB_SLAVE_HOSTS}"
	SEARCH=" ${DB_SLAVE_HOSTS} "
	[ "${SEARCH// $( "${CRM_NODE}" -n ) /}" = "${SEARCH}" ] && return 2 # No slave running locally
	return 1 # One slave is running locally
}

# ------------------------------------------------------------------------
# Prints a list of nodes, their ID's and their status. Each line is one
# node. The line contains three fields separated by a tab ($'\t'). The
# first field is the node name, the second its ID and the third the status
# (online, standby, OFFLINE).
#
# ------------------------------------------------------------------------
function getNodeList() {
	[ -z "${CRM_MON}" ] \
		&& return 1
	"${CRM_MON}" -1n 2>/dev/null \
		| sed	-n \
			-e 's/^Node \(.*\) (\(.*\)): \([^ ][^ ]*\)$/\1\t\2\t\3/p' \
			-e 's/^Node \(.*\) (\(.*\)): \([^ ][^ ]*\) *(\([^ ]*\))$/\1\t\2\t\3/p'
}



# ------------------------------------------------------------------------
# Prints a list of *unclean* nodes, which is a list of nodes that have
# more than one ID.
#
# ------------------------------------------------------------------------
function getUncleanNodeList() {
	getNodeList \
		| cut -d$'\t' -f1 \
		| sort \
		| uniq -c \
		| sed -e '/^ *1 /d' -e 's/ *[0-9]* //'
}






# ------------------------------------------------------------------------
# Get the replication MySQL credentials from the cluster.
#
# Global variables changed:
#    $REP_USER_NAME: User name to use for the repliation
#    $REP_USER_PASSWORD: Password for the user to use for the repliation
function readReplicationUserCredentials() {
	REP_USER_NAME=$( "${CRM_RESOURCE}" --resource MariaDB:0  --get-parameter replication_user 2>/dev/null )
	REP_USER_PASSWORD=$( "${CRM_RESOURCE}" --resource MariaDB:0  --get-parameter replication_passwd 2>/dev/null )
}

# ------------------------------------------------------------------------
# Asks JBoss nicely to start.
#
# Works on non-RAS-2.0 systems and on RAS-2.0
# systems.
#
# ------------------------------------------------------------------------
function startJBoss() {
	if [ -z "${CRM}" ]; then
		# Old style check (look for PID on local system)
		service ${JBOSS_SERVICE} start
	else
		# Ask the cluster management software:
		"${CRM}" resource start "${RSC_APPSERVER}"
	fi
}



# ------------------------------------------------------------------------
# Asks JBoss nicely to stop. Works on non-RAS-2.0 systems and on RAS-2.0
# systems.
#
# ------------------------------------------------------------------------
function stopJBoss() {
	if [ -z "${CRM}" ]; then
		# Old style check (look for PID on local system)
		service ${JBOSS_SERVICE} stop
	else
		# Ask the cluster management software:
		"${CRM}" resource stop "${RSC_APPSERVER}"
	fi
}

# ------------------------------------------------------------------------
# Print a title centered on the screen with STANDOUT
#
# Parameters:
#    $1     : Title to print (keep it short so that it fits on one line)
#    $2     : Optional color (e.g., $GOOD or $BAD)
#
# ------------------------------------------------------------------------
function printTitle() {
	local TITLE="${1}" ; shift
	if [ ${#} -gt 0 ]; then
		local COLOR="${1}" ; shift
	else
		local COLOR=""
	fi

	if [ -z "${TERMWIDTH}" ]; then
		echo -en "${COLOR}${TITLE}${NORMAL}"
	else
		local MISSING_WS=$(( TERMWIDTH - ${#TITLE} ))
		local LEFT=$(( (TERMWIDTH - ${#TITLE}) / 2 + ${#TITLE} ))
		local RIGHT=$(( TERMWIDTH - LEFT ))
		echo -e "${STANDOUT}${COLOR}$( printf "%${LEFT}s" "${TITLE}" ; printf "%${RIGHT}s" "" )${NORMAL}"
	fi
}



# ------------------------------------------------------------------------
# Sets up a bunch of environment variables that may or may not be helpful
#
# ------------------------------------------------------------------------

if isInTerminal; then
	TPUT="$( findExe tput /bin /usr/bin )"
	TERMWIDTH=$( ${TPUT} cols )
	FOLD="$( findExe fold /bin /usr/bin )"
	if [ -z "${FOLD}" ]; then
		FOLD=cat
	else
		FOLD="${FOLD} -sw${TERMWIDTH}"
	fi
	USECOLOR="${USECOLOR:-yes}"
else
	TPUT=
	TERMWIDTH=
	FOLD=cat
	USECOLOR="${USECOLOR:-no}"
fi
if [[ "${USECOLOR}" == "yes" ]]; then
	HIDE_CURSOR="\e[?25l"
	SHOW_CURSOR="\e[?25h"
	BOLD="\033[1m"
	GOOD="\e[32;01m"
	WARN="\e[33;01m"
	BAD="\e[31;01m"
	REALLYBAD="\e[31;5;1m"
	HILITE="\e[36;01m"
	BRACKET="\e[34;01m"
#	BOLD=$( tput bold )
#	NORMAL=$( tput sgr0 )
#	GOOD="$( tput setaf 2 )"
#	WARN="$( tput setaf 3 )"
#	BAD="$( tput setaf 1 )"
#	HILITE="$( tput setaf 3 )"
#	BRACKET="$( tput setaf 4 )"
	STANDOUT="$( tput smso )"
	# If we run bash with "-x" it will log all the color assignemts
	# which actually sets the colors and whatnot.
	# Keep "NORMAL" at the end to reset all the effects!
	NORMAL="\033[0m$( tput sgr0 )"
else
	HIDE_CURSOR=""
	SHOW_CURSOR=""
	BOLD=""
	GOOD=""
	WARN=""
	BAD=""
	REALLYBAD=""
	HILITE=""
	BRACKET=""
	STANDOUT=""
	NORMAL=""
fi

# Try to find the CRM tools. These variables are going to be empty
# if heartbeat/pacemaker is not installed
CRM="$( findExe crm /bin /usr/bin /sbin /usr/sbin )"
CRM_RESOURCE="$( findExe crm_resource /bin /usr/bin /sbin /usr/sbin )"
CRM_FAILCOUNT="$( findExe crm_failcount /bin /usr/bin /sbin /usr/sbin )"
CRM_MON="$( findExe crm_mon /bin /usr/bin /sbin /usr/sbin )"
CRM_NODE="$( findExe crm_node /bin /usr/bin /sbin /usr/sbin )"
CRM_ATTRIBUTE="$( findExe crm_attribute /bin /usr/bin /sbin /usr/sbin )"


MYSQL="$( findExe mysql /bin /usr/bin /usr/local/mysql/bin )"
MYSQLD="$( findExe mysqld /usr/libexec /usr/sbin /usr/bin )"
MYSQLDUMP="$( findExe mysqldump /bin /usr/bin /usr/local/mysql/bin )"
MYSQL_OPTS="${MYSQL_OPTS:-}"

MYSQLD_PID=

# Names of the resources we control. The variable names are generic, e.g., "APPSERVER"
# is either JBoss or Wildfly
# Not part of RAS => we don't have an "appserver" resource
RSC_APPSERVER=
JBOSS_SERVICE=${SERVICE:-wildfly}

# Define some user readable names for our generic stuff, e.g., "Wildfly" for the
# appserver resource
LBL_APPSERVER="${LBL_APPSERVER:-${RSC_APPSERVER}}"


OK_MASTER_SLAVE_POS_DIFFERENCE=${OK_MASTER_SLAVE_POS_DIFFERENCE:-500000000}
OK_MASTER_SLAVE_FILE_DIFFERENCE=${OK_MASTER_SLAVE_FILE_DIFFERENCE:-2}

FACILITY_CODE=
if [ -f "/etc/gwn/server.conf" ]; then
	eval $(
		sed	-n \
			-e 's/^[ \t]*facility_code:[ \t]*\([^ \t][^ \t]*\)$/FACILITY_CODE="\1";/p' \
			/etc/gwn/server.conf
	)
fi

#
# Possible status codes that "system-status" may return:
#

# JBoss
STATUS_JBOSS_NOT_RUNNING=1
(( STATUS_JBOSS_MASK = STATUS_JBOSS_NOT_RUNNING ))

# DB Master
STATUS_DB_MASTER_NOT_RUNNING=2
(( STATUS_DB_MASTER_MASK = STATUS_DB_MASTER_NOT_RUNNING ))

# DB Slave running/not running
                                 #   1
                                 #   2 6 3 1
                                 #   8 4 2 6 8 4 2 1
STATUS_DB_NO_SLAVE_RUNNING=4     #           0 1     = 4
STATUS_DB_SOME_SLAVES_RUNNING=8  #           1 0     = 8
(( STATUS_DB_SLAVE_RUNNING_MASK = STATUS_DB_NO_SLAVE_RUNNING + STATUS_DB_SOME_SLAVES_RUNNING ))

# DB Slave replication status
#   Logic: if there is at least one slave too far behind then
#          we report that (even if some others are behind).
                                 #   1
                                 #   2 6 3 1
                                 #   8 4 2 6 8 4 2 1
STATUS_DB_SOME_BEHIND=16         #     0 0 1         = 16
STATUS_DB_ALL_BEHIND=32          #     0 1 0         = 32
STATUS_DB_SOME_TOO_FAR_BEHIND=48 #     0 1 1         = 48
STATUS_DB_ALL_TOO_FAR_BEHIND=64  #     1 0 0         = 64
(( STATUS_DB_REPLICATION_MASK = STATUS_DB_SOME_BEHIND + STATUS_DB_ALL_BEHIND + STATUS_DB_ALL_TOO_FAR_BEHIND ))

