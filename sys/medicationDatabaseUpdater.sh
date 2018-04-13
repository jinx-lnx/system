#!/bin/bash -u

##
## Script that checks whether a new Meds DB needs to be loaded
##
## $Id$
##

# ----------------------------------------------------------------------------
# Pull in the generic functions
# ----------------------------------------------------------------------------

. /opt/gwn/system/functions.sh


# Note: Since PLATSUP-20736, we run this on every server; production or not.
# ----------------------------------------------------------------------------


if [ ${#} -gt 0 ]; then
    MEDSDB="${1}" ; shift
else
    MEDSDB="/var/tmp/MedicationDatabase.tgz"
fi

# If the file does not exist, quietly exit (PLATSUP-24070)
if [ ! -e ${MEDSDB} ] ; then
  logger "Medication database tarball not found. Skipping import."
  exit
fi

OUTPUT_ON_SUCCESS=${OUTPUT_ON_SUCCESS:-false} # Default to false
case "${OUTPUT_ON_SUCCESS}" in
    true|false)
        # Nothing to be done
        ;;
    *)
        # Can't have that; must be either unset, true or false
        echo "Unknown value \"${OUTPUT_ON_SUCCESS}\" for environment variable OUTPUT_ON_SUCCESS; cannnot run"
        exit 3
        ;;
esac

# MySQL credentials... pass them in to this script like this:
#   VAR_MYSQL_USER=xyz VAR_MYSQL_PASS=abc ${0}
# If that doesn't happen the defaults here are going to be used
# and this script will loudly complain about it
VAR_MYSQL_USER="${VAR_MYSQL_USER:-}"
VAR_MYSQL_PASS="${VAR_MYSQL_PASS:-}"
VAR_MYSQL_DB="${VAR_MYSQL_DB:-GWN_R5}"

if [ -z "${VAR_MYSQL_USER}" -o -z "${VAR_MYSQL_PASS}" ]; then
    [ -z "${VAR_MYSQL_USER}" ] && echo "No mysql user given. Please set the environment VAR_MYSQL_USER prior to starting this script" \
        | fold -s
    [ -z "${VAR_MYSQL_PASS}" ] && echo "No mysql password given. Please set the environment VAR_MYSQL_PASS prior to starting this script" \
        | fold -s
    exit 2
fi

SCRIPTNAME="$( basename "$( readlink -f "${BASH_SOURCE[0]}" )" .sh )"
PIDFILE="/var/run/${SCRIPTNAME}.pid"
LOADERSCRIPT="${LOADERSCRIPT:-/opt/gwn/system/medicationDatabaseLoader.sh}"
CHECKSUMMER="${CHECKSUMMER:-sha1sum}"
CHECKSUMMER_CHECKOPTS="${CHECKSUMMER_CHECKOPTS:--c --status}"
CHECKSUMMER_CREATEOPTS="${CHECKSUMMER_CREATEOPTS:--b}"
CHECKSUMDIR="${CHECKSUMDIR:-/var/cache}"
CHECKSUMFILE="${CHECKSUMDIR}/$( basename "${MEDSDB}" ).$( basename "${CHECKSUMMER}" sum )"

if [ -f "${PIDFILE}" ] ; then
    [ "$( readlink -f /proc/$$/exe )" = "$( readlink -f /proc/$( cat "${PIDFILE}" )/exe )" ] \
        && exit
fi
echo -n "$$" > "${PIDFILE}"
trap "rm '${PIDFILE}'" EXIT

mkdir -p "${CHECKSUMDIR}"
[ -f "${CHECKSUMFILE}" ] \
    && "${CHECKSUMMER}" ${CHECKSUMMER_CHECKOPTS} "${CHECKSUMFILE}" \
    && exit 0

if [ -f "${MEDSDB}" ]; then
    if [ -x "${LOADERSCRIPT}" ]; then
        OUTPUT="$(
            VAR_MYSQL_USER="${VAR_MYSQL_USER}" \
                VAR_MYSQL_PASS="${VAR_MYSQL_PASS}" \
                VAR_MYSQL_DB="${VAR_MYSQL_DB}" \
                "${LOADERSCRIPT}" "${MEDSDB}" 2>&1
        )"
        RESULT=${?}
    elif [ -f "${LOADERSCRIPT}" ]; then
        INTERPRETER=$( sed -n '1s/^#!\(.*\)/\1/p' "${LOADERSCRIPT}" )
        if [ -z "${INTERPRETER}" ]; then
            case "$( file -ib "${LOADERSCRIPT}" )" in
                *shellscript*)    INTERPRETER=bash   ;;
                *python*)         INTERPRETER=python ;;
            esac
        fi
        if [ -z "${INTERPRETER}" ]; then
            echo "\"${LOADERSCRIPT}\" exists but is of unknown type; cannot run script"
            RESULT=2
        else
            OUTPUT="$(
                VAR_MYSQL_USER="${VAR_MYSQL_USER}" \
                    VAR_MYSQL_PASS="${VAR_MYSQL_PASS}" \
                    VAR_MYSQL_DB="${VAR_MYSQL_DB}" \
                    ${INTERPRETER} "${LOADERSCRIPT}" "${MEDSDB}" 2>&1
            )"
            RESULT=${?}
        fi
    else
        echo "Medication database loader script \"${LOADERSCRIPT}\" not found"
        RESULT=1
    fi
    
    if [ ${RESULT} -eq 0 ]; then
        ${OUTPUT_ON_SUCCESS} && echo -e "${OUTPUT}"
        "${CHECKSUMMER}" ${CHECKSUMMER_CREATEOPTS} "${MEDSDB}" > "${CHECKSUMFILE}"
        exit 0
    else
        echo -e "${OUTPUT}"
        exit ${RESULT}
    fi
fi
