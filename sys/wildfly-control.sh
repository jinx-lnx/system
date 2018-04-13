#!/bin/bash -u


function logLevelInfoForClass() {
	local CLASS="${1}"

	while [ ! -z "${CLASS}" ]; do
		local CURRENT_LEVEL="$( /opt/wildfly/bin/jboss-cli.sh --connect "read-attribute --node=/subsystem=logging/logger=${CLASS} level" )"
		if [ -z "${CURRENT_LEVEL}" ]; then
			echo "${CLASS}: <default>"
		else
			echo "${CLASS}: ${CURRENT_LEVEL}"
		fi
		local NEW_CLASS="${CLASS%.*}"
		if [ "${CLASS}" = "${NEW_CLASS}" ]; then
			CLASS=
		else
			CLASS="${NEW_CLASS}"
		fi
	done
}

function logLevelInfoForAll() {
	/opt/wildfly/bin/jboss-cli.sh --connect "read-attribute --node=/subsystem=logging/logger=* level" \
		| sed -n -e '/logger=/{N;N;s/\n/ /g;s/.*logger=\([^ ]*\) .*result=/\1\t/;p}' \
		| sort
}

function setLogLevel() {
	local CLASS="${1}"
	local LEVEL="$( echo "${2}" | tr '[:lower:]' '[:upper:]' )"

	case "${LEVEL}" in
		DEBUG|CONFIG|INFO|WARN|WARNING|ERROR|FATAL|OFF)
			local CURRENT_LEVEL="$( /opt/wildfly/bin/jboss-cli.sh --connect "read-attribute --node=/subsystem=logging/logger=${CLASS} level" )"
			local NEW_LEVEL=
			local RESULT_TEXT=
			if [ "${CURRENT_LEVEL}" = "${LEVEL}" ]; then
				echo "Class \"${CLASS}\" is already set to \"${LEVEL}\""
			else
				echo -ne "Changing \"${CLASS}\" from \"${CURRENT_LEVEL}\" to \"${LEVEL}\"... "
				# First attempt to remove the class if it exists
				RESULT_TEXT="$( /opt/wildfly/bin/jboss-cli.sh --connect "/subsystem=logging/logger=${CLASS}:remove" )"
				# Then add it again with the desired log level
				RESULT_TEXT="$( /opt/wildfly/bin/jboss-cli.sh --connect "/subsystem=logging/logger=${CLASS}:add(level=${LEVEL})" )"
				NEW_LEVEL="$( /opt/wildfly/bin/jboss-cli.sh --connect "read-attribute --node=/subsystem=logging/logger=${CLASS} level" )"
				logger -t "${LOGGER_TAG}" "\"${SUDO_USER}\" changed \"${CLASS}\" from \"${CURRENT_LEVEL}\" to \"${NEW_LEVEL}\""
				case "${RESULT_TEXT}" in
					*outcome*success*)
						echo -e "done.\nNew level is now \"${HILITE}${NEW_LEVEL}${NORMAL}\"."
						;;
					*)
						echo -e "failed.\nLevel is \"${HILITE}${NEW_LEVEL}${NORMAL}\"."
						;;
				esac
			fi
			;;
		*)
			echo -e "${WARN}Invalid level \"${LEVEL}\"${NORMAL} for class \"${HILIE}${CLASS}${NORMAL}\"${NORMAL}"
			;;
	esac
}


function reformatHl7() {
		if [ ! -e /opt/assets/Global/Common/Hl7/hl7XSL.xslt ] ; then
			echo -e "\n${BAD}ERROR${NORMAL}: No ${BOLD}hl7XSL.xslt${NORMAL} file present.\n"
		elif [ ! -e /opt/config/hl7.xml ] ; then
			echo -e "\n${BAD}ERROR${NORMAL}: No ${BOLD}hl7.xml file${NORMAL} present.\n"
		else
			sudo -u jboss xmlstarlet tr /opt/assets/Global/Common/Hl7/hl7XSL.xslt /opt/config/hl7.xml > /opt/config/hl7changed.xml
			if [ $? -eq 0 ] ; then
				mv /opt/config/hl7changed.xml /opt/config/hl7.xml
				chown jboss:jboss /opt/config/hl7.xml
			else
				echo -e "\n${BAD}ERROR${NORMAL}: Something went wrong during reformat. Aborting.\n"
			fi
		fi
}


