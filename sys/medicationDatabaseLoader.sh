#!/bin/bash

# Global variables for the script
# -------------------------------
VAR_BASEDIR=$(dirname $0)
VAR_DUMPFILE="${1}"

# MySQL credentials... pass them in to this script like this:
#   VAR_MYSQL_USER=xyz VAR_MYSQL_PASS=abc ${0}
# If that doesn't happen the defaults here are going to be used
# and this script will loudly complain about it
VAR_MYSQL_USER="${VAR_MYSQL_USER:-}"
VAR_MYSQL_PASS="${VAR_MYSQL_PASS:-}"
VAR_MYSQL_DB="${VAR_MYSQL_DB:-GWN_R5}"


# Helper functions
# ----------------

execute_mysql () {
	# $1 contains the MySQL query
	QUERY=$1
	echo ">> ${QUERY}"
	echo "${QUERY}" | mysql -u${VAR_MYSQL_USER} -p${VAR_MYSQL_PASS} ${VAR_MYSQL_DB}
	
}

echo_step () {
	echo -e "\n* ${1}"
}

die () {
	echo -e "\nERROR: $1" | fold -s
	exit 1
}

dieIfError() {
        local RESULT=$?
        [ ${RESULT} -eq 0 ] && return 0
        [ -z "${1}" ] || echo -e "${1}" | fold -s 
        exit ${RESULT}
}

cleanup() {
    if [ "${#VAR_WORKDIR}" -gt 5 -a -d "${VAR_WORKDIR}" ] ; then
        echo_step "Cleaning up ${VAR_WORKDIR}"
        rm -rf "${VAR_WORKDIR}"
    fi
}


# Script starts here:
# -------------------

if [ -z "${VAR_MYSQL_USER}" -o -z "${VAR_MYSQL_PASS}" ]; then
    [ -z "${VAR_MYSQL_USER}" ] && echo "No mysql user given. Please set the environment VAR_MYSQL_USER prior to starting this script" \
        | fold -s 
    [ -z "${VAR_MYSQL_PASS}" ] && echo "No mysql password given. Please set the environment VAR_MYSQL_PASS prior to starting this script" \
        | fold -s 
    exit 2
fi

echo "GetWellNetwork Medication Database Loader"
echo "-------------------------------------------"


if [ ! -f "${VAR_DUMPFILE}" ] ; then
	die "No dump file was provided. Please provide the database dump file as first parameter."
fi

# Create a working directory in tmp
VAR_WORKDIR=$(mktemp -d /opt/tmp/medsdb.XXXXXXXX)
trap cleanup INT TERM EXIT

echo_step "Changing permissions on the temporary folder"
chmod -R a+rwx ${VAR_WORKDIR}

echo_step "Extracting given tarball"
tar -xvz -C ${VAR_WORKDIR} -f ${VAR_DUMPFILE} \
	|| die "Unable to extract medication database dump"


echo_step "Check if system is eligible for snapshot"

if [ -f "${VAR_WORKDIR}/canRun.sh" ]; then
	# There is a canRun script, so we should reference it.  Call it, if error status, terminate

	OUTPUT="$(
            VAR_MYSQL_USER="${VAR_MYSQL_USER}" \
                VAR_MYSQL_PASS="${VAR_MYSQL_PASS}" \
                VAR_MYSQL_DB="${VAR_MYSQL_DB}" \
				${VAR_WORKDIR}/canRun.sh)"

	# In this case, if canRun.sh returns non-zero, we want to tell the calling script,
	# medicationDatabaseUpdater.sh, that all is well and that it should update the
	# checksum, so it does not get called again the next night. If canRun.sh returns
	# non-zero, exit this script with a zero return code (PLATSUP-20909).
	if [ $? -ne 0 ] ; then
		echo_step "System is not eligible for this snapshot. Telling caller script to update checksum."
		exit 0
	fi
fi


echo_step "Creating temporary MEDTMP table structure"
test ! -f ${VAR_WORKDIR}/medTmpSetup.sql \
	&& die "Cannot find ${VAR_WORKDIR}/medTmpSetup.sql."
	
cat ${VAR_WORKDIR}/medTmpSetup.sql | mysql -u${VAR_MYSQL_USER} -p${VAR_MYSQL_PASS} ${VAR_MYSQL_DB}
dieIfError "Could not create temporary tables, check that ${VAR_MYSQL_USER} has FILE permissions"

echo_step "Table's created, loading data"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_Medications_DUMP' into table MEDTMP_Medications"
dieIfError "Could not import data into MEDTMP_Medications, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_MedicationDatasheets_DUMP' into table MEDTMP_MedicationDatasheets"
dieIfError "Could not import data into MEDTMP_MedicationDatasheets, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_MedicationCodes_DUMP' into table MEDTMP_MedicationCodes"
dieIfError "Could not import data into MEDTMP_MedicationCodes, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_MedicationNames_DUMP' into table MEDTMP_MedicationNames"
dieIfError "Could not import data into MEDTMP_MedicationNames, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_Attribute_DUMP' into table MEDTMP_Attribute"
dieIfError "Could not import data into MEDTMP_Attribute, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_MedicationAttributes_DUMP' into table MEDTMP_MedicationAttributes"
dieIfError "Could not import data into MEDTMP_MedicationAttributes, check that ${VAR_MYSQL_USER} has FILE permissions"

execute_mysql "LOAD DATA INFILE '${VAR_WORKDIR}/MEDCORE_DatabaseVersion_DUMP' into table MEDTMP_DatabaseVersion"
dieIfError "Could not import data into MEDTMP_DatabaseVersion, check that ${VAR_MYSQL_USER} has FILE permissions"

echo_step "Database loaded."

# Cleanup
echo_step "Cleaning up... Removing work directory and scratch data"
test -d "${VAR_WORKDIR}" && rm -r "${VAR_WORKDIR}"
