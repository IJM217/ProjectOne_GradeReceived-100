# Welcome to our P2P BitTorrent-like System

## This project simulates a P2P file-sharing system similar to BitTorrent. It allows users to download and upload files using a tracker and seeder.

# Components Overview:

## Tracker (UDP Server)

> The **Tracker** manages the metadata of files and facilities peer discovery between clients and seeders

- Functionality:
  - Coordinates peer discovery
  - Maintains a list of available peers
  - Periodically removes inactive peers
  - Communicates with peers using UDP

## Seeder (TCP Server)

> The **Seeder** shares the file with peers by breaking it into chunks and serving those chunks via TCP.

- Functionality:
  - Hosts files and divies them into ~512KB chunks
  - Registers with the ** Tracker ** using UDP
  - Transmits chunks to leechers using TCP
  - Sends periodic "keepalive"/heartbeat messages to the tracker to indicate active status

## Leecher (TCP Client)

> The **Leecher** is the client that downloads files from the seeder, reconstructing the file as it downloads chunks in parallel.

- Functionality:
  - Contacts the ** Tracker ** via UDP to get a list of available peers
  - Establishes TCP connections with multiple seeders (using threads) to download the file in parallel
  - Reconstructs the complete file by downloading the chunk s
  - Automatically transitions to the ** Seeder ** role after downloading the file to continue sharing the file with other peers

## Additional Features

- File Integrity Verification: Files are verified using SHA-256 hashes to ensure data integrity during downloads
- Protocol Design:
  1. Message Types
     > The MessageType enum classifies messages based on their role in the communication:
- COMMAND: Messages related to control or commands (e.g., registering a seeder, requesting seeders).
- DATA: The actual file chunk data that is exchanged between peers.
- CONTROL: Messages that manage the communication process, such as acknowledgments (ACK) or error handling. 2. Command Types

  > The CommandType enum defines different commands that a peer can send to another peer or the tracker:

- REGISTER: A seeder registers itself with the tracker to announce availability.
- KEEPALIVE: Periodic messages sent from a seeder to the tracker to - signal that the seeder is still active.
- REQUEST: A leecher requests seeders from the tracker.
- GET: A leecher requests a specific file chunk from a seeder.
- GET_COUNT: A leecher queries the tracker for the total number of chunks in the file.
- BECOME_SEEDER: After successfully downloading a file, a leecher can become a seeder to share the file.

3. Control Types
   > The ControlType enum handles specific response types related to the control of communication:

- ACK: An acknowledgment response to confirm receipt of a message.
- ERROR: A response to indicate an error in processing a request.
- PEER_LIST: A list of seeders available for the requested file.
- CHUNK_DATA: Contains the data for a specific file chunk.
- CHUNK_COUNT: Contains the total number of chunks for the requested file.

4.  Header Creation and Message Serialization
    > The header structure ensures that each message can be identified and appropriately handled.

- ` create_header`: This function creates the header for a message, which includes:

- ` message_type`: Type of the message (e.g., command, data, control).
- `command_type` : Specifies the command (e.g., register, request).
- `control_type`: Specifies the control response (e.g., ACK, error). Any other optional parameters (passed as kwargs).

- `create_message`: This function serializes a message consisting of a header and an optional body into a byte format using pickle. This allows for easy transmission of the message over a network.

- `parse_message`: This function deserializes the incoming byte data into a header and body, making it easier to process and interpret the message at the receiving end.

# How to Run the Program:

#### Packages customtkinter and ttkbootstrap need to be installed in order to run GUI

Follow the steps below to run the program:

#### Step 1: Start the Tracker(only one is needed)

> Open a terminal and run the following command to start the tracker

    ```
    python tracker.py
    ```

#### Step 2: Start the Client

> Open another terminal window and run the following command to start the client:

    ```
    python peer.py
    ```

#### Step 3: Seed a File

1. Click on the "Add File to Seed" button.
2. Browse until you find your desired file.
3. The File will then be seeded for other peers to download in the network.

#### Step 4: To Download a File

> Type the file name in the text box and then click the "Start Download" button

1. The file will be available in the downloads folder created in the working directory
