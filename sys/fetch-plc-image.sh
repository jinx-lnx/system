#!/bin/bash
# -------------------------------------------------------------------
# MANAGED BY SALT
# -------------------------------------------------------------------

##
## Wrapper script for the new image manager fetcher, using proper proxy
## configuration, as given by Salt. This wrapper is needed, so the call
## can also be made via sudo for non-root users.
##


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
        --repo-base http://img.getwellnetwork.com/PLC \
        --local-repo /opt/plc-root/opt/images --mount-locally --purge-local ${PROXY} \
        ${HOSTID} ${*}

# Adjust the permissions
find /opt/plc-root/opt/images -maxdepth 1 -exec chgrp --no-dereference www-data {} \;
