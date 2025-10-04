import argparse
import threading
import os
import logging
import time
import socket
from datetime import datetime
from seeder import Seeder
from leecher import Leecher
import common
import customtkinter as ctk # needs to be installed before running peer.py
from ttkbootstrap import Style # needs to be installed before running peer.py
from tkinter import ttk, filedialog, messagebox


class Peer:

    def __init__(self, download_directory, host='127.0.0.1', port=None):
        self.download_directory = os.path.abspath(download_directory)
        os.makedirs(self.download_directory, exist_ok=True)
        self.host = host
        self.port = port or self._find_available_port()
        self.logger = logging.getLogger(f"Peer-{self.port}")
        self.logger.info(f"Peer at {self.host}:{self.port} | Downloads: {self.download_directory}")

        self.active_seeders = []  # List of Seeder instances
        self.downloads = {}  # {filename: Leecher instance}
        self.completed_downloads = {}  # {filename: {'completed_at': datetime, 'path': str}}
        self.running = True
        self.lock = threading.Lock()

        # Initialize GUI
        self.root = ctk.CTk()
        self.style = Style(theme='darkly')
        self.root.title("P2P File Sharing Peer")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.stop)

        self._setup_gui()

    def _setup_gui(self): # Building the GUI
        # Main frame
        main_frame = ctk.CTkFrame(self.root)
        main_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Seeding section
        seeding_frame = ctk.CTkFrame(main_frame)
        seeding_frame.pack(fill='x', padx=5, pady=5) # box containing files being seeded by the seeder in GUI

        ctk.CTkLabel(seeding_frame, text="Seeding Files", font=('Helvetica', 14, 'bold')).pack(anchor='w')

        self.seeding_listbox = ttk.Treeview(seeding_frame, columns=('File', 'Port'), show='headings', height=5)
        self.seeding_listbox.heading('File', text='File')
        self.seeding_listbox.heading('Port', text='Port')
        self.seeding_listbox.pack(fill='x', padx=5, pady=5)

        add_seed_button = ctk.CTkButton(seeding_frame, text="Add File to Seed", command=self._add_seed_file)
        add_seed_button.pack(pady=5)

        # Download section
        download_frame = ctk.CTkFrame(main_frame)
        download_frame.pack(fill='x', padx=5, pady=5)

        ctk.CTkLabel(download_frame, text="Download Files", font=('Helvetica', 14, 'bold')).pack(anchor='w')

        self.download_entry = ctk.CTkEntry(download_frame, placeholder_text="Enter file name to download")
        self.download_entry.pack(fill='x', padx=5, pady=5)

        download_button = ctk.CTkButton(download_frame, text="Start Download", command=self._start_download)  # download box in GUI
        download_button.pack(pady=5)

        # Progress section
        progress_frame = ctk.CTkFrame(main_frame)
        progress_frame.pack(fill='both', expand=True, padx=5, pady=5)

        ctk.CTkLabel(progress_frame, text="Download Progress", font=('Helvetica', 14, 'bold')).pack(anchor='w')

        self.progress_listbox = ttk.Treeview(progress_frame, columns=('File', 'Progress', 'Size'), show='headings',
                                             height=10)
        self.progress_listbox.heading('File', text='File')
        self.progress_listbox.heading('Progress', text='Progress')
        self.progress_listbox.heading('Size', text='Size')
        self.progress_listbox.pack(fill='both', expand=True, padx=5, pady=5)

        # Start updating GUI
        self._update_gui()

    def _update_gui(self):
        """Continually update the GUI in time intervals
        """
        if self.running:
            # Update seeding list
            self.seeding_listbox.delete(*self.seeding_listbox.get_children())
            for seeder in self._list_seeded_files(): # list of files being seeded by seeder
                self.seeding_listbox.insert('', 'end', values=(os.path.basename(seeder['path']), seeder['port']))

            # Update download progress
            self.progress_listbox.delete(*self.progress_listbox.get_children())
            for download in self._list_downloads_in_progress():
                self.progress_listbox.insert('', 'end', values=(download['name'], download['progress'], download['size_human']))

            self.root.after(1000, self._update_gui)

    def _add_seed_file(self):
        """Allows user to open a file for seeding anywhere on their device
        """
        file_path = filedialog.askopenfilename() # allows file browser to open up
        if file_path:
            if self._start_seeding_file(file_path):
                messagebox.showinfo("Success", f"Started seeding {os.path.basename(file_path)}")
            else:
                messagebox.showerror("Error", f"Failed to start seeding {os.path.basename(file_path)}")

    def _start_download(self):
        """Start Download button functionality
            handles user error with message boxes
        """
        file_name = self.download_entry.get().strip() # get file name from text box
        if file_name:
            self._download_file(file_name)
            messagebox.showinfo("Info", f"Download of {file_name} started.")
        else:
            messagebox.showwarning("Warning", "Please enter a file name to download.") # handles error if no file name entered

    def _find_available_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('', 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def start(self):
        self.root.mainloop()

    def stop(self):
        """When window is closed, end the life of the peer
        """
        if not self.running:  # dead already?
            return  # Already stopped
        self.running = False
        with self.lock:  # if it is alive, we terminate
            for seeder in self.active_seeders:
                seeder['seeder'].stop()
        self.logger.info("Peer stopped")
        if self.root:
            self.root.destroy()
            self.root = None  # Set root to None after destruction

    def _start_seeding_file(self, file_path, port=None):
        """Using the seeder, begin seeding the file.
            Calls the seeder class and runs it within its own thread
        """
        try:
            port = port or self._find_available_port()
            seeder = Seeder(file_path, host=self.host, listen_port=port)
            threading.Thread(target=seeder.start, daemon=True).start()
            with self.lock:
                self.active_seeders.append({'seeder': seeder, 'path': file_path})
            self.logger.info(f"Seeding {file_path} on port {port}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to seed {file_path}: {e}")
            return False

    def _download_file(self, file_name):
        """Calls the leecher class and runs its command line logs in another thread
         """
        with self.lock:
            if file_name in self.downloads: # check if file is already downloading currently
                self.logger.warning(f"Already downloading {file_name}")
                return
            leecher = Leecher(file_name, output_directory=self.download_directory, host=self.host, port=self.port)
            self.downloads[file_name] = leecher
        threading.Thread(target=self._download_thread, args=(file_name, leecher), daemon=True).start()
        self.logger.info(f"Download started for {file_name}")

    def _download_thread(self, file_name, leecher):
        """Updates the command line with information for the file being downloaded
        """
        try:
            if leecher.download_file():
                self.logger.info(f"Downloaded {file_name}")
                if leecher.verify_file():
                    self.logger.info(f"Verified {file_name}")
                    if leecher.start_seeding():
                        self.logger.info(f"Now seeding {file_name}")
                        with self.lock:
                            self.completed_downloads[file_name] = {
                                'completed_at': datetime.now(),
                                'path': os.path.join(self.download_directory, file_name)
                            }
                    else:
                        self.logger.error(f"Seeding failed for {file_name}")
                else:
                    self.logger.error(f"Verification failed for {file_name}")
            else:
                self.logger.error(f"Download failed for {file_name}")
        except Exception as e:
            self.logger.error(f"Error downloading {file_name}: {e}")
        finally:
            with self.lock:
                self.downloads.pop(file_name, None)

    def _list_seeded_files(self):
        """Provides a list of files that are being seeded by the user
        """
        with self.lock:
            return [{'path': seeder['path'], 'port': seeder['seeder'].listen_port} for seeder in self.active_seeders]

    def _list_downloads_in_progress(self):
        """Live progress of download
        """
        downloads = []
        with self.lock:
            for filename, leecher in self.downloads.items():
                downloaded = len(leecher.downloaded_chunks)
                total = leecher.total_chunks or 0
                progress = f"{(downloaded / total * 100):.1f}%" if total else "0%" # calculation of percentage of download
                downloads.append({
                    'name': filename,
                    'progress': progress,
                    'chunks': f"{downloaded}/{total}",
                    'size_human': self._format_size(leecher.file_size) if leecher.file_size else "0 B"
                })
        return downloads

    def _format_size(self, size_bytes):
        """Used to format the size of the bytes for downloads

            method used for simplicity and anti-redundancy
        """
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        elif size_bytes < 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def main():
    parser = argparse.ArgumentParser(description='P2P File Sharing Peer')
    parser.add_argument('--download-dir', default='./downloads', help='Directory for downloaded files')
    parser.add_argument('--host', default='127.0.0.1', help='Host IP address')
    parser.add_argument('--port', type=int, default=None, help='Port to listen on (random if not specified)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    peer = Peer(args.download_dir, host=args.host, port=args.port)
    try:
        peer.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        peer.stop()


if __name__ == '__main__':
    main()
