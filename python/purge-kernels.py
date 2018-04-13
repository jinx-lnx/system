#!/usr/bin/env python2

from apt.cache import Cache
from argparse import ArgumentParser
from platform import uname
from re import match, search
from subprocess import Popen, PIPE, STDOUT


def die(msg):
  print '\nERROR: {0}\n'.format(msg)
  exit(1)


if __name__ == '__main__':
  # Parse the command line arguments
  parser = ArgumentParser(description='Generate the apt-get command to purge obsolete Kernel packages.')
  parser.add_argument('--all', action='store_true', required=False,
                    help='DANGEROUS: generates code to remove ALL Kernal packages')
  args = parser.parse_args()

  # Get the currently running Kernel version
  m = match('(\S+)-(generic|aws).*$', uname()[2])
  if m is None:
    die('Unable to detect currently running Kernel version')

  # First, need to escape all periods for use in the regex later. Then replace all
  # dashes with periods (so those become wildcards in the regex). The following package
  # Debian package version strings are considered equivalent:
  #    ii  linux-generic-lts-xenial             4.4.0.53.40
  #    ii  linux-headers-4.4.0-53               4.4.0-53.74~14.04.1 
  # Note the search roots, '4.4.0.53' vs '4.4.0-53'! Tricky shit!
  #
  current = m.group(1).replace('.', '\.').replace('-','.')
  current_str = m.group(1)

  # This will hold all purgable Kernel packages and the keepers
  purgable = []
  keepers = []

  # Open the APT cache
  cache = Cache()
  for p in cache.keys():
    if cache[p].installed is None:
      continue
    m = match('^linux-(image|headers|virtual|generic).*$', p)
    if m is None:
      continue

    m = search(current, cache[p].installed.version)
    if m is None or args.all == True:
      purgable.append(p)
    else:
      keepers.append(p)

  # Summarize the result
  purgable.sort()
  keepers.sort()
  print '\nCurrently running Kernel: {0}'.format(current_str)

  if len(keepers) > 0:
    print '\n KEEPING these packages:'
    for k in keepers:
      print '    - {0}'.format(k)

  if len(purgable) > 0:
    print '\nThe following Kernel images can be purged from this server:\n'
    for p in purgable:
      print '    - {0}'.format(p)

    print '\nConvenient purge command:'
    if args.all == True:
      print '\nWARNING * DANGER * WARNING : The following command will remove all Kernel packes.'
      print 'If you reboot the server without installing any Kernel packages, it will be bricked!\n'
    print 'apt-get purge {0}\n'.format(' '.join(purgable))

  print
