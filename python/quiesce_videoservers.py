#!/usr/bin/env python2

'''
This script is supposed to facilitate setting video servers to quiescent or
to reactivate them again.

All available video servers must be listed in /etc/hosts and they must be named
"vlsX...". This script maintains a list of these video servers. THe user can
then specify which video servers to quiesce or to activate. This list of user
specified servers is matched up with the list of servers read from the hosts
file. The user can specify a simple name, e.g., vls1, as long as this name
matches only one of the servers from /etc/hosts. If multiple servers are matched
the user needs to specify a longer name, e.g., vls1.seft.

The resulting list of matched video servers is then paired with controllers
from Configuration.xml by the resolved IP address of the video server and the
IP field of the controller.
'''

# Make "print" a function, like in python3
from __future__ import print_function

import os
import sys
import re
import datetime
import socket
import argparse
import xml.etree.ElementTree
import shutil

class VlsServer(object):
    '''
    Represents one video server with a name.
    The IP address(es) for the video server can be requested but
    initially won't be looked up.
    '''

    def __init__(self, fqdn, ip=None):
        '''Initializes the server'''
        self._fqdn = fqdn
        if ip:
            self._ip_looked_up = True
            self._ip = [ip] # Not looked up yet
        else:
            self._ip_looked_up = False
            self._ip = None
        self._controllers = []

    def __repr__(self):
        '''Returns a printable representation of this object.'''
        rep = 'VlsServer(fqdn="{fqdn}"'.format(fqdn=self._fqdn)
        if self._ip_looked_up:
            rep += ', ip="{ip}"'.format(ip=self._ip)
        return rep + ')'

    def __eq__(self, other):
        '''
        Define equality test: two objects of this class are
        equal if their FQDN are equal.
        '''
        if isinstance(other, self.__class__):
            return self._fqdn == other._fqdn # pylint: disable=protected-access
        return NotImplemented

    def __ne__(self, other):
        '''
        Define non-equality test: two objects of this class are
        unequal if their FQDN are different.
        '''
        if isinstance(other, self.__class__):
            return self._fqdn != other._fqdn # pylint: disable=protected-access
        return NotImplemented

    def __hash__(self):
        '''Override the default hash behavior: return the hash of the FQDN.'''
        return hash(self._fqdn)

    def get_fqdn(self):
        '''Returns the FQDN of this server.'''
        return self._fqdn

    def get_ip_addresses(self):
        '''
        Returns the IP address associated with the name of this server.

        If the IP address has previously looked up that IP address is
        returned otherwise the IP address is looked up.
        '''
        if not self._ip_looked_up:
            self._ip = get_server_ip_addresses([self._fqdn])
            self._ip_looked_up = True
        return self._ip

    def add_matching_controllers(self, controllers):
        '''Add all matching controllers from controllers.'''
        for controller in controllers:
            # Check if any of the resolved addresses of the controller
            # matches the IP address of this VLS server
            ip_address = self.get_ip_addresses()
            for controller_ip_address in controller.get_ip_addresses():
                if controller_ip_address in ip_address:
                    # Found it!
                    self._controllers.append(controller)
                    break

    def get_controllers(self):
        '''Return the set of controllers associated with this server.'''
        return self._controllers




class Controller(object):
    '''Represents a controller in a controller group.'''

    def __init__(self, controller_node, quiescent_controllers):
        '''Initializes this controller with the controller node from media-meta-server.'''
        self._node = controller_node
        self._ip_field = controller_node.find('ip').text.lower()
        self._id = controller_node.find('id').text
        self._ip_looked_up = False
        self._ip_address = None
        self._is_quiescent = self._id in quiescent_controllers

    def __repr__(self):
        '''Returns a printable representation of this object.'''
        rep = 'Controller(id="{id}"'.format(id=self._id)
        if self._ip_looked_up:
            rep += ', ip={ip}'.format(ip=self._ip_address)
        return rep + ')'

    def get_id(self):
        '''Returns the ID of this controller'''
        return self._id

    def get_ip_addresses(self):
        '''
        Returns the IP address associated with the name of this controller.

        If the IP address has previously looked up that IP address is
        returned otherwise the IP address is looked up.
        '''
        if not self._ip_looked_up:
            self._ip_address = get_server_ip_addresses([self._ip_field])
            self._ip_looked_up = True
        return self._ip_address

    def is_quiescent(self):
        '''Returns a Truth about whether this controller is already quiescent.'''
        return self._is_quiescent

