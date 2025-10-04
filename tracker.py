#IJ Masters, MSTISR001
#CS3 A1

import socket
import threading
import logging
import time
import common

class Tracker:

    def __init__(self, host=common.TRACKER_IP, port=common.TRACKER_PORT):
        """ Constructor for tracker class.
            Args:
                host: The host number from the common file; local host
                port: The port from the common file; random hardcoded port
        """
        self.host = host
        self.port = port
        self.logger = logging.getLogger("Tracker")
        self.seeders = {}  # {file_name: [ { 'host':..., 'port':..., 'last_seen':..., 'file_size':..., 'chunk_count':... }, ... ]}
        self.running = False  # flag for control
        self.lock = threading.Lock()
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP server initialised
        self.logger.info(f"Tracker initialized at {self.host}:{self.port}")  # CLI logging for status

    def start(self):
        """Starts the tracker[UDP server]
            cleanup is done in separate thread
            provides command line logs for updates on status of peers
        """
        self.socket.bind((self.host, self.port))
        self.running = True
        threading.Thread(target=self._cleanup, daemon=True).start()  # cleaning up list of inactive seeders runs on a separate thread
        self.logger.info(f"Tracker started on {self.host}:{self.port}")

        while self.running:
            try:
                data, addr = self.socket.recvfrom(common.BUFFER_SIZE)  # initial UDP client information/message
                threading.Thread(target=self._handle_message, args=(data, addr), daemon=True).start()  # message interpretaion done in separate thread
            except Exception as e:
                self.logger.error(f"Error receiving message: {e}")

        self.stop()

    def stop(self):
        """Close UDP server while terminating tracker.py"""
        self.running = False
        try:
            self.socket.close()
        except:
            pass
        self.logger.info("Tracker stopped")

    def _handle_message(self, data, addr):
        """Handles the messaging protocol created in the common file
            Args:
                data: contains the message received from the UDP client
                addr: address of UDP client
        """
        try:
            header, body = common.parse_message(data)  # splits message into header and body
            if header.get('message_type') == common.MessageType.COMMAND.value:
                cmd = header.get('command_type')
                if cmd in [common.CommandType.REGISTER.value, common.CommandType.BECOME_SEEDER.value]:
                    self._handle_register(header, addr)  # if client is requesting to become seeder, let it be
                elif cmd == common.CommandType.KEEPALIVE.value:
                    self._handle_keepalive(header, addr)  #  is the seeder still active?
                elif cmd == common.CommandType.REQUEST.value:
                    self._handle_request(header, addr)
                else:
                    self.logger.warning(f"Unknown command from {addr}: {cmd}")
            else:
                self.logger.warning(f"Invalid message type from {addr}")
        except Exception as e:
            self.logger.error(f"Error processing message from {addr}: {e}")

    def _handle_register(self, header, addr):
        """Registers a seeder with a certain file and adds them to the active seeder list for that file
            Args:
                header: message header from UDP client seeder
                addr: Address of UDP client seeder

        """
        file_name = header.get('file_name')
        host = header.get('host') or addr[0]
        port = header.get('port')
        file_size = header.get('file_size')
        chunk_count = header.get('chunk_count')
        if not file_name or not port:
            return

        seeder = {  # dictionary to store necessary seeder information received from client
            'host': host,
            'port': port,
            'last_seen': time.time(),
            'file_size': file_size,
            'chunk_count': chunk_count
        }
        with self.lock:  # synchronization lock; adds one seeder at a time to active list
            self.seeders.setdefault(file_name, [])
            for i, s in enumerate(self.seeders[file_name]):  # avoid adding the same seeder twice; if it exists, update the seeder information
                if s['host'] == host and s['port'] == port:
                    self.seeders[file_name][i] = seeder
                    break
            else:
                self.seeders[file_name].append(seeder)  # seeder added to active list

        self.logger.info(f"Registered seeder for '{file_name}': {host}:{port}")
        response = common.create_message(
            common.create_header(common.MessageType.CONTROL, control_type=common.ControlType.ACK)
        )
        self.socket.sendto(response, addr)  # send response to client to update client in regards to seeder registration

    def _handle_keepalive(self, header, addr):
        """Receives keepalive ping from client
            used in keeping the active seeders in the list
        """
        file_name = header.get('file_name')
        host = header.get('host') or addr[0]
        port = header.get('port')
        with self.lock:  # synchronization lock
            if file_name in self.seeders:
                for seeder in self.seeders[file_name]:
                    if seeder['host'] == host and seeder['port'] == port:
                        seeder['last_seen'] = time.time()
                        break

    def _handle_request(self, header, addr):
        """Handles the request sent by the leecher
            Args:
                header: message header from leecher UDP client
                addr: address of leecher UDP client
        """
        file_name = header.get('file_name')
        active_seeders = []
        file_size = 0
        chunk_count = 0
        with self.lock:  # synchronized lock; only one leecher request is carried out at a time
            if file_name in self.seeders and self.seeders[file_name]: #if file name is a match; prep the seeders information to be sent to leecher
                active_seeders = [(s['host'], s['port']) for s in self.seeders[file_name]]
                file_size = self.seeders[file_name][0]['file_size']
                chunk_count = self.seeders[file_name][0]['chunk_count']

        response_header = common.create_header(# message structure
            common.MessageType.CONTROL,
            control_type=common.ControlType.PEER_LIST,
            file_size=file_size,
            chunk_count=chunk_count
        )
        response_body = {'seeders': active_seeders}  # dictionary of active seeders in message to leecher
        self.logger.info(f"Sending {len(active_seeders)} seeders for '{file_name}' to {addr}")
        response = common.create_message(response_header, response_body) # message structure to send to leecher
        self.socket.sendto(response, addr) # message sent to leecher

    def _cleanup(self):
        """Checks if a seeder is still active
            if dead, then remove from active list
        """
        while self.running:
            time.sleep(common.TRACKER_TIMEOUT / 2)
            now = time.time()
            with self.lock:  # synchronization lock
                for file_name in list(self.seeders.keys()):
                    self.seeders[file_name] = [
                        s for s in self.seeders[file_name]
                        if now - s['last_seen'] < common.TRACKER_TIMEOUT  # iterate through list of seeders and compare last seen time with 30 seconds
                    ]
                    if not self.seeders[file_name]:
                        del self.seeders[file_name]
                        self.logger.info(f"Removed '{file_name}' (no active seeders)")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    tracker = Tracker()
    try:
        print(f"Starting tracker on {tracker.host}:{tracker.port}...")
        tracker.start()
    except KeyboardInterrupt:
        print("Tracker stopped by user")
    finally:
        tracker.stop()
