import os
import json
import datetime
import threading
import time
import uuid
import re
from flask import Flask, request, jsonify, send_from_directory
import tracker

app = Flask(__name__, static_folder='static', static_url_path='')

# Ensure directories are initialized
tracker.init_directories()

# Global lock for crawler execution to prevent concurrent overlapping checks
crawl_lock = threading.Lock()

def bg_scheduler():
    """Background scheduler thread that runs checks every minute."""
    print("Background scheduler daemon started.")
    while True:
        try:
            with crawl_lock:
                tracker.run_tracker()
        except Exception as e:
            print(f"Error in background scheduler: {e}")
        time.sleep(60)

# Start background thread
scheduler_thread = threading.Thread(target=bg_scheduler, daemon=True)
scheduler_thread.start()

def slugify(text):
    """Convert text to a URL-friendly slug."""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\-]', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')

@app.route('/')
def serve_index():
    """Serve main HTML dashboard."""
    return app.send_static_file('index.html')

@app.route('/api/monitors', methods=['GET'])
def get_monitors():
    """API endpoint to get monitors config."""
    return jsonify(tracker.load_monitors())

@app.route('/api/monitors', methods=['POST'])
def add_or_edit_monitor():
    """API endpoint to add a new monitor or update an existing one."""
    data = request.json
    if not data or 'name' not in data or 'url' not in data:
        return jsonify({'error': 'Name and URL are required.'}), 400

    monitors = tracker.load_monitors()
    monitor_id = data.get('id')

    if monitor_id:
        # Edit existing
        monitor = next((m for m in monitors if m['id'] == monitor_id), None)
        if not monitor:
            return jsonify({'error': f"Monitor with ID '{monitor_id}' not found."}), 404
    else:
        # Create new
        slug = slugify(data['name'])
        # Ensure slug is unique
        existing_ids = {m['id'] for m in monitors}
        monitor_id = slug
        counter = 1
        while monitor_id in existing_ids:
            monitor_id = f"{slug}-{counter}"
            counter += 1
            
        monitor = {
            'id': monitor_id,
            'last_checked': None,
            'last_changed': None,
            'status': 'pending',
            'last_error': None
        }
        monitors.append(monitor)

    # Populate config fields
    monitor['name'] = data['name'].strip()
    monitor['url'] = data['url'].strip()
    monitor['active'] = data.get('active', True)
    monitor['check_interval_mins'] = int(data.get('check_interval_mins', 60))
    monitor['sensitivity'] = data.get('sensitivity', 'medium')
    monitor['min_char_diff'] = int(data.get('min_char_diff', 0))
    monitor['include_selectors'] = data.get('include_selectors', '').strip()
    monitor['ignore_selectors'] = data.get('ignore_selectors', '').strip()

    tracker.save_monitors(monitors)
    return jsonify({'success': True, 'monitor': monitor, 'monitors': monitors})

@app.route('/api/monitors/<monitor_id>', methods=['DELETE'])
def delete_monitor(monitor_id):
    """API endpoint to delete a monitor and clean its archive data."""
    monitors = tracker.load_monitors()
    monitor = next((m for m in monitors if m['id'] == monitor_id), None)
    if not monitor:
        return jsonify({'error': f"Monitor with ID '{monitor_id}' not found."}), 404

    # Remove from list
    monitors = [m for m in monitors if m['id'] != monitor_id]
    tracker.save_monitors(monitors)

    # Note: We keep the archive folder in data/archive/<id> to prevent accidental data loss,
    # but the config is deleted.
    return jsonify({'success': True, 'monitors': monitors})

@app.route('/api/check', methods=['POST'])
def force_check():
    """API endpoint to force check all active monitors or a specific one."""
    data = request.json or {}
    monitor_id = data.get('id')
    
    # Run the crawl check inside a lock to prevent concurrent collisions
    with crawl_lock:
        if monitor_id:
            monitors = tracker.load_monitors()
            monitor = next((m for m in monitors if m['id'] == monitor_id), None)
            if not monitor:
                return jsonify({'error': f"Monitor with ID '{monitor_id}' not found."}), 404
            
            print(f"Force checking single monitor: {monitor['name']}")
            tracker.check_single_monitor(monitor)
            tracker.save_monitors(monitors)
        else:
            print("Force checking all active monitors")
            tracker.run_tracker(force_all=True)

    return jsonify({'success': True, 'monitors': tracker.load_monitors()})

