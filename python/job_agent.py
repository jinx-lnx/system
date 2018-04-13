#!/usr/bin/python2
"""
This is the second generation Job Agent, now implemented as a
daemon. The previous incarnation was a one-shot script, triggered
by cron every 5 minutes. This one is multi-threaded and will be
logging to syslog.

This agent communicates only to the assigned Job Relay host
to fetch pending jobs based on serverCode (aka facility code),
MAC address and host name.

This implementation is intended to run as a service.

The true source of this file lives here:
git@git.hq:saltmaster/salt.git

"""

import argparse
import json
import logging
import traceback
from Queue import Queue, Empty
from fcntl import lockf, LOCK_EX, LOCK_NB
from httplib import HTTPSConnection
from logging.handlers import SysLogHandler
from os import getpid, unlink
from os.path import isfile
from signal import signal, SIGTERM
from subprocess import Popen, PIPE
from threading import Thread
from time import sleep
from traceback import format_exc

from config import ServerConfig
from gwncryptolib import PortableStringCrypt

LOCKFILE = '/var/run/lock/job_agent.lock'
PAYLOAD_KEY = 'Ay2xw+9SP/S7SLF6'
DEFAULT_SLEEP_TIME = 1200


# -------------------------------------------------------------------
# Helper methods
# -------------------------------------------------------------------


def shutdown(sig, frame):
    log.info('Shutting down after receiving signal {0}'.format(sig))
    exit(0)


def fetch(sig, frame):
    log.info('--- FETCHING')


def get_human_readable(size):
    """
    Convert any number in a human readable format.
    For example 306875480 turns into 292.7 MB.
    """

    suffixes = [' B', 'KB', 'MB', 'GB', 'TB']
    suffixIndex = 0
    while size > 1024:
        suffixIndex += 1  # increment the index of the suffix
        size = size / 1024.0  # apply the division
    return "%7.1f %s" % (size, suffixes[suffixIndex])


def support_unsupported(obj):
    """
    Helper method for the JSON parser to support serializing unsupported objects.
    For now, we just convert everything to strings.
    """
    return '{0}'.format(obj)


# -------------------------------------------------------------------
# Processor classes
# -------------------------------------------------------------------

class JobProcessor:
    def __init__(self, job, jobRelay=None):
        self._job = job
        self._jobRelay = jobRelay

        # Assemble the response map
        self._response = {'status': 'ERROR'}

    def execute(self):
        """
        Abstract method for the subclasses to implement.
        """
        pass

    def submit_result(self):
        # Convert the response object to JSON and post it back to the job relay
        jresponse = json.dumps(self._response, default=support_unsupported)  # , indent=4)
        log.info('Truncated job response from processor, in JSON: %s...', jresponse[:40])
        self._jobRelay.submit_result(True if self._response['status'] == 'SUCCESS' else False, jresponse)


class PythonProcessor(JobProcessor):
    """
    The PythonProcessor expects a plain text Python script in the
    self._job['contents'] property. It will compile that source code
    and execute it. The result from the Python code is expected as a
    dict in a new variable called 'result'. The script's result
    is then wrapped into self._response['data'] and sent back to
    the server.
    Exception handling in the script is not needed, as execution
    is wrapped in a big try-catch-block here, which determines the
    value of self._response['status'] in the response to the server.
    Since the Python code of the provided script is embedded into
    the current environment, the nested script can trigger sending
    status updates to the job relay by simply calling:

    jobRelay.update_status('Some update string...')
    """

    def execute(self):
        try:
            # Provide jobRelay for embedded Python code (if needed)
            jobRelay = self._jobRelay
            log.info('Job relay provided for embedded script: {0}'.format(jobRelay))

            # Decode the wrapped Python script
            source = self._job['contents']
            log.info('Decoded the Python source code:\n{0}'.format(source))

            # Compile and execute the code.
            result = None
            log.info('Compiling python code...')
            code = compile(source, '<string>', 'exec')
            log.info('Compilation complete. Executing...')
            exec code
            log.info('Execution complete.')

            if result is None:
                raise Exception('The embedded script did not create a result object')
            else:
                # Copy any notes from the script's result object to the outer response
                if 'notes' in result:
                    self._response['notes'] = result['notes']
                self._response['data'] = result
                self._response['status'] = 'SUCCESS'

        except BaseException as e:
            self._response['notes'] = 'Script execution failed: {0}'.format(e)
            log.error(format_exc())


