#!/usr/bin/python
import json
import os.path
import requests
import subprocess
import sys
import syslog
import time
import traceback
import xml.etree.ElementTree as ET
from datetime import datetime
from gwncryptolib import PortableStringCrypt
from job_agent import JobRelay

############################
# GLOBAL VARIABLES
############################

syslog.openlog('PLSDeploymentWrapper', 0, syslog.LOG_LOCAL4)

try:
    arg1 = sys.argv[1]
    g_release_label = arg1
except:
    sys.exit("Missing/Incorrect json for the release label. Argv 1")

try:
    jinfo = json.loads(sys.argv[2])
    jr = JobRelay(**jinfo)
except ValueError as details:
    print "Unexpected error:", details
    sys.exit("Missing/Incorrect json for script values. Argv 2")

# These are the steps we are going to be workign with
deployment_steps = ["process_initialized", "set_banner", "database_dump", "set_nagios_downtime", "deploy_code",
                    "check_deployment", "rem_banner", "finishing"]
deployment_steps_label = ["Deployment Initialized", "Set Support Banner", "Database Backup", "Nagios Downtime",
                          "Deploy Code", "Checking Deployment", "Remove Support Banner", "Wrapping up"]

# Max time in seconds we can proceed w/o retriggering a back up in seconds
skip_backup_interval = 7200  # 2 hours

# Time to wait between steps
between_steps_wait = 1;  # 5 seconds

# Time interval toi send uptaes while process still runs
taking_long_update = 9;  # Nine 5 second intervals (45 seconds)

# Tracker for processes that take too long
__is_running_count = 0

# Current deployment Step
__current_step = 0

# How many loops to wait for the .deployed file to appear
__deployed_wait = 20  # 20 seconds
__deployed_loops = 90  # 30 min (90 20 second loops)

############################
# Utility Objects
############################
__status_success = 1
__status_error = 0


class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


############################
# Helper functions
############################
def getDBDumpFile():
    dt = datetime.fromtimestamp(time.time())
    str = dt.strftime('%Y-%m-%d')
    return str;


def postStatusUpdate(data):
    data = json.dumps(data)
    jr.update_status(data)
    return "OK"


def getDeploymentStatus(started, completed, status, notes, action, inProgress):
    global deployment_steps
    global __is_running_count
    global __current_step
    global deployment_steps_label
    # print "Curr Step: ", __current_step, " vs " , len(deployment_steps)
    currstep = deployment_steps[__current_step]
    currlabel = deployment_steps_label[__current_step]
    if __current_step + 1 >= len(deployment_steps) or status == __status_error:
        nextstep = None
    else:
        if inProgress:
            currstep = deployment_steps[__current_step] + "_" + str(__is_running_count)
            nextstep = "Still in progress"
        else:
            nextstep = deployment_steps_label[__current_step + 1]
    data = {
        "step": currstep,
        "started": started,
        "completed": completed,
        "status": status,
        "notes": notes,
        "steplabel": currlabel,
        "nextstep": nextstep,
        "action": action
    }
    return data;


def getStatusUpdateData(job_id, job_name, payload):
    payload['jobId'] = job_id
    print payload
    encrypted = PortableStringCrypt().encrypt(PAYLOAD_KEY, json.dumps(payload))
    # encrypted = base64.b64encode(json.dumps(payload))
    data = {
        "payload": encrypted,
        "jobId": job_id,
        "name": job_name
    }
    return data;


def print_yellow(x):
    syslog.syslog('WARN: %s' % x)
    print bcolors.WARNING + x + bcolors.ENDC
    return;


def print_green(x):
    syslog.syslog('SUCCESS: %s' % x)
    print bcolors.OKGREEN + x + bcolors.ENDC
    return;


def print_red(x):
    syslog.syslog('ERROR: %s' % x)
    print bcolors.FAIL + x + bcolors.ENDC
    return;


############################
# Lambda Functions
############################
current_milli_time = lambda: int(round(time.time() * 1000))
current_second_time = lambda: int(round(time.time()))


#####################################################################################################
# Step Functions
#####################################################################################################
def triggerDeployment():
    global g_release_label
    try:
        print "Will deploy label soon:"
        print g_release_label
        new_env = os.environ.copy()
        new_env['SUDO_USER'] = 'reporter'
        child = subprocess.Popen(['sudo', '/opt/gwn/system/wildfly-deploy.sh', g_release_label, '-n'], env=new_env)
        streamdata = child.communicate()[0]
        rc = child.returncode
        # rc = 0
        message = "Unknown"
        r_status = 0
        print "Message back form deploy script: "
        print rc
        if rc == 0:
            message = "Completeed with no errors. Code 0"
            r_status = 1
        elif rc == 1:
            message = "Generic execution error. Code 1"
        elif rc == 10:
            message = "Cannot find requested PLS version on server. Code 10"
        elif rc == 11:
            message = "Unable to stop JBoss. Code 11"
        elif rc == 12:
            message = "Unable to run Liquibase. Code 12"
        else:
            message = "Unknown return code: " + rc

        return {"status": r_status, "message": message}
    except:
        e = sys.exc_info()[0]
        return {"status": 0, "message": e}


def triggerBackup():
    # Trigger BACKUP Script here
    os.system("sudo /opt/gwn/system/daily-backup.sh")
    # os.system("sudo /home/reporter/daily-backup.sh ")
    # print "/opt/FACILITY-BACKUP/GWN-R5_"+getDBDumpFile()+".sql.xz.gp"
    print "Dailiy Back up process started ..."
    #Post update: backup found!
    step_status = __status_success
    step_notes = "Triggering backup script via: sudo /opt/gwn/system/daily-backup.sh"
    completed = current_milli_time()
    deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
    posted_update = postStatusUpdate(deployment_update)
    time.sleep(10);


def checkBackupTime(fileName, starttime):
    wasRunning = False
    isRunningLoop(starttime)
    timeSinceLastBackup = skip_backup_interval + 1
    try:
        secondsSinceLastEdit = os.path.getmtime(fileName)
        timeSinceLastBackup = current_second_time() - secondsSinceLastEdit
        print "Total time since last back up: %d", int(timeSinceLastBackup)
        if timeSinceLastBackup > skip_backup_interval:
            print "Too long since last update even after we tried to re-run bacup script. something is werid, last ran on:" + time.ctime(secondsSinceLastEdit)
            time.sleep(5);
            print "Returning error here, we cant just keep triggering backup script."
            return {"status": 0, "message": "We tried to retrigger backup with no luck. Last Backup ran : " + time.ctime(secondsSinceLastEdit)}
        else:
            return {"status": 1, "message": "Found valid backup: " + time.ctime(secondsSinceLastEdit)}
    except:
        step_status = __status_success
        step_notes = "Backup file not found!"
        completed = current_milli_time()
        deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
        posted_update = postStatusUpdate(deployment_update)
        triggerBackup();
	return checkBackupTime(fileName, starttime)

def isRunningLoop(starttime):
    global taking_long_update
    global __is_running_count
    __is_running_count = 0
    isRunning = os.path.isfile("/tmp/cron.daily.backup.lck")
    isRunningLoop = 0
    if isRunning:
        #Post initial is running wait
        step_status = __status_success
        step_notes = "Backup process already running. Time to sit and wait."
        completed = current_milli_time()
        deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
        posted_update = postStatusUpdate(deployment_update)
    
    while (isRunning):
        __is_running_count += 1
        print "Waiting... still running"
        print "isrunning loop: ", isRunningLoop
        print "taking to long update: ", taking_long_update
        if isRunningLoop > taking_long_update:
            # Send update to UI
            print_yellow("Database backup still running... here chilling and waiting")
            isRunningLoop = 0
            step_status = __status_success
            step_notes = "Still running, </tmp/cron.daily.backup.lck> file present."
            completed = current_milli_time()
            # Post update
            deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
            posted_update = postStatusUpdate(deployment_update)
        isRunningLoop += 1
        time.sleep(5);
        isRunning = os.path.isfile("/tmp/cron.daily.backup.lck")
    print "Completed isRunning loop. Lock file not present anymore."