def ask_yes_no(msg, default_answer=None):
    '''
    Returns True or False based on:
      * If default_answer with a value of "yes" or "true": True
      * If default_answer with a value of "no" or "false": False
      * Otherwise asks the user the question msg and expects an answer of "yes", "true",
        "no" or "false" (case doesn't matter) and depending on that answer returns
        True or False. If the answer was not understood this function repeats the question.
    '''
    if default_answer == 'yes':
        return True
    if default_answer == 'no':
        return False
    while True:
        try:
            answer = raw_input('{msg}? [Y/n] '.format(msg=msg))
        except KeyboardInterrupt:
            return False
        if answer == '':
            return True
        lower_answer = answer.lower()
        if lower_answer in ['y', 'yes', 'true']:
            return True
        if lower_answer in ['n', 'no', 'false']:
            return False
        print('Sorry, I did not understand "{answer}"...'.format(answer=answer))

def get_server_ip_addresses(server_names):
    '''
    Lookup all IP addresses for a list of server names. The result is a set of
    IP addresses (no duplicates). If a name is already an IP address no lookup
    is performed but that IP address is one of those returned.
    '''

    for server_name in [server_name for server_name in server_names if server_name]:
        ips = set()
        try:
            socket_info_list = socket.getaddrinfo(server_name, 80)
            for ip_address in [socket_info[4][0] for socket_info in socket_info_list]:
                ips.add(ip_address)
        except socket.gaierror:
            pass
        return ips

def remove_quiescent_controllers(media_meta_server_node, controller_ids):
    '''
    Remove the <quiescent-controller> nodes matching the controller_ids list from the
    media_meta_server_node. Returns True if any node was removed.
    '''
    modified = False
    # Make a copy o fthe findall result and iterate over that.
    # Not sure if modyfing the tree would cause problems if we
    # iterated over the findall result directly.
    for node in list(media_meta_server_node.findall('./quiescent-controller')):
        if node.text in controller_ids:
            media_meta_server_node.remove(node)
            modified = True
    return modified

def add_quiescent_controllers(media_meta_server_node, controller_ids):
    '''
    Add <quiescent-controller> nodes for all controller_ids to the media_meta_server_node
    that currently don't have one.
    '''
    modified = False
    for controller_id in controller_ids:
        existing_quiescent_controllers = [element
                                          for element in (media_meta_server_node
                                                          .findall('./quiescent-controller'))
                                          if element.text == controller_id]
        if not existing_quiescent_controllers:
            element = xml.etree.ElementTree.Element('quiescent-controller')
            element.text = controller_id
            insert_before = media_meta_server_node.findall('./controller-groups')[-1]
            insert_before_index = media_meta_server_node.getchildren().index(insert_before) + 1
            media_meta_server_node.insert(insert_before_index, element)
            modified = True
    return modified

def backup_config_file(configuration_xml):
    '''
    Backup the config file and tell the user about it
    '''
    (base_path_and_file, extension) = os.path.splitext(configuration_xml)
    file_copy = ('{base}_{date}_{time}{ext}'
                 .format(base=base_path_and_file,
                         date=datetime.datetime.today().strftime('%Y-%m-%d'),
                         time=datetime.datetime.today().strftime('%H-%M-%S'),
                         ext=extension))
    shutil.copyfile(configuration_xml, file_copy)
    print('Backup written to "{backup_file}".'.format(backup_file=file_copy), file=sys.stderr)

