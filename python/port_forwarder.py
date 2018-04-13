#!/usr/bin/python2

import paramiko
import select
from SocketServer import BaseRequestHandler, ThreadingTCPServer
import threading

# Logging
import logging
log = logging.getLogger(__name__)


CHUNK_SIZE = 1024
""" The buffer size for sending data back and forth through the tunnel. """


class ForwardServer (ThreadingTCPServer):
    """
    Override a few attributes of the standard ThreadingTCPServer.
    """
    daemon_threads = True
    allow_reuse_address = True
    

class PortForwarder():
    """
    Establish a single SSH connection to a remote system and manage an arbitrary
    number of SSH tunnels to that remote system.
    
    Example for usage:
    
    from port_forwarder import PortForwarder
    p = PortForwarder(ssh_host='ssh_endpoint_host.com', username='myuser', password='mypasswd')
    p.start_port_forward(1234, 'somehost', 80, True)

    # Do the work...
    
    p.shutdown()
    
    """
    
    def __init__(self, ssh_host, username, password, ssh_port=22):
        """
        Initialize the SSH tunnel to the given host.
        """
        
        log.info("Initializing SSH tunnel to {0}:{1}".format(ssh_host, ssh_port))
        
        # A flag we can use to abort all port forwards while in transfer mode
        self.__shut_down = threading.Event()
        
        # Remember the tunnel threads we launch
        self.__tunnel_servers = []
        
        # Set up the TCP tunnel to the remote end
        self.__transport = paramiko.Transport((ssh_host, ssh_port))
        self.__transport.connect(hostkey=None, username=username, password=password, pkey=None)
        
        
    def start_port_forward(self, local_port, target_host, target_port,
                           local_address="",
                           abort_transfer_on_exit=False):
        
        log.info("Creating new SSH tunnel from local port {0}:{1} to {2}:{3}".format(local_address, local_port, target_host, target_port))
        
        # Make the transport available to the inner handler class
        my_transport = self.__transport
        
        # Make the event available in the inner handler class (if requested)
        if abort_transfer_on_exit == True:
            my_shut_down = self.__shut_down
        else:
            my_shut_down = None
            
        
        class ForwardHandler(BaseRequestHandler):
            '''
            '''            
            def handle(self):
                
                channel = my_transport.open_channel('direct-tcpip',
                                                 (target_host, target_port), (local_address,0))
        
                log.info("Entering tunnel data transfer loop")            
            
                while True:
                    r, w, x = select.select([channel, self.request], [], [])
                    
                    if channel in r:
                        data = channel.recv(CHUNK_SIZE)
                        if len(data) == 0:
                                channel.close()
                                break
                        else:
                            self.request.send(data)
                        
                    if self.request in r:
                        data = self.request.recv(CHUNK_SIZE)
                        if len(data) == 0:
                                break
                        else:
                            channel.send(data)
                            
                    if my_shut_down and my_shut_down.is_set():
                        log.info("Tunnel shutdown signal received. Closing tunnel.")
                        break                                        
                
                log.info("Shutting down resouces and port forwarder thread.")
                self.request.close()
                            
            
        # Starting up TCP server with the above inner class as its request handler
        s = ForwardServer((local_address,local_port), ForwardHandler)
        self.__tunnel_servers.append(s)
        t = threading.Thread(target=s.serve_forever)
        t.setDaemon(True)
        t.start()
        
        
    def shutdown(self):
        log.info("Shutting down all SSH tunnels")
        self.__shut_down.set()
        
        for s in self.__tunnel_servers:
            log.info("    -  Shutting down {0}".format(s))
            s.shutdown()

