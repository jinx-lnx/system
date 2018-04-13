#!/bin/bash -u

#
# This is the appserver side of the script that deploys a pre-compiled PLS
# If you give a PLS tag, the script will try to sync only the given tag:
#
# jboss7 deploy 6.00.00-QA-05
#
# You can also run this script interactively by adding a '-n' parameter
# in addition to the requested tag to deploy.
#
# The RETURN VALUE of the script indicates what kind of problem occured:
#   1 : Generic execution error
#  10 : Cannot find requested PLS version on server
#  11 : Unable to stop JBoss
#  12 : Unable to run Liquibase
#  13 : Error during execution of deployment-script files
#

# No colors in interactive mode:
if [ "${2:-}" == "-n" ] ; then
  USECOLOR=no
fi

SCRIPT_PATH="$( readlink -f "${BASH_SOURCE[0]}" )"
BASE_DIR="$( dirname "${SCRIPT_PATH}" )"
if [ ! -f "${BASE_DIR}/functions.sh" ]; then echo "'functions.sh' not found" ; exit 1; fi
. "${BASE_DIR}/functions.sh"


# Constants
# ---------------------------------------------------------------------------
JBOSSCONTROL="${BASE_DIR}/jboss7-control.sh"
WORKDIR=$(mktemp -d /opt/tmp/deploy.XXXXXXXX)
LOCALDEPOSIT="/opt/deploymentStage"
DEPLOYFOLDER="/opt/jboss7/standalone/deployments"
ASSETSFOLDER="${DEPLOYFOLDER}/assets.war"
EARFOLDER="${DEPLOYFOLDER}/pls.ear"

FORCETAG=
INTERACTIVE="TRUE"
DEV=$(whoami)

# Hack to run non-interactively: Only if the first option is the tag and the second
# option is "-n" we will run non-interactively. Let's spare a fancy option parser
# for the next person who needs to touch this deployment script...

if [ ${#} -eq 1 ]; then
  # Interactive mode with given tag to deploy
  FORCETAG="${1}" ; shift
elif [ ${#} -eq 2 ]; then
  # Only if second parameter is "-n", use non-interactive mode
  if [ "${2}" == "-n" ] ; then
    FORCETAG="${1}"
    INTERACTIVE="FALSE"
  fi
fi


# Functions
# ---------------------------------------------------------------------------


function question() {
  VAL=
  while [ -z "$VAL" ] ; do
    echo -en "\n ${WARN}${1}${NORMAL} : " >&2
    read VAL
  done
  echo >&2
  echo "$VAL"
}


function printStep() {
  echo -e "\n${GOOD}*${NORMAL} ${BOLD}${1}${NORMAL}"
}



function fileExists() {
  echo -ne "\t${1}  \t"
  if [ -e "${1}" ] ; then
    echo -e "[${GOOD}OK${NORMAL}]"
    return 0
  else
    echo -e "[${BAD}MISSING${NORMAL}]"
    return 1
  fi
}


function cleanUp() {
  printStep "Cleaning up"
  test -d "${WORKDIR}" && rm -rf ${WORKDIR}
  exit 0
}


# Remove work directory after execution
trap cleanUp SIGINT SIGTERM


# Script starts here
# ---------------------------------------------------------------------------

echo -e "

${BOLD}
  ******************************************************************
  **              JBoss-7 PLS Deployment Script (rev 9)           **
  ******************************************************************
${NORMAL}"


# Not running as 'root'? Not good.
if [ "${DEV}" != "root" ] ; then
  die "\n${BAD}ERROR:${NORMAL} This script needs root privileges. Please run it with 'sudo'." 1
fi


# Figure out where JBoss is running. Make sure that we deploy on the correct host.
# We should only allow to deploy on the host that is guaranteed to have JBoss running.
JBOSS_HOST=$( locateJBoss )
JBOSS_RUNNING_STATUS=${?}
case ${JBOSS_RUNNING_STATUS} in
  0)  # Not running. Not ideal but nothing breaks. However, we should check
      # where the appserver would be started.
      APPSERVER_IP_HOST=$( locateAppserverIp )
      case ${?} in
        0) # Huh? Bad? We don't even have the appserver IP??!?
          die "${BAD}ERROR:${NORMAL} JBoss is not running and it could not be determined where it would be started." 1
          ;;
        1) # Appserver IP configured locally => ok
          # Nothing to do
          ;;
        2) # Appserver IP configured remotely => bad
          die "${BAD}ERROR:${NORMAL} JBoss is not running and it would be started on ${HILITE}${APPSERVER_IP_HOST}${NORMAL}.\nYou should deploy on ${APPSERVER_IP_HOST}" 1
          ;;
        esac
        ;;
  1) # Appserver running locally => ok
      # Nothing to do
    ;;
  2) # JBoss running remotely. Can't deploy here!
    die "${BAD}ERROR:${NORMAL} JBoss is running on ${HILITE}${JBOSS_HOST}${NORMAL}.\nYou should deploy on ${JBOSS_HOST}" 1
    ;;
