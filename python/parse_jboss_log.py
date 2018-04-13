#!/usr/bin/python2

# ----------------------------------------------------------------------------
# JBoss log parser. Scans through a rolling window of log entries in the JBoss
# server.log files and generates a report based on regular expressions that
# indicate different levels of "badness".

# $Id$
# ----------------------------------------------------------------------------

import traceback
import sys
import re
import os
import logging
import operator
import time
from optparse import OptionParser
from datetime import datetime, timedelta



# ----------------------------------------------------------------------------
# Define the regular expressions that indicate problems
# ----------------------------------------------------------------------------

# Regular expressions that should be considered critical
criticalRegex = {
                 'Out Of Memory'                : re.compile('java\.lang\.OutOfMemoryError'),
                 'JMS Disconnect'               : re.compile('JmsEventReceiver.* No more messages for you!$'),
                 'JDBC Exception'               : re.compile('org\.hibernate\.util.\JDBCException'),
                 'Configuration.xml problem'    : re.compile('(org\.apache\.xerces\.impl\.XMLErrorReporter|Unable to parse the XML file. Rejected file on disk renamed)')
}


# Regular expressions that we should be warned about
warningRegex = {
                'ClassCastException'            : re.compile('java\.lang\.ClassCastException'),
                'NullPointerException'          : re.compile('java\.lang\.NullPointerException'),
                'Curriculum Without Start Unit' : re.compile('Curriculum.*does not have Start Unit'),
                'SMTP Exceptions'               : re.compile('com\.sun\.mail\.smtp\.SMTPAddressFailedException'),
                'JEP Parser Exceptions'         : re.compile('com\.singularsys\.jep\.(parser\.)?ParseException'),
                'Printer Failure'               : re.compile('Unable to print to printer'),
                'GWN Task Problems'             : re.compile('com\.gwn\.plife\.task\.exception\.(\w)+')
}

# Pattern that matches any exception; for calculating the "exceptions per hour" (EPH)
anyException = re.compile('(([\w\$]+\.)+[A-Z][\w\$]*(Exception|Error|Failure))[^\w]')



# ----------------------------------------------------------------------------
# Define some constants
# ----------------------------------------------------------------------------

logRoot = '/opt/logs'
logName = 'server.log'
scanWindowHours = 24


# ----------------------------------------------------------------------------
# Find the first log line that is within the scan window 
# ----------------------------------------------------------------------------

def findFirstLine(logger, logFile, scanWindowStart, logTimePattern):
    
    skippedLines = 0
    for line in logFile:
        m = re.search(logTimePattern, line)
        if(m):
            lineDate = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
            if (lineDate < scanWindowStart):
                #logger.debug("   " + str(lineDate) + " < " + str(scanWindowStart))
                continue
            else:
                logger.debug("    Skipped " + str(skippedLines) + " lines in this file.")
                logger.debug("    Found first log entry within scan window: " + str(lineDate))
                return lineDate

        skippedLines += 1
        if (skippedLines%5000 == 0):
            logger.debug("    Skipped " + str(skippedLines) + " lines so far...")
            
    logger.debug("All lines scanned and nothing was found.")
            

# ----------------------------------------------------------------------------
# Parse a given log line with a given dictionary of regular expressions
# ----------------------------------------------------------------------------

def parseLine(logger, logLine, regexMap, matchCounters):
    
    l = logLine.strip()
    
    for (desc, regex) in regexMap.items():
        m = regex.search(l)
        
        if (m):            
            # Use the actual exception string plus the summary as key in the summary map
            key = m.group(0) + " (" + desc + ")"
            if(matchCounters.has_key(key)):
                matchCounters[key] += 1
            else:
                matchCounters[key] = 1  


# ----------------------------------------------------------------------------
# Print a sorted report of the given result dictionary
# ----------------------------------------------------------------------------
def printSortedReport(exceptionMatches, logTimeSpan, title, limit=None):
    
    if (len(exceptionMatches)<1):
        return
    
    print "-----------------------------------------------------------------------------"
    print title
    print "-----------------------------------------------------------------------------\n"

    sortedExceptions = sorted(exceptionMatches.iteritems(), key=operator.itemgetter(1), reverse=True)
    rowCount = 0;
    
    # Stupid old Python 2.6 does not have timedelta.total_seconds() yet...
    logTimeSpanHours = logTimeSpan.days * 24 + logTimeSpan.seconds / 3600.0

    print '   {0:>6}  {1:>7}  {2}'.format( "Count", "EPH", "Exception")
    print "   --------------------------------------------------------------------------"
    for (exception, count) in sortedExceptions:
        rowCount += 1
        eph = float(count) / float(logTimeSpanHours)
        print '   {0:>6}  {1:>7.1f}  {2}'.format( count, eph, exception)
        if (limit and rowCount>=limit):
            break
        
    print "\n\n"
            


