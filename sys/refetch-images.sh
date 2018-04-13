#!/bin/bash -u

while read LINE; do
	RUN_AS="${LINE%%[ $'\t']*}"
	CMD="${LINE#*[ $'\t']}"
	FETCH_COMMAND=$(
		echo -e "${CMD}" \
			| sed	-n \
				-e 's|.*\(/opt/gwn/[^ \t;\&|]*/fetch-[^ \t;\&|]*\).*|\1|p'
	)
	MAIL_SUBJECT=$(
		echo -e "${CMD}" \
			| sed	-n \
				-e 's|.*-s[ \t]*"\([^"]*\).*|\1|p' \
				-e "s|.*-s[ \t]*'\([^']*\).*|\1|p" \
			| sed \
				-e 's|[ \t]*(@*reboot)[ \t]*||'
	)
	echo "Run \"${FETCH_COMMAND} ${@}\" as ${RUN_AS}" >&2
	sudo -u "${RUN_AS}"  "${FETCH_COMMAND}" "${@}" 2>&1 \
		| /opt/gwn/python/servermail.py -s "${MAIL_SUBJECT} (new master)"
done < <( sed -n -e 's|@reboot[ \t]*\([^ \t].*fetch-.*\)|\1|p' /etc/cron.d/* )