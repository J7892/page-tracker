import os
import sys
import json
import datetime
import difflib
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load env variables from .env if present
load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
MONITORS_FILE = os.path.join(DATA_DIR, 'monitors.json')
CONFIG_FILE = os.path.join(DATA_DIR, 'config.json')

def init_directories():
    """Ensure data directories exist."""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(MONITORS_FILE):
        with open(MONITORS_FILE, 'w') as f:
            json.dump([], f, indent=2)

def load_monitors():
    """Load monitors list from file."""
    init_directories()
    try:
        with open(MONITORS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading monitors: {e}")
        return []

def save_monitors(monitors):
    """Save monitors list to file."""
    init_directories()
    try:
        with open(MONITORS_FILE, 'w') as f:
            json.dump(monitors, f, indent=2)
    except Exception as e:
        print(f"Error saving monitors: {e}")

def get_smtp_config():
    """Retrieve SMTP configuration from Environment or config.json."""
    # First priority: Environment variables
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = os.getenv('SMTP_PORT')
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASS')
    email_from = os.getenv('EMAIL_FROM')
    email_to = os.getenv('EMAIL_TO')
    smtp_secure = os.getenv('SMTP_SECURE', 'true').lower() == 'true'

    # Second priority: config.json
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, email_from, email_to]):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    smtp_host = smtp_host or config.get('smtp_host')
                    smtp_port = smtp_port or config.get('smtp_port')
                    smtp_user = smtp_user or config.get('smtp_user')
                    smtp_pass = smtp_pass or config.get('smtp_pass')
                    email_from = email_from or config.get('email_from')
                    email_to = email_to or config.get('email_to')
                    if 'smtp_secure' in config:
                        smtp_secure = config.get('smtp_secure')
            except Exception as e:
                print(f"Error loading config.json: {e}")

    # Validate
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass, email_from, email_to]):
        return None

    # Auto-resolve secure connection protocol based on standard port behaviors to prevent configuration hangs
    try:
        port_num = int(smtp_port)
        if port_num == 587:
            smtp_secure = False
        elif port_num == 465:
            smtp_secure = True
    except Exception:
        pass

    return {
        'host': smtp_host,
        'port': int(smtp_port),
        'user': smtp_user,
        'pass': smtp_pass,
        'from': email_from,
        'to': email_to,
        'secure': smtp_secure
    }

def format_json_data(data):
    """Recursively formats JSON data into clean, readable text lines for diffing."""
    lines = []
    
    if isinstance(data, dict):
        for k, v in data.items():
            # Skip noise fields like analytic IDs, paths, trackers
            if k in ["path", "google_analytics", "pluralDelimiter", "suppressDeprecationErrors", "rcmp_stats", "theme", "webpack"]:
                continue
            
            # If the value is a string that looks like serialized JSON, try to parse it
            if isinstance(v, str) and (v.strip().startswith('[') or v.strip().startswith('{')):
                try:
                    parsed_v = json.loads(v)
                    v = parsed_v
                except Exception:
                    pass
            
            if isinstance(v, (dict, list)):
                sub_text = format_json_data(v)
                if sub_text.strip():
                    lines.append(f"\n--- {k} ---")
                    lines.append(sub_text)
            else:
                lines.append(f"{k}: {v}")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            sub_text = format_json_data(item)
            if sub_text.strip():
                lines.append(f"\n[Item #{i+1}]")
                lines.append(sub_text)
    else:
        if data is not None:
            return str(data)
        
    return "\n".join(lines).strip()

def clean_text(text):
    """Normalize whitespace and clean up line endings."""
    lines = [line.strip() for line in text.splitlines()]
    # Remove empty lines
    cleaned_lines = []
    for line in lines:
        if line:
            cleaned_lines.append(line)
        elif cleaned_lines and cleaned_lines[-1] != "":
            cleaned_lines.append("")
    return "\n".join(cleaned_lines).strip()

