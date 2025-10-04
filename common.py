import hashlib #used to create SHA-256 hashes for verifying data integrity
import pickle
import logging   #used to track and log important events during execution
from enum import Enum  #used to create enumerations for message and command types
import os        #used to interact with the file system


CHUNK_SIZE = 512 * 1024  #each chunk is split into 512kb sizes
HEADER_SIZE = 1024     #size limit for message headers (to parse messages properly)
TRACKER_TIMEOUT = 60    #1 minute time...when a peer is considered inactive
KEEPALIVE_INTERVAL = 30  #seconds between keepalive messages
BUFFER_SIZE = 1024    #buffer size for sending/receiving UDP messages

TRACKER_IP = "127.0.0.1" #IP address where the tracker runs (localhost)
TRACKER_PORT = 9000 #port number for the tracker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

#MessageType defines types of messages exchanged
class MessageType(Enum):
    COMMAND = "command"  #used for commands like register, request, etc.
    DATA = "data"   #for sending actual file chunks
    CONTROL = "control"  #for responses like ACK or error messages

#CommandType defines all possible commands a peer can send
class CommandType(Enum):
    REGISTER = "register"  #seeder registering itself with the tracker
    KEEPALIVE = "keepalive"   #seeder notifying tracker it's still active
    REQUEST = "request"    #keecher asking tracker for available seeders
    GET = "get"    #leecher requesting a specific chunk of the file
    GET_COUNT = "get_count"
    BECOME_SEEDER = "become_seeder"  #leecher notifying tracker that it has become a seeder after download

#ControlType defines types of control responses that can be sent back
class ControlType(Enum):
    ACK = "ack"  #acknowledge that a message/command was received successfully
    ERROR = "error"
    PEER_LIST = "peer_list" #seeders in a list
    CHUNK_DATA = "chunk_data"
    CHUNK_COUNT = "chunk_count"

#Fucntion to create a message header
def create_header(message_type, command_type=None, control_type=None, **kwargs):
    header = {
        "message_type": message_type.value,
        "command_type": command_type.value if command_type else None,
        "control_type": control_type.value if control_type else None,
    }
    header.update(kwargs)
    return {k: v for k, v in header.items() if v is not None}#remove any None values to clean up

#Function to create a full message(HEADER + BODY)
def create_message(header, body=None):
    return pickle.dumps({"header": header, "body": body})#combine and serialize

#Function to parse/unpack a message
def parse_message(data):
    message = pickle.loads(data)#deserialize
    return message.get("header", {}), message.get("body")

def get_file_info(file_path):
    file_size = os.path.getsize(file_path)#get size of file in bytes
    chunk_count = (file_size + CHUNK_SIZE - 1) // CHUNK_SIZE  # Ceiling division
    return file_size, chunk_count

#Function to split a file into chunks and hashes
def split_file(file_path):
    chunks = [] #list to store chunks of file
    hashes = [] #list to store hash of each chunk (for verification)
    with open(file_path, 'rb') as f:#open file in binary read mode
        while True:
            chunk = f.read(CHUNK_SIZE)#read chunk of data
            if not chunk:#stop if no more data
                break
            chunks.append(chunk)
            hashes.append(compute_hash(chunk))
    return chunks, hashes

def compute_hash(data):
    if isinstance(data, str):#if data is a string convert to bytes
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()#return hexadecimal hash string