SCRIPT_PATH="$( readlink -f "${BASH_SOURCE[0]}" )"
BASE_DIR="$( dirname "${SCRIPT_PATH}" )"
if [ ! -f "${BASE_DIR}/functions.sh" ]; then echo "'functions.sh' not found" ; exit 1; fi
. "${BASE_DIR}/functions.sh"

LOGGER_TAG="$( basename "${SCRIPT_PATH}" .sh )"
SUDO_USER="${SUDO_USER:-root}"

if [ ${#} -eq 0 ]; then
	COMMAND="help"
else
	COMMAND="${1}" ; shift
fi


case "${COMMAND}" in

	zap|terminate|restart)
		# These are no longer supported in Ubuntu
		echo "The \"${COMMAND}\" command is not supported."
		;;

	stop)
		# No running jboss? Nothing do to.
		if ! isJBossRunning; then
			echo "No running Wildfly found"
			exit
		fi

		#### BEGIN: Force User to Provide Authorization and Reason for Restart ####
		test -z "${MAILNAME:-}" && MAILNAME=${SUDO_USER}
		case "${MAILNAME}" in
			admin*|root)
				MAILNAME=
				;;
		esac

		while [ -z "${MAILNAME:-}" ] ; do
			read -p "Please Provide Your REAL Name: " MAILNAME
		done
		while [ -z "${MAILREASON:-}" ] ; do
			read -p "Please Provide the REASON why you want to ${COMMAND} Wildfly: " MAILREASON
		done

		cat << EOF | /opt/gwn/python/servermail.py -s "Wildfly Stopped Manually" -c sthompson@getwellnetwork.com
Wildfly was stopped (command: ${COMMAND}) manually by "${MAILNAME}".

