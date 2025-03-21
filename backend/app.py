from flask import Flask, request, render_template, jsonify, send_from_directory, session
import subprocess
import os
import time
import threading
import logging
import tempfile
import glob
import base64
import uuid
import shutil
from io import BytesIO
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from PIL import Image
from flask_cors import CORS
import json
import datetime
import atexit

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('remote_browser')

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Add a secret key for sessions
# Enable CORS for all routes with credentials support
CORS(app, resources={r"/*": {"origins": ["http://localhost:3000"], "supports_credentials": True}})

# Create a temporary directory for screenshots
SCREENSHOT_DIR = tempfile.mkdtemp(prefix="browser_screenshots_")
logger.info(f"Using temporary directory for screenshots: {SCREENSHOT_DIR}")

# Session management dictionaries
browser_instances = {}  # Maps session_id -> browser instance
screenshot_threads = {}  # Maps session_id -> screenshot thread
keep_taking_screenshots = {}  # Maps session_id -> boolean flag
current_screenshots = {}  # Maps session_id -> current screenshot filename
current_screenshot_data = {}  # Maps session_id -> base64 encoded screenshot data

# Locks
screenshot_locks = {}  # Maps session_id -> screenshot lock
browser_locks = {}  # Maps session_id -> browser lock

# Constants
MAX_SCREENSHOTS = 3  # Keep fewer screenshots to reduce disk I/O
SCREENSHOT_INTERVAL = 0.05  # Take screenshots every 0.05 seconds (20 FPS)
SESSION_TIMEOUT = 1800  # 30 minutes of inactivity before closing browser

# Simplified key mapping with only the allowed keys
KEY_MAPPING = {
    'ENTER': Keys.ENTER,
    'BACK_SPACE': Keys.BACK_SPACE
}

def get_session_id():
    """Get or create a session ID for the current user."""
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        logger.info(f"Created new session: {session['session_id']}")
        
        # Initialize session-specific locks
        if session['session_id'] not in screenshot_locks:
            screenshot_locks[session['session_id']] = threading.Lock()
        if session['session_id'] not in browser_locks:
            browser_locks[session['session_id']] = threading.Lock()
        
        # Set default values for this session
        current_screenshots[session['session_id']] = "placeholder.png"
        keep_taking_screenshots[session['session_id']] = False
        
        # Create session directory for screenshots
        session_dir = os.path.join(SCREENSHOT_DIR, session['session_id'])
        os.makedirs(session_dir, exist_ok=True)
        
        # Create a placeholder screenshot for this session
        placeholder_path = os.path.join(session_dir, "placeholder.png")
        if not os.path.exists(placeholder_path):
            img = Image.new('RGB', (800, 600), color='gray')
            img.save(placeholder_path)
    
    return session['session_id']

