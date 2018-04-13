#!/usr/bin/python2

from argparse import ArgumentParser, FileType
from fileinput import input
from json import dumps, loads
from httplib import HTTPSConnection
from re import search, MULTILINE
from subprocess import check_output
from sys import stdin


class Sysinf:

    @staticmethod
    def find_mac_ip():

        # For the unique identifier of this server, gather mac_eth0 and IP of eth0 and hash it
        eth0 = check_output(['/sbin/ip', 'addr', 'show', 'eth0'])
        s = search('link/ether (([0-9a-f]{2}:){5}[0-9a-f]{2}).*\n.*inet (([0-9]+\.){3}[0-9]+)', eth0, flags=MULTILINE)
        if s is not None:
            eth0_mac = s.group(1)
            eth0_ip = s.group(3)
            return (eth0_mac, eth0_ip)
        else:
            return None

    @staticmethod
    def push_to_sysinf(put_url, info):
        """
        Attempt to post the given URL to the central sysinf server. First, try directly.
        then try through local Squid proxy, then throught Squid on 'appserver.gwn', then
        give up.
        """
        headers = {'Content-Type': 'application/json'}
        sysinf_success = False
        info['sysinf_access'] = 'direct'
        json_info = dumps(info)

        try:
            # Try to send DIRECTLY to the new sysinf server
            sysinf = HTTPSConnection('sysinf.getwellnetwork.com', timeout=15)
            sysinf.request('PUT', put_url, json_info, headers)
            sysinf.getresponse()
            sysinf.close()
            sysinf_success = True
        except Exception as e:
            pass

        if not sysinf_success:
            try:
                # Try to send via LOCAL Squid port (if site enforces upstream proxy) to the new sysinf server
                info['sysinf_access'] = 'local-proxy'
                json_info = dumps(info)
                sysinf = HTTPSConnection('localhost', 3128, timeout=15)
                sysinf.set_tunnel('sysinf.getwellnetwork.com', 443)
                sysinf.request('PUT', put_url, json_info, headers)
                sysinf.getresponse()
                sysinf.close()
                sysinf_success = True
            except Exception as e:
                pass

        if not sysinf_success:
            try:
                # Try to send VIA APPSERVER to the new sysinf server
                info['sysinf_access'] = 'proxy'
                json_info = dumps(info)
                sysinf = HTTPSConnection('appserver.gwn', 3128, timeout=15)
                sysinf.set_tunnel('sysinf.getwellnetwork.com', 443)
                sysinf.request('PUT', put_url, json_info, headers)
                sysinf.getresponse()
                sysinf.close()
                sysinf_success = True
            except Exception as e:
                pass

    @staticmethod
    def send_server_info(info):

        (eth0_mac, eth0_ip) = Sysinf.find_mac_ip()
        put_url = '/server_info/store/{0}/{1}'.format(eth0_mac, eth0_ip)
        Sysinf.push_to_sysinf(put_url, info)

    @staticmethod
    def send_server_metrics(metrics):

        (eth0_mac, eth0_ip) = Sysinf.find_mac_ip()
        info = {
            'mac': eth0_mac,
            'ip': eth0_ip,
            'host_name': check_output(['/bin/hostname', '-f']).strip(),
            'metrics': metrics
        }
        put_url = '/server_metrics/store'
        Sysinf.push_to_sysinf(put_url, info)


if __name__ == '__main__':

    parser = ArgumentParser(description='SysInfo information pusher')
    parser.add_argument('--type', choices=['info','metrics'], required=True,
            help='what type of sysinf data to push')
    parser.add_argument('--infile', nargs='?', type=FileType('r'), default=stdin,
            help='where to read the sysinf data from; defaults to stdin')
    args = parser.parse_args()

    stdin_data = []
    for line in args.infile:
        stdin_data.append(line.strip())
    stdin_str = '\n'.join(stdin_data)

    try:
        stdin_dict = loads(stdin_str)
        if args.type == 'info':
            Sysinf.send_server_info(stdin_dict)
        elif args.type == 'metrics':
            Sysinf.send_server_metrics(stdin_dict)
        exit(0)
    except Exception as e:
        print 'FAILED TO SEND SERVER INFO: {0}'.format(e)
        exit(1)

