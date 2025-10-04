

import socket     #for network communication
import threading
import logging     #Logging for keeping track of what's happening
import os, sys   #for interacting with files and system
import common

#Seeder class to seed a file to other peers who request it
class Seeder:
    def __init__(self, file_path, tracker_host=common.TRACKER_IP, tracker_port=common.TRACKER_PORT,
                 host='127.0.0.1', listen_port=None):
        self.file_path = os.path.abspath(file_path) #converts the file path to an absolute path
        self.file_name = os.path.basename(file_path) #get the file name
        self.tracker_host = tracker_host #get the IP address of the tracker to register the seeder
        self.tracker_port = tracker_port #tracker port number
        self.host = host #IP address the seeder will list on.
        self.listen_port = listen_port or self._find_available_port() #if there isn't a provided prt find an available one
        self.logger = logging.getLogger(f'Seeder-{self.listen_port}')
        self.running = False #flag to show if its running
        self.shutdown_event = threading.Event() #used to stop background threads when needed

        #Checking if file exists and error if it doesn't
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"File not found: {self.file_path}")

        self.file_size, self.chunk_count = common.get_file_info(self.file_path)
        self.chunks, self.hashes = common.split_file(self.file_path)

        #Create TCP and UDP sockets for communication
        self.tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) #allows reuse of address
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.logger.info(f"Seeder ready for '{self.file_name}' ({self.file_size} bytes, {self.chunk_count} chunks)")

    def _find_available_port(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('', 0)) #bind to any free port
        port = sock.getsockname()[1]
        sock.close() #close temporary socket
        return port

    #Function to start seeding process
    def start(self):
        if not self._register_with_tracker():#always have to register seeder with tracker first
            return False

        #start listening for peer connections
        self.tcp_socket.bind((self.host, self.listen_port))
        self.tcp_socket.listen(5)#allow up to 5 connections
        self.running = True
        threading.Thread(target=self._send_keepalive, daemon=True).start()
        self.logger.info(f"Seeder started on {self.host}:{self.listen_port} for file '{self.file_name}'")

        #Main loop to handle incoming connections
        while self.running and not self.shutdown_event.is_set():
            self.tcp_socket.settimeout(1.0)#timeout so we can check if we should stop
            try:
                client_socket, client_addr = self.tcp_socket.accept()
                threading.Thread(target=self._handle_client, args=(client_socket, client_addr), daemon=True).start()
            except socket.timeout:
                continue #timeout reached, check loop condition again

        #Stop everything when loop exits
        self.stop()
        return True

    def stop(self):
        self.running = False
        self.shutdown_event.set()
        self.tcp_socket.close()
        self.udp_socket.close()
        self.logger.info("Seeder stopped")

    #Function to register with tracker so other peers know we are seeding this file
    def _register_with_tracker(self):
        header = common.create_header(
            common.MessageType.COMMAND,
            command_type=common.CommandType.REGISTER,
            file_name=self.file_name,
            host=self.host,
            port=self.listen_port,
            file_size=self.file_size,
            chunk_count=self.chunk_count
        )
        #create a message using the header we prepared
        message = common.create_message(header)


        #Basically telling the tracker I have this file and I'm available to share it
        self.udp_socket.sendto(message, (self.tracker_host, self.tracker_port))#sending the message to the tracker using UDP (User Datagram Protocol)
        self.udp_socket.settimeout(5)

        try:
            #waiting to receive a response from the tracker.
            response, _ = self.udp_socket.recvfrom(common.BUFFER_SIZE)
            response_header, _ = common.parse_message(response)

            #checking if the response type is CONTROL and if it contains an ACK
            success = (response_header.get('message_type') == common.MessageType.CONTROL.value and
                       response_header.get('control_type') == common.ControlType.ACK.value)

            if success:
                self.logger.info(f"Registered with tracker for file '{self.file_name}'")
            return success
        except:
            return False #failed to register

    #keepalive messages to tracker to say we are still online
    def _send_keepalive(self):
        while self.running and not self.shutdown_event.is_set():
            header = common.create_header(
                common.MessageType.COMMAND,
                command_type=common.CommandType.KEEPALIVE,
                file_name=self.file_name,
                host=self.host,
                port=self.listen_port
            )
            message = common.create_message(header)
            self.udp_socket.sendto(message, (self.tracker_host, self.tracker_port))
            self.shutdown_event.wait(common.KEEPALIVE_INTERVAL)

    #Function to handle each peer connection
    def _handle_client(self, client_socket, client_addr):
        try:
            #setting a timeout of 30 seconds on the connection with the peer and if the peer takes too long to respond, we stop waiting
            client_socket.settimeout(30)
            data = client_socket.recv(common.HEADER_SIZE)#getting request


            if not data:#if no data was received stop here
                return
            header, _ = common.parse_message(data)

            #Checking if the received message is a COMMAND type.
            #COMMAND means the peer is asking for something
            if header.get('message_type') == common.MessageType.COMMAND.value:
                command_type = header.get('command_type')
                if command_type == common.CommandType.GET.value:#if peer is asking for a specific chunk
                    self._send_chunk(header.get('chunk_index'), client_socket)#send requested chunk
                elif command_type == common.CommandType.GET_COUNT.value:#if peer is asking how many chunks this file has
                    self._send_chunk_count(client_socket) #send chunk count
        finally:
            client_socket.close()

    def _send_chunk(self, chunk_index, client_socket):
        if chunk_index is not None and 0 <= chunk_index < self.chunk_count:
            chunk = self.chunks[chunk_index]
            chunk_hash = self.hashes[chunk_index]
            response_header = common.create_header(
                common.MessageType.CONTROL,
                control_type=common.ControlType.CHUNK_DATA,
                chunk_index=chunk_index,
                chunk_size=len(chunk),
                hash=chunk_hash
            )
            message = common.create_message(response_header, chunk)
            client_socket.sendall(message)
            self.logger.info(f"Sent chunk {chunk_index} ({len(chunk)} bytes)")
        else:
            self._send_error(client_socket, f"Invalid chunk index: {chunk_index}")

    def _send_chunk_count(self, client_socket):
        response_header = common.create_header(
            common.MessageType.CONTROL,
            control_type=common.ControlType.CHUNK_COUNT,
            file_name=self.file_name,
            file_size=self.file_size,
            chunk_count=self.chunk_count
        )
        message = common.create_message(response_header)
        client_socket.sendall(message)
        self.logger.info(f"Sent chunk count: {self.chunk_count}")

    def _send_error(self, client_socket, error_message):
        error_header = common.create_header(
            common.MessageType.CONTROL,
            control_type=common.ControlType.ERROR,
            error_message=error_message
        )
        client_socket.sendall(common.create_message(error_header))



if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python seeder.py <file_path>")
        sys.exit(1)
    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    try:
        seeder = Seeder(file_path)
        seeder.start()
    except KeyboardInterrupt:
        print("Seeder stopped by user")
    except Exception as e:
        print(f"Error starting seeder: {e}")