def fetch_page_content(url, include_selectors=None, ignore_selectors=None):
    """Fetch website HTML and parse content with BS4 using selectors."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }
    
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    html = response.text
    soup = BeautifulSoup(html, 'html.parser')
    
    # 0. Extract JSON data from script tags before decomposing them
    json_contents = []
    from urllib.parse import urljoin
    
    # Special handler for Prime Minister of Canada (pm.gc.ca) news list which loads via AJAX
    if "pm.gc.ca" in url.lower() and ("/news" in url.lower() or "/nouvelles" in url.lower()):
        lang_prefix = "/fr/" if "/fr/" in url.lower() else "/en/"
        ajax_path = f"{lang_prefix}views/ajax"
        ajax_url = urljoin(url, ajax_path)
        payload = {
            "view_name": "news",
            "view_display_id": "page_1",
            "view_args": "",
            "page": 0
        }
        try:
            ajax_headers = headers.copy()
            ajax_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
            ajax_headers["X-Requested-With"] = "XMLHttpRequest"
            ajax_res = requests.post(ajax_url, headers=ajax_headers, data=payload, timeout=20)
            if ajax_res.ok:
                ajax_text = ajax_res.text.strip()
                if ajax_text.startswith("<textarea>") and ajax_text.endswith("</textarea>"):
                    ajax_text = ajax_text[10:-11].strip()
                ajax_data = json.loads(ajax_text)
                for cmd in ajax_data:
                    if cmd.get("command") == "insert" and cmd.get("data"):
                        view_html = cmd["data"]
                        view_soup = BeautifulSoup(view_html, 'html.parser')
                        for el in view_soup(["script", "style", "noscript", "svg", "iframe", "img"]):
                            el.decompose()
                        clean_view_text = view_soup.get_text()
                        if clean_view_text.strip():
                            view_tag = soup.new_tag("div")
                            view_tag.string = f"\n--- PM News Feed ---\n" + clean_view_text.strip()
                            json_contents.append(view_tag)
        except Exception as ex:
            print(f"Error fetching PM news AJAX view: {ex}")

    for script in soup.find_all("script"):
        stype = script.get("type", "")
        if stype in ["application/json", "application/ld+json", "application/settings+json", "drupal-settings-json"] or "json" in stype.lower():
            if script.string:
                try:
                    data = json.loads(script.string)
                    formatted_text = format_json_data(data)
                    if formatted_text.strip():
                        # Create a container div with the formatted JSON content
                        json_tag = soup.new_tag("div")
                        json_tag.string = formatted_text
                        json_contents.append(json_tag)
                        
                    # Detect and resolve Drupal Views AJAX endpoints
                    if isinstance(data, dict) and "views" in data:
                        views_config = data["views"]
                        ajax_path = views_config.get("ajax_path")
                        ajax_views = views_config.get("ajaxViews", {})
                        
                        if ajax_path and ajax_views:
                            ajax_url = urljoin(url, ajax_path)
                            for view_key, view_params in ajax_views.items():
                                view_name = view_params.get("view_name")
                                view_display_id = view_params.get("view_display_id")
                                view_args = view_params.get("view_args", "")
                                
                                payload = {
                                    "view_name": view_name,
                                    "view_display_id": view_display_id,
                                    "view_args": view_args,
                                    "page": 0
                                }
                                
                                try:
                                    ajax_headers = headers.copy()
                                    ajax_headers["Accept"] = "application/json, text/javascript, */*; q=0.01"
                                    ajax_headers["X-Requested-With"] = "XMLHttpRequest"
                                    ajax_res = requests.post(ajax_url, headers=ajax_headers, data=payload, timeout=20)
                                    if ajax_res.ok:
                                        ajax_text = ajax_res.text.strip()
                                        if ajax_text.startswith("<textarea>") and ajax_text.endswith("</textarea>"):
                                            ajax_text = ajax_text[10:-11].strip()
                                        ajax_data = json.loads(ajax_text)
                                        for cmd in ajax_data:
                                            if cmd.get("command") == "insert" and cmd.get("data"):
                                                view_html = cmd["data"]
                                                view_soup = BeautifulSoup(view_html, 'html.parser')
                                                
                                                for el in view_soup(["script", "style", "noscript", "svg", "iframe", "img"]):
                                                    el.decompose()
                                                    
                                                clean_view_text = view_soup.get_text()
                                                if clean_view_text.strip():
                                                    view_tag = soup.new_tag("div")
                                                    view_tag.string = f"\n--- Drupal Dynamic View: {view_name} ---\n" + clean_view_text.strip()
                                                    json_contents.append(view_tag)
                                except Exception as ex:
                                    print(f"Error fetching Drupal AJAX view {view_name}: {ex}")
                except Exception:
                    pass
                    
    # Append formatted JSON content to the body so it is processed by BeautifulSoup
    if json_contents:
        target_parent = soup.body if soup.body else soup
        for tag in json_contents:
            target_parent.append(tag)
            
    # 1. Strip scripts, styles, images, inline content that changes dynamically
    for element in soup(["script", "style", "noscript", "svg", "iframe", "img"]):
        element.decompose()
        
    # 2. Decompose ignore selectors if specified
    if ignore_selectors:
        selectors = [s.strip() for s in ignore_selectors.split(',') if s.strip()]
        for selector in selectors:
            try:
                for element in soup.select(selector):
                    element.decompose()
            except Exception as e:
                print(f"Warning: Invalid ignore selector '{selector}': {e}")
                
    # 3. Extract target text using include selectors
    if include_selectors:
        selectors = [s.strip() for s in include_selectors.split(',') if s.strip()]
        target_texts = []
        for selector in selectors:
            try:
                matches = soup.select(selector)
                for match in matches:
                    target_texts.append(match.get_text())
            except Exception as e:
                print(f"Warning: Invalid include selector '{selector}': {e}")
        text = "\n\n".join(target_texts)
    else:
        # Fallback to body or document text
        if soup.body:
            text = soup.body.get_text()
        else:
            text = soup.get_text()
            
    return clean_text(text)

def check_sensitivity(old_text, new_text, sensitivity_level):
    """
    Determine similarity ratio and return whether change is significant.
    Preset ratio thresholds:
    always: 1.0 (any difference)
    high: 0.999 (99.9% similarity)
    medium: 0.99 (99% similarity)
    low: 0.95 (95% similarity)
    """
    if old_text == new_text:
        return False, 1.0
        
    ratio = difflib.SequenceMatcher(None, old_text, new_text).ratio()
    
    # Map presets
    threshold = 1.0
    if isinstance(sensitivity_level, str):
        level = sensitivity_level.lower()
        if level == 'always':
            threshold = 1.0
        elif level == 'high':
            threshold = 0.999
        elif level == 'medium':
            threshold = 0.99
        elif level == 'low':
            threshold = 0.95
        else:
            threshold = 0.99  # default to medium
    else:
        try:
            threshold = float(sensitivity_level)
        except (ValueError, TypeError):
            threshold = 0.99
            
    # If similarity ratio is LESS than threshold, it has changed
    is_changed = ratio < threshold
    return is_changed, ratio

def send_notification(monitor, old_text, new_text, ratio):
    """Send SMTP email notification with a visual diff report."""
    smtp_config = get_smtp_config()
    if not smtp_config:
        print("SMTP email notification skipped: Email settings not configured.")
        return False
        
    monitor_name = monitor.get('name', monitor.get('url'))
    monitor_url = monitor.get('url')
    
    # Generate plaintext diff
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    diff = list(difflib.unified_diff(
        old_lines, 
        new_lines, 
        fromfile='Previous Version', 
        tofile='New Version', 
        lineterm=''
    ))
    diff_text = "\n".join(diff)
    
    # Generate summary stats
    added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
    removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
    
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"[Page Tracker] Change detected: {monitor_name}"
    msg['From'] = smtp_config['from']
    msg['To'] = smtp_config['to']
    
    text_body = f"""Webpage Change Detected!

