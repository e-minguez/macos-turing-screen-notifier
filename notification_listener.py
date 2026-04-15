import os
import sqlite3
import plistlib
import time
import select
import subprocess
import json
import sys
import argparse
from datetime import datetime

# Mac Absolute Time (Jan 1 2001) to Unix Epoch (Jan 1 1970) offset
MAC_EPOCH_OFFSET = 978307200

def mac_time_to_datetime(mac_time):
    if mac_time is None: 
        return datetime.now()
    return datetime.fromtimestamp(mac_time + MAC_EPOCH_OFFSET)

class NotificationWatcher:
    def __init__(self, db_path, verbose=False):
        self.db_path = db_path
        self.wal_path = db_path + "-wal"
        self.verbose = verbose
        self.last_seen_rec_id = 0
        self.app_cache = {}  # Cache for app_id -> (App Name, Icon Path)
        self.ensure_db_paths()
        self.initialize_last_seen()

    def log_info(self, msg):
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] [INFO] {msg}", file=sys.stderr)

    def log_error(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"[{timestamp}] [ERROR] {msg}", file=sys.stderr)

    def ensure_db_paths(self):
        if not os.path.exists(self.db_path):
            self.log_error(f"Error: Database not found at {self.db_path}")
            sys.exit(1)

    def get_app_details(self, bundle_id):
        """Resolves Bundle ID to App Name and Icon Path using mdfind and Info.plist."""
        if bundle_id in self.app_cache:
            return self.app_cache[bundle_id]

        app_name = bundle_id
        icon_path = None

        try:
            # Find the app path using Spotlight metadata
            # Use 'c' for case-insensitive matching
            cmd = ['mdfind', f"kMDItemCFBundleIdentifier == '{bundle_id}'c"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            paths = result.stdout.strip().split('\n')
            
            if paths and paths[0]:
                app_path = paths[0]
                info_plist_path = os.path.join(app_path, 'Contents', 'Info.plist')
                
                if os.path.exists(info_plist_path):
                    with open(info_plist_path, 'rb') as f:
                        plist = plistlib.load(f)
                        
                        # Resolve Name: Try DisplayName -> Name -> Bundle ID
                        app_name = plist.get('CFBundleDisplayName') or plist.get('CFBundleName') or bundle_id
                        
                        # Resolve Icon
                        icon_file = plist.get('CFBundleIconFile')
                        if icon_file:
                            if not icon_file.endswith('.icns'):
                                icon_file += '.icns'
                            icon_path = os.path.join(app_path, 'Contents', 'Resources', icon_file)

        except Exception as e:
            # If anything fails, we just fallback to the bundle ID
            pass

        self.app_cache[bundle_id] = (app_name, icon_path)
        return app_name, icon_path

    def initialize_last_seen(self):
        """Initialize the last_seen_rec_id to the most recent notification's ID."""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Fetch the MAX rec_id (efficient on indexed PK)
            cursor.execute("SELECT MAX(rec_id) as max_id FROM record")
            row = cursor.fetchone()
            
            if row and row['max_id'] is not None:
                self.last_seen_rec_id = row['max_id']
                self.log_info(f"Initialized. Starting from Record ID: {self.last_seen_rec_id}")
            else:
                self.last_seen_rec_id = 0
                self.log_info("Database empty or no records found. Starting from 0.")
            conn.close()
        except sqlite3.Error as e:
            self.log_error(f"Database error during init: {e}")
        except Exception as e:
            self.log_error(f"Error initializing: {e}")

    def decode_notification_content(self, blob):
        """Decodes the binary plist blob from the database."""
        try:
            # plistlib.loads handles binary plist formats
            content = plistlib.loads(blob)
            
            # The structure of the plist is internal and can vary.
            # Usually, the meaningful content is in a 'req' (request) dictionary.
            req = content.get('req', {})
            
            title = ""
            subtitle = ""
            body = ""
            
            # Helper to safely extract strings
            def get_str(data, key):
                val = data.get(key, "")
                return str(val) if val is not None else ""

            if isinstance(req, dict):
                title = get_str(req, 'titl')
                subtitle = get_str(req, 'subt')
                body = get_str(req, 'body')
            else:
                # Fallback if 'req' isn't the structure
                title = get_str(content, 'titl')
                body = get_str(content, 'body')
            
            return title, subtitle, body
            
        except Exception as e:
            return "Error decoding", "", str(e)

    def check_for_new_notifications(self):
        """Queries the database for any records newer than self.last_seen_rec_id."""
        self.log_info(f"Checking for records > ID {self.last_seen_rec_id}...")
        try:
            start_time = time.time()
            # Open in read-only mode implicitly by just connecting
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Efficient query using indexed rec_id
            query = """
                SELECT r.rec_id, r.delivered_date, a.identifier, r.data 
                FROM record r 
                JOIN app a ON r.app_id = a.app_id 
                WHERE r.rec_id > ? 
                ORDER BY r.rec_id ASC
            """
            
            cursor.execute(query, (self.last_seen_rec_id,))
            rows = cursor.fetchall()
            
            query_time = time.time()
            if self.verbose:
                 self.log_info(f"Query completed in {query_time - start_time:.4f}s. Rows found: {len(rows)}")

            if rows:
                for row in rows:
                    rec_id = row['rec_id']
                    delivered_date = row['delivered_date']
                    app_id = row['identifier']
                    data_blob = row['data']
                    
                    # Update our high-water mark
                    if rec_id > self.last_seen_rec_id:
                        self.last_seen_rec_id = rec_id
                    
                    decode_start = time.time()
                    title, subtitle, body = self.decode_notification_content(data_blob)
                    
                    app_resolve_start = time.time()
                    app_name, icon_path = self.get_app_details(app_id)
                    app_resolve_end = time.time()

                    if self.verbose:
                         self.log_info(f"Processed rec_id {rec_id}: AppResolve={app_resolve_end - app_resolve_start:.4f}s, Decode={app_resolve_start - decode_start:.4f}s")
                    
                    # Construct JSON output
                    notification = {
                        "timestamp": mac_time_to_datetime(delivered_date).isoformat(),
                        "app_name": app_name,
                        "bundle_id": app_id,
                        "icon_path": icon_path,
                        "title": title,
                        "subtitle": subtitle,
                        "message": body
                    }
                    print(json.dumps(notification), flush=True)

            conn.close()
            
        except sqlite3.Error as e:
            self.log_error(f"SQL Error: {e}")
        except Exception as e:
            self.log_error(f"Error checking db: {e}")

    def watch(self):
        """Watches the DB directory and its files for changes using kqueue."""
        db_dir = os.path.dirname(self.db_path)
        self.log_info(f"Monitoring directory: {db_dir}")
        
        # Files to watch specifically
        files_to_watch = ['db', 'db-wal', 'db-shm']
        
        while True:
            fds = []
            try:
                kq = select.kqueue()
                kevents = []
                
                # We watch the directory itself to catch new file creations/rotations
                dir_fd = os.open(db_dir, os.O_RDONLY)
                fds.append(dir_fd)
                kevents.append(select.kevent(dir_fd, filter=select.KQ_FILTER_VNODE,
                                            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                                            fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND))

                # Watch the specific files
                for fname in files_to_watch:
                    fpath = os.path.join(db_dir, fname)
                    if os.path.exists(fpath):
                        fd = os.open(fpath, os.O_RDONLY)
                        fds.append(fd)
                        kevents.append(select.kevent(fd, filter=select.KQ_FILTER_VNODE,
                                                    flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE | select.KQ_EV_CLEAR,
                                                    fflags=select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME))

                self.log_info(f"Kqueue registered for {len(kevents)} targets. Waiting for events...")
                
                while True:
                    # Wait for event
                    events = kq.control(kevents, 1, None)
                    
                    for event in events:
                        target_name = "Unknown"
                        # Try to find which FD triggered
                        for i, fd in enumerate(fds):
                            if event.ident == fd:
                                if i == 0: target_name = "directory"
                                else: target_name = files_to_watch[i-1]
                                break

                        ev_flags = []
                        if event.fflags & select.KQ_NOTE_WRITE: ev_flags.append("WRITE")
                        if event.fflags & select.KQ_NOTE_EXTEND: ev_flags.append("EXTEND")
                        if event.fflags & select.KQ_NOTE_DELETE: ev_flags.append("DELETE")
                        if event.fflags & select.KQ_NOTE_RENAME: ev_flags.append("RENAME")
                        
                        self.log_info(f"Kernel event caught on {target_name}: {'|'.join(ev_flags)}")
                        
                        if event.fflags & (select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND):
                            self.check_for_new_notifications()
                        
                        if event.fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME):
                            self.log_info(f"Target {target_name} rotated/deleted. Re-acquiring...")
                            raise IOError("File rotation")

            except (OSError, IOError) as e:
                time.sleep(0.1)
            except KeyboardInterrupt:
                return
            finally:
                for fd in fds:
                    try: os.close(fd)
                    except: pass

def get_default_db_path():
    # Path to the Notification Center database
    # Valid for macOS Sequoia (15) and likely recent previous versions (Big Sur, Monterey, Ventura, Sonoma)
    return os.path.expanduser("~/Library/Group Containers/group.com.apple.usernoted/db2/db")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Watch macOS notifications and output them as JSON.")
    parser.add_argument("--db", type=str, default=get_default_db_path(), help="Path to the notification database file.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose output (status messages).")
    
    args = parser.parse_args()
    
    watcher = NotificationWatcher(db_path=args.db, verbose=args.verbose)
    watcher.watch()