Reason:
"${MAILREASON}".
EOF
		#### END: Force User to Provide Authorization and Reason for Restart ####

		# Hand over to init script
		stopJBoss

		# Wait for Wildfly to shut down before ending script
		echo -n "Waiting up to 60 seconds for Wildfly to shut down: "
		for I in $(seq 1 60) ; do
			isJBossRunning || break
			echo -n "."
			sleep 1
		done
		echo

		JBOSS_HOST=$( locateJBoss )
		case ${?} in
			0)	# Wildfly is NOT running, we're in the clear
				;;
			1)	# Wildfly is running locally, we can kill it
				JPID=$( getJBossPid )
				if [ ${?} -eq 0 ]; then
					echo -e "\n${BAD}ERROR${NORMAL}: Wildfly did not shut down in time. ${BOLD}Terminating Wildfly PID ${JPID}${NORMAL}.\n"
					kill -9 ${JPID}
					echo -e "${GOOD}Terminated${NORMAL}."
				else
					echo -e "\nERROR: Wildfly did not shut down in time.\n\nIt seems to be running locally but the PID could not be found. Could not terminate Wildfly.\n"
				fi

				;;
			2)	# Wildfly is running but not locally
				echo -e "\n${BAD}ERROR${NORMAL}: Wildfly did not shut down in time.\n\nHowever, Wildfly is not running locally, so you need to log into \"${HILITE}${JBOSS_HOST}${NORMAL}\" and rereun this script there.\n"
				;;
		esac
		;;


	start)
		JBOSS_HOST=$( locateJBoss )
		case ${?} in
			0) # Not running, can continue
				;;
			1) # Wildfly running locally
				JPID=$( getJBossPid )
				echo -e "\n${BAD}ERROR${NORMAL}${BOLD}:${NORMAL} Detected Wildfly running locally (pid: ${JPID}). Refusing to start again.\n"
				exit
				;;
			2) # Wildfly running remotely
				echo -e "\n${BAD}ERROR${NORMAL}${BOLD}:${NORMAL} Detected Wildfly running on \"${JBOSS_HOST}\". Refusing to start again.\n"
				exit
			;;
		esac

		# This is probably useless with Heartbeat. The RA should handle that.
		# Still, we keep it in here for non-Heartbeat systems.
		echo "Creating .dodeploy flags"
		for M in assets.war pls.ear ; do
			echo "     Touching ${M}"
			rm -f /opt/wildfly/standalone/deployments/${M}.*
			test -d /opt/wildfly/standalone/deployments/${M} && touch /opt/wildfly/standalone/deployments/${M}.dodeploy
		done

		startJBoss
		;;

	log|debuglog)
		JBOSS_HOST=$( locateJBoss )
		case ${?} in
			0)	# Wildfly is NOT running
				echo -e "${WARN}WARNING${NORMAL}${BOLD}:${NORMAL} Wildfly ${BOLD}not running${NORMAL}."
				;;
			1)	# Wildfly is running locally, nothing special to do
				;;
			2)	# Wildfly is running but not locally
				echo -e "${WARN}WARNING${NORMAL}${BOLD}:${NORMAL} Wildfly ${BOLD}not running locally${NORMAL} but on \"${HILITE}${JBOSS_HOST}${NORMAL}\".\nYou might want to watch the logs there."
				;;
		esac
		case "${COMMAND}" in
			log)
				tail -F /opt/wildfly/standalone/log/server.log
				;;
			debuglog)
				tail -F /opt/wildfly/standalone/log/debug.log
				;;
		esac
		;;

	edit|editconf|edithl7)
		JBOSS_HOST=$( locateJBoss )
		if [ ${?} -eq 2 ]; then # Wildfly is running but not locally
			echo -e "${WARN}WARNING${NORMAL}${BOLD}:${NORMAL} Wildfly not running locally but on \"${HILITE}${JBOSS_HOST}${NORMAL}\".\nYou might want to ${COMMAND} there.\nPress <Enter> to continue."
			read
		fi
		case "${COMMAND}" in
			edit)
				sudoedit -u jboss /opt/wildfly/standalone/configuration/standalone.xml
				;;

			editconf)
				sudoedit -u jboss /opt/wildfly/standalone/deployments/assets.war/WEB-INF/config/Configuration.xml
				;;
			edithl7)
				sudoedit -u jboss /opt/wildfly/standalone/deployments/assets.war/WEB-INF/config/hl7.xml
				reformatHl7
				;;
		esac
		;;

	portcheck)
		JBOSS_HOST=$( locateJBoss )
		if [ ${?} -eq 2 ]; then # Wildfly is running but not locally
			echo -e "${WARN}Note${NORMAL}${BOLD}:${NORMAL} Wildfly not running locally but on \"${HILITE}${JBOSS_HOST}${NORMAL}\"."
		fi
			
		HL7CONF="/opt/wildfly/standalone/deployments/assets.war/WEB-INF/config/hl7.xml"
		if [ -f "${HL7CONF}" ] ; then
			# Find only enabled interfaces
			for NAME in $(xmlstarlet sel -t -m "//listener[enabledOnStart='true'] | //sender[enabledOnStart='true']" -v "@id" -n ${HL7CONF} 2> /dev/null) ; do
				CLIENTINTERFACE=$(xmlstarlet sel -t -m "//listener[@id='${NAME}'] | //sender[@id='${NAME}']" -v "clientInterfaceName" ${HL7CONF} 2> /dev/null)
				PORT=$(xmlstarlet sel -t -m "//listener[@id='${NAME}'] | //sender[@id='${NAME}']" -v "port" ${HL7CONF} 2> /dev/null)
				PERSIST=$(xmlstarlet sel -t -m "//listener[@id='${NAME}'] | //sender[@id='${NAME}']" -v "persist" ${HL7CONF} 2> /dev/null)
                 
				echo -e "\n${STANDOUT}Connection Status of Interface '${NAME}' (Clients Interface Name: '${CLIENTINTERFACE}')${NORMAL}"
				test -n "${PORT}" && netstat -an | grep ${PORT}
				if [ "$PERSIST" == "false" ]; then 
					echo -e "${BOLD}NOTE: This is configured as a transient connection, you may not see an active connection${NORMAL}"
				fi
			done
		else
			echo "ERROR: Cannot find hl7.xml"
		fi
		;;

	deploy)
		"${BASE_DIR}/wildfly-deploy.sh" "${@}"
		;;

	reformatHl7)
		reformatHl7
		;;

	loglevel)
		JBOSS_HOST=$( locateJBoss )
		case ${?} in
			0)	# Wildfly is NOT running
				echo -e "${BAD}ERROR${NORMAL}: Wildfly is ${BOLD}not running${NORMAL}"
				;;
			1)	# Wildfly is running locally, nothing special to do
				if [ ${#} -eq 1 ]; then
					setLogLevel "${1}" "INFO"
				elif [ ${#} -eq 2 ]; then
					setLogLevel "${1}" "${2}"
				else
					echo -e "${BAD}Incorrect number of parameters for${NORMAL} \"${HILITE}${COMMAND}${NORMAL}\":"
					echo -e "  ${COMMAND} <class> <level> # set log level of <class> to <level>"
					echo -e "- or -"
					echo -e "  ${COMMAND} <class>         # set log level of <class> to INFO"
				fi
				;;
			2)	# Wildfly is running but not locally
				echo -e "ERROR: Wildfly not running locally but on \"${JBOSS_HOST}\"."
				;;
		esac
		;;


	loglevelinfo)
		JBOSS_HOST=$( locateJBoss )
		case ${?} in
			0)	# Wildfly is NOT running
				echo -e "${BAD}ERROR${NORMAL}: Wildfly is ${BOLD}not running${NORMAL}"
				;;
			1)	# Wildfly is running locally, nothing special to do
				if [ ${#} -eq 0 ]; then
					logLevelInfoForAll
				elif [ ${#} -eq 1 ]; then
				    logLevelInfoForClass "${1}"
				else
					echo -e "${BAD}Incorrect number of parameters for${NORMAL} \"${HILITE}${COMMAND}${NORMAL}\":"
					echo -e "  ${COMMAND} <class>"
				fi
				;;
		esac
		;;

	help)
		cat << EOF

Wildfly: Supported commands
---------------------------

start        : Start the Wildfly service

stop         : Stop the Wildfly service. If the process does not
               shut down after 60 seconds, it will automatically
               be terminated.

log          : Follow the 'server.log'

debuglog     : Follow the 'debug.log'

edit         : Edit JBoss' standalone.xml configuration file

editconf     : Edit PLS' Configuration.xml file

edithl7      : Edit PLS' hl7.xml file

portcheck    : Show the ports and connections used for HL7

deploy       : Deploy a certain PLS build
               Usage: wildfly deploy {optional PLS tag}

loglevel     : Edit the JBoss loglevel right now (no restart needed)
               Usage: wildfly loglevel {log class} {new log level}

loglevelinfo : Shows log levels for various logging classes
               Usage: wildfly loglevelinfo  [<class>]
               If "<class>" is omitted all currently defined log levels
               are printed.
               If "<class>" is given then the log level of that class
               (or package) is printed and then it's parent package, 
               the parent of the parent of the class (or package) and
               so on.
EOF
	;;

  *)
	echo "Unsupported command: ${COMMAND}"
	;;

esac