esac



# We need to find out the real username
case "${SUDO_USER:-}" in
  ""|jboss|root)
    REALUSER=$(question "Please enter your GWN user name")
    ;;
  *)
    REALUSER=${SUDO_USER}
    ;;
esac

if [ ! -d "${LOCALDEPOSIT}" ] ; then
  printStep "Creating local PLS deposit folder '${LOCALDEPOSIT}'"
  mkdir ${LOCALDEPOSIT} || die "\n${BAD}ERROR:${NORMAL} Unable to create '${LOCALDEPOSIT}'" 1
fi


if [ -n "${FORCETAG}" ] ; then
  printStep "You specified a PLS tag explicitly: ${FORCETAG}"
fi

printStep "Gathering available tags:"
# Extract the available and mounted PLS images versions from the current mounts:
# Turn this:
#    /dev/loop0 /opt/deploymentStage/PLS-6.03.22/mounted squashfs ro,relatime 0 0
#    /dev/loop1 /opt/deploymentStage/PLS-6.03.21/mounted squashfs ro,relatime 0 0
#    /dev/loop4 /opt/deploymentStage/PLS-6.05.00-QA-25/mounted squashfs ro,relatime 0 0
# into this:
#    6.03.22
#    6.03.21
#    6.05.00-QA-25
cat /proc/mounts | grep squashfs | grep "PLS-6" | awk '{print $2}' \
	| sed 's|/opt/deploymentStage/PLS-\(.*\)/mounted|   >> \1|' | sort

if [ -z "${FORCETAG}" ] ; then
  TAG=$(question "Please enter the tag to deploy")
else
  TAG=${FORCETAG}
fi

printStep "Checking availability for '${TAG}'"

cat /proc/mounts | egrep -q "PLS-${TAG}/mounted.*squashfs"
if [ $? -ne 0 ] ; then
  die "\n${BAD}ERROR:${NORMAL} Cannot find mounted PLS package folder for '${TAG}' in ${LOCALDEPOSIT}" 10
fi

IMAGEROOT="${LOCALDEPOSIT}/PLS-${TAG}/mounted"
echo ""

# In non-interactive mode, set all yes/no questions for auto-ansert 'y'
if [ "${INTERACTIVE}" == "FALSE" ] ; then
  AUTO_ANSWER_YESNO="Y"
else
  AUTO_ANSWER_YESNO=
fi


if askYesNo "Ready to deploy assets?" ; then
	DEPLOYASSETS="y"
else
  DEPLOYASSETS="n"
fi
if [ "${DEPLOYASSETS}" == "y" ] ; then

  if [ ! -d "${ASSETSFOLDER}" ] ; then
    printStep "Creating assets.war folder"
    mkdir ${ASSETSFOLDER}
  fi

  printStep "Pass 1: Syncing Skins to JBoss folder with 'delete' option"
  cat > ${WORKDIR}/.deploy.filter << EOF
- .*