def parse_args():
    '''
    Parse the command line args and return an object represenging them.
    '''

    def lower_arg(arg):
        '''
        Helper function for the ArgumentParser to convert an argument to lowercase
        '''
        return arg.lower()

    def yes_no_arg(arg):
        '''
        Helper function for the ArgumentParser that returns "yes" for the values
        "yes" or "true" and "no" for the values "no" or "false" (case doesn't matter).
        Raises an exception if arg is of any other value.
        '''
        arg = arg.lower()
        if arg in ['yes', 'true']:
            return 'yes'
        if arg in ['no', 'false']:
            return 'no'
        msg = 'expected one of "yes", "no", "true" or "false" but got "{arg}"'.format(arg=arg)
        raise argparse.ArgumentTypeError(msg)


    parser = argparse.ArgumentParser(description=('Tool to toggle quiescent mode of video'
                                                  ' controllers on appservers.'))
    parser.add_argument('-s', '--state',
                        default='on',
                        choices=['on', 'off'],
                        action='store',
                        dest='vls_active',
                        help=('specify if the video server(s) should be set to quiescent ("off") or'
                              ' active ("on")'))
    parser.add_argument('--config',
                        default=('/opt/wildfly/standalone/deployments/assets.war/WEB-INF/config'
                                 '/Configuration.xml'),
                        action='store',
                        dest='configuration_xml',
                        help='location of the Configuration.xml file if not in a standard location')
    parser.add_argument('-n', '--dry-run',
                        action='store_true',
                        dest='dry_run',
                        help='do not modify Configuration.xml, just print what would be done')
    parser.add_argument('--answer',
                        action='store',
                        type=yes_no_arg,
                        dest='default_answer',
                        help='batch mode: answer "yes" to any question')
    parser.add_argument('-l', '--list',
                        action='store_true',
                        dest='list_status',
                        help='List all controllers and their current status')
    parser.add_argument('vls_server',
                        nargs='*',
                        action='store',
                        type=lower_arg,
                        default=[],
                        help='list of video servers')
    return parser.parse_args()

def get_ipv4_hosts():
    '''
    Reads /etc/hosts and returns a list of (ip, hostname).
    Only the first hostname on a line is returned. Also,
    continuation lines are ignored.
    '''
    pattern = re.compile(r'((?:[0-9]{1,3}\.){3}[0-9]{1,3})\s(.+)')
    with open('/etc/hosts', 'r') as hosts_file:
        for line in hosts_file:
            result = re.match(pattern, line)
            if result:
                ip_address = result.group(1)
                yield ip_address, set(result.group(2).split())

def get_videoservers_from_hosts():
    '''
    Generator for a list of of video servers read from /etc/hosts.
    '''
    for ip_address, host_list in get_ipv4_hosts():
        host_list = [host.lower() for host in host_list if host.lower().startswith('vls')]
        if host_list:
            host = max(host_list, key=len)
            server = VlsServer(host, ip=ip_address)
            yield server

def get_video_servers_from_names(names, video_servers):
    '''
    Matches up video servers from get_video_servers_from_hosts with the list of given
    names.
    The result is a dict with the name as the key and a list of VideoServer objects
    found for that name.
    '''
    result = {}
    for name in names:
        # First try to match up the exact name
        servers = []
        for video_server in video_servers:
            if name == video_server.get_fqdn():
                servers.append(video_server)
        # If nothing was found, try again but check if a video servers
        # FQDN starts with the requested name + '.'
        if not servers:
            part_name = '{name}.'.format(name=name)
            for video_server in video_servers:
                if video_server.get_fqdn().startswith(part_name):
                    servers.append(video_server)
        result[name] = servers
    return result

def get_all_controllers(media_meta_server_node):
    '''Returns a list of all controllers from the media meta server node.'''
    quiescent_controllers = set([element.text
                                 for element
                                 in media_meta_server_node.findall('./quiescent-controller')])
    controller_nodes = media_meta_server_node.findall('./controller-groups/controllers')
    return [Controller(controller_node, quiescent_controllers)
            for controller_node in controller_nodes]

def get_available_video_servers(controllers):
    '''
    Generates a list of available video servers (from /etc/hosts).
    Each of these servers will be initialized with a list of Controller
    objects for that server.
    '''
    available_video_servers = list(get_videoservers_from_hosts())
    for vls_server in available_video_servers:
        vls_server.add_matching_controllers(controllers)
    return available_video_servers


