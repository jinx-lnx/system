#!/usr/bin/python2
"""
This script fetches images that are distributed through the image-manager.
The true source of this file lives in the Image Manager git repository
(not in Salt), at this URL: git@git.hq:linuxadmin/pydevops.git
"""

import argparse
import io
import logging
import md5

from base64 import b64decode
from Crypto.Cipher import AES
from fcntl import lockf, LOCK_EX, LOCK_NB
from hashlib import sha1
from json import loads
from os.path import exists, getsize, join, isfile, islink, realpath
from os import unlink, listdir, makedirs, symlink, getpid
from re import search, sub
from subprocess import check_call
from urllib2 import ProxyHandler, build_opener, HTTPError, URLError
from urlparse import urlparse
from shutil import rmtree
from socket import getfqdn
from traceback import print_exc


# Constants
encryption_key = b64decode('AB59EA0D21EA8C73918FD41F860EAE49')

# Set up the logger
logging.basicConfig(format='%(asctime)s [%(levelname)-8s] %(message)s')
logger = logging.getLogger()


# Parse the command line options
#
parser = argparse.ArgumentParser(description='Fetch images from remote repository.')
parser.add_argument('--repo-base', metavar='URL', type=str, required=True,
                    help='The base URL for the repository\'s manifest.json file (the directory)')
parser.add_argument('--proxy', metavar='http://HOST:PORT', type=str, required=False,
                    help='Set this if the request to Amazon needs to go through a proxy')
parser.add_argument('--host-id', metavar='HOSTNAME', type=str, required=False,
                    help='Use this host ID against the manifest when deciding which '
                         'images we need. Defaults to the system\'s full host name.')
parser.add_argument('--local-repo', metavar='PATH', type=str, required=True,
                    help='The local directory for downloading image files to')
parser.add_argument('--mount-locally', action='store_true', default=False,
                    help='If this parameter is set, SquashFS images will be automatically be mounted '
                         '(only set if for SquashFS images)')
parser.add_argument('--purge-local', action='store_true', default=False,
                    help='DANGEROUS! If set, all files not in the manifest will be deleted from '
                         'the local directory specified in --local-repo.')
parser.add_argument('--debug', action='store_true',
                    help='Turn on detailed logging')

args = parser.parse_args()
if args.debug:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.ERROR)


# Try to obtain the file lock for this process
# --------------------------------------------

# Hash the base URL, so it does not contain special characters
m = md5.new()
m.update(args.repo_base)
LOCKFILE='/opt/tmp/fetch-image-{0}.lock'.format(m.hexdigest())
lock_file = None

try:
    logger.debug('Acquiring lock file {0}'.format(LOCKFILE))
    lock_file = open(LOCKFILE, 'w')
    lockf(lock_file, LOCK_EX | LOCK_NB)
    lock_file.write('{0}'.format(getpid()))
    lock_file.flush()
except IOError as io:
    logger.error('Unable to obtain file lock ({0}). Process already running?'.format(io))
    exit(1)


def open_url_connection(url, proxy=None, headers=None):
    if not headers:
        headers = {}
    if proxy is not None:
        logger.debug('  Using the following proxy: {0}'.format(proxy))
        proxy_handler = ProxyHandler({'http': proxy, 'https': proxy})
        url_opener = build_opener(proxy_handler)
    else:
        url_opener = build_opener()

    # Add special User-Agent, so appservers will always allow us through (Squid auth)
    url_opener.addheaders = [('User-agent', 'APT-HTTP')]
    for k in headers:
        url_opener.addheaders.append((k, headers[k]))

    logger.debug('  Sending these HTTP headers: {0}'.format(url_opener.addheaders))
    connection = url_opener.open(url, timeout=120)
    if 'X-Cache' in connection.headers:
        logger.debug('  X-Cache response: {0}'.format(connection.headers['X-Cache']))
    return connection