# ----------------------------------------------------------------------------
# Script starts here
# ----------------------------------------------------------------------------

# Parse the command line options
parser = OptionParser()
parser.add_option("-d", "--debug", action="store_true", dest="debug",
                  help="Print extra debug messages during scan")
parser.add_option("-c", "--critical", dest="critical", type="int",
                  help="Critical threshold for EPH")
parser.add_option("-w", "--warn", dest="warning", type="int",
                  help="Warning threshold for EPH")
parser.add_option("-l", "--logroot", dest="logroot",
                  help="Alternative path to scan for the log files")
parser.add_option("-n", "--min-count", dest="min_count", type="int",
                  help="Minimum number of occurances before an exception is shown in 'Top 20'")
parser.add_option("-e", "--min-eph", dest="min_eph", type="float",
                  help="Minimum value for EPH before an exception is shown in 'Top 20'")
parser.add_option("-p", "--min-pls", dest="min_pls",
                  help="Minimum version of PLS to be present on localhost for scan, ex: 'R5_7_14'")

(options, args) = parser.parse_args()

logLevel = logging.WARN
if(options.debug):
    logLevel = logging.DEBUG

if(options.logroot):
    logRoot = options.logroot
    
# Configure logging
logging.basicConfig(level=logLevel, format='%(relativeCreated)d\t%(levelname)s\t%(message)s')
logger = logging.getLogger()

# Was a minimum PLS version given? Before we do anything, try to find out the PLS version.
if (options.min_pls):

    try:
        from httplib import HTTPConnection
        import urllib
        current_pls = None
        
        logger.debug("Checking PLS version on local server...")
        http = HTTPConnection('localhost', 8080, timeout=5)
        params = urllib.urlencode({'authUserName' : 'gwnreporter', 'authUserPassword' : 'ixNq^4nJJeX1', 'runCheck': 'com.gwn.plife.sysinfo.checks.AppVersionCheck'})
        headers = {"Content-type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        http.request("POST", "/Admin/sysinfo/Sysinfo.action", params, headers)
        response = http.getresponse()

        if (response.status == 200):
            data = response.read()
            m = re.search('<app-version>(.*)</app-version>', data, re.MULTILINE)
            if (m):
                current_pls = m.group(1)
            
        http.close()
        
        if (not current_pls or current_pls < options.min_pls):
            print "UNKNOWN: Unsupported version of PLS found: '" + str(current_pls) \
                + "' (need at least " + options.min_pls + ")"
            exit (3)
        else:
            logger.debug("Found PLS version on local server: " + current_pls)
            
    except Exception as e:
        print "UNKNOWN: Unable to determine PLS version: " + str(e) + "\n"
        traceback.print_exc(file=sys.stdout)
        exit (3)

# Set up a few variables
scanWindow = timedelta(hours=scanWindowHours)
scanWindowStart = datetime.now() - scanWindow
logger.debug("Scan window starts at " + str(scanWindowStart))
logSuffix = []
logTimePattern = '^([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}),'

# Count the matches
criticalMatches = {}
warningMatches = {}
allExceptionMatches = {}


# Generate an array of log suffixes
for i in range(20,0,-1):
    logSuffix.append('.' + str(i))
    
logSuffix.append('')

# Find the oldest logfile that has data within the scan window
logCount = 0

for s in range(0,len(logSuffix)):
    logFileName = logRoot + '/' + logName + logSuffix[s]
    
    if os.path.exists(logFileName):
        logCount +=1
        fileTime = datetime.fromtimestamp(os.path.getmtime(logFileName))
        logger.debug("File exists: '" + logSuffix[s] + "', time: " + str(fileTime) + ", in scan range: "
                     + str(fileTime>scanWindowStart))
        
        if (fileTime>scanWindowStart):
            logger.debug("Found oldest file that needs to be scanned: " + logSuffix[s])
            break

if (logCount<1):
    print "CRITICAL: Cannot find a single log file to parse"
    exit(2)
    

firstLogLineDate = None
totalLines = 0
returnValue = 0
scanStart = time.time()

# Now iterate over the files within the scan window and work on them
for s in range(s,len(logSuffix)):
    logFileName = logRoot + '/' + logName + logSuffix[s]
    logger.debug("Scanning log file " + logFileName + "...")
    
    try:
        logFile = open(logFileName, 'r')
        
        # Calculate how large our log time span is
        if (not firstLogLineDate):
            logLineDate = findFirstLine(logger, logFile, scanWindowStart, logTimePattern)
            
            # If no logLineDate was found in the log, skip this log and scan the next
            if (not logLineDate):
                logFile.close()
                continue
            
            firstLogLineDate = logLineDate
            logTimeSpan = datetime.now()-logLineDate
            logger.debug("Available log data spans: " + str(logTimeSpan))
        
            # Add a grace period of a few minutes, in case the log was quiet for a while
            if (firstLogLineDate-timedelta(minutes=10) > scanWindowStart):
                print "WARNING: The available log entries do not fill the scan window. Log data available for: " \
                            + str(logTimeSpan)
                returnValue = 1           
                

        for logLine in logFile:
            
            totalLines += 1
            
            # Parse the line for all critical exceptions
            parseLine(logger, logLine, criticalRegex, criticalMatches)
        
            # Parse the line for all warning exceptions
            parseLine(logger, logLine, warningRegex, warningMatches)
            
            # Parse the line for any exception
            m = anyException.search(logLine)
            if (m):
                if (allExceptionMatches.has_key(m.group(1))):
                    allExceptionMatches[m.group(1)] += 1
                else:
                    allExceptionMatches[m.group(1)] = 1
        
        logFile.close()
    except Exception as e:
        print "CRITICAL: Error parsing log file: " + str(e) + "\n"
        traceback.print_exc(file=sys.stdout)
        exit(2)

logger.debug("Total number of lines scanned: {0}".format(totalLines))
if totalLines < 100:
    print "CRITICAL: Less than 100 lines of eligible log entries found. Something is not right.\n"
    exit(2)

# Separate the logging output a bit
logger.debug("Generating report...\n\n")
scanDuration = time.time() - scanStart


# ----------------------------------------------------------------------------
# Generate the output report
# ----------------------------------------------------------------------------

returnValue = 0

# Find the highest EPH in the allExceptionMatches
highestEph = None
if (len(allExceptionMatches)>0):
    sortedAllExceptionMatches = sorted(allExceptionMatches.iteritems(), key=operator.itemgetter(1), reverse=True)
    highestEph = {
                  'count'       : sortedAllExceptionMatches[0][1],
                  'exception'   : sortedAllExceptionMatches[0][0],
                  'eph'         : float(sortedAllExceptionMatches[0][1] / float(logTimeSpan.days * 24 + logTimeSpan.seconds / 3600.0))
                  }
    

# If there are _any_ critical exceptions, the final result will be 'CRITICAL'
if (len(criticalMatches)>0):
    print "CRITICAL: Critical exceptions found in the log!\n\n"
    returnValue = 2

# If "-c" option was given, evaluate the highest EPH value for CRITICAL
elif (options.critical and highestEph and highestEph['eph']>=options.critical):
    print "CRITICAL: Highest number of 'exceptions per hour' exceeded critical threshold (" \
            + str(highestEph['eph']) + " " + highestEph['exception'] + " per hour)"
    returnValue = 2
    
# If "-w" option was given, evaluate the highest EPH value for WARNING
elif (options.warning and highestEph and highestEph['eph']>=options.warning):
    print "WARNING: Highest number of 'exceptions per hour' exceeded warning threshold (" \
            + str(highestEph['eph']) + " " + highestEph['exception'] + " per hour)"
    returnValue = 1
    
# If there are _any_ warning exceptions, the final result will be 'WARNING'   
elif (len(warningMatches)>0):
    print "WARNING: Dangerous exceptions found in the log! Please escalate to DEV.\n\n"
    returnValue = 1

else:
    print "OK: No exceptions or problems found in the logs"
    returnValue = 0
    

# Need a separator line between Nagios summary and rest of the report
print ""    
printSortedReport(criticalMatches, logTimeSpan, 'Critical Exceptions found:')
printSortedReport(warningMatches, logTimeSpan, 'Warning Exceptions found:')

# If display restrictions were given on the command line, purge the allExceptionMatches first
if (options.min_count or options.min_eph):
    
    # Okay, a bit repetitive to calculate this again here, but the script was a quick project ;-)
    logTimeSpanHours = logTimeSpan.days * 24 + logTimeSpan.seconds / 3600.0
    
    for key in allExceptionMatches.keys():
        
        if (options.min_count and allExceptionMatches[key] < options.min_count):
            del allExceptionMatches[key]
            continue
        
        if (options.min_eph):
            eph = float(allExceptionMatches[key]) / float(logTimeSpanHours)
            if (eph < options.min_eph):
                del allExceptionMatches[key]
                continue
        
printSortedReport(allExceptionMatches, logTimeSpan, 'Top 20 of all Exceptions found:', limit=20)

print "{0:<20} : {1:>20}".format("Scan window start", scanWindowStart.strftime("%Y-%m-%d %H:%M"))
print "{0:<20} : {1:>20}".format("Scan window span", str(scanWindow))
print "{0:<20} : {1:>20}".format("Scanned log data", str(logTimeSpan))
print "{0:<20} : {1:>20}".format("Total lines scanned", totalLines)
print "{0:<20} : {1:>20.2f} seconds".format("Scan time", scanDuration)
print "{0:<20} : {1:>20.2f} lines per second".format("Scan rate", totalLines / scanDuration)

# PLATSUP-16841: Always return "OK"
returnValue = 0
exit(returnValue)