class SqlProcessor(JobProcessor):
    def execute(self):
        try:
            import MySQLdb
            from re import match

            db_conn = MySQLdb.connect('localhost', 'reporter', 'V0y3ur', 'GWN_R5');
            cursor = db_conn.cursor(MySQLdb.cursors.DictCursor)
            cursor.execute('SELECT VERSION()')
            row = cursor.fetchone()
            if 'VERSION()' in row and match('^10', row['VERSION()']):
                log.info('MariaDB version 10 detected. Setting enhanced read-only mode')
                cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ UNCOMMITTED, READ ONLY')
            else:
                log.info('No MariaDB version 10 detected. Setting legacy transaction isolation')
                cursor.execute('SET SESSION TRANSACTION ISOLATION LEVEL READ UNCOMMITTED')

            log.info('About to execute read-only SQL (truncated): %s...', self._job['contents'][:40])
            cursor.execute(self._job['contents'])
            self._response['data'] = cursor.fetchall()
            self._response['status'] = 'SUCCESS'
            cursor.close()

            # We need to patch up any boolean fields of type BIT(1);
            # they get returned as unicode strings '\x00' and '\x01'.
            # Nasty hack, that is!
            #
            row_hack = False
            for row in self._response['data']:
                for k in row.keys():
                    # Also: some DBs have bogus values or encodings. Force UTF-8 and ignore
                    # any conversion errors.
                    try:
                        if isinstance(row[k], str):
                            row[k] = unicode(row[k], errors='ignore')
                    except BaseException as e:
                        log.warn('ERROR formatting data for key [{0}]: [{1}]'.format(k, e))
                    if row[k] == '\x00':
                        row[k] = 0
                        row_hack = True
                    elif row[k] == '\x01':
                        row[k] = 1
                        row_hack = True

            if row_hack == True:
                log.info('Note: boolean row hack applied to the results!')

        except BaseException as e:
            self._response['notes'] = 'SQL execution failed: {0}'.format(e)
            log.error(format_exc())


class BinaryServerSide(JobProcessor):
    """
    """

    def execute(self):
        try:
            # Expects the payload 'contents' property to contain the full command line to launch
            # the external process
            command = json.loads(self._job['contents'])
            if type(command) != list:
                raise Exception('The payload contents did not contain a command as a list.')

            # Append some info for the external process to instantiate a JobRelay instance
            relay_info = self._jobRelay.get_info()
            command.append(json.dumps(relay_info))

            log.info('Synchronously launching external binary: {0}'.format(command))
            p = Popen(command, stdout=PIPE, stderr=PIPE)
            (stdout, stderr) = p.communicate()
            exit_code = p.returncode
            self._response['data'] = {
                'stdout': stdout,
                'stderr': stderr
            }

            log.info('External binary completed with exit code {0} '
                     'and this output data: {1}'.format(exit_code, self._response['data']))

            if exit_code == 0:
                self._response['status'] = 'SUCCESS'

        except BaseException as e:
            self._response['notes'] = 'Script execution failed: {0}'.format(e)
            log.error(format_exc())


# -------------------------------------------------------------------
# Classes
# -------------------------------------------------------------------