def download_file(args, img):
    """
    Download the encrypted file into a temp file. Resume if a partial temp
    file was found. If the checksum does not match in the end, discard the
    file and abort, so it can try again later.

    :return: True if the download was successful, False if there was a problem
    """
    local_temp_crypt_file = '{0}/{1}.part'.format(args.local_repo, img)
    if exists(local_temp_crypt_file):
        existing_size = getsize(local_temp_crypt_file)
        headers = {'Range': 'bytes={0}-'.format(existing_size)}
        logger.debug('  Partial download found. Attempting to resume. Sending headers: {0}'.format(headers))
    else:
        existing_size = 0
        headers = {}

    # Skip the download if the file is already completely downloaded
    if not exists(local_temp_crypt_file) or getsize(local_temp_crypt_file) < manifest['images'][img]['size']:
        total_downloaded = existing_size
        with io.open(local_temp_crypt_file, 'ab') as writer:
            resp = open_url_connection('{0}/{1}'.format(args.repo_base, img),
                                       proxy=args.proxy, headers=headers)

            while True:
                block = resp.read(2**22)
                if not block:
                    break
                total_downloaded += len(block)
                writer.write(block)
                logger.debug('    Saved %.2f%% of the file',
                             (100. * total_downloaded / manifest['images'][img]['size']))
    else:
        logger.debug('  Downloaded file already complete in local repo.')

    # Verify the checksum of the downloaded file
    logger.debug('  Checking encrypted file\'s checksum...')
    local_temp_crypt_sha1 = get_file_checksum(local_temp_crypt_file)
    if local_temp_crypt_sha1 != manifest['images'][img]['cryptSha1']:
        logger.error('  Checksum of downloaded encrypted file does not match manifest. Discarding.')
        unlink(local_temp_crypt_file)
        return False

    # Checksum matches. Decrypt the encrypted file.
    logger.debug('  Checksum of encrypted file is correct. Decrypting '
                 'temporary file {0}'.format(local_temp_crypt_file))
    crypt_size = getsize(local_temp_crypt_file)
    decrypted_bytes = 0
    with io.open(local_plain_file, 'wb') as plain:
        with io.open(local_temp_crypt_file, 'rb') as crypt:
            # The first <AES.block_size> bytes are the IV
            iv = crypt.read(AES.block_size)
            cipher = AES.new(encryption_key, AES.MODE_CFB, iv)
            while True:
                block = crypt.read(2**22)
                if not block:
                    break
                p = cipher.decrypt(block)
                plain.write(p)
                decrypted_bytes += len(p)
                logger.debug('    Decrypted %.2f%% of the file', (100. * decrypted_bytes / crypt_size))

    # Verify checksum of plain file
    logger.debug('  Checking plain file\'s checksum...')
    local_plain_sha1 = get_file_checksum(local_plain_file)
    if local_plain_sha1 != manifest['images'][img]['plainSha1']:
        logger.error('  Checksum of decrypted image file does not match manifest. Discarding.')
        unlink(local_plain_file)
        return False
    else:
        logger.debug('  Checksum of decrypted image is correct.')

    # The plain file is correct. We can discard the temporary, encrypted file
    logger.debug('  Removing temporary encrypted file: {0}'.format(local_temp_crypt_file))
    unlink(local_temp_crypt_file)
    return True


def get_file_checksum(file_name):
    file_sha1 = sha1()
    with io.open(file_name, 'rb') as check:
        while True:
            data_block = check.read(2 ** 22)
            if not data_block:
                break
            file_sha1.update(data_block)
    return file_sha1.hexdigest()


def is_loop_mounted(mount_target):
    # Need to convert to real path in case they are symlinked elsewhere (PLATSUP-20660)
    real_path = realpath(mount_target)
    with io.open('/proc/mounts', 'r') as mtab:
        for l in mtab:
            if 'squashfs' in l and real_path in l:
                return True
    return False


def get_loop_mounts(local_repo):
    """
    Iterates over the server's mount table and filters all squashfs mounts that are rooted
    in the mount target for the images. For example, if the --mount-target parameter was
    'tmp/mounts', the following line would be considered:

    /dev/loop0 /tmp/mounts/PLS-6.05.00-QA-04 squashfs ro,relatime 0 0

    From this line, the second token is extracted and added to the result list.

    :param local_repo: The local directory where images are loop-mounted
    :return: A list of all active mounts within the given mount target
    """
    result = []
    with io.open('/proc/mounts', 'r') as mtab:
        for l in mtab:
            if 'squashfs' in l and local_repo in l:
                result.append(l.split()[1])
    return result


def create_loop_devices():
    """
    Ensure that a minimum of 16 loopback devices are present on the system. Will attempt
    to create missing device nodes.
    """
    for d in range(0, 16):
        dev_name = '/dev/loop{0}'.format(d)
        try:
            if not exists(dev_name):
                logger.debug('Creating missing loopback device: {0}'.format(dev_name))
                check_call(['/bin/mknod', '-m', '660', dev_name, 'b', '7', str(d)])
                check_call(['/bin/chgrp', 'disk', dev_name])
        except Exception as e:
            logger.error('Unable to create missing loopback device {0}: {1}'.format(dev_name, e))