Monitored Page: {monitor_name}
URL: {monitor_url}
Checked at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Similarity Index: {ratio:.4f} (Threshold: {monitor.get('sensitivity', 'medium')})
Change Summary: {added} lines added, {removed} lines removed

Diff Output:
----------------------------------------
{diff_text}
----------------------------------------

Manage your monitors or view the archive in the Webpage Tracker Dashboard."""

    # Simple clean HTML table diff format for email client
    diff_html_rows = []
    for line in diff:
        if line.startswith('+++') or line.startswith('---') or line.startswith('@@'):
            diff_html_rows.append(f'<tr style="background-color: #f1f5f9; color: #64748b;"><td style="font-family: monospace; padding: 2px 8px; white-space: pre-wrap;">{line}</td></tr>')
        elif line.startswith('+'):
            diff_html_rows.append(f'<tr style="background-color: #dcfce7; color: #15803d;"><td style="font-family: monospace; padding: 2px 8px; white-space: pre-wrap;">{line}</td></tr>')
        elif line.startswith('-'):
            diff_html_rows.append(f'<tr style="background-color: #fee2e2; color: #b91c1c;"><td style="font-family: monospace; padding: 2px 8px; white-space: pre-wrap;">{line}</td></tr>')
        else:
            diff_html_rows.append(f'<tr style="color: #334155;"><td style="font-family: monospace; padding: 2px 8px; white-space: pre-wrap;">{line}</td></tr>')
            
    html_body = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; max-width: 800px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #4f46e5; color: white; padding: 20px; border-radius: 8px 8px 0 0;">
          <h2 style="margin: 0; font-size: 20px;">Webpage Change Detected</h2>
          <p style="margin: 5px 0 0 0; opacity: 0.9;">Page: <strong>{monitor_name}</strong></p>
        </div>
        <div style="border: 1px solid #e2e8f0; border-top: none; border-radius: 0 0 8px 8px; padding: 20px; background-color: #fafafa;">
          <table style="width: 100%; border-collapse: collapse; margin-bottom: 20px;">
            <tr>
              <td style="padding: 6px 0; color: #64748b; font-weight: 500; width: 140px;">URL:</td>
              <td style="padding: 6px 0;"><a href="{monitor_url}" style="color: #4f46e5; text-decoration: none;">{monitor_url}</a></td>
            </tr>
            <tr>
              <td style="padding: 6px 0; color: #64748b; font-weight: 500;">Checked At:</td>
              <td style="padding: 6px 0;">{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</td>
            </tr>
            <tr>
              <td style="padding: 6px 0; color: #64748b; font-weight: 500;">Similarity Index:</td>
              <td style="padding: 6px 0;">{ratio:.4f} (Sensitivity preset: {monitor.get('sensitivity', 'medium')})</td>
            </tr>
            <tr>
              <td style="padding: 6px 0; color: #64748b; font-weight: 500;">Change Summary:</td>
              <td style="padding: 6px 0;">
                <span style="background-color: #dcfce7; color: #15803d; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 13px; margin-right: 5px;">+{added} lines</span>
                <span style="background-color: #fee2e2; color: #b91c1c; padding: 2px 8px; border-radius: 4px; font-weight: bold; font-size: 13px;">-{removed} lines</span>
              </td>
            </tr>
          </table>
          
          <h3 style="color: #334155; margin-bottom: 10px; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px;">Changes Diff</h3>
          <div style="background-color: white; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden; max-height: 400px; overflow-y: auto;">
            <table style="width: 100%; border-collapse: collapse;">
              {"".join(diff_html_rows)}
            </table>
          </div>
          <p style="color: #64748b; font-size: 12px; margin-top: 20px; text-align: center;">
            This email was sent automatically by your Webpage Change Tracker.
          </p>
        </div>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        if smtp_config['secure']:
            server = smtplib.SMTP_SSL(smtp_config['host'], smtp_config['port'], timeout=15)
        else:
            server = smtplib.SMTP(smtp_config['host'], smtp_config['port'], timeout=15)
            server.starttls()
            
        server.login(smtp_config['user'], smtp_config['pass'])
        server.sendmail(smtp_config['from'], [smtp_config['to']], msg.as_string())
        server.quit()
        print(f"Change email notification sent successfully to {smtp_config['to']}")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def check_single_monitor(monitor, force=False):
    """
    Perform crawl and change check for a single monitor.
    Returns (changed, error_msg)
    """
    monitor_id = monitor['id']
    url = monitor['url']
    sensitivity = monitor.get('sensitivity', 'medium')
    min_char_diff = int(monitor.get('min_char_diff', 0))
    include_selectors = monitor.get('include_selectors')
    ignore_selectors = monitor.get('ignore_selectors')
    
    # 1. Fetch current content
    try:
        new_text = fetch_page_content(url, include_selectors, ignore_selectors)
    except Exception as e:
        error_msg = str(e)
        monitor['last_checked'] = datetime.datetime.now().isoformat()
        monitor['status'] = 'failed'
        monitor['last_error'] = error_msg
        print(f"Crawl failed for '{monitor['name']}': {error_msg}")
        return False, error_msg
        
    # 2. Get previous content from archive
    archive_dir = os.path.join(DATA_DIR, 'archive', monitor_id)
    history_file = os.path.join(archive_dir, 'history.json')
    
    last_text = ""
    is_first_run = True
    
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r') as f:
                history = json.load(f)
                if history:
                    last_version = history[-1]
                    last_file_path = os.path.join(archive_dir, last_version['filename'])
                    if os.path.exists(last_file_path):
                        with open(last_file_path, 'r') as f_txt:
                            last_text = f_txt.read()
                        is_first_run = False
        except Exception as e:
            print(f"Error reading history for '{monitor_id}': {e}")
            # If history fails to parse, treat as first run to recover
            is_first_run = True
            
    timestamp = datetime.datetime.now().isoformat()
    formatted_ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{formatted_ts}.txt"
    
    # If first run, always save initial copy but do not notify
    if is_first_run:
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
            
        with open(os.path.join(archive_dir, filename), 'w') as f:
            f.write(new_text)
            
        initial_history = [{
            'timestamp': timestamp,
            'changes_summary': 'Initial version captured',
            'filename': filename,
            'ratio': 1.0,
            'added': 0,
            'removed': 0
        }]
        
        with open(history_file, 'w') as f:
            json.dump(initial_history, f, indent=2)
            
        monitor['last_checked'] = timestamp
        monitor['last_changed'] = timestamp
        monitor['status'] = 'success'
        monitor['last_error'] = None
        print(f"Initial capture for '{monitor['name']}' successful.")
        return True, None
        
    # 3. Check for differences
    is_changed, ratio = check_sensitivity(last_text, new_text, sensitivity)
    
    # Check minimum character difference threshold if triggered
    if is_changed and min_char_diff > 0:
        char_diff = abs(len(new_text) - len(last_text))
        if char_diff < min_char_diff:
            print(f"Change detected for '{monitor['name']}' but ignored: character diff ({char_diff}) < min_char_diff ({min_char_diff})")
            is_changed = False
            
    if is_changed:
        # Save content
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
            
        with open(os.path.join(archive_dir, filename), 'w') as f:
            f.write(new_text)
            
        # Get diff summary stats
        old_lines = last_text.splitlines()
        new_lines = new_text.splitlines()
        diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
        added = sum(1 for line in diff if line.startswith('+') and not line.startswith('+++'))
        removed = sum(1 for line in diff if line.startswith('-') and not line.startswith('---'))
        summary = f"Similarity: {ratio:.4f}. Added {added} lines, removed {removed} lines."
        
        # Load and append history log
        history_data = []
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r') as f:
                    history_data = json.load(f)
            except Exception:
                pass
                
        history_entry = {
            'timestamp': timestamp,
            'changes_summary': summary,
            'filename': filename,
            'ratio': ratio,
            'added': added,
            'removed': removed
        }
        history_data.append(history_entry)
        
        with open(history_file, 'w') as f:
            json.dump(history_data, f, indent=2)
            
        monitor['last_checked'] = timestamp
        monitor['last_changed'] = timestamp
        monitor['status'] = 'success'
        monitor['last_error'] = None
        
        print(f"Change DETECTED for '{monitor['name']}'. Similarity: {ratio:.4f}")
        
        # Send Email Alert
        send_notification(monitor, last_text, new_text, ratio)
        return True, None
    else:
        # No change, only update checked time
        monitor['last_checked'] = timestamp
        monitor['status'] = 'success'
        monitor['last_error'] = None
        print(f"No changes detected for '{monitor['name']}'. Check complete.")
        return False, None

def run_tracker(force_check_id=None, force_all=False):
    """Main crawler loop to run checks."""
    monitors = load_monitors()
    if not monitors:
        print("No monitors configured.")
        return
        
    now = datetime.datetime.now()
    updated = False
    
    for monitor in monitors:
        # Check active status unless target forced
        is_target = force_check_id and (monitor['id'] == force_check_id)
        if not monitor.get('active', True) and not is_target:
            continue
            
        # Determine schedule
        should_run = False
        if force_all or is_target:
            should_run = True
        else:
            # Check elapsed time
            last_checked_str = monitor.get('last_checked')
            interval_mins = int(monitor.get('check_interval_mins', 60))
            
            if not last_checked_str:
                should_run = True
            else:
                try:
                    last_checked = datetime.datetime.fromisoformat(last_checked_str)
                    elapsed = (now - last_checked).total_seconds() / 60
                    if elapsed >= interval_mins:
                        should_run = True
                except Exception:
                    should_run = True
                    
        if should_run:
            print(f"Checking monitor: {monitor['name']} ({monitor['url']})...")
            check_single_monitor(monitor)
            updated = True
            
    if updated:
        save_monitors(monitors)
        print("Crawler run completed. Monitors updated.")
    else:
        print("No monitors were due for check.")

if __name__ == '__main__':
    # Parse CLI Arguments
    force_all = '--force' in sys.argv
    target_id = None
    for arg in sys.argv[1:]:
        if not arg.startswith('--'):
            target_id = arg
            break
            
    run_tracker(force_check_id=target_id, force_all=force_all)
