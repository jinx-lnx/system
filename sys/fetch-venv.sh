#!/bin/bash
# -------------------------------------------------------------------
# MANAGED BY SALT
# -------------------------------------------------------------------

##
## Wrapper script for the new image manager fetcher, using proper proxy
## configuration, as given by Salt. This wrapper is needed, so the call
## can also be made via sudo for non-root users.
##


# No proxy configured in Salt
PROXY=""


# Run the fetcher
/opt/gwn/python/fetch-images.py \
        --repo-base http://img.getwellnetwork.com/VENV \
        --local-repo /opt/gwn/venv/_repo ${PROXY} --purge-local ${*}


# Expecting venv repos with a name pattern of SomeName-yyyy.mm.dd.tgx
REPO=/opt/gwn/venv/_repo
DEPLOY=/opt/gwn/venv
CHANGED=false

if [ "${1-}" == "--debug" ] ; then
  OUT=/dev/stdout
else
  OUT=/dev/null
fi

echo "Checking available virtualenv images" > ${OUT}

# Generate a unique list of available modules and filter out non-matching cruft
MODULES=$(ls ${REPO} | egrep "^([A-Za-z0-9]+)-[0-9]{4}\.[0-9]{2}\.[0-9]{2}\.tgz$" | sed -e 's/^\([A-Za-z0-9]\+\)-[0-9]\{4\}\.[0-9]\{2\}\.[0-9]\{2\}\.tgz$/\1/' | sort | uniq)

for M in ${MODULES} ; do

  echo -e "\n* Evaluating module '${M}'..." > ${OUT}
  TARGET="${DEPLOY}/${M}"
  CHKSUM="${TARGET}/deployed-checksum.sha256"

  # For each module, select the most recent one (highest date)
  TOP_VERSION=$(ls ${REPO}/${M}-* | sort -r | head -1)
  if [ -n "${TOP_VERSION}" ] ; then
    echo "   * Most recent version available: ${TOP_VERSION}" > ${OUT}

    if [ -f "${CHKSUM}" ] ; then
      # If the tarball's checksum has changed, initiate deployment
      CHK1=$(/usr/bin/sha256sum ${TOP_VERSION} | /usr/bin/cut -f1 -d ' ')
      CHK2=$(cat ${CHKSUM} | /usr/bin/cut -f1 -d ' ')
      if [ "${CHK1}" == "${CHK2}" ] ; then
        echo -e "  * Checksum has not changed. Skipping deployment" > ${OUT}
        continue
      fi
    fi

    # Nothing was deployed before
    echo "   * Checksum changed (or nothing deployed yet); deploying ${M}..." > ${OUT}

    # Is it a valid tarball?
    tar -tzf ${TOP_VERSION} >/dev/null 2>&1 || continue
    echo "   * Tarball validated, deploying into ${TARGET}" > ${OUT}
    UWSGI=/etc/uwsgi/apps-enabled/${M}.ini
    NGINX=/etc/nginx/venv/venv-${M}.conf

    # Delete old install
    test -d "${TARGET}" && rm -rf "${TARGET}"
    mkdir ${TARGET}
    tar -xz -C ${TARGET} -f ${TOP_VERSION}
    chown -R jboss:www-data ${TARGET}

    # Successfully extracted, checksum it for the next run
    /usr/bin/sha256sum ${TOP_VERSION} > ${CHKSUM}
    CHANGED=true

    echo "   * Setting up UWSGI configuration in ${UWSGI}" > ${OUT}
    cat << EOF > ${UWSGI}
[uwsgi]
uwsgi-socket = ${TARGET}/module.sock
uid = jboss
gid = www-data
chdir = ${TARGET}
module = module:app
master = true
workers = 1
threads = 4
vacuum = true
virtualenv = ${TARGET}/venv
lazy-apps = true
plugin = python34
harakiri = 60
EOF

    # Extract the web context name from the manifest.yaml file
    CONTEXT=$(grep web_context ${TARGET}/manifest.yaml | sed -e "s/^web_context:[ ]*[']\?\([A-Za-z0-9]\+\)[']\?/\1/")
    if [ -z "${CONTEXT}" ] ; then
      echo "   * ERROR: unable to extract web context! Deployment might fail!"
      continue
    fi

    echo "   * Setting up nginx configuration in ${NGINX} for ${M}" > ${OUT}
    cat << EOF > ${NGINX}
# =======================================================
# Managed by fetch-venv.sh. Do not edit!
# =======================================================

        # The uwsgi config for ${M}
        location /${CONTEXT} {
            include uwsgi_params;
            uwsgi_pass unix://${TARGET}/module.sock;
        }

EOF

  fi
done

if [ "${CHANGED}" == "true" ] ; then
  echo -e "\n* At least one module changed. Restarting UWSGI service" > ${OUT}
  /usr/sbin/service uwsgi restart > ${OUT}

  /usr/bin/pgrep nginx >/dev/null
  if [ $? -eq 0 ] ; then
    echo -e "\n* Restarting nginx service" > ${OUT}
    service nginx restart > ${OUT}
  else
    echo -e "\n* Skipping nginx restart as it is not running" >${OUT}
  fi

fi