class JobRelay:
    # def __init__(self, relay_host, my_server_code, my_host_name, my_mac, jobId=None, name=None, log=None):
    def __init__(self, **kwargs):
        """
        The constructor for the JobRelay takes a keyword-based argument to initialize.
        This was needed, because the JobRelay may be instantiated from the external
        deployment wrapper, or any other long-running script, and we want to conveniently
        instantiate a JobRelay there from a dict of parameters that were passed to the script.
        :param kwargs: The required parameters are relay_host, my_server_code, my_host_name
            and my_mac. Optional parameters are jobId and name if this JobRelay is already
            tied to a specific job.
        :return:
        """
        # Parse the required parameters
        self.__relay_host = kwargs['relay_host']
        self.__my_server_code = kwargs['my_server_code']
        self.__my_host_name = kwargs['my_host_name']
        self.__my_mac = kwargs['my_mac']

        # Parse the optional parameters
        self.__jobId = None if 'jobId' not in kwargs else kwargs['jobId']
        self.__name = None if 'name' not in kwargs else kwargs['name']

        self.__relay_base = '/job-relay'

        # Since this class may be imported by the deployment script, we must have an optional
        # logger internally
        self.__log = None if 'log' not in kwargs else kwargs['log']

    def log_info(self, *argv):
        if self.__log is not None:
            self.__log.info(*argv)

    def log_error(self, *argv):
        if self.__log is not None:
            self.__log.error(*argv)

    def __performRequest(self, method, url, body=None, headers={}, expectJson=True):
        """
        Send the HTTP request to the job relay on a non-shared connection.
        Cannot share it because of a bug in httplib: https://code.google.com/p/httplib2/issues/detail?id=250
        """
        conn = HTTPSConnection(self.__relay_host, timeout=30)

        if body is not None:
            headers['content-length'] = len(body)
        else:
            headers['content-length'] = 0

        self.log_info('Sending request to %s: %s with headers: %s', self.__relay_host, url, headers)
        conn.request(method, url, body, headers)
        resp = conn.getresponse()
        self.log_info('  Got response: %s %s', resp.status, resp.reason)

        # Before we do some error checking, we need to read the full response
        data = resp.read()

        if resp.status != 200:
            self.log_error('  Did not receive a 200 response code. Here is the full response body: %s', data)
            raise Exception('Unexpected status response received. Expected 200, got {0}'.format(resp.status))

        resp_type = resp.getheader('content-type', '-unknown-')
        self.log_info('  Response type: %s', resp_type)

        if expectJson == False:
            # Simply return the response as string
            return data
        else:
            # Enforce JSON and parse into a dict before returning
            if resp_type != 'application/json':
                self.log_error('  Did not receive a JSON response content type. Here is the full response body: %s',
                               data)
                raise Exception('Unexpected response type received for "{0}": {1}'.format(url, resp_type))

            resp_obj = json.loads(data, encoding='utf-8')
            self.log_info('  Response decoded from JSON: %s', resp_obj)
            return resp_obj

    def fetch_job(self):
        url = '{0}/jobs/fetch/{1}/{2}/{3}'.format(self.__relay_base, self.__my_server_code,
                                                  self.__my_mac, self.__my_host_name)
        return self.__performRequest('GET', url, expectJson=True)

    def set_job_info(self, jobId, name):
        """
        Once the jobId and name of the current job are known, update the JobRelay with that
        info to easily perform status updates, etc.
        :param jobId: The current jobId
        :param name: the name of the current job
        """
        self.__jobId = jobId
        self.__name = name

    def get_info(self):
        """
        Return a dict that contains all the info needed to create a JobRelay instance
        for external processes to send a status update to the relay.
        """
        return {
            'relay_host': self.__relay_host,
            'my_server_code': self.__my_server_code,
            'my_host_name': self.__my_host_name,
            'my_mac': self.__my_mac,
            'jobId': self.__jobId,
            'name': self.__name
        }

    def update_status(self, status_text):
        """
        If the set_job_info() method was called before and jobId/name are known,
        dispatch a status message about the current job to the job relay.
        """
        if self.__jobId is None or self.__name is None or status_text is None:
            self.log_error('Cannot send status because jobId and name are not known or no status given')
            return

        status = {
            'jobId': self.__jobId,
            'name': self.__name,
            'macAddress': self.__my_mac,
            'payload': PortableStringCrypt().encrypt(PAYLOAD_KEY, status_text)
        }
        json_status = json.dumps(status)
        url = '{0}/status/append'.format(self.__relay_base)
        headers = {'content-type': 'application/json'}
        s = self.__performRequest('POST', url, json_status, headers, expectJson=False)
        self.log_info('Updated status ({0}). Job Relay said: {1}'.format(status_text, s))

    def submit_result(self, success, raw_payload=None):
        """
        Post back a response about the execution of the current job.
        """
        resp = {
            'jobId': self.__jobId,
            'name': self.__name,
            'macAddress': self.__my_mac,
            'status': 'success' if success == True else 'failure',
            'payload': PortableStringCrypt().encrypt(PAYLOAD_KEY, raw_payload)
        }

        json_resp = json.dumps(resp)
        self.log_info('Truncated embedded processor result into JSON result object: %s...', json_resp[:40])
        self.log_info('Raw processor result: {0}. Encrypted playload: {1}'.format(
            get_human_readable(len(raw_payload)), get_human_readable(len(json_resp))))
        url = '{0}/results/submit'.format(self.__relay_base)
        headers = {'content-type': 'application/json'}
        status = self.__performRequest('POST', url, json_resp, headers, expectJson=False)
        self.log_info('Job Relay said: {0}'.format(status))