def get_session_dir(session_id):
    """Get the screenshot directory for this session."""
    session_dir = os.path.join(SCREENSHOT_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    return session_dir

def setup_browser(session_id):
    """Initialize the headless browser for a specific session with detailed logging."""
    session_browser_lock = browser_locks.get(session_id) or threading.Lock()
    
    with session_browser_lock:
        if session_id in browser_instances and browser_instances[session_id] is not None:
            logger.info(f"Browser for session {session_id} already running, reusing existing instance")
            return browser_instances[session_id]
        
        try:
            logger.info(f"Setting up Chrome browser for session {session_id}...")
            
            # Create a temporary directory that will be automatically cleaned up
            temp_profile_dir = tempfile.mkdtemp(prefix=f"chrome_temp_{session_id}_")
            logger.info(f"Created temporary Chrome profile directory: {temp_profile_dir}")
            
            # Set up debugging port (unique for each session)
            debugging_port = 9222 + hash(session_id) % 1000
            
            # Configure Chrome options
            chrome_options = Options()
            chrome_options.add_argument(f"--remote-debugging-port={debugging_port}")
            chrome_options.add_argument(f"--user-data-dir={temp_profile_dir}")
            chrome_options.add_argument("--no-first-run")
            chrome_options.add_argument("--no-default-browser-check")
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-logging")
            chrome_options.add_argument("--log-level=3")
            chrome_options.add_argument("--silent")
            
            # Check chromedriver
            chromedriver_path = "./chromedriver-linux64/chromedriver"
            if not os.path.exists(chromedriver_path):
                error_msg = f"Chromedriver not found at {chromedriver_path}"
                logger.error(error_msg)
                raise Exception(error_msg)
            
            if not os.access(chromedriver_path, os.X_OK):
                logger.info("Chromedriver not executable, attempting to make it executable")
                os.chmod(chromedriver_path, 0o755)
            
            logger.info(f"Using chromedriver at: {chromedriver_path}")
            
            # Configure webdriver service with logging
            service = Service(
                executable_path=chromedriver_path,
                log_output=os.path.join(temp_profile_dir, "chromedriver.log")
            )
            
            # Create the browser instance
            logger.info(f"Creating Chrome webdriver instance for session {session_id} with debugging port {debugging_port}...")
            try:
                browser = webdriver.Chrome(service=service, options=chrome_options)
                logger.info(f"Chrome instance created successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to create Chrome instance: {str(e)}")
                # Try to read chromedriver log if it exists
                log_path = os.path.join(temp_profile_dir, "chromedriver.log")
                if os.path.exists(log_path):
                    with open(log_path, 'r') as f:
                        logger.error(f"Chromedriver log contents: {f.read()}")
                # Clean up the temporary directory on failure
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
                raise
            
            # Store the browser instance and its temporary directory
            browser_instances[session_id] = browser
            browser_instances[session_id].temp_profile_dir = temp_profile_dir
            
            # Test the browser instance
            logger.info(f"Testing browser instance by navigating to Google...")
            try:
                browser.set_page_load_timeout(10)
                browser.get("https://www.google.com")
                logger.info(f"Current page title: {browser.title}")
                logger.info(f"Initial navigation successful for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to load initial page: {str(e)}")
                raise
            
            # Start screenshot thread for this session
            start_screenshot_thread(session_id)
            
            # Set last activity time for session timeout
            browser_instances[session_id].last_activity = time.time()
            
            return browser
            
        except Exception as e:
            logger.error(f"Failed to initialize browser for session {session_id}", exc_info=True)
            logger.error(f"Error details: {str(e)}")
            
            # Cleanup on failure
            if session_id in browser_instances and browser_instances[session_id]:
                try:
                    browser_instances[session_id].quit()
                except Exception as cleanup_error:
                    logger.error(f"Error during browser cleanup: {str(cleanup_error)}")
                browser_instances[session_id] = None
            
            # Clean up temporary directory on failure
            if 'temp_profile_dir' in locals():
                try:
                    shutil.rmtree(temp_profile_dir, ignore_errors=True)
                    logger.info(f"Cleaned up temporary profile directory after failure: {temp_profile_dir}")
                except Exception as cleanup_error:
                    logger.error(f"Error cleaning up temporary profile directory: {str(cleanup_error)}")
            
            raise

def cleanup_old_screenshots(session_id):
    """Delete old screenshots for a session, keeping only the most recent ones."""
    session_dir = get_session_dir(session_id)
    try:
        # Get all screenshot files sorted by modification time (newest first)
        files = sorted(
            glob.glob(os.path.join(session_dir, "screenshot-*.png")),
            key=os.path.getmtime,
            reverse=True
        )
        
        # Keep only the MAX_SCREENSHOTS most recent files
        for old_file in files[MAX_SCREENSHOTS:]:
            try:
                os.remove(old_file)
                logger.debug(f"Deleted old screenshot for session {session_id}: {old_file}")
            except Exception as e:
                logger.warning(f"Failed to delete old screenshot {old_file} for session {session_id}: {str(e)}")
    except Exception as e:
        logger.error(f"Error cleaning up old screenshots for session {session_id}: {str(e)}")

def start_screenshot_thread(session_id):
    """Start the screenshot thread for a specific session if not already running."""
    if session_id in screenshot_threads and screenshot_threads[session_id] is not None and screenshot_threads[session_id].is_alive():
        logger.info(f"Screenshot thread for session {session_id} already running")
        return
    
    logger.info(f"Starting screenshot thread for session {session_id}...")
    keep_taking_screenshots[session_id] = True
    screenshot_threads[session_id] = threading.Thread(
        target=take_screenshots, 
        args=(session_id,)
    )
    screenshot_threads[session_id].daemon = True
    screenshot_threads[session_id].start()
    logger.info(f"Screenshot thread started for session {session_id}")

def take_screenshots(session_id):
    """Continuously take screenshots for a specific session."""
    logger.info(f"Screenshot thread started for session {session_id}")
    
    session_dir = get_session_dir(session_id)
    session_lock = screenshot_locks.get(session_id) or threading.Lock()
    
    while keep_taking_screenshots.get(session_id, False):
        try:
            # Check if browser instance exists and is responsive
            if session_id not in browser_instances or browser_instances[session_id] is None:
                logger.warning(f"Browser instance not available for session {session_id}")
                time.sleep(0.5)
                continue
            
            browser = browser_instances[session_id]
            
            # Take screenshot
            screenshot_data = browser.get_screenshot_as_base64()
            if not screenshot_data:
                logger.error(f"Failed to capture screenshot for session {session_id}: No data returned")
                time.sleep(0.5)  # Wait a bit longer on error
                continue
            
            # Generate filename with timestamp
            timestamp = int(time.time() * 1000)
            filename = f"screenshot-{timestamp}.png"
            filepath = os.path.join(session_dir, filename)
            
            # Save screenshot and update current data
            with session_lock:
                # Save the file
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(screenshot_data))
                
                # Update current screenshot information
                current_screenshots[session_id] = filename
                current_screenshot_data[session_id] = screenshot_data
                
                # Clean up old screenshots
                cleanup_old_screenshots(session_id)
            
            logger.info(f"Screenshot saved as {filename} for session {session_id}")
            
            # Adaptive sleep to maintain target frame rate
            time.sleep(SCREENSHOT_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error taking screenshot for session {session_id}: {str(e)}")
            time.sleep(0.5)  # Wait a bit longer on error
    
    logger.info(f"Screenshot thread stopped for session {session_id}")

def stop_session_browser(session_id):
    """Stop the browser and screenshot thread for a specific session."""
    logger.info(f"Stopping browser for session {session_id}")
    
    # Stop screenshot thread
    keep_taking_screenshots[session_id] = False
    
    # Get session lock
    session_browser_lock = browser_locks.get(session_id) or threading.Lock()
    
    with session_browser_lock:
        if session_id in browser_instances and browser_instances[session_id]:
            try:
                logger.info(f"Quitting browser for session {session_id}...")
                browser_instances[session_id].quit()
                
                # Clean up temporary profile directory
                if hasattr(browser_instances[session_id], 'temp_profile_dir'):
                    temp_dir = browser_instances[session_id].temp_profile_dir
                    try:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        logger.info(f"Cleaned up temporary profile directory for session {session_id}")
                    except Exception as e:
                        logger.error(f"Error cleaning up temporary profile directory for session {session_id}: {str(e)}")
                
            except Exception as e:
                logger.error(f"Error quitting browser for session {session_id}: {str(e)}")
            finally:
                browser_instances[session_id] = None
                logger.info(f"Browser stopped for session {session_id}")

def check_session_timeouts():
    """Check for and close inactive browser sessions."""
    current_time = time.time()
    sessions_to_check = list(browser_instances.keys())
    
    for session_id in sessions_to_check:
        if session_id in browser_instances and browser_instances[session_id] is not None:
            # Check if session has a last_activity attribute
            if hasattr(browser_instances[session_id], 'last_activity'):
                last_activity = browser_instances[session_id].last_activity
                if current_time - last_activity > SESSION_TIMEOUT:
                    logger.info(f"Session {session_id} timed out after {SESSION_TIMEOUT} seconds of inactivity")
                    stop_session_browser(session_id)

# Start a thread to periodically check for session timeouts
def start_timeout_checker():
    """Start a thread to periodically check for session timeouts."""
    def timeout_checker():
        while True:
            check_session_timeouts()
            time.sleep(60)  # Check every minute
            
    timeout_thread = threading.Thread(target=timeout_checker)
    timeout_thread.daemon = True
    timeout_thread.start()
    logger.info("Session timeout checker started")

# Update the last activity time for a session
def update_session_activity(session_id):
    """Update the last activity time for a session."""
    if session_id in browser_instances and browser_instances[session_id] is not None:
        browser_instances[session_id].last_activity = time.time()

@app.route('/')
def index():
    """Render the main page."""
    # Get or create a session ID
    session_id = get_session_id()
    return render_template('index.html')

@app.route('/start_browser', methods=['POST'])
def start_browser():
    """Start the browser and screenshot thread for the current session."""
    session_id = get_session_id()
    
    try:
        logger.info(f"Received request to start browser for session {session_id}")
        browser = setup_browser(session_id)
        update_session_activity(session_id)
        return jsonify({"status": "success", "message": "Browser started", "session_id": session_id})
    except Exception as e:
        logger.error(f"Error starting browser for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})

@app.route('/stop_browser', methods=['POST'])
def stop_browser():
    """Stop the browser and screenshot thread for the current session."""
    session_id = get_session_id()
    
    try:
        logger.info(f"Received request to stop browser for session {session_id}")
        stop_session_browser(session_id)
        return jsonify({"status": "success", "message": "Browser stopped", "session_id": session_id})
    except Exception as e:
        logger.error(f"Error stopping browser for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error stopping browser: {str(e)}"})

@app.route('/navigate', methods=['POST'])
def navigate():
    """Navigate to a URL with auto-start if browser not running."""
    session_id = get_session_id()
    
    try:
        url = request.json.get('url')
        logger.info(f"Received navigation request to: {url} for session {session_id}")
        
        if not url:
            logger.warning(f"Navigation request missing URL for session {session_id}")
            return jsonify({"status": "error", "message": "URL is required"})
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Navigate to URL
        logger.info(f"Navigating to {url} for session {session_id}...")
        browser_instances[session_id].get(url)
        logger.info(f"Successfully navigated to {url} for session {session_id}")
        
        # Update session activity
        update_session_activity(session_id)
        
        return jsonify({"status": "success", "message": f"Navigated to {url}", "session_id": session_id})
    except Exception as e:
        logger.error(f"Error during navigation for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Navigation error: {str(e)}"})