def validate_vls_servers(vls_servers, vls_servers_map, available_video_servers):
    '''
    Takes the list of requested server names (vls_servers) and checks if
    each has an entry with zero, or more than one VlsServer and prints an
    error about that condition.
    If no errors occurred returns a list of VlsServers, None otherwise.
    '''

    result = set()
    have_errors = False
    for name in vls_servers:
        if not vls_servers_map[name]:
            print('ERROR: Could not find a video server for "{name}"'.format(name=name),
                  file=sys.stderr)
            have_errors = True
        elif len(vls_servers_map[name]) > 1:
            sample_name = '.'.join(vls_servers_map[name][0].get_fqdn().split('.')[:-1])
            print(('ERROR: Multiple video servers found for "{name}": {vs_list}\n'
                   '       (You probably need to be more specific, e.g., specify {sample})')
                  .format(name=name,
                          vs_list=', '.join([vs.get_fqdn() for vs in vls_servers_map[name]]),
                          sample=sample_name), file=sys.stderr)
            have_errors = True
        else:
            server = vls_servers_map[name][0]
            if server in result:
                print('ERROR: "{name}" found more than once'.format(name=name), file=sys.stderr)
                have_errors = True
            else:
                result.add(server)
    if not have_errors:
        return result
    print('Available video servers:', file=sys.stderr)
    for video_server in available_video_servers:
        print(' * {name}: {ip}'.format(name=video_server.get_fqdn(),
                                       ip=', '.join(video_server.get_ip_addresses())),
              file=sys.stderr)


def validate_controllers(vls_servers, controllers):
    '''
    Goes through the list of video servers and checks the matched controllers
    for sanity.  The function returns a list of warnings that should
    be presented to the user.
    '''
    dangling_controller_ids = list([controller.get_id() for controller in controllers])
    warnings = []
    for vls_server in vls_servers:
        found_controllers = vls_server.get_controllers()
        if not found_controllers:
            warnings.append('WARNING: No matching controller found for {vls_server}'
                            .format(vls_server=vls_server.get_fqdn()))
        else:
            if len(found_controllers) > 1:
                warnings.append(('WARNING: Multiple controllers found for {vls_server}:'
                                 ' {controller_names}')
                                .format(vls_server=vls_server.get_fqdn(),
                                        controller_names=', '.join([controller.get_id()
                                                                    for controller
                                                                    in found_controllers])))
            for controller in found_controllers:
                dangling_controller_ids.remove(controller.get_id())
    for controller_id in dangling_controller_ids:
        warnings.append('WARNING: Controller {controller_id} has no video server'
                        .format(controller_id=controller_id))
    return warnings

def get_controllers_to_modify(vls_servers, make_active):
    '''
    Returns the list of controllers that should be modified. This method may
    print a warning for every controller that belongs to more than one
    server.
    '''
    controller_ids = []
    for vls_server in vls_servers:
        found_controllers = vls_server.get_controllers()
        for controller in found_controllers:
            controller_id = controller.get_id()
            if controller_id in controller_ids:
                print('WARNING: controller {controller_id} found more than once'
                      .format(controller_id=controller_id), file=sys.stderr)
            elif make_active:
                if controller.is_quiescent():
                    controller_ids.append(controller_id)
                else:
                    print('NOTE: {controller_id} already active'
                          .format(controller_id=controller_id), file=sys.stderr)
            elif not controller.is_quiescent():
                controller_ids.append(controller_id)
            else:
                print('NOTE: {controller_id} already quiescent'
                      .format(controller_id=controller_id), file=sys.stderr)
    return controller_ids

def choose_servers(available_video_servers, available_controllers, opts):
    '''
    Present a list of video servers to the user and let her chhoose which ones to
    operate on.
    '''
    from dialog import Dialog

    d = Dialog()
    current_status = []
    warnings = []
    for vs in available_video_servers:
        controllers = vs.get_controllers()
        if controllers:
            for controller in controllers:
                current_status.append((controller.get_id(),
                                       vs.get_fqdn(),
                                       0 if controller.is_quiescent() else 1))
        else:
            warnings.append('WARNING: No controller found for {vls_server}'
                            .format(vls_server=vs.get_fqdn()))
    for warning in validate_controllers(available_video_servers, available_controllers):
        warnings.append(warning)

    if not current_status:
        warnings.append(('ERROR: No controller found for any of the'
                         ' video servers {video_servers}.')
                        .format(video_servers=', '
                                .join([vs.get_fqdn() for vs in available_video_servers])))
        d.msgbox('\n'.join(warnings))
        return None, None

    if warnings:
        d.msgbox('\n'.join(warnings), width=0, height=0)
    code, requested_active_controller_ids = d.checklist(('Please choose which controllers'
                                                         ' should be active:'),
                                                        choices=current_status)
    if code != 0:
        return None, None
    activate_controller_ids = []
    quiesce_controller_ids = []
    for vs in available_video_servers:
        for controller in vs.get_controllers():
            controller_id = controller.get_id()
            if controller.is_quiescent():
                if controller_id in requested_active_controller_ids:
                    activate_controller_ids.append(controller_id)
            else:
                if controller_id not in requested_active_controller_ids:
                    quiesce_controller_ids.append(controller_id)
    return activate_controller_ids, quiesce_controller_ids