def stepDbDump():
    started = current_milli_time()
    try:
        print "Starting DB dump check"
        print "Is the backup script running now?"
        wasRunning = False
        isRunningLoop(started)  # Loop while the lock fiel is removed
        # Busy loop is over, lets get the latest time this run and be done with it
        fileName = "/opt/FACILITY-BACKUP/GWN-R5_" + getDBDumpFile() + ".sql.xz.gpg"
        print "BackUp File name should be at: " + fileName
        backupExists = os.path.isfile(fileName)
        if backupExists:
            print "Back up found, we need to check when was it last edited"
	    secondsSinceLastEdit = os.path.getmtime(fileName)
            timeSinceLastBackup = current_second_time() - secondsSinceLastEdit
            print "Total time since last back up: ", int(timeSinceLastBackup), "seconds"
            if timeSinceLastBackup > skip_backup_interval:
                #Post too long since last baxckup
                step_status = __status_success
                step_notes = "Backup file is too old. " + time.ctime(secondsSinceLastEdit)
                completed = current_milli_time()
                deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
                print "Too long since last update, lets trigger db dump again, last one on: " + time.ctime(secondsSinceLastEdit)
                triggerBackup();
                return checkBackupTime(fileName, started)
            else:
                return {"status": 1, "message": "Found valid backup: " + time.ctime(secondsSinceLastEdit)}
        else:
            print "not found, lets retrigger the dump"
            step_status = __status_success
            step_notes = "Backup file not found!"
            completed = current_milli_time()
            deployment_update = getDeploymentStatus(current_milli_time(), completed, step_status, step_notes, None, True)
            posted_update = postStatusUpdate(deployment_update)
            triggerBackup();
            return checkBackupTime(fileName, started)
    except:
        e = sys.exc_info()[0]
        traceback.print_exc()
        return {"status": 0, "message": "Runtime Exception: " + str(e)}


#####################################################################################################
# Execution Starts Here
#####################################################################################################
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

############## STEP 1111111111111111111111111111111111111111111111111111111111111
############## Update deployment start
time.sleep(between_steps_wait)
__current_step = 0
started = current_milli_time()
print_yellow("Starting deployment wrapper ...")
step_status = __status_success
step_notes = "Started"
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, None, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 1 completed: Deployment started")
time.sleep(2);
################################################################################


############## STEP 222222222222222222222222222222222222222222222222222222222222
############## Set banner
print_yellow("Step 2 started: Banner set in ESM")
time.sleep(between_steps_wait)
started = current_milli_time()
step_status = __status_success
step_notes = ""
step_action = "set_banner"
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 2 completed: Banner set in ESM")
time.sleep(2);
################################################################################


############## STEP 333333333333333333333333333333333333333333333333333333333333
############## Database Dump
print_yellow("Step 3 started: Database dump check")
time.sleep(between_steps_wait)
started = current_milli_time()
# raw_input("Lets fake the DB dump is running... click enter whenever you are tired... ")
checkDBackup = stepDbDump()
completed = current_milli_time()
if checkDBackup['status'] == 1:
    step_status = __status_success  # Get it from the actual stuff we found in the db
    step_notes = checkDBackup['message']
    # Post update
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, None, False)
    posted_update = postStatusUpdate(deployment_update)
    __current_step += 1
    print_green("Step 3 completed: Database dump check")
else:
    step_status = __status_error  # Get it from the actual stuff we found in the db
    step_notes = checkDBackup['message']
    # Post update with error
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, None, False)
    posted_update = postStatusUpdate(deployment_update)
    print_red("Step 3 failed: Database dump check completed with error, exiting...")
    sys.exit(step_notes)
time.sleep(2);
################################################################################


############## STEP 44444444444444444444444444444444444444
############## Set banner
print_yellow("Step 4 started: Set Nagios downtime")
time.sleep(between_steps_wait)
started = current_milli_time()
completed = current_milli_time()
step_status = __status_success
step_notes = ""
step_action = "set_nagios"
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 4 completed: Set Nagios downtime")
time.sleep(2);
################################################################################


############## STEP 55555555555555555555555555555555555555555555555555555555555
############## Deploy Code
print_yellow("Step 5 started: deploy code")
time.sleep(between_steps_wait)
started = current_milli_time()
step_notes = ""
### Start DO the Work

deployed = triggerDeployment()
if deployed['status'] != 1:
    step_status = __status_error
    step_notes = deployed['message']
    # Post update with error
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, None, False)
    posted_update = postStatusUpdate(deployment_update)
    print_red("Step 5 failed: deploy code, exiting...")
    sys.exit(step_notes)

### End Do the work
step_notes = deployed['message']
step_status = __status_success
step_action = None
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 5 completed: deploy code")
time.sleep(2);
################################################################################