@app.route('/click', methods=['POST'])
def click():
    """Perform a click at the specified coordinates with auto-start if needed."""
    session_id = get_session_id()
    
    try:
        x = request.json.get('x')
        y = request.json.get('y') 
        logger.info(f"Received click request at coordinates ({x}, {y}) for session {session_id}")
        
        if x is None or y is None:
            logger.warning(f"Click request missing coordinates for session {session_id}")
            return jsonify({"status": "error", "message": "X and Y coordinates are required"})
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        browser = browser_instances[session_id]
        
        # Get both window and viewport sizes
        window_size = browser.get_window_size()
        viewport_size = browser.execute_script("""
            return {
                width: window.innerWidth || document.documentElement.clientWidth,
                height: window.innerHeight || document.documentElement.clientHeight,
                scroll_x: window.pageXOffset || document.documentElement.scrollLeft,
                scroll_y: window.pageYOffset || document.documentElement.scrollTop
            };
        """)
        
        logger.info(f"Window size: {window_size}, Viewport size: {viewport_size}")
        
        # Ensure coordinates are within viewport bounds
        x = max(0, min(x, viewport_size['width']))
        y = max(0, min(y, viewport_size['height']))
        
        # Add scroll offset to coordinates
        actual_x = x + viewport_size['scroll_x']
        actual_y = y + viewport_size['scroll_y']
        
        logger.info(f"Adjusted coordinates: ({actual_x}, {actual_y})")
        
        # Simple visual feedback
        browser.execute_script(f"""
            const dot = document.createElement('div');
            dot.style.cssText = 'position:fixed;width:10px;height:10px;background:red;border-radius:50%;z-index:99999;pointer-events:none;';
            dot.style.left = '{x}px';
            dot.style.top = '{y}px';
            document.body.appendChild(dot);
            setTimeout(() => dot.remove(), 500);
        """)
        
        try:
            # First, try using JavaScript click for better reliability
            click_result = browser.execute_script("""
                const element = document.elementFromPoint(arguments[0], arguments[1]);
                if (element) {
                    element.click();
                    return true;
                }
                return false;
            """, x, y)
            
            if click_result:
                logger.info(f"Click performed using JavaScript at ({x}, {y})")
            else:
                # If JavaScript click fails, use ActionChains
                logger.info("JavaScript click failed, trying ActionChains...")
                
                # Reset mouse position to top-left corner
                actions = ActionChains(browser)
                actions.move_to_element(browser.find_element('tag name', 'body'))
                actions.perform()
                
                # Move to the target coordinates and click
                actions = ActionChains(browser)
                actions.move_by_offset(x, y)
                actions.click()
                actions.perform()
                
                logger.info(f"Click performed using ActionChains at ({x}, {y})")
            
            # Update session activity
            update_session_activity(session_id)
            
            return jsonify({
                "status": "success",
                "message": f"Clicked at coordinates ({x}, {y})"
            })
                
        except Exception as e:
            logger.error(f"Click operation failed for session {session_id}: {str(e)}", exc_info=True)
            
            # Try one last time with direct JavaScript event dispatch
            try:
                logger.info("Trying direct JavaScript event dispatch...")
                success = browser.execute_script("""
                    const element = document.elementFromPoint(arguments[0], arguments[1]);
                    if (element) {
                        const event = new MouseEvent('click', {
                            view: window,
                            bubbles: true,
                            cancelable: true,
                            clientX: arguments[0],
                            clientY: arguments[1]
                        });
                        element.dispatchEvent(event);
                        return true;
                    }
                    return false;
                """, x, y)
                
                if success:
                    logger.info("Click performed using direct JavaScript event dispatch")
                    return jsonify({
                        "status": "success",
                        "message": f"Clicked at coordinates ({x}, {y}) using JavaScript event"
                    })
                else:
                    return jsonify({"status": "error", "message": f"Click error: No element found at coordinates"})
                
            except Exception as js_error:
                logger.error(f"All click methods failed for session {session_id}: {str(js_error)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Click error: {str(e)}"})
            
    except Exception as e:
        logger.error(f"Error during click operation for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Click error: {str(e)}"})

