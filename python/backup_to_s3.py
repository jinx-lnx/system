#!/usr/bin/python2
'''
Backup facility files to a subfolder on dedicated Amazon S3 Cloud Storage.
'''

from optparse import OptionParser
import sys
import os
import socket
import boto
import mmap
from boto.s3.bucket import Key
from boto.exception import S3ResponseError
from boto.s3.multipart import MultiPartUpload
from time import time
from hashlib import sha1


# 'backup-agent'
_s3_access_key = "AKIAJPIJPSQTUZKRUQHA"
_s3_secret_key = "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"
_s3_bucket_name = "gwn-site-backup"
_s3_sha1_meta_key = 'gwn-sha1'

# Chunk size in megabytes for multipart uploads
_chunk_size_mb = 100

# What is the threshold for using multipart upload versus standart upload?
_chunk_threshold_mb = 1024

# Helper variables for standard transfer call-back method
last_bytes = 0
last_timestamp = 0



def die(message, details=None):
    '''
    Terminate the script with a big fat error message.
    '''
    
    print "\n***\n*** ERROR:", message, "\n***"
    if(details):
        print details
    sys.exit(1)
    


def get_human_readable(size):
    '''
    Convert any number in a human readable format.
    For example 306875480 turns into 292.7 MB.
    '''
    
    suffixes=[' B','KB','MB','GB','TB']
    suffixIndex = 0
    while size > 1024:
        suffixIndex += 1 #increment the index of the suffix
        size = size/1024.0 #apply the division
    return "%7.1f %s" % (size,suffixes[suffixIndex])


    
def progress(part, total):
    '''
    Call-back function that is called by the S3 standard upload thread.
    '''
    
    global last_bytes
    global last_timestamp
    
    byte_per_sec = (part - last_bytes) / (time() - last_timestamp)
    
    if (part != total):
        print "    - Transfered %s of %s so far: %3d%%    (%s/s)" \
            % (get_human_readable(part), get_human_readable(total), (part * 100 / total), get_human_readable(byte_per_sec))
    else:
        print "    - Transfered %s of %s       : 100%%" % (get_human_readable(part), get_human_readable(total))        
    
    last_bytes = part
    last_timestamp = time()


def standard_transfer(k, myfile, meta):
    '''
    Perform the standard upload for files smaller than the _chunk_threshold_mb variable.
    '''
    global last_timestamp
    print "\n* Starting standard transfer"
    last_timestamp = time()
    for key in meta.keys():
        k.set_metadata(key, meta[key])

    k.set_contents_from_file(myfile, reduced_redundancy=False, encrypt_key=True,
                             cb=progress, num_cb=10)
    

def multipart_transfer(bucket, k, myfile, file_size, meta):
    '''
    Any transfer over 5 GB needs to be done using multipart upload.
    '''
    
    chunk_size = 1024 * 1024 * _chunk_size_mb
    chunks = file_size / chunk_size
    print "\n* Starting multipart transfer with {0} chunks of {1} each".format(chunks, get_human_readable(chunk_size))
    multipart_upload = None
    
    try:
        multipart_upload = bucket.initiate_multipart_upload(k, reduced_redundancy=False,
                encrypt_key=True, metadata=meta)
        for c in range(0, chunks + 1):
            offset = c * chunk_size
            length = min(chunk_size, file_size-(c*chunk_size))            
            mm = mmap.mmap(myfile.fileno(), prot=mmap.PROT_READ, length=length, offset=offset)
            start = time()
            multipart_upload.upload_part_from_file(mm, c+1)
            byte_per_sec = length / ( time() - start + 0.01)
            print "   Sent chunk {0} of {1} at {2}/s. Size: {3}.".format(c+1, chunks+1,
                    get_human_readable(byte_per_sec), get_human_readable(length))
            
        multipart_upload.complete_upload()
    except BaseException as e:
        if multipart_upload is not None:
            multipart_upload.cancel_upload()
            die("Multipart upload failed", "Error: {0}".format(type(e)))
    

def main():

    global _s3_access_key
    global _s3_secret_key
    global _s3_bucket_name

    usageStr = "Usage: %prog [options]"
    parser = OptionParser(usage=usageStr)
    
    parser.add_option("-f", "--file", dest="filename",
                  help="which file to back up in the Cloud", metavar="FILE")
    parser.add_option("-a", "--access-key", dest="s3_access_key",
                  help="the access key for the S3 bucket", metavar="STRING")
    parser.add_option("-s", "--secret-key", dest="s3_secret_key",
                  help="the secret key for the S3 bucket", metavar="STRING")
    parser.add_option("-b", "--bucket", dest="s3_bucket",
                  help="the name of the S3 bucket", metavar="STRING")

    (options, args) = parser.parse_args()
    
    if options.filename is None:
        die("Option -f is required");
    if options.s3_access_key is not None:
        _s3_access_key = options.s3_access_key
    if options.s3_secret_key is not None:
        _s3_secret_key = options.s3_secret_key
    if options.s3_bucket is not None:
        _s3_bucket_name = options.s3_bucket

    # Get my own full host name
    host_name = socket.getfqdn()
    
    if not host_name or len(host_name)<1:
        die("Cannot determine full host name");

    if not os.path.isfile(options.filename):
        die("Given file '" + options.filename + "' is not a file.")
        
    basename = os.path.basename(options.filename)
    file_size = os.path.getsize(options.filename)

    print "-"*70
    print "Backup to Amazon S3:", options.filename
    print "-"*70
    
        
    print "\n* Connecting to Cloud"
    try:
        conn = boto.connect_s3(_s3_access_key, _s3_secret_key)
        bucket = conn.get_bucket(_s3_bucket_name)
    except S3ResponseError as e:
        die("Unable to connect to Cloud", e)
    

    need_transfer = True
    key_str = '/' + host_name + '/' + basename
    k = bucket.get_key(key_str)
    
    with open(options.filename, 'rb') as myfile:
    
        # Since multipart uploads do not support checksums, we have to generate our own
        # and provide it as a meta tag. Then we can compare against that to check if
        # the very same file is already uploaded. Simply use our own checksum regardless
        # of upload type.    
        print "\n* Generating SHA-1 checksum of local file"
        myfile.seek(0)
        checksum = sha1()
        buff = myfile.read(1024 * 1024)
        while buff:
            checksum.update(buff)
            buff = myfile.read(1024 * 1024)
        myfile.seek(0)
        local_file_sha1 = checksum.hexdigest()
        print "  Local file checksum: ", local_file_sha1

        print "\n* Checking if remote file exists:", key_str
        
        if k:
            remote_file_sha1 = k.get_metadata(_s3_sha1_meta_key)
            print "  File already exists. Remote GWN checksum: {0}".format(remote_file_sha1)
            if (local_file_sha1 == remote_file_sha1):
                print "  SHA-1 checksum identical. Skipping file transfer."
                need_transfer = False
    
                
        if need_transfer:
            print "\n* File transfer required. Determining transfer method."
            
            if not k:
                k = Key(bucket)
                k.storage_class='STANDARD_IA'
                k.key = key_str
                
            meta = { _s3_sha1_meta_key : local_file_sha1 }

            if file_size < _chunk_threshold_mb * 1024 * 1024:
                standard_transfer(k, myfile, meta)
            else:
                multipart_transfer(bucket, k, myfile, file_size, meta)
            
        
        print "All done.\n\n"




if __name__ == '__main__':
    main()