@app.route('/api/history/<monitor_id>', methods=['GET'])
def get_history(monitor_id):
    """API endpoint to retrieve history log of changes for a monitor."""
    archive_dir = os.path.join(tracker.DATA_DIR, 'archive', monitor_id)
    history_file = os.path.join(archive_dir, 'history.json')
    
    if not os.path.exists(history_file):
        return jsonify([])
        
    try:
        with open(history_file, 'r') as f:
            history = json.load(f)
            return jsonify(history)
    except Exception as e:
        return jsonify({'error': f"Failed to load history: {e}"}), 500

@app.route('/api/diff/<monitor_id>/<timestamp>', methods=['GET'])
def get_diff(monitor_id, timestamp):
    """API endpoint to generate and return visual line diff data between a version and its predecessor."""
    archive_dir = os.path.join(tracker.DATA_DIR, 'archive', monitor_id)
    history_file = os.path.join(archive_dir, 'history.json')
    
    if not os.path.exists(history_file):
        return jsonify({'error': 'No history found for this monitor.'}), 404
        
    try:
        with open(history_file, 'r') as f:
            history = json.load(f)
    except Exception as e:
        return jsonify({'error': f"Failed to read history log: {e}"}), 500
        
    # Find matching version
    idx = -1
    for i, entry in enumerate(history):
        if entry['timestamp'] == timestamp:
            idx = i
            break
            
    if idx == -1:
        return jsonify({'error': f"Version with timestamp '{timestamp}' not found."}), 404
        
    entry = history[idx]
    current_filepath = os.path.join(archive_dir, entry['filename'])
    if not os.path.exists(current_filepath):
        return jsonify({'error': f"Snapshot file '{entry['filename']}' not found in archive."}), 404
        
    with open(current_filepath, 'r') as f:
        current_text = f.read()
        
    # Load previous content
    previous_text = ""
    if idx > 0:
        prev_entry = history[idx - 1]
        prev_filepath = os.path.join(archive_dir, prev_entry['filename'])
        if os.path.exists(prev_filepath):
            with open(prev_filepath, 'r') as f:
                previous_text = f.read()
                
    # Calculate line-by-line diff details
    old_lines = previous_text.splitlines()
    new_lines = current_text.splitlines()
    
    ndiff = list(difflib.ndiff(old_lines, new_lines))
    
    diff_data = []
    old_line_no = 1
    new_line_no = 1
    
    for line in ndiff:
        prefix = line[:2]
        content = line[2:]
        
        if prefix == '  ': # Unchanged
            diff_data.append({
                'type': 'unchanged',
                'old_line': old_line_no,
                'new_line': new_line_no,
                'text': content
            })
            old_line_no += 1
            new_line_no += 1
        elif prefix == '- ': # Removed
            diff_data.append({
                'type': 'removed',
                'old_line': old_line_no,
                'new_line': None,
                'text': content
            })
            old_line_no += 1
        elif prefix == '+ ': # Added
            diff_data.append({
                'type': 'added',
                'old_line': None,
                'new_line': new_line_no,
                'text': content
            })
            new_line_no += 1
        elif prefix == '? ': # Character level hints
            continue
            
    return jsonify({
        'timestamp': timestamp,
        'summary': entry['changes_summary'],
        'ratio': entry.get('ratio', 1.0),
        'added': entry.get('added', 0),
        'removed': entry.get('removed', 0),
        'diff': diff_data,
        'current_text': current_text,
        'previous_text': previous_text
    })

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """API endpoint to load SMTP settings (with password redacted)."""
    settings = {
        'smtp_host': '',
        'smtp_port': 587,
        'smtp_user': '',
        'smtp_pass': '',  # Redacted
        'smtp_secure': True,
        'email_from': '',
        'email_to': '',
        'has_password': False
    }
    
    if os.path.exists(tracker.CONFIG_FILE):
        try:
            with open(tracker.CONFIG_FILE, 'r') as f:
                config = json.load(f)
                settings['smtp_host'] = config.get('smtp_host', '')
                settings['smtp_port'] = config.get('smtp_port', 587)
                settings['smtp_user'] = config.get('smtp_user', '')
                settings['smtp_secure'] = config.get('smtp_secure', True)
                settings['email_from'] = config.get('email_from', '')
                settings['email_to'] = config.get('email_to', '')
                if config.get('smtp_pass'):
                    settings['has_password'] = True
        except Exception as e:
            print(f"Error loading config.json: {e}")
            
    # Also check if override is in environment
    if os.getenv('SMTP_HOST'):
        settings['smtp_host'] = os.getenv('SMTP_HOST')
        settings['smtp_port'] = int(os.getenv('SMTP_PORT', 587))
        settings['smtp_user'] = os.getenv('SMTP_USER')
        settings['smtp_secure'] = os.getenv('SMTP_SECURE', 'true').lower() == 'true'
        settings['email_from'] = os.getenv('EMAIL_FROM')
        settings['email_to'] = os.getenv('EMAIL_TO')
        settings['has_password'] = bool(os.getenv('SMTP_PASS'))
        settings['env_overridden'] = True

    return jsonify(settings)