@app.route('/scroll', methods=['POST'])
def scroll():
    """Perform a scroll action in the browser."""
    session_id = get_session_id()
    
    try:
        delta_x = request.json.get('deltaX', 0)
        delta_y = request.json.get('deltaY', 0)
        logger.info(f"Received scroll request with deltaX={delta_x}, deltaY={delta_y} for session {session_id}")
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Convert the delta values to a reasonable scroll amount
        # Adjust these multipliers based on testing
        scroll_x = int(delta_x * 0.5)
        scroll_y = int(delta_y * 0.5)
        
        # Execute JavaScript to scroll the page
        script = f"""
            window.scrollBy({scroll_x}, {scroll_y});
            return [window.scrollX, window.scrollY];
        """
        scroll_position = browser_instances[session_id].execute_script(script)
        
        logger.info(f"Scrolled by ({scroll_x}, {scroll_y}) for session {session_id}, new position: {scroll_position}")
        
        # Update session activity
        update_session_activity(session_id)
        
        return jsonify({
            "status": "success",
            "message": f"Scrolled by ({scroll_x}, {scroll_y})",
            "position": scroll_position,
            "session_id": session_id
        })
        
    except Exception as e:
        logger.error(f"Error during scroll operation for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Scroll error: {str(e)}"})

@app.route('/type_text', methods=['POST'])
def type_text():
    """Type text into the currently focused element."""
    session_id = get_session_id()
    
    try:
        text = request.json.get('text', '')
        logger.info(f"Received text input: '{text}' for session {session_id}")
        
        if not text:
            return jsonify({"status": "error", "message": "No text provided"})
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Use ActionChains to send the text to the active element
        actions = ActionChains(browser_instances[session_id])
        actions.send_keys(text)
        actions.perform()
        
        logger.info(f"Text input sent: '{text}' for session {session_id}")
        
        # Update session activity
        update_session_activity(session_id)
        
        return jsonify({
            "status": "success",
            "message": f"Text input sent: '{text}'",
            "session_id": session_id
        })
        
    except Exception as e:
        logger.error(f"Error during text input for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Text input error: {str(e)}"})