############## STEP 666666666666666666666666666666666666666666666666666666666666
############## Check deployment
print_green("Step 6 started: check deployment")
step_notes = '';
time.sleep(between_steps_wait)
started = current_milli_time()
completed = current_milli_time()
### Do the work HERE
### First Check: pls.deployed exists or it already failed (pls.failed)
time.sleep(10);
loop_count = 0
deployed = os.path.isfile("/opt/wildfly/standalone/deployments/pls.ear.deployed")
deployed_failed = os.path.isfile("/opt/wildfly/standalone/deployments/pls.ear.failed")
# Enter loop until file found or we time out
while (deployed != True and deployed_failed != True and (loop_count < __deployed_loops)):
    time.sleep(__deployed_wait);
    print_yellow("Looping until .deployed or .failed files is there: " + str(loop_count))
    loop_count = loop_count + 1
    deployed_failed = os.path.isfile("/opt/wildfly/standalone/deployments/pls.ear.failed")
    deployed = os.path.isfile("/opt/wildfly/standalone/deployments/pls.ear.deployed")

print_yellow("Terminated .deployed loop")
# Did we find the .faield file? lets add that to the notes!
if deployed_failed:
    step_notes = "pls.ear.failed file found! Thats not good! "
    print_yellow(step_notes)
if deployed:
    step_notes = "check1=[pls.ear.deployed file found.] "
    print_yellow(step_notes)
else:
    print "Setting up failure update: ", step_notes
    ls_list = os.listdir("/opt/wildfly/standalone/deployments/")
    ls_list_str = ', '.join(ls_list)
    step_notes += "Deployments folder: " + ls_list_str
    step_status = __status_error
    step_action = None
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
    posted_update = postStatusUpdate(deployment_update)
    print_red("Exiting: " + step_notes)
    sys.exit(step_notes)

print_yellow(step_notes)
print_yellow("Starting second check...")
# Second Check: jboss process
grep = subprocess.check_output("ps -ef | grep java | grep jboss", shell=True)
if grep == "":
    step_notes += "No process found!  "
    step_status = __status_error
    step_action = None
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
    posted_update = postStatusUpdate(deployment_update)
    print_red("Exiting: " + step_notes)
    sys.exit(step_notes)
else:
    step_notes += "check2=[Process found: " + grep[:16] + "] "
print_yellow(step_notes)

print_yellow("Starting 3rd check...")
# Third Check: sys info call
url = "http://localhost:8080/Admin/sysinfo/Sysinfo.action?runCheck=com.gwn.plife.sysinfo.checks.AppVersionCheck&authUserName=gwnreporter&authUserPassword=ixNq^4nJJeX1"
# url = "http://www.google.com"
pls_status = "NOTOK"
try:
    r = requests.post(url)
    root = ET.fromstring(r.text)
    step_notes += "Sysinfo call status OK. Returned server version<" + root[0].text + ">"
    pls_status = root[0].get("status-code")
# pls_status = "OK"
except:
    e = sys.exc_info()[0]
    pls_status = "Exception: " + str(e)

if pls_status == "OK":
    print "check3=[Sysinfo call returned status OK.] "
else:
    step_notes += "Invalid status [" + pls_status + "] returned from sysinfo call. "
    step_status = __status_error
    step_action = None
    deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
    posted_update = postStatusUpdate(deployment_update)
    print_red("Exiting: " + step_notes)
    sys.exit(step_notes)

print_yellow(step_notes)
### End Do the work
step_status = __status_success
step_action = None
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 5 completed: deploy code")
time.sleep(2);
################################################################################


############## STEP 77777777777777777777777777777777777777777777777777777777777
############## Remove banneri
time.sleep(between_steps_wait)
started = current_milli_time()
completed = current_milli_time()
step_status = __status_success
step_notes = ""
step_action = "rem_banner"
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 6 completed: Banner removed in ESM")
time.sleep(2);
################################################################################


############## STEP 888888888888888888888888888888888888888888888888888888888888
############## Wrapping up
time.sleep(between_steps_wait)
started = current_milli_time()
completed = current_milli_time()
step_status = __status_success
step_notes = "Finishing process"
step_action = None
deployment_update = getDeploymentStatus(started, current_milli_time(), step_status, step_notes, step_action, False)
posted_update = postStatusUpdate(deployment_update)
__current_step += 1
print_green("Step 7 completed: wrapping up")
################################################################################

print_green("#################### Completed deployment!")
# We might need to complete de deployment ourselves