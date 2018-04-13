#!/usr/bin/env python
# -*- coding: utf8 -*-

"""
Provides a class for string encryption that is compatible with a patching
Java class.

The true source of this file lives in the cryptolib repository:
git@git.hq:internal-engineering/cryptolib.git
"""

from Crypto.Cipher import AES
from base64 import b64encode, b64decode, encodestring
from os import urandom
from cStringIO import StringIO
from gzip import GzipFile
from array import array


class PortableStringCrypt():
    def __init__(self):
        pass

    @staticmethod
    def encrypt(secret, plain_text, line_breaks=False):

        # Generate a random IV
        iv = urandom(16)
        cipher = AES.new(secret, AES.MODE_CBC, iv)

        # Zip the plain text first
        zipped = StringIO()
        z = GzipFile(fileobj=zipped, mode='w')
        z.write(plain_text)
        z.close()

        # Add proper PKCS#7 padding, required for AES
        padlength = 16 - (len(zipped.getvalue()) % 16)
        padded = zipped.getvalue() + chr(padlength) * padlength

        # Encrypt the zipped plaintext
        encrypted = cipher.encrypt(padded)

        if line_breaks:
            return encodestring(iv + encrypted)
        else:
            return b64encode(iv + encrypted)

    @staticmethod
    def decrypt(secret, encrypted_base64):

        # Decode from Base64
        encrypted = b64decode(encrypted_base64)

        # Strip the IV from the beginning
        iv = encrypted[0:16]

        # Decrypt the data from position 16 on (skip over prefixed IV)
        cipher = AES.new(secret, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted[16:])

        # Detect and remove potential PKCS#7 padding
        padcount = array('B', decrypted[-1])[0]
        if padcount <= 16 and decrypted[-padcount:] == (chr(padcount) * padcount):
            decrypted = decrypted[:-padcount]

        # Unzip the decrypted data          
        zipped = StringIO(decrypted)
        z = GzipFile(fileobj=zipped, mode='r')
        return z.read()
