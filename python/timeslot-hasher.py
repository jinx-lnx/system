#!/usr/bin/python3

"""
TIMESLOT HASHER

Author: Bernd Nigmann

This helper script determines at runtime, if it is time to perform a
task based on a task tag and a given set of weekdays and hours.

The use case is that we want every server to run a certain task, like
auto-highstating, once a week, but we want the actual time slot to be
different for each server to avoid congestion on central resources.

This tool assigns a 15 minute time slot for any server that runs it,
based on the server's own host name and an arbitrary tag that is passed
in. The tool will assign the same time slot to a particular server
every time it is run.

This script should be called on minutes 02, 17, 32 and 47 of every hour
to check if this host (own hostname) needs to run right now. If the
calculated time slot matches the current time, the script's return value
is zero. If it is not, it returns 1.

Required parameters:
  --tag STRING : a tag to identify the purpose of the time hash,
          for example "highstate", "offsitebackup"
  --weekdays DAY DAY ... : which weekdays (three-letter abbreviations)
          are supposed to be used
  --hours HOUR HOUR ... : which hours of the day are supposed to be
          used (24-hour clock)
  --bash : output the variables as bash variable assignments
  --quiet : don't output anything

For example to calculate the timeslot hash for a "HIGHSTATE" task that
should run Mon through Fri between 11pm and 8am local server time, the
command would be this:

    # timeslot-hasher.py --tag HIGHSTATE --weekdays mon tue wed thu fri \
        --hours 23 0 1 2 3 4 5 6 7 8

    {
        "host_name": "appserver.bnd.gwn",
        "host_tag_hash": "607156934b4eac3e9c572f0f2b96ef7cb27696f15ca464da3cfdd392",
        "must_run": false,
        "next": "Mon Oct  9 23:00:00 2017",
        "next_timestamp": 1507604400,
        "now": "Thu Oct  5 14:56:31 2017",
        "now_timestamp": 1507229791,
        "picked_hour": 23,
        "picked_quarter": 0,
        "picked_weekday": "mon"
    }

"""

from argparse import ArgumentParser
from calendar import day_abbr
from datetime import datetime, timedelta
from hashlib import sha224
from json import dumps
from socket import getfqdn
from time import time, mktime


if __name__ == '__main__':

    # Parse the command line arguments
    parser = ArgumentParser(description='Tool to hash a task into a time slot based on hostname and a tag.')
    parser.add_argument('--tag', metavar='STRING', type=str, required=True,
                    help='a tag to identify the task to generate a time hash for')
    parser.add_argument('--weekdays', metavar='WEEKDAY', type=str, required=True, nargs='+',
                        help='list of weekdays to consider, example: mon tue wed thu ...')
    parser.add_argument('--hours', metavar='HOUR', type=int, required=True, nargs='+',
                        help='list of hours of the day to consider (24-hour clock), example: 23 0 1 2 3 ...')
    parser.add_argument('--bash', required=False, action='store_true',
                        help='produce output in bash variable assignments (for sourcing)')
    parser.add_argument('--quiet', required=False, action='store_true',
                        help='do not produce any output')

    args = parser.parse_args()

    # Verify the given weekdays are valid
    try:
        for w in args.weekdays:
            datetime.strptime(w, '%a')
    except:
        print('ERROR: The given weekday list contains an invalid weekday: {0}'.format(args.weekdays))
        exit(1)

    # Verify the given hours are valid
    for h in args.hours:
        if h < 0 or h > 23:
            print('ERROR: The given hours list contains an invalid hour: {0}'.format(args.hours))
            exit(1)

    # Get my host name and hash it with the given tag
    my_hostname = getfqdn().lower()
    my_hash = sha224()
    my_hash.update(my_hostname.encode())
    my_hash.update(args.tag.encode())
    hex_digest = my_hash.hexdigest()

    # Now chop the sha224 hash into pieces and use each for hashing this host
    # into one of the possible weekdays, hours of the day and quarters of the hour
    # respectively.
    # acbffd4079b48b6b7cf1dd034aa4d03b778312e56b6481eeabcaf242 is chopped into
    # acbffd  4079b4  8b6b7c   and unused for now: f1dd034aa4d03b778312e56b6481eeabcaf242

    weekday_hash = hex_digest[0:6]
    picked_weekday = args.weekdays[int(weekday_hash, 16) % len(args.weekdays)]

    hour_hash = hex_digest[6:12]
    picked_hour = args.hours[int(hour_hash, 16) % len(args.hours)]

    quarter_hash = hex_digest[12:18]
    picked_quarter = int(quarter_hash, 16) % 4

    # Check if _right now_ is the right time
    now = datetime.now()
    must_run = False

    # Weekday check
    if day_abbr[now.weekday()].lower() == picked_weekday.lower():

        # Hour check
        if picked_hour == now.hour:

            # Quarter check
            if picked_quarter*15 <= now.minute < (picked_quarter+1)*15:
                must_run = True

    # Apply the picked hour and minute to the current timestamp, ignoring the weekday for now
    picked_time = now.replace(hour=picked_hour, minute=picked_quarter*15, second=0, microsecond=0)

    # Has today's slot passed? Add a day, so we can find the _next_ occurrence.
    if picked_time < now:
        picked_time = picked_time + timedelta(days=1)

    # Add a day until we have a weekday match again
    while day_abbr[picked_time.weekday()].lower() != picked_weekday.lower():
        picked_time = picked_time + timedelta(days=1)

    # Gather the result
    result = {
        'host_name': my_hostname,
        'host_tag_hash': hex_digest,
        'now': now.strftime('%c'),
        'now_timestamp': int(time()),
        'next': picked_time.strftime('%c'),
        'next_timestamp': int(mktime(picked_time.timetuple())),
        'picked_weekday': picked_weekday.lower(),
        'picked_hour': picked_hour,
        'picked_quarter': picked_quarter,
        'must_run': must_run
    }

    if not args.quiet:
        # Format the output depending on the requested mode
        if args.bash:
            for k in sorted(result.keys()):
                print('{0}={1}'.format(k.upper(), result[k]))
        else:
            print(dumps(result, indent=4, sort_keys=True))

    if must_run:
        exit(0)
    else:
        exit(1)
