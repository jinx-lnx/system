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


# No proxy configured in Salt
PROXY=""


# Run the fetcher
/opt/gwn/python/fetch-images.py \
        --repo-base http://img.getwellnetwork.com/MEDS2 \
        --local-repo /var/tmp ${PROXY} ${*}

# Adjust the permissions
test -f /var/tmp/MedicationDatabase.tgz && chgrp jboss /var/tmp/MedicationDatabase.tgz