"""
Script execution starts here:
"""
try:
    # Make sure we have enough loopback devices
    create_loop_devices()

    # Determine my host name. For better transparency, we will automatically map
    # 'ras[0-9]' to appserver. Via cron job, only one of the nodes will fetch
    # images, and that makes scheduling builds easier.
    my_hostname = getfqdn().lower()
    my_alt_hostname = None
    logger.debug('Detected my own host name: %s', my_hostname)

    if args.host_id is not None:
        my_alt_hostname = args.host_id.lower()
    elif search('^ras[0-9]\.', my_hostname) is not None:
        my_alt_hostname = sub('^ras[0-9]\.', 'appserver.', my_hostname)

    if my_alt_hostname is not None:
        logger.debug('  Alternate host name: %s', my_alt_hostname)

    # Parse the manifest URL for sanity
    m = urlparse('{0}/manifest.json'.format(args.repo_base))

    # Fetch the manifest file
    manifest_url = '{0}://{1}{2}'.format(m.scheme, m.netloc, m.path)
    logger.debug('Fetching manifest file: {0}'.format(manifest_url))
    conn = open_url_connection(manifest_url, proxy=args.proxy)
    data = conn.read()
    manifest = loads(data)

    # Capture all files in the local repo, so we can later delete obsolete images
    local_files = listdir(args.local_repo)
    required_mounts = []

    # Iterate over the images of the manifest and check which ones we need to download
    logger.debug('Processing image manifest')
    if 'images' not in manifest:
        raise Exception('Unexpected manifest file. Cannot find images.')

    for img in manifest['images']:
        logger.debug('Checking image %s', img)

        if 'distribution' not in manifest['images'][img] \
                or not isinstance(manifest['images'][img]['distribution'], list):
            logger.debug('  No distribution rule found. Skipping.')
            continue

        dist = manifest['images'][img]['distribution']

        # Empty distribution field: nobody needs the image
        if len(dist) == 0:
            logger.debug('  Empty distribution field. Skipping.')
            continue

        # Wildcard distribution or my hostname listed?
        if '*' not in dist and my_hostname not in dist \
                and (my_alt_hostname is None or my_alt_hostname not in dist):
            logger.debug('  Neither wildcard distribution nor my hostname is listed. Skipping.')
            continue

        # Check if the file is already local and the SHA1 checksum matches
        local_plain_file = '{0}/{1}'.format(args.local_repo, manifest['images'][img]['plainFileName'])
        logger.debug('  Checking local repository for plain file: {0}'.format(local_plain_file))
        download_required = False
        if exists(local_plain_file):
            logger.debug('  Local file present. Checking content against checksum.')
            local_sha1 = get_file_checksum(local_plain_file)
            logger.debug('  Local file SHA1: {0}'.format(local_sha1))
            if local_sha1 != manifest['images'][img]['plainSha1']:
                logger.debug('  Does not match expected plain checksum. Download required.')
                download_required = True
            else:
                logger.debug('  Checksum matches. Skipping download.')
        else:
            logger.debug('  Plain file not in local repo yet. Download required.')
            download_required = True

        if download_required:
            success = download_file(args, img)
            if not success:
                continue

        # Remove the file from the list (if it is in there; just downloaded files are not in the list)
        if manifest['images'][img]['plainFileName'] in local_files:
            local_files.remove(manifest['images'][img]['plainFileName'])

        # If the plain file name ends in ".sqfs" and auto-mounting enabled, make sure this image file is mounted
        if args.mount_locally and manifest['images'][img]['plainFileName'][-5:] == '.sqfs':
            logger.debug('  SquashFS image detected. Image mounting requested. Checking if it is mounted.')
            try:
                # The SQFS gets mounted underneath the version in a directory called 'mounted'. Example:
                # mount_root_dir   : "/opt/tmp/testrepo/PLC_3_2_1_GA/"
                # mount_symlink    : "/opt/tmp/testrepo/PLC_3_2_1_GA/image.sqfs"
                # mount_target_dir : "/opt/tmp/testrepo/PLC_3_2_1_GA/mounted/"
                mount_root_dir = join(args.local_repo, manifest['images'][img]['version'])
                mount_symlink = join(mount_root_dir, 'image.sqfs')
                mount_target_dir = join(mount_root_dir, 'mounted')
                required_mounts.append(mount_target_dir)
                if not is_loop_mounted(mount_target_dir):
                    if exists(mount_root_dir):
                        # The 'mount_root_dir', if it exists, should only contain 2 entries: the symlink to
                        # the SquashFS image ('image.sqfs') and the 'mount_target_dir' directory ('mounted').
                        # If there is more, we need to clean out the image folder, as it probably still
                        # contains cruft from the old image manager.
                        logger.debug('  Not mounted. Looking for unexpected cruft in {0}'.format(mount_root_dir))
                        mount_root_contents = listdir(mount_root_dir)
                        for entry in listdir(mount_root_dir):
                            if entry in ['image.sqfs', 'mounted']:
                                mount_root_contents.remove(entry)

                        # Sanity check on mount_root_dir, so we don't delete '/'
                        if len(mount_root_dir) > 5 and len(mount_root_contents) > 0:
                            logger.warn('    Found unexpected content in {0}: {1}'.format(mount_root_dir,
                                                                                          mount_root_contents))
                            logger.warn('    PURGING {0}'.format(mount_root_dir))
                            rmtree(mount_root_dir)

                    # If the mount_target_dir does not exist (or was just purged) , create it
                    if not exists(mount_target_dir):
                        # Mount point not there? Create it.
                        makedirs(mount_target_dir, mode=0755)

                    logger.debug('  Mounting {0} into {1}'.format(local_plain_file, mount_target_dir))
                    check_call(['/bin/mount', '-o', 'ro', local_plain_file, mount_target_dir])
                else:
                    logger.debug('  Image is already mounted.')
                    if download_required:
                        logger.debug('  But image was replaced by new file. Remounting.')
                        check_call(['/bin/umount', '-f', mount_target_dir])
                        check_call(['/bin/mount', '-o', 'ro', local_plain_file, mount_target_dir])

                # Create a symlink for Francis
                if not exists(mount_symlink):
                    symlink('../{0}'.format(manifest['images'][img]['plainFileName']), mount_symlink)
            except Exception as e:
                logger.error('Unable to mount {0}: {1}'.format(local_plain_file, e))
        else:
            logger.debug('  No --mount-locally set or no SquashFS image detected. Skipping auto-mount.')

    # Unmount all active mounts that are no longer supposed to be mounted
    if args.mount_locally:
        active_mounts = get_loop_mounts(args.local_repo)
        for m in required_mounts:
            if m in active_mounts:
                active_mounts.remove(m)
        logger.debug('Checking for obsolete mounts')
        for u in active_mounts:
            try:
                mount_target_dir = u
                mount_root_dir = u[:-8]     # Strip '/mounted'
                mount_symlink = join(mount_root_dir, 'image.sqfs')

                logger.debug('  Unmounting obsolete image: {0}'.format(u))
                logger.debug('    /bin/umount -f {0}'.format(mount_target_dir))
                logger.debug('    /bin/rmdir {0}'.format(mount_target_dir))
                logger.debug('    /bin/rm {0}'.format(mount_symlink))
                logger.debug('    /bin/rmdir {0}'.format(mount_root_dir))
                check_call(['/bin/umount', '-f', mount_target_dir])
                check_call(['/bin/rmdir', mount_target_dir])
                if islink(mount_symlink):
                    check_call(['/bin/rm', mount_symlink])
                check_call(['/bin/rmdir', mount_root_dir])
            except Exception as e:
                logger.error('Unable to unmount and remove {0}: {1}'.format(u, e))
    else:
        logger.debug('No --mount-target set. Skipping mount clean-up.')

    # Do we need to purge obsolete files form the local directory?
    if args.purge_local:
        logger.info('Checking for obsolete local files')
        for f in local_files:
            purge_file = '{0}/{1}'.format(args.local_repo, f)
            if not islink(purge_file) and isfile(purge_file):
                logger.debug('  Purging file: {0}'.format(purge_file))
                unlink(purge_file)

except HTTPError as h:
    logger.error('HTTPError: code={0}, info={1}'.format(h.code, h.info()))
except URLError as u:
    logger.error('Unable to connect to the remote repository: {0}'.format(u.reason))
except Exception as e:
    logger.error('Fetching images failed unexpectedly. Full stack trace follows.')
    print_exc()
finally:
    # Close and remove the lockfile at the end
    if lock_file is not None:
        try:
            lock_file.close()
        except IOError:
            pass
    if isfile(LOCKFILE):
        unlink(LOCKFILE)
        logger.debug('Removed lock file')