@app.route('/send_key', methods=['POST'])
def send_key():
    """Send a special key to the browser (limited to Enter and Backspace)."""
    session_id = get_session_id()
    
    try:
        key = request.json.get('key')
        modifiers = request.json.get('modifiers', {})
        logger.info(f"Received key input: {key} with modifiers: {modifiers} for session {session_id}")
        
        if not key:
            return jsonify({"status": "error", "message": "No key provided"})
        
        # Only allow ENTER and BACK_SPACE
        if key not in KEY_MAPPING:
            return jsonify({"status": "error", "message": f"Unsupported key: {key}"})
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Map the key to Selenium Keys
        selenium_key = KEY_MAPPING.get(key)
        
        # Use ActionChains to send the key with shift modifier only
        actions = ActionChains(browser_instances[session_id])
        
        # Add shift modifier if needed
        if modifiers.get('shift'):
            actions.key_down(Keys.SHIFT)
        
        # Send the key
        actions.send_keys(selenium_key)
        
        # Release shift if needed
        if modifiers.get('shift'):
            actions.key_up(Keys.SHIFT)
        
        # Perform the action
        actions.perform()
        
        logger.info(f"Key sent: {key} with modifiers: {modifiers} for session {session_id}")
        
        # Update session activity
        update_session_activity(session_id)
        
        return jsonify({
            "status": "success",
            "message": f"Key sent: {key}",
            "session_id": session_id
        })
        
    except Exception as e:
        logger.error(f"Error sending key for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Key input error: {str(e)}"})
        
