#!/bin/bash

# If no parameters are given, change into the chroot.
# Otherwise pass the parameters as command to chroot.

PLCROOT=/opt/plc-root
export GWN_FACILITY="$( /opt/gwn/python/get-facility-code.py )"
TZLINK="../usr/share/zoneinfo/$(cat /etc/timezone)"

echo "${TZLINK}" > "${PLCROOT}/timezone.info"

# Add '/opt/bin' to PATH for inside the plcroot
set | grep -qE "PATH=.*/opt/bin" || export PATH="${PATH}:/opt/bin"

# Override the HOME variable to emulate the Gentoo server behavior,
# since you enter the plcroot as root.
export HOME=/root

if [ -z "${1}" ] ; then
  chroot ${PLCROOT} /bin/bash
else
  chroot ${PLCROOT} "${@}"
fi
