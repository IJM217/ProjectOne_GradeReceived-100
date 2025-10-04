import socket
import threading
import os
import logging
import random
from concurrent.futures import ThreadPoolExecutor #manages pool of thread to concurrently download chunks 
import common

class Leecher:

    def __init__(self, file_name, output_directory="./downloads", host='127.0.0.1', port=None):
        """ Constructor for Leecher class.
            Args: 
                file_name: file to be downloaded 
                output_directory: directory to store files and seed files once the leecher has them 
                host: host IP address 
                port: port for communciation, default is none 
        """
        self.file_name = file_name
        self.output_directory = os.path.abspath(output_directory)
        os.makedirs(self.output_directory, exist_ok=True)
        self.host = host
        self.port = port or self._find_available_port() #sets port if defined or generates a free port
        self.logger = logging.getLogger(f"Leecher-{self.port}") #logger for errors

        #key Leecher variables
        self.seeders = []              # List of available seeders [(ip, port), ...]
        self.downloaded_chunks = {}    # {chunk_index: chunk_data}
        self.chunk_hashes = {}         # {chunk_index: hash_value}
        self.total_chunks = 0          # total expected chunks for a file
        self.file_size = 0             # size of the desired file in bytes 

        self.download_complete = False # download status
        self.lock = threading.Lock()   # For thread-safe operations, ensures thread happen one at a time (such as download and file assembly)
        self.download_event = threading.Event()  # Signals download completion

        self.logger.info(f"Leecher initialized for file '{self.file_name}'")

    def _find_available_port(self):
        """Find an available port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port

    def request_seeders_from_tracker(self):
        """Contact the Tracker to get available seeders for the requested file.
            Method sends a request to the tracker using a UDP socket to recieve metadata on the available seeders 
            for a desired file. 

            Returns: 
                bool: True if seeders were successfully retrieved, False is no seeders were found or if an error occurred
            Raises: 
                Exception: If there is an issue with contacting the tracker or processing the response
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock: #set up TCP socket
                header = common.create_header(
                    common.MessageType.COMMAND, # inititation message (requesting seeders)
                    command_type=common.CommandType.REQUEST, 
                    file_name=self.file_name #request the file by name
                )
                sock.sendto(common.create_message(header), (common.TRACKER_IP, common.TRACKER_PORT))
                sock.settimeout(5) # 5 sec timeout for response 
                data, _ = sock.recvfrom(common.BUFFER_SIZE)
                response_header, response_body = common.parse_message(data)

                self.seeders = response_body.get('seeders', []) #extract the seeder's list
                self.total_chunks = response_header.get('chunk_count', 0) #extract the total # of chunks for the desired file
                self.file_size = response_header.get('file_size', 0) #extract file size 

                if not self.seeders:
                    self.logger.warning(f"No seeders available for {self.file_name}")
                    return False

                self.logger.info(f"Received {len(self.seeders)} seeders for {self.file_name}")
                self.logger.info(f"File has {self.total_chunks} chunks, total size: {self.file_size} bytes")
                return True

        except Exception as e:
            self.logger.error(f"Error requesting seeders: {e}")
            return False

    def download_chunk(self, seeder_ip, seeder_port, chunk_index):
        """
            Downloads a specified chunk from a seeder.
        
            Args:
                seeder_ip (str): IP address of the seeder.
                seeder_port (int): Port number of the seeder.
                chunk_index (int): Index of the chunk to be downloaded.
            
            Returns:
                bool: True if the chunk was successfully downloaded, False otherwise.
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock: #TCP connection
                sock.settimeout(10) # sec 10 timeout for conenction
                sock.connect((seeder_ip, seeder_port))
                header = common.create_header(
                    common.MessageType.COMMAND,
                    command_type=common.CommandType.GET,
                    chunk_index=chunk_index,
                    file_name=self.file_name
                )
                sock.sendall(common.create_message(header))

                response_data = b""
                chunk_received = False
                while not chunk_received:
                    data = sock.recv(common.CHUNK_SIZE + common.HEADER_SIZE)
                    if not data:
                        break
                    response_data += data
                    try:
                        response_header, chunk_data = common.parse_message(response_data)
                        chunk_received = True
                    except Exception:
                        continue

                if chunk_received:
                    with self.lock:
                        self.downloaded_chunks[chunk_index] = chunk_data
                        self.chunk_hashes[chunk_index] = response_header.get('hash')
                    self.logger.info(f"Downloaded chunk {chunk_index} from {seeder_ip}:{seeder_port}")
                    return True
                else:
                    self.logger.error(f"Failed to download chunk {chunk_index}")
                    return False

        except Exception as e:
            self.logger.error(f"Error downloading chunk {chunk_index} from {seeder_ip}:{seeder_port}: {e}")
            return False

    def download_file(self, max_concurrent_downloads=4):
        """
        Downloads all chunks of the file from available seeders.
        
        Args:
            max_concurrent_downloads (int): Max # of concurrent chunk downloads, default is 4 .
        
        Returns:
            bool: True if the file was successfully downloaded, False otherwise.
        """
        if not self.request_seeders_from_tracker():
            self.logger.error("Failed to get seeders from tracker. Download aborted.")
            return False

        if self.total_chunks == 0:
            self.logger.error("Invalid chunk count (0). Download aborted.")
            return False

        self.logger.info(f"Starting download of {self.file_name} with {max_concurrent_downloads} concurrent connections")
        chunks_to_download = list(range(self.total_chunks))

        # Use ThreadPoolExecutor for parallel downloads
        with ThreadPoolExecutor(max_workers=max_concurrent_downloads) as executor:
            while chunks_to_download and not self.download_complete: #until all chunks are downloaded 
                remaining_futures = []

                # Submit tasks for available chunks
                while chunks_to_download and len(remaining_futures) < max_concurrent_downloads: #download available chunks and at most the max # of chunks 
                    chunk_index = random.choice(chunks_to_download)
                    chunks_to_download.remove(chunk_index) #update the chunks_to_download, indicating the chunk has been processed 
                    if not self.seeders:
                        self.logger.error("No seeders available")
                        return False
                    seeder = random.choice(self.seeders) #randomly select a seeder to download a chunk from
                    future = executor.submit(self.download_chunk, seeder[0], seeder[1], chunk_index) #create new thread for the next download
                    remaining_futures.append((future, chunk_index))

                # Wait for all submitted tasks to complete
                for future, chunk_idx in remaining_futures:
                    success = future.result()  # This blocks until the future completes
                    if not success:
                        # If download failed, add chunk back to the queue
                        chunks_to_download.append(chunk_idx)

                # Check if all chunks have been downloaded
                with self.lock:
                    if len(self.downloaded_chunks) == self.total_chunks: #ensure all chunks are downloaded 
                        self.download_complete = True
                        self.logger.info("All chunks downloaded successfully")
                        break

        # Assemble the file if download is complete
        if self.download_complete:
            self.assemble_file()
            return True
        else:
            self.logger.error("Download incomplete")
            return False

    def assemble_file(self):
        """Assemble all downloaded chunks into the complete file. 
            Method verifies that all chunks have been sucessfully downloaded before reconstructing the original file by writing 
            the chunks in order. If chunks are missing, the assembly process fails 

            Returns: 
                bool: True if the file is successfully assembled, False otherwise 
            Logs: 
                - Error if the chunks are missing 
                - Error if an exception occurs during file writing 
                - Success message when the file is assembled
        """
        try:
            # handle missing chunks 
            if len(self.downloaded_chunks) != self.total_chunks: 
                self.logger.error(f"Cannot assemble file: missing chunks. Got {len(self.downloaded_chunks)}/{self.total_chunks}")
                return False

            output_path = os.path.join(self.output_directory, self.file_name)
            with open(output_path, 'wb') as out_file:
                for i in range(self.total_chunks):
                    chunk = self.downloaded_chunks.get(i)
                    if chunk:
                        out_file.write(chunk)
                    else:
                        self.logger.error(f"Missing chunk {i} during assembly")
                        return False

            self.logger.info(f"File assembled successfully: {output_path} ({os.path.getsize(output_path)} bytes)")
            self.download_event.set()
            return True

        except Exception as e:
            self.logger.error(f"Error assembling file: {e}")
            return False

    def verify_file(self):
        """Verify the integrity of the downloaded file by checking chunk hashes.
            Method reads the assembled file chunk by chunk, computes the SHA-256 hash for each chunk, 
            and compares it with the expected hash stoed in chunk_hashes. If any chunk hash doesn't match, the verification failes (corrupt or lost data)

            Returns:
                bool: True if all chunks pass the hash verification, False otherwise 
            Logs: 
                - Error if any chunk's hash doesn't match the expected hash 
                - Error if an exception occurs during file reading or hashing 
                - Success message when all chunks are correct
        """
        try:
            output_path = os.path.join(self.output_directory, self.file_name) 
            with open(output_path, 'rb') as file:
                #loop through all chunks
                for i in range(self.total_chunks): 
                    chunk = file.read(common.CHUNK_SIZE)
                    if common.compute_hash(chunk) != self.chunk_hashes.get(i):
                        self.logger.error(f"Hash mismatch for chunk {i}")
                        return False
            self.logger.info("File integrity verified successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error verifying file: {e}")
            return False

    def register_as_seeder(self):
        """Register with the tracker as a seeder for the downloaded file.
            Method registers with the tracker, indication that the leecher is available to seed the newly 
            downloaded file. 

            Returns: 
                - bool: True if registration was successful (recieved tracker ACK), False otherwise 
            Logs: 
                - Error message if registration fails or the ACK not recieved 
                - Error message if an exception occurs during registration
        """
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock: #UDP (client) connection
                header = common.create_header(
                    common.MessageType.COMMAND,
                    command_type=common.CommandType.BECOME_SEEDER,
                    file_name=self.file_name,
                    port=self.port, #starting hosting from this IP and port 
                    file_size=self.file_size,
                    chunk_count=self.total_chunks
                )
                sock.sendto(common.create_message(header), (common.TRACKER_IP, common.TRACKER_PORT))
                sock.settimeout(5)
                data, _ = sock.recvfrom(common.BUFFER_SIZE)
                response_header, _ = common.parse_message(data)

                if response_header.get('control_type') == common.ControlType.ACK.value:
                    self.logger.info(f"Successfully registered as seeder for {self.file_name}")
                    return True
                else:
                    self.logger.error("Failed to register as seeder")
                    return False

        except Exception as e:
            self.logger.error(f"Error registering as seeder: {e}")
            return False

    def start_seeding(self):
        """Start seeding the downloaded file.
            Method check if the file has been fully downloaded and exisits in the output dir, then 
            registers the file with the tracker and starts a Seeder creates a new Seeder object. 

            Returns: 
                -bool: True if seeding start successfulyl, False otherwise 
            
            Logs: 
                - Error if the file is not fully downloaded (awaiting chunks)
                - Error if the file is missing in the output dir 
                - Error if registration with the tracker fails (lost/no ACK)
        """
        from seeder import Seeder  # Import here to avoid circular imports
        try:
            if not self.download_complete:
                self.logger.error("Cannot start seeding: download not complete")
                return False

            file_path = os.path.join(self.output_directory, self.file_name)
            if not os.path.exists(file_path):
                self.logger.error(f"Cannot start seeding: file not found at {file_path}")
                return False

            if not self.register_as_seeder():
                self.logger.error("Failed to register with tracker as a seeder")
                return False

            seeder = Seeder(file_path, listen_port=self.port)
            threading.Thread(target=seeder.start, daemon=True).start()
            self.logger.info(f"Now seeding {self.file_name} on port {self.port}")
            return True

        except Exception as e:
            self.logger.error(f"Error starting seeding: {e}")
            return False

    def wait_for_download(self, timeout=None):
        """ Wait for the download to complete. 
            Helper method blocks the execution until the downloa event is set or the specified timeout is reached 

            Args: 
                - timeout : the max time (in sec) to wait for the download to complete, default is none (indefinte)
            Returns: 
                bool: True if the download completes within the timeout, False if the timeout is reached. 
        """
        return self.download_event.wait(timeout)

if __name__ == '__main__':
    import sys
    if len(sys.argv) != 2:
        print("Usage: python leecher.py <file_name>")
        sys.exit(1)

    file_name = sys.argv[1]
    leecher = Leecher(file_name)
    if leecher.download_file(max_concurrent_downloads=4):
        print(f"Download complete: {file_name}")
        if leecher.verify_file():
            print("File integrity verified")
            if leecher.start_seeding():
                print(f"Now seeding {file_name}")
        else:
            print("File verification failed")
    else:
        print("Download failed")