@app.route('/get_latest_screenshot')
def get_latest_screenshot():
    """Get the filename of the latest screenshot."""
    session_id = get_session_id()
    session_lock = screenshot_locks.get(session_id) or threading.Lock()
    
    with session_lock:
        filename = current_screenshots.get(session_id, "placeholder.png")
        return jsonify({"filename": filename})

@app.route('/get_screenshot_data')
def get_screenshot_data():
    """Get the base64 encoded data of the latest screenshot for direct streaming."""
    session_id = get_session_id()
    session_lock = screenshot_locks.get(session_id) or threading.Lock()
    
    with session_lock:
        data = current_screenshot_data.get(session_id)
        return jsonify({"data": data})

@app.route('/screenshots/<filename>')
def serve_screenshot(filename):
    """Serve a screenshot file."""
    session_id = get_session_id()
    session_dir = get_session_dir(session_id)
    return send_from_directory(session_dir, filename)

@app.route('/browser_status')
def browser_status():
    """Check if browser is running for the current session."""
    session_id = get_session_id()
    is_running = session_id in browser_instances and browser_instances[session_id] is not None
    logger.info(f"Browser status check for session {session_id}: {'running' if is_running else 'not running'}")
    return jsonify({"running": is_running})

@app.route('/system_info')
def system_info():
    """Get system information for debugging."""
    import platform
    import sys
    
    # Count active sessions
    active_sessions = sum(1 for browser in browser_instances.values() if browser is not None)
    
    info = {
        "platform": platform.platform(),
        "python_version": sys.version,
        "selenium_version": webdriver.__version__,
        "flask_version": app.version,
        "screenshot_dir": SCREENSHOT_DIR,
        "active_sessions": active_sessions,
        "total_sessions_created": len(browser_instances),
        "screenshot_interval": f"{SCREENSHOT_INTERVAL} seconds",
        "max_screenshots": MAX_SCREENSHOTS,
        "chrome_binary": chrome_options.binary_location if 'chrome_options' in locals() else "Not initialized"
    }
    logger.info(f"System info: {info}")
    return jsonify(info)

