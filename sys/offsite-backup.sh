#!/bin/bash

##
##  Copies the FACILITY-BACKUP files off-site. Preferably to
##  Amazon S3. If that cannot be reached, you can force the transfer
##  to go to Colossus.hq by adding the following entry to
##  /etc/gwn/server.conf:
##
##      offsite_backup: HQ
##
##


# First, check if it's even our turn _right now_ (based on the hash of our host name)
if [ ! -x /opt/gwn/python/timeslot-hasher.py ] ; then
  # The checker script is missing, bailing out
  exit
fi

/opt/gwn/python/timeslot-hasher.py --tag OFFSITE --weekdays mon tue wed thu fri sat sun \
    --hours 0 1 2 3 4 5 6 --quiet

# Not our turn? Bail out fast.
if [ $? -eq 1 ] ; then
  exit 1
fi



. /opt/gwn/system/functions.sh

PIDFILE=/dev/shm/OffsiteBackup.pid


# Are we running in a true terminal or from cron?
if isInTerminal ; then
  LOGFILE=/dev/stdout
else
  LOGFILE=$(mktemp /opt/tmp/OffsiteBackup.log.XXXXXXXXXX)
fi


# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------


function print_step() {
  echo -e "\n* ${*}" >> ${LOGFILE}
}

function clean_up() {
  print_step "Cleaning up..."
  test -f "${PIDFILE}" && rm ${PIDFILE}
  test -f "${LOGFILE}" && rm ${LOGFILE}
}

function die() {
  echo -e "\n  ***\n  *** ${@}\n  ***\n"
  echo -e "Full output:\n------------"
  test -f "${LOGFILE}" && cat ${LOGFILE}
  exit 1
}



# ----------------------------------------------------------------------------
# Script start
# ----------------------------------------------------------------------------

# Are we already running?
if [ -f "${PIDFILE}" ] ; then
  # Don't want to run multiple copies
  exit
else
  # Create PID file and ensure cleanup after script ends or aborts
  echo "$$" > ${PIDFILE}
  trap clean_up EXIT TERM KILL INT
fi

# Never run on test servers
if isTestServer ; then
  if isInTerminal ; then
    echo -e "\n *** ERROR: This is a test server. Offsite backup not supported.\n"
  fi
  exit
fi

# Only run if the server is marked for production
if ! isProduction ; then
  if isInTerminal ; then
    die "This server is not marked for production use in /etc/gwn/server.conf."
  fi
  exit 1
fi

# Pick the configured off-site backup method. Default is Amazon s3.
if [ -n "$(grep -E "offsite_backup:.*HQ" /etc/gwn/server.conf)" ] ; then
  TARGET="HQ"
elif [ -n "$(grep -E "offsite_backup:.*custom" /etc/gwn/server.conf)" ] ; then
  TARGET="custom"
elif [ -n "$(grep -E "offsite_backup:.*off" /etc/gwn/server.conf)" ] ; then
  logger "Offsite backup disabled in server.conf"
  exit
else
  TARGET="s3"
fi


  HOST=$(hostname -f)
  if test -z "${HOST}" ; then
    die "ERROR: Invalid hostname detected."
  fi
  
  SOURCEDIR=/opt/FACILITY-BACKUP

  # To be on the safe side that there are backups available to send off-site,
  # we use yesterday's daily backups. Then we don't have to worry about when
  # the daily backup is done and when the server got their offsite slot.
  YESTERDAY=$(date -d '1 day ago' +'%F')
  
  ## Does the backup dir exist?
  ##
  if test ! -d "${SOURCEDIR}" ; then
    die "ERROR: Could not find source directory '${SOURCEDIR}'"
  fi

  # Capture the success/failure of the backup
  RET=0



  # -------------------------------------------------------------------------
  # Configured backup to Amazon S3
  # -------------------------------------------------------------------------
  if [ "${TARGET}" = "s3" ] ; then

    S3_BACKUP=/opt/gwn/python/backup_to_s3.py
    if [ -x "${S3_BACKUP}" ] ; then
      print_step "Starting backup to Amazon S3: $(date)"

      for FILE in $(find ${SOURCEDIR}/{Assets,GWN,System}*${YESTERDAY}* -type f) ; do
        ${S3_BACKUP} -f ${FILE} >> ${LOGFILE} 2>&1
        RET=$(expr ${RET} + $?)
      done
    else
      die "Cannot find or execute ${S3_BACKUP} script"
    fi



  # -------------------------------------------------------------------------
  # Configured backup to Colossus at HQ
  # -------------------------------------------------------------------------
  elif [ "${TARGET}" = "HQ" ] ; then

    print_step "Starting backup to Colossus: $(date)"

    # Since the backup files don't change, we can do inplace and append to support
    # extra-slow sites that time out or abort often. In order to prevent the script
    # from running for days (like it often does at FFL), a timeout should abort
    # early and retry.
    timeout -s KILL 18h rsync -crvh --stats --no-motd --inplace --append-verify --timeout=7200 \
        ${SOURCEDIR}/*${YESTERDAY}* rsync://colossus.hq/FACILITY/${HOST}  >> ${LOGFILE} 2>&1
    RET=$?



  # -------------------------------------------------------------------------
  # Configured backup to use custom script
  # -------------------------------------------------------------------------
  elif [ "${TARGET}" = "custom" ] ; then

    die "Custom backup method not implemented yet"

  else

    die "Unsupported off-site backup target: '${TARGET}'"

  fi


  # -------------------------------------------------------------------------
  # Check the return value of the backup script and act accordingly
  # -------------------------------------------------------------------------

  if [ ${RET} -ne 0 ] ; then
    die "ERROR: Some error occured during offsite backup: $(date)"
  else
    print_step "Offsite backup complete at $(date)"
  fi

  # Mail the logfile to root and discard it
#  if [ -f "${LOGFILE}" ] ; then
#    # Too noisy and nobody ever reads it :-(
#    cat ${LOGFILE} | mail -s "New Offsite Backup: ${HOST}" bnigmann@getwellnetwork.com
#    test -f "${LOGFILE}" && rm $LOGFILE
#  fi