@app.route('/api/settings', methods=['POST'])
def save_settings():
    """API endpoint to save SMTP configuration."""
    data = request.json
    if not data:
        return jsonify({'error': 'No configuration data provided.'}), 400
        
    config = {}
    if os.path.exists(tracker.CONFIG_FILE):
        try:
            with open(tracker.CONFIG_FILE, 'r') as f:
                config = json.load(f)
        except Exception:
            pass
            
    # Update fields
    config['smtp_host'] = data.get('smtp_host', '').strip()
    config['smtp_port'] = int(data.get('smtp_port', 587))
    config['smtp_user'] = data.get('smtp_user', '').strip()
    config['smtp_secure'] = data.get('smtp_secure', True)
    config['email_from'] = data.get('email_from', '').strip()
    config['email_to'] = data.get('email_to', '').strip()
    
    # Only update password if a new one is typed
    new_pass = data.get('smtp_pass', '').strip()
    if new_pass:
        config['smtp_pass'] = new_pass
        
    try:
        with open(tracker.CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f"Failed to save settings file: {e}"}), 500

@app.route('/api/test-email', methods=['POST'])
def test_email():
    """API endpoint to send a test email using saved settings."""
    smtp_config = tracker.get_smtp_config()
    # If client sends temporary credentials for testing, merge them
    client_data = request.json or {}
    if client_data:
        # Check if we should merge unsaved changes for the test
        if not smtp_config:
            smtp_config = {}
        for key in ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_pass', 'email_from', 'email_to', 'smtp_secure']:
            config_key = key.replace('smtp_', '') if 'smtp_' in key else key
            if key in client_data and client_data[key]:
                if key == 'smtp_port':
                    smtp_config['port'] = int(client_data[key])
                else:
                    smtp_config[config_key] = client_data[key]
                    
        # Fill missing values from files if any
        stored = tracker.get_smtp_config() or {}
        for k, v in stored.items():
            if k not in smtp_config or not smtp_config[k]:
                smtp_config[k] = v

    if not smtp_config or not all(k in smtp_config for k in ['host', 'port', 'user', 'pass', 'from', 'to']):
        return jsonify({'error': 'SMTP Configuration is incomplete.'}), 400
        
    # Send test email
    msg = MIMEMultipart('alternative')
    msg['Subject'] = "[Page Tracker] Test Notification Email"
    msg['From'] = smtp_config['from']
    msg['To'] = smtp_config['to']
    
    body = f"Hello! This is a test email sent from your Webpage Change Tracker backend.\n\nYour SMTP configuration is working correctly!\nSent at: {datetime.datetime.now().isoformat()}"
    msg.attach(MIMEText(body, 'plain'))
    
    try:
        if smtp_config.get('secure', True):
            server = smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port'], timeout=15)
        else:
            server = smtplib.SMTP(smtp_config['host'], smtp_config['port'], timeout=15)
            server.starttls()
            
        server.login(smtp_config['user'], smtp_config['pass'])
        server.sendmail(smtp_config['from'], [smtp_config['to']], msg.as_string())
        server.quit()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': f"Failed to send email: {e}"}), 500

@app.route('/api/test-selectors', methods=['POST'])
def test_selectors():
    """API endpoint to run BeautifulSoup text extraction on a URL for testing selector accuracy."""
    data = request.json
    if not data or 'url' not in data:
        return jsonify({'error': 'URL is required.'}), 400
        
    url = data['url'].strip()
    include_selectors = data.get('include_selectors', '').strip()
    ignore_selectors = data.get('ignore_selectors', '').strip()
    
    try:
        preview_text = tracker.fetch_page_content(url, include_selectors, ignore_selectors)
        lines = preview_text.splitlines()
        word_count = len(preview_text.split())
        char_count = len(preview_text)
        
        # Show first 100 lines for the preview
        preview_lines = lines[:100]
        truncated = len(lines) > 100
        
        return jsonify({
            'success': True,
            'word_count': word_count,
            'char_count': char_count,
            'line_count': len(lines),
            'preview': "\n".join(preview_lines),
            'truncated': truncated
        })
    except Exception as e:
        return jsonify({'error': f"Fetch failed: {e}"}), 500

if __name__ == '__main__':
    # Default to port 5001 to avoid common macOS AirPlay Receiver conflicts on port 5000
    port = int(os.getenv('PORT', 5001))
    # Listen on all network interfaces for local access
    app.run(host='0.0.0.0', port=port, debug=False)