+ /Skin
+ /Skin/**

+ /Skins

+ /Skins/REclipse
+ /Skins/REclipse/**

+ /Skins/BubbleUp
+ /Skins/BubbleUp/**

+ /Skins/GTown
+ /Skins/GTown/**

+ /Skins/IFOKiosk
+ /Skins/IFOKiosk/**

+ /Skins/MenWorking
+ /Skins/MenWorking/**

+ /Skins/Seniors
+ /Skins/Seniors/**

+ /Global
+ /Global/Common
+ /Global/Common/ASHP
+ /Global/Common/ASHP/**

+ Global/Common/Lexicomp
+ Global/Common/Lexicomp/**

+ /Global/Common/PedPals
+ /Global/Common/PedPals/**

- **
EOF


  rsync -qrc --delete --filter ". ${WORKDIR}/.deploy.filter" \
	${IMAGEROOT}/assets.war/. ${ASSETSFOLDER}/.

  printStep "Pass 2: Syncing everything to JBoss folder with 'overwrite' option"
  rsync -qrc --exclude='/WEB-INF/config/*.xml' \
    --exclude='.*' \
    ${IMAGEROOT}/assets.war/. \
    ${ASSETSFOLDER}/.

  printStep "Fixing file ownership and permissions in Assets"
  chown -R jboss:jboss ${ASSETSFOLDER}
  chmod -R g+w ${ASSETSFOLDER}
fi

echo ""
if askYesNo "Ready to deploy PLS?"; then
  DEPLOYPLS="y"
else
  DEPLOYPLS="n"
fi
if [ "${DEPLOYPLS}" == "y" ] ; then

  printStep "Checking if JBoss is running"
  case ${JBOSS_RUNNING_STATUS} in
    0) # Not running
      ;;
    *) # JBoss running locally or remotely, need to stop it first
      # We could use "stopJBoss" but $JBOSSCONTROL sends out emails!
      MAILNAME="${REALUSER}" MAILREASON="Deploying ${TAG}" ${JBOSSCONTROL} stop

      # Double check if JBoss is really gone
      isJBossRunning \
        && die "\n${BAD}ERROR:${NORMAL} Could not stop JBoss" 11
      ;;
  esac

  if [ ! -d "${EARFOLDER}" ] ; then
      printStep "Creating directory ${EARFOLDER}"
      mkdir ${EARFOLDER}
  fi

  printStep "Syncing EAR from staging dir to '${EARFOLDER}', skipping axis2 services folder"
  rsync -vrc --delete --exclude='.rsyncsums' \
    --exclude='/axis2.war/WEB-INF/services' \
    ${IMAGEROOT}/pls.ear/. \
    ${EARFOLDER}/.
  chown -R jboss:jboss ${EARFOLDER}

  if [ -d /opt/jboss7/standalone/tmp ] ; then
    printStep "Cleaning up the JBoss tmp folder"
    rm -rf /opt/jboss7/standalone/tmp
  fi


  # --------------------------------------------------------------------------
  # Developer-generated Script execution (if packaged)
  # --------------------------------------------------------------------------
  if [ -d "${IMAGEROOT}/deployment-scripts" ] ; then
    printStep "Found a deployment-scripts folder. Will now execute all available shell scripts in alphabetical order."
    pushd ${IMAGEROOT}/deployment-scripts >/dev/null
    for SCRIPT in $(ls | egrep "[0-9]{3}-.*\.sh" | sort) ; do
      if askYesNo "   ==> Execute ${SCRIPT}?" ; then
        # If a script was found in the deployment scripts folder, execute it as the non-privileged jboss user
        sudo -u jboss bash ${SCRIPT}
        if [ $? -ne 0 ] ; then
          if askYesNo "       ERROR: Execution failed! Abort deployment?" ; then
            die "Deployment aborted, because deployment-script '${SCRIPT}' failed" 13
          fi
        fi
      fi
    done
    popd >/dev/null
  fi


  # --------------------------------------------------------------------------
  # Liquibase Execution (if packaged)
  # --------------------------------------------------------------------------

  printStep "Checking if we need to run liquibase for this deployment"
  fileExists "${IMAGEROOT}/liquibase"
  if [ -d "${IMAGEROOT}/liquibase" ] ; then

    printStep "Preparing liquibase environment"
    LTEMPDIR=${WORKDIR}/liquibase.temp
    mkdir ${LTEMPDIR}

    # Discover the path for the latest MariaDB Java Client
    DRIVER=$(find /opt/jboss7/modules/org/mariadb/ -name 'mariadb-java-client*.jar' | sort | tail -n1)
    cat << EOF > ${LTEMPDIR}/liquibase.properties
changeLogFile=changes.xml
classpath=${IMAGEROOT}/liquibase:${LTEMPDIR}:${DRIVER}
driver=org.mariadb.jdbc.Driver
EOF

    NAMESPACE="ds=urn:jboss:domain:datasources:1.1"
    XA_XPATH=".//ds:xa-datasource[@pool-name='GWN_R5_XA']"
    DS_XPATH=".//ds:datasource[@pool-name='GWN_R5']"
    STANDALONE=/opt/jboss7/standalone/configuration/standalone.xml

    XA_SERVER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='ServerName']" ${STANDALONE} | tr -d '[[:space:]]')
    if [ -n "${XA_SERVER}" ] ; then
      # XA datasource in use here
      # -------------------------
      XA_PORT=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='PortNumber']" ${STANDALONE} | tr -d '[[:space:]]')
      XA_DB=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='DatabaseName']" ${STANDALONE} | tr -d '[[:space:]]')
      DB_USER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:security/ds:user-name" ${STANDALONE} | tr -d '[[:space:]]')
      DB_PWD=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:security/ds:password" ${STANDALONE} | tr -d '[[:space:]]')
      cat << EOF >> ${LTEMPDIR}/liquibase.properties
url=jdbc:mysql://${XA_SERVER}:${XA_PORT}/${XA_DB}
username=${DB_USER}
password=${DB_PWD}
EOF

    else

      # Classic datasource in use here
      # ------------------------------

      CONN_URL=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:connection-url" ${STANDALONE} | tr -d '[[:space:]]')
      DB_USER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:security/ds:user-name" ${STANDALONE} | tr -d '[[:space:]]')
      DB_PWD=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:security/ds:password" ${STANDALONE} | tr -d '[[:space:]]')
      cat << EOF >> ${LTEMPDIR}/liquibase.properties
url=${CONN_URL}
username=${DB_USER}
password=${DB_PWD}
EOF

    fi

    # Run Liquibase with the generated properties file
    printStep "Running liquibase..."
    java -jar ${IMAGEROOT}/liquibase/liquibase.jar --defaultsFile=${LTEMPDIR}/liquibase.properties \
        --logLevel=info update || die "Executing Liquibase failed" 12

  fi


  # -----------------------------------------------------------------------
  # If a standalone.xml is part of the image, replace the one on the server
  # -----------------------------------------------------------------------

  NEW_STANDALONE="${LOCALDEPOSIT}/PLS-${TAG}/mounted/config/standalone.xml"
  if [ -f "${NEW_STANDALONE}" ] ; then

    printStep "Found a template for standalone.xml in the PLS image. Will override running standalone.xml."
    NAMESPACE="ds=urn:jboss:domain:datasources:1.1"
    XA_XPATH=".//ds:xa-datasource[@pool-name='GWN_R5_XA']"
    DS_XPATH=".//ds:datasource[@pool-name='GWN_R5']"
    PROD_STANDALONE=/opt/jboss7/standalone/configuration/standalone.xml

    # Extract the legacy connection parameters (non-XA datasource)
    CONN_URL=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:connection-url" ${PROD_STANDALONE} | tr -d '[[:space:]]')
    DB_USER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:security/ds:user-name" ${PROD_STANDALONE} | tr -d '[[:space:]]')
    DB_PWD=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${DS_XPATH}/ds:security/ds:password" ${PROD_STANDALONE} | tr -d '[[:space:]]')

    # Do we have an XA datasource in the standalone.xml file yet?
    XA_SERVER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='ServerName']" ${PROD_STANDALONE} | tr -d '[[:space:]]')

    if [ -n "${XA_SERVER}" ] ; then
      # XA datasource already here; extract its connection parameters
      # -------------------------------------------------------------
      XA_PORT=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='PortNumber']" ${PROD_STANDALONE} | tr -d '[[:space:]]')
      XA_DB=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:xa-datasource-property[@name='DatabaseName']" ${PROD_STANDALONE} | tr -d '[[:space:]]')
      XA_DB_USER=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:security/ds:user-name" ${PROD_STANDALONE} | tr -d '[[:space:]]')
      XA_DB_PWD=$(xml sel -T -N "${NAMESPACE}" -t --value-of "${XA_XPATH}/ds:security/ds:password" ${PROD_STANDALONE} | tr -d '[[:space:]]')
    else
      # No XA datasource yet; convert the legacy connection parameters to XA parameters
      # -------------------------------------------------------------------------------
      XA_SERVER=$(echo "${CONN_URL}" | sed -e 's|^jdbc:mysql://\([^:]\+\):\([0-9]\+\)/\([^?]\+\)\?.*$|\1|')
      XA_PORT=$(echo "${CONN_URL}" | sed -e 's|^jdbc:mysql://\([^:]\+\):\([0-9]\+\)/\([^?]\+\)\?.*$|\2|')
      XA_DB=$(echo "${CONN_URL}" | sed -e 's|^jdbc:mysql://\([^:]\+\):\([0-9]\+\)/\([^?]\+\)\?.*$|\3|')
      XA_DB_USER=${DB_USER}
      XA_DB_PWD=${DB_PWD}
    fi

    # Replace the values in the standalone.xml template accordingly
    # -------------------------------------------------------------
    BACKUPXML="/opt/tmp/standalone-pre-deploytool-$(date +"%s").xml"
    WORKXML="/opt/tmp/standalone-$(date +"%s").xml"
    SUCCESS=TRUE
    xml ed -N "${NAMESPACE}" \
        -u "${DS_XPATH}/ds:connection-url" -v "${CONN_URL}" \
        -u "${DS_XPATH}/ds:security/ds:user-name" -v "${DB_USER}" \
        -u "${DS_XPATH}/ds:security/ds:password" -v "${DB_PWD}" \
        -u "${XA_XPATH}/ds:xa-datasource-property[@name='ServerName']" -v "${XA_SERVER}" \
        -u "${XA_XPATH}/ds:xa-datasource-property[@name='PortNumber']" -v "${XA_PORT}" \
        -u "${XA_XPATH}/ds:xa-datasource-property[@name='DatabaseName']" -v "${XA_DB}" \
        -u "${XA_XPATH}/ds:security/ds:user-name" -v "${XA_DB_USER}" \
        -u "${XA_XPATH}/ds:security/ds:password" -v "${XA_DB_PWD}" \
	${NEW_STANDALONE} > ${WORKXML}
    if [ $? -ne 0 ] ; then
      SUCCESS=FALSE
    fi

    if [ "${SUCCESS}" == "TRUE" ] ; then
      # Validate the replaced standalone.xml
      xml val ${WORKXML} || SUCCESS=FALSE
    fi

    if [ "${SUCCESS}" == "TRUE" ] ; then
      printStep "Standalone.xml replacement successful and result validated."
      printStep "Replacing production version and keeping previous version as backup in ${BACKUPXML}"
      mv ${PROD_STANDALONE} ${BACKUPXML} && mv ${WORKXML} ${PROD_STANDALONE}
      printStep "Adjusting permissions for ${PROD_STANDALONE}"
      chown jboss:jboss ${BACKUPXML} ${PROD_STANDALONE}
    else
      printStep "STANDALONE.XML REPLACEMENT FAILED. SKIPPING."
    fi
    
    cat << EOF


Extracted datasource information from existing standalone.xml:
=============================================================

Legacy:
         URL      : ${CONN_URL}
         USER     : ${DB_USER}
         PASSWORD : ${DB_PWD}

XA:
         SERVER   : ${XA_SERVER}
         PORT     : ${XA_PORT}
         DB       : ${XA_DB}
         USER     : ${XA_DB_USER}
         PASSWORD : ${XA_DB_PWD}
EOF


  else
    printStep "No standalone.xml found in the PLS build. Skipping replacement."
  fi


  echo ""
  printStep "Clearing Medication Database checksum file."
  test -f /var/cache/MedicationDatabase.tgz.sha1 && rm -f /var/cache/MedicationDatabase.tgz.sha1


  echo ""
  if askYesNo "Would you like to launch JBoss now?"; then
    printStep "Launching JBoss"
    ${JBOSSCONTROL} start
  fi
fi

if [ "${DEPLOYASSETS}" == "y" -o "${DEPLOYPLS}" == "y" ] ; then
  GWNTAG="null"
  [ "${DEPLOYPLS}" == "y" ] && GWNTAG="'${TAG}'"

  ASSETSTAG="null"
  [ "${DEPLOYASSETS}" == "y" ] && ASSETSTAG="'${TAG}'"

  printStep "Logging deployment for '${REALUSER}'"
  echo

  wget -q -O/dev/null --timeout 10 --tries 2 "https://services.hq/cgi-bin/logPlsDeployment.pl?facilityId=$(/opt/gwn/python/get-facility-code.py)&hostName=$(hostname -f)&releaseGwn=${GWNTAG}&releaseAssets=${ASSETSTAG}&deployedBy=${REALUSER}"

  if [ $? -ne 0 ] ; then
    echo "\n${BAD}WARNING:${NORMAL} Unable to log deployment. Wget call failed."
  fi
else
  printStep "Nothing was deployed. Not logging deployment"
fi


# vim: set cindent tabstop=2 shiftwidth=2 expandtab:
