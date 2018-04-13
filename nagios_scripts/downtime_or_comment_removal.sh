#!/bin/sh
#Uncomment/Comment the appropriate lines below depending on if you are clearing downtime or comments
NOW='date +%s'

for line in `cat downtimeid_list.txt`;do
#for line in `cat commentid_list.txt`;do

#   echo "[$NOW] DEL_HOST_COMMENT;$line;$NOW" > /var/lib/nagios/rw/nagios.cmd
#   echo "[$NOW] DEL_SVC_COMMENT;$line;$NOW" > /var/lib/nagios/rw/nagios.cmd
   echo "[$NOW] DEL_SVC_DOWNTIME;$line;$NOW" > /var/lib/nagios/rw/nagios.cmd
   echo "[$NOW] DEL_HOST_DOWNTIME;$line;$NOW" > /var/lib/nagios/rw/nagios.cmd
   echo "Removed comment id and/or downtime id $line"

done