class JobProcessorThread(Thread):
    def __init__(self, log, job_queue, name):
        Thread.__init__(self, name=name)
        self.daemon = True
        self.__log = log
        self.__job_queue = job_queue
        self.__log.info('Initializing worker {0}'.format(name))

    def run(self):
        while True:
            try:
                self.__log.info('  -- alive and waiting for work')
                job_processor = self.__job_queue.get(True, 150)
                self.__log.info('  -- TASK RECEIVED: {0}. Executing...'.format(job_processor))
                job_processor.execute()
                job_processor.submit_result()
            except Empty:
                pass
            except BaseException as be:
                log.error('Error in worker thread: {0}'.format(be))


# -------------------------------------------------------------------
# Service starts here
# -------------------------------------------------------------------

if __name__ == '__main__':

    # Parse the command line options
    parser = argparse.ArgumentParser(description='Service that manages execution of jobs from ESM.')

    parser.add_argument('--relay-host', metavar='RELAY_HOST', type=str, required=True, dest='relay_host',
                        help='The job relay host that this job agent should contact')
    parser.add_argument('--proxy', metavar='http://HOST:PORT', type=str, required=False,
                        help='Set this if the request to Amazon needs to go through a proxy')

    args = parser.parse_args()

    # Extract info from server_config
    server_config = ServerConfig()

    # Set up the logger to log to console and syslog
    logging.basicConfig(format='%(asctime)s (%(threadName)-10s) [%(levelname)-8s] %(message)s')
    log = logging.getLogger()
    syslog = SysLogHandler(address='/dev/log')
    fmt = logging.Formatter('job_agent (%(threadName)-10s) [%(levelname)-8s] %(message)s')
    syslog.setFormatter(fmt)
    log.addHandler(syslog)
    log.setLevel(logging.INFO)

    # Make sure we are running exclusively
    try:
        log.info('Acquiring lock file {0}'.format(LOCKFILE))
        lock_file = open(LOCKFILE, 'w')
        lockf(lock_file, LOCK_EX | LOCK_NB)
        lock_file.write('{0}'.format(getpid()))
        lock_file.flush()
    except IOError as io:
        log.error('Unable to obtain file lock ({0}). Process already running?'.format(io))
        exit(1)

    log.info('Starting job agent in daemon mode.')

    # Determine my primary NIC's MAC address as server identifier
    try:
        with open('/sys/class/net/eth0/address', 'r') as mac_file:
            mac = mac_file.readline().strip()

            if mac is None or len(mac) < 2:
                raise Exception()
        log.info('Determined my MAC address: %s', mac)
    except:
        log.error('Unable to determine MAC address of eth0')
        exit(1)

    # We're exclusive. Let's go.
    try:
        # Register signal handler
        signal(SIGTERM, shutdown)

        # Set up the job queue and worker threads for the "regular" tasks"
        default_job_queue = Queue(maxsize=15)
        for i in range(0, 3):
            t = JobProcessorThread(log, default_job_queue, 'JobWorker{0}'.format(i))
            t.start()

        # Set up the job queue and single worker threads for the deployment tasks
        deployment_job_queue = Queue(maxsize=1)
        t = JobProcessorThread(log, deployment_job_queue, 'LongWorker')
        t.start()

        sleep_time = 5

        # Enter infinite loop of fetching next job from job relay
        # -------------------------------------------------------
        while True:

            try:
                log.info('=== Looking for the next job ===')

                # We need to build a JobRelay instance for the initial contact. We don't know
                # the current jobId or name yet, so that will be updated later.
                jr_params = {
                    'relay_host': args.relay_host,
                    'my_server_code': server_config.get_string('facility_code', False),
                    'my_host_name': server_config.get_string('full_host_name', False),
                    'my_mac': mac,
                    'log': log
                }
                jr = JobRelay(**jr_params)

                # Check if there are scripts to run
                resp_obj = jr.fetch_job()

                if resp_obj['next_job'] is None:
                    log.info('No jobs waiting for me. Going back to sleep.')
                    sleep_time = DEFAULT_SLEEP_TIME
                else:
                    # If the relay says there are more jobs waiting, keep fetching them
                    # quickly. If no more are up, increase the wait time again.
                    if 'remaining_jobs' in resp_obj:
                        if resp_obj['remaining_jobs'] > 0:
                            sleep_time = 5
                            log.info('More jobs waiting after this.')
                        else:
                            sleep_time = DEFAULT_SLEEP_TIME
                            log.info('No more jobs waiting after this.')
                        log.info('Setting sleep time to {0} seconds.'.format(sleep_time))

                    # The nested job should look like this:
                    # { 'jobId': 1, 'allowedMacs': [ '08:00:27:9b:89:e0'], 'name': 'Some Hello Job',
                    # 'serverCode': 'BND2', 'payload': 'mBaMFLur1iTHZUBaC8AwuyLI...'}
                    job = resp_obj['next_job']

                    log.info('Parsing and decoding jobId={0}, name="{1}"'.format(job['jobId'], job['name']))
                    jr.set_job_info(job['jobId'], job['name'])

                    # From here on we have a jobId and can post status and results back to the job relay
                    # that we will pass to the appropriate worker thread

                    try:
                        # Decrypt the payload, expect a nested job inside:
                        # {"type": "python", "contents": "\nprint 'Hello World!'\nresult = { }\n"}
                        job_payload = PortableStringCrypt().decrypt(PAYLOAD_KEY, job['payload'])
                        job_object = json.loads(job_payload)

                        # Sort the job implementation into the appropriate worker bucket
                        if job_object['type'] == 'sql':
                            default_job_queue.put(SqlProcessor(job_object, jr))
                        elif job_object['type'] == 'python':
                            default_job_queue.put(PythonProcessor(job_object, jr))
                        elif job_object['type'] == 'binary-server-side':
                            deployment_job_queue.put(BinaryServerSide(job_object, jr))
                        else:
                            log.error('Unsupported job type: {0}'.format(job_object['type']))

                    except Exception as e:
                        traceback.print_exc()
                        jr.submit_result(False, json.dumps({'error': 'Unable to parse job payload ({0})'.format(e)}))


            except KeyboardInterrupt:
                log.info('Shutting down due to KeyboardInterrupt')
                exit(0)
            except BaseException as be:
                log.error('Error processing next job: {0}'.format(be))
                traceback.print_exc()
                sleep(15)

            sleep(sleep_time)

    except SystemExit:
        pass
    except BaseException as e:
        log.error('Exception in job agent: {0}'.format(type(e)))
        log.error(traceback.format_exc())
    finally:
        # Close and remove the lockfile at the end
        if lock_file is not None:
            try:
                lock_file.close()
            except IOError:
                pass
        if isfile(LOCKFILE):
            unlink(LOCKFILE)
            log.info('Removed lock file')

    log.info('Job agent terminated.')
