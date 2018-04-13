#!/usr/bin/env bash 
set -u

##
## Appserver backup script for S4 appservers
##

. /opt/gwn/system/functions.sh

ASSETS7FOLDER="/opt/jboss7/standalone/deployments/assets.war"
ASSETS9FOLDER="/opt/wildfly/standalone/deployments/assets.war"
BACKUPTARGET="/opt/FACILITY-BACKUP"
MYSQLDUMP=$(which mysqldump)
TODAY=$(date +"%F")
SYSINF_STR='{"daily_backup": {'
LCKFILE="/tmp/cron.daily.backup.lck"

# ----------------------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------------------
function printHeading() {
  echo -e "\n\n# -----------------------------------------------------------------------------------------" 
  echo -e "# ${1}" 
  echo -e "# -----------------------------------------------------------------------------------------\n"
}

function printError() {
  echo -e "\n  ***\n  *** ${@}\n  ***\n"
}

function die() {
  echo '{"daily_backup": {"status": "ERROR:' "${@}" '"}}' | /opt/gwn/python/sysinf.py --type info
  printError ${@}
  exit 1
}

function cleanToday() {
  for q in opt/FACILITY-BACKUP/*"${TODAY}"* ; do
    [[ -e "${q}" ]] ||
    echo -e "\n Purging previous backups from today"
    rm -f /opt/FACILITY-BACKUP/*"${TODAY}".* ||
    echo -e "no existing backup from today nothing to delete"
    break
  done
}

function keepLastThree() {

  if test -z "${1}" ; then
    printError "ERROR: No pattern specified for keepLastThree()"
    exit 1
  fi

  echo -e "\n* Purging all but the most recent three: ${1}"

  KEEPERS=$(find "${BACKUPTARGET}" -name "${1}" | sort | tail -n3)

  for FILE in $(find "${BACKUPTARGET}" -name "${1}" | sort) ; do

    TEST=$(echo "${KEEPERS}" | grep "${FILE}")

    if test -n "${TEST}" ; then
      echo -e "\t-- Keeping recent file ${FILE}"
    else
      echo -e "\t-- Purging file ${FILE}"
      rm "${FILE}"
    fi
  done
}

function bckupwork() {
  # ----------------------------------------------------------------------------
  # mysqldump with --single-transaction and ignoring some volatile tables
  # ----------------------------------------------------------------------------

  # Only if a local MariaDB server is installed
  dpkg -l mariadb-server >/dev/null 2>&1
  if [ $? -eq 0 ] ; then
    printHeading "Creating full, encrypted GWN database dump to '${GWN_FILE}'"
    COMMAND="time ${MYSQLDUMP} --single-transaction --add-drop-table --create-options --quick \
	--ignore-table GWN_R5.LOG_TmpInternetSummary \
	--ignore-table GWN_R5.TMP_Utilization \
	--ignore-table GWN_R5.MEDTMP_Medication \
	--extended-insert -u backup -ps3r3nd1p1ty GWN_R5 \
	${VERBOSE1} \
	| xz -1 | gpg --homedir /root/.gnupg --compress-algo none -e -r Facility \
	${VERBOSE2} > ${GWN_FILE}.part"
    eval "${COMMAND}" || die "ERROR: Problems during the database backup"
    # Rename the partial file to the 'real' name
    test -f "${GWN_FILE}".part && mv "${GWN_FILE}".part "${GWN_FILE}"
    SYSINF_DB=$(buildComponentStr "database" "created" "${GWN_FILE}")
  else
    printHeading "No MariaDB server installed locally. Skipping database backup"
    SYSINF_DB='"database": { "status": "skipped" }'
  fi
}

function bckupsysfol() {
  tar -cj --exclude='/opt/plc-root/opt/www/plc-bs*' --exclude='/opt/plc-root/opt/www/patches' \
    /etc \
    /lib/ufw \
    /opt/plc-root/opt/www \
    /opt/plc-root/opt/data \
    /opt/jboss7/standalone/configuration \
    /opt/wildfly/standalone/configuration \
	| gpg --homedir /root/.gnupg --compress-algo none -e -r Facility \
	> "${SYSTEM_FILE}"
  echo "  System backup created:"
  ls -lh "${SYSTEM_FILE}"
  SYSINF_SYSTEM=$(buildComponentStr "system" "created" "${SYSTEM_FILE}")
}

function buildComponentStr() {
  printf '"%s": { "status": "%s", %s }' "${1}" "${2}" "$(stat -c '"size": %s, "file_name": "%n"' "${3}")"
}

function bckupassets() {
  COMMAND="tar -c --exclude='/opt/jboss7/standalone/deployments/assets.war/plc' \
    --exclude='/opt/wildfly/standalone/deployments/assets.war/plc' \
	${ASSETS7FOLDER} \
	${ASSETS9FOLDER} \
	${VERBOSE1} \
	| xz -1 \
	| gpg --homedir /root/.gnupg --compress-algo none -e -r Facility \
	${VERBOSE2} > ${ASSETS_FILE}"
  eval "${COMMAND}" || die "ERROR: Problems backing up JBoss-7 assets"
  SYSINF_ASSETS=$(buildComponentStr "assets" "created" "${ASSETS_FILE}")
}

# ----------------------------------------------------------------------------
# Script start
# ----------------------------------------------------------------------------
lock 9 "${LCKFILE}" "${BASH_SOURCE[0]} is already running. Wait your turn"

# Register the cleanup call at EXIT
function cleanup_lockfile() {
  echo "Cleaning up lock file"
  clean_up "${LCKFILE}"
}
trap cleanup_lockfile EXIT

# When the is_production flag is false, this script should not be run via cron.
# Salt manages the cron file. But for the PLS deployment wrapper, we do need
# these backups, so just print a warning and still proceed with the backup.
# (PLATSUP-26645)
if ! isProduction ; then
  echo "This server is not marked for production use in /etc/gwn/server.conf. Proceeding with backup, though."
fi

printHeading "Daily backup script starting on $(hostname -f) at $(date)"
SYSINF_STR="${SYSINF_STR}"'"start": "'"$(date -Iseconds)"'", '

echo -e "* Verifying target folder"
test ! -d "${BACKUPTARGET}" && mkdir -p "${BACKUPTARGET}"

# If this is run in a terminal, show some progress bars. Otherwise (cron) be quiet.
if ! isInTerminal ; then
  VERBOSE1=""
  VERBOSE2=""
else
  VERBOSE1="| pv -w 75 -cN RAW"
  VERBOSE2="| pv -w 75 -cN XZ"
fi



# ----------------------------------------------------------------------------
# Do we need to run the database backup?
# ----------------------------------------------------------------------------

GWN_FILE="${BACKUPTARGET}"/GWN-R5_"${TODAY}".sql.xz.gpg
if [[ -f "${GWN_FILE}" ]] ; then
  cleanToday
  bckupwork
else
  bckupwork
fi

# Purge all but the most recent 3 backup files
keepLastThree "GWN-R5_????-??-??\.sql\.*\.gpg"


# ----------------------------------------------------------------------------
# Back up various system folders and files
# ----------------------------------------------------------------------------

printHeading "Archiving a selection of system folders"
SYSTEM_FILE="${BACKUPTARGET}"/System_"${TODAY}".tbz.gpg
if [[ -f "${SYSTEM_FILE}" ]] ; then
  cleanToday
  bckupsysfol
else
  bckupsysfol
fi

keepLastThree "System_????-??-??\.*\.gpg"



# ----------------------------------------------------------------------------
# Back up assets folder
# ----------------------------------------------------------------------------

printHeading "Archiving assets folder"

ASSETS_FILE="${BACKUPTARGET}"/Assets-R5_"${TODAY}".txz.gpg
if test -f "${ASSETS_FILE}" ; then
  cleanToday
  bckupassets
else
  bckupassets
fi

keepLastThree "Assets-R5_????-??-??\.*\.gpg"

SYSINF_STR=$(printf '%s "components": { %s, %s, %s },' "${SYSINF_STR}" "${SYSINF_DB}" "${SYSINF_SYSTEM}" "${SYSINF_ASSETS}")


# ----------------------------------------------------------------------------
# Copy today's files over to one of the video servers
# ----------------------------------------------------------------------------


printHeading "Trying to offload the backups on the first streaming server that responds"

FACILITY=$(/opt/gwn/python/get-facility-code.py)
STREAMSUCCESS=""
for I in 1 2 3 4 5 6 7 ; do
  RDEST="rsync://vls${I}.${FACILITY}.gwn/backup"
  echo -n "* Trying rsync to ${RDEST}... "
  RTEST=$(rsync --contimeout=5 "${RDEST}" 2>/dev/null)
  
  if [ -z "${RTEST}" ] ; then
    echo "failed."
  else
    echo "received response."
    echo "* Rsyncing backup files"
    rsync -aq --delete --filter '+ G*' --filter '+ A*' --filter '+ S*' --filter '- **' "${BACKUPTARGET}"/. "${RDEST}"/.
    if [ $? -gt 0 ] ; then
      printError "ERROR: Problems during rsync"
    else
      STREAMSUCCESS="true"
      SYSINF_VLS=$(printf '"vls_offload": "success", "vls_target": "%s"' "${RDEST}")
      break
    fi
  fi
done

# Was the rsync to one of the streamers successful?
if [ -z "${STREAMSUCCESS}" ] ; then
  SYSINF_VLS='"vls_offload": "failed"'
  printError "ERROR: Unable to offload the backups to any streaming server"
fi

SYSINF_STR=$(printf '%s %s, "end": "%s"}}' "${SYSINF_STR}" "${SYSINF_VLS}" "$(date -Iseconds)")
printf "${SYSINF_STR}" | /opt/gwn/python/sysinf.py --type info

printHeading "Daily Backup complete: $(date)"
df -h
