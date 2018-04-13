#!/bin/bash

# Service Level Agreement reporting cron job
# ------------------------------------------
#
# This cron job frequently tries to access a page in PLS and logs success
# or failure in a database table. A failure or a missing log event for any
# 5-minute-period is considered a down state.
#
# The following database table needs to exist for this script to work:
#
#  CREATE TABLE `GWN_SLAReport` (
#     `timestamp` datetime NOT NULL,
#     `success` tinyint(1) NOT NULL DEFAULT '0',
#     `firstAttemptSuccess` tinyint(1) NOT NULL DEFAULT '1',
#     KEY `idx_timestamp` (`timestamp`)
#   ) ENGINE=InnoDB DEFAULT CHARSET=utf8
#

. /opt/gwn/system/functions.sh

# Never run on test servers
if isTestServer ; then
  if isInTerminal ; then
    echo -e "\n *** ERROR: This is a test server. SLA report not supported.\n"
  fi
  exit
fi

# Only run this on production machines
if ! isProduction ; then
  if isInTerminal ; then
    echo -e "\n *** ERROR: This server is not marked for production use in /etc/gwn/server.conf.\n"
  fi
  exit
fi


# The check URL
CHECK_URL="http://appserver.gwn/Admin/sysinfo/Sysinfo.action?runCheck=com.gwn.plife.sysinfo.checks.AppVersionCheck&authUserName=gwnreporter&authUserPassword=ixNq^4nJJeX1"


# MySQL command
MYSQL="/usr/bin/mysql -ur5user -pr5user GWN_R5"

# Check if the reporting table exists
${MYSQL} -e "DESC GWN_SLAReport" >/dev/null 2>&1
if [ $? -ne 0 ] ; then
  # If run by cron, only complain once per hour
  if isInTerminal || [ $(date +"%M") -eq 00 ] ; then
    echo -e "\n*** ERROR: SLA reporting table 'GWN_SLAReport' does not exist yet or access denied.\n"
  fi
  exit 1
fi


# Evil hack to make sure the script retries up to 4 minutes after the first test,
# before the next scheduled run for this script rolls around. Not pretty, but until
# we can do this in Python, we'll have this ugly hack.
#
STARTMINUTE=$(expr $(date +"%s") / 60)
ENDMINUTE=$(expr ${STARTMINUTE} + 4)
FIRSTSUCCESS=1

# Repeat while we are in the 4-minute interval for the current test run
while [ $(expr $(date +"%s") / 60) -lt ${ENDMINUTE} ] ; do

  if isInTerminal ; then
    echo "Started: $STARTMINUTE, Not reached $ENDMINUTE: NOW: $(expr $(date +"%s") / 60)"
  fi

  RESULT=$(timeout -s TERM 50s /usr/bin/wget -q --timeout=45 --tries=1 -O - ${CHECK_URL} \
	| grep -Ei '(status-code="OK"|Login form)')

  if [ -n "${RESULT}" ] ; then
    if isInTerminal ; then
      echo "SUCCESS: FIRST? $FIRSTSUCCESS"
    fi
    ${MYSQL} -e "INSERT INTO GWN_SLAReport VALUES (now(), 1, ${FIRSTSUCCESS})"
    exit 0
  else
    if isInTerminal ; then
      echo "FAIL"
    fi
    FIRSTSUCCESS=0
  fi

  sleep 30

done

# All attempts fail. Need to report this interval as failed.
${MYSQL} -e "INSERT INTO GWN_SLAReport VALUES (now(), 0, 0)"

