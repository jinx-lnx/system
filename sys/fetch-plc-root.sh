#!/bin/bash -u
# -------------------------------------------------------------------
# MANAGED BY SALT
# -------------------------------------------------------------------

##
## Wrapper script for the new image manager fetcher, using proper proxy
## configuration, as given by Salt. This wrapper is needed, so the call
## can also be made via sudo for non-root users.
##

# The local repo for the sync-root
IMG=/opt/image-plc-root


# If this is not the 'appserver' node, bail out
IS_APP=$(/opt/gwn/system/run-on-node appserver /bin/echo "TRUE")
if [ "${IS_APP}" != "TRUE" ] ; then
  exit
fi

# No host-id needed on appservers
HOSTID=""



# No proxy configured in Salt
PROXY=""


# Run the actual fetcher
/opt/gwn/python/fetch-images.py \
        --repo-base http://img.getwellnetwork.com/PLC-ROOT \
        --local-repo ${IMG} --mount-locally --purge-local ${PROXY} \
        ${HOSTID} ${*}

if [ $? -ne 0 ] ; then
  echo "ERROR: image fetcher returned non-zero. Aborting"
  exit 1
fi


# Now sync the most recent mounted plc-root image to the plc-root directory
# -------------------------------------------------------------------------

PROOT=/opt/plc-root
if [ "${1-}" == "--debug" ] ; then
  VERBOSE="-v --progress"
  OUT=/dev/stdout
else
  VERBOSE="-q"
  OUT=/dev/null
fi

IMAGES=$(egrep --only-matching "${IMG}/plc-root-[0-9\.-]+/mounted" /proc/mounts | sort)
NEWEST=$(echo "${IMAGES}" | tail -n 1)
echo -e "\nConsidering the following mounted plc-root images:\n${IMAGES}\n" > ${OUT}
echo -e "\nSelected newest image:\n${NEWEST}\n" > ${OUT}

# Abort if nothing is found
if [ -z "${NEWEST}" ] ; then
  echo "ERROR: no plc-root image mounted. Aborting."
  exit 1
fi

# First, sync the hotpatch folder with the 'delete' option:
test ! -d ${PROOT}/opt/assets/hot-patches && mkdir -p ${PROOT}/opt/assets/hot-patches
rsync -ac ${VERBOSE} --no-motd --delete \
        ${NEWEST}/opt/assets/hot-patches/. \
        ${PROOT}/opt/assets/hot-patches/.

# Then sync everything else:
rsync -ac ${VERBOSE} --no-motd ${NEWEST}/. ${PROOT}/.

# Fix perms for ssh keys
chmod -R o=,g= "${PROOT}/root/.ssh"

# Trigger a reload of the plc UWSGI application by touching the UWSGI-monitored file
test -f /opt/plc-root/opt/cgi/entry_point.py && touch /opt/plc-root/opt/cgi/entry_point.py

# Adjust the permissions (later)
# TODO: something like find /opt/plc-root/opt/images -maxdepth 1 -exec chgrp --no-dereference www-data {} \;