def servers_from_args(available_video_servers, controllers, opts):
    '''
    Constructs two lists of controller IDs
      * IDs of controllers to quiesce, and
      * IDs of controllers to activate
    and returns the tupe (list to activate, list to quiesce).

    If there are controllers to activate/quiesce ask_yes_no is being used to confirm
    the action.

    Note that this method currently returns a tuple where one of the two items is None.
    '''
    warnings = validate_controllers(available_video_servers, controllers)
    for warning in warnings:
        print(warning, file=sys.stderr)

    for vls_server in available_video_servers:
        for controller in vls_server.get_controllers():
            print('INFO: controller for {vls_server}: {controller_name}'
                  .format(vls_server=vls_server.get_fqdn(),
                          controller_name=controller.get_id()), file=sys.stderr)

    video_server_map = get_video_servers_from_names(opts.vls_server, available_video_servers)
    vls_servers = validate_vls_servers(opts.vls_server, video_server_map, available_video_servers)

    if vls_servers:
        controller_ids = get_controllers_to_modify(vls_servers, opts.vls_active == 'on')

        if controller_ids:
            print('INFO: Controllers to be {action} to quiescent list: {controller_ids}'
                  .format(action='removed from' if opts.vls_active == 'on' else 'added to',
                          controller_ids=', '.join(controller_ids)), file=sys.stderr)
            if ask_yes_no('\nContinue and apply changes', opts.default_answer):
                if opts.vls_active == 'on':
                    return controller_ids, None
                return None, controller_ids
        else:
            print('INFO: All controllers are already {new_state}, nothing to do.'
                  .format(new_state='active' if opts.vls_active == 'on' else 'quiescent'),
                  file=sys.stderr)

    return None, None

def list_status(video_servers, controllers):
    '''
    List the current status of all controllers.
    '''
    controller_status = []
    for vs in video_servers:
        controllers = vs.get_controllers()
        if controllers:
            for controller in controllers:
                controller_status.append('{vls}\t{controller}\t{status}'
                                         .format(vls=vs.get_fqdn(),
                                                 controller=controller.get_id(),
                                                 status='quiescent' if controller.is_quiescent()
                                                 else 'active'))
        else:
            print('WARNING: No controller found for {vls_server}'
                  .format(vls_server=vs.get_fqdn()),
                  file=sys.stderr)
    if controller_status:
        print('\n'.join(controller_status))
    else:
        print(('ERROR: No controller found for any of the'
               ' video servers {video_servers}.')
              .format(video_servers=', '
                      .join([vs.get_fqdn() for vs in video_servers])),
              file=sys.stderr)

def main(opts):
    '''
    Main code
    '''
    config_tree = xml.etree.ElementTree.parse(opts.configuration_xml)

    media_meta_server_node = config_tree.findall('./media-meta-server')[0]

    controllers = get_all_controllers(media_meta_server_node)
    available_video_servers = get_available_video_servers(controllers)
    if not available_video_servers:
        print('No video servers found in /etc/hosts, cannot continue!', file=sys.stderr)
        sys.exit(0)
    if opts.list_status:
        list_status(available_video_servers, controllers)
        sys.exit(0)
    activate_controller_ids, quiesce_controller_ids = (
        (servers_from_args if opts.vls_server
         else choose_servers)(available_video_servers, controllers, opts))

    if activate_controller_ids:
        remove_quiescent_controllers(media_meta_server_node, activate_controller_ids)
    if quiesce_controller_ids:
        add_quiescent_controllers(media_meta_server_node, quiesce_controller_ids)
    if activate_controller_ids or quiesce_controller_ids:
        backup_config_file(opts.configuration_xml)
        config_tree.write(opts.configuration_xml,
                          encoding='utf-8',
                          xml_declaration=True,
                          method='xml')

if __name__ == '__main__':
    main(parse_args())