@app.route('/save_page_info', methods=['POST'])
def save_page_info():
    """Save the current page information including HTML content, URL, timestamp, and wallet address."""
    session_id = get_session_id()
    
    try:
        # Get wallet address from request
        wallet_address = request.json.get('wallet_address', 'Not connected')
        logger.info(f"Saving page info with wallet address: {wallet_address} for session {session_id}")
        
        # Auto-start browser if not running
        if session_id not in browser_instances or browser_instances[session_id] is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                browser = setup_browser(session_id)
                logger.info(f"Browser auto-started successfully for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to auto-start browser for session {session_id}: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        browser = browser_instances[session_id]
        
        # Get current URL
        current_url = browser.current_url
        
        # Get current HTML content
        html_content = browser.page_source
        
        # Get screenshot
        screenshot_data = browser.get_screenshot_as_base64()
        
        # Create timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Create save directory if it doesn't exist
        save_dir = os.path.join(SCREENSHOT_DIR, session_id, 'saved_pages')
        os.makedirs(save_dir, exist_ok=True)
        
        # Generate filename based on timestamp
        filename_base = f"page_capture_{timestamp.replace(':', '-').replace('.', '_')}"
        
        # Save HTML content
        html_path = os.path.join(save_dir, f"{filename_base}.html")
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        # Save screenshot
        screenshot_path = os.path.join(save_dir, f"{filename_base}.png")
        with open(screenshot_path, 'wb') as f:
            f.write(base64.b64decode(screenshot_data))
        
        # Save metadata
        metadata = {
            'url': current_url,
            'timestamp': timestamp,
            'wallet_address': wallet_address,
            'html_file': f"{filename_base}.html",
            'screenshot_file': f"{filename_base}.png",
            'session_id': session_id
        }
        
        metadata_path = os.path.join(save_dir, f"{filename_base}.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Page info saved for session {session_id}: URL={current_url}, Timestamp={timestamp}")
        
        # Update session activity
        update_session_activity(session_id)
        
        return jsonify({
            "status": "success",
            "message": "Page information saved successfully",
            "data": {
                "url": current_url,
                "timestamp": timestamp,
                "wallet_address": wallet_address,
                "session_id": session_id,
                "files": {
                    "html": f"{filename_base}.html",
                    "screenshot": f"{filename_base}.png",
                    "metadata": f"{filename_base}.json"
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error saving page info for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error saving page info: {str(e)}"})

def cleanup_temp_files():
    """Clean up temporary files on application exit."""
    try:
        logger.info(f"Cleaning up temporary directory: {SCREENSHOT_DIR}")
        # Clean up screenshot directory
        shutil.rmtree(SCREENSHOT_DIR, ignore_errors=True)
        
        # Clean up any remaining temporary Chrome profiles
        for session_id, browser in browser_instances.items():
            if browser and hasattr(browser, 'temp_profile_dir'):
                try:
                    temp_dir = browser.temp_profile_dir
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    logger.info(f"Cleaned up temporary profile directory for session {session_id}")
                except Exception as e:
                    logger.error(f"Error cleaning up temporary profile directory for session {session_id}: {str(e)}")
        
        # Force quit any remaining browser instances
        for session_id, browser in browser_instances.items():
            if browser:
                try:
                    browser.quit()
                except:
                    pass
                
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")

# Register cleanup function to run on exit
atexit.register(cleanup_temp_files)

if __name__ == '__main__':
    # Create a placeholder screenshot
    placeholder_path = os.path.join(SCREENSHOT_DIR, "placeholder.png")
    if not os.path.exists(placeholder_path):
        img = Image.new('RGB', (1920, 1080), color='gray')
        img.save(placeholder_path)
    
    logger.info("Starting Flask application...")
    app.run(host='0.0.0.0', port=5000, debug=True)