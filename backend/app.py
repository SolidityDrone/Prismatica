from flask import Flask, request, render_template, jsonify, send_from_directory, session, send_file
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
from datetime import datetime, timedelta
import atexit
from typing import Dict
import zipfile

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('remote_browser')

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Add a secret key for sessions
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Allow cookies in cross-origin requests
app.config['SESSION_COOKIE_SECURE'] = False  # Set to True in production with HTTPS

# Enable CORS for all routes with credentials support
CORS(app, 
     resources={r"/*": {
         "origins": ["http://localhost:3000"],
         "supports_credentials": True,
         "allow_headers": ["Content-Type"],
         "expose_headers": ["Set-Cookie"],
         "methods": ["GET", "POST", "OPTIONS"]
     }})

# Create a temporary directory for screenshots
SCREENSHOT_DIR = tempfile.mkdtemp(prefix="browser_screenshots_")
logger.info(f"Using temporary directory for screenshots: {SCREENSHOT_DIR}")

class BrowserSession:
    def __init__(self):
        self.browser = None
        self.last_activity = datetime.now()
        self.screenshot_thread = None
        self.keep_taking_screenshots = True
        self.current_screenshot = "placeholder.png"
        self.current_screenshot_data = None
        self.screenshot_lock = threading.Lock()
        self.browser_lock = threading.Lock()
        self.screenshot_dir = tempfile.mkdtemp(prefix=f"browser_screenshots_{uuid.uuid4()}_")

    def update_activity(self):
        self.last_activity = datetime.now()

    def cleanup(self):
        try:
            if self.browser:
                self.browser.quit()
            if self.screenshot_dir:
                shutil.rmtree(self.screenshot_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up browser session: {str(e)}")

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, BrowserSession] = {}
        self.cleanup_thread = threading.Thread(target=self._cleanup_inactive_sessions, daemon=True)
        self.cleanup_thread.start()

    def get_session(self, session_id: str) -> BrowserSession:
        if session_id not in self.sessions:
            self.sessions[session_id] = BrowserSession()
        self.sessions[session_id].update_activity()
        return self.sessions[session_id]

    def remove_session(self, session_id: str):
        if session_id in self.sessions:
            self.sessions[session_id].cleanup()
            del self.sessions[session_id]

    def _cleanup_inactive_sessions(self):
        while True:
            try:
                current_time = datetime.now()
                inactive_sessions = [
                    session_id for session_id, session in self.sessions.items()
                    if (current_time - session.last_activity) > timedelta(minutes=30)
                ]
                for session_id in inactive_sessions:
                    logger.info(f"Cleaning up inactive session: {session_id}")
                    self.remove_session(session_id)
            except Exception as e:
                logger.error(f"Error in cleanup thread: {str(e)}")
            time.sleep(300)  # Check every 5 minutes

# Initialize the session manager
session_manager = SessionManager()

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
    
    session_id = session['session_id']
    # Ensure the session exists in the session manager
    session_manager.get_session(session_id)
    return session_id

def get_session_dir(session_id):
    """Get the screenshot directory for this session."""
    session_dir = os.path.join(SCREENSHOT_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)
    return session_dir

def setup_browser(session_id: str):
    """Initialize the headless browser with detailed logging for a specific session."""
    session = session_manager.get_session(session_id)
    
    with session.browser_lock:
        if session.browser is not None:
            logger.info(f"Browser already running for session {session_id}, reusing existing instance")
            return session.browser
        
        try:
            logger.info(f"Setting up Chrome browser for session {session_id}...")
            chrome_options = Options()
            chrome_options.add_argument("--headless=new")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-dev-tools")
            chrome_options.add_argument("--remote-debugging-port=9222")  # Fixed debugging port
            chrome_options.add_argument("--disable-features=VizDisplayCompositor")
            
            # Create temp directories
            temp_dir = os.path.join(tempfile.gettempdir(), f"chrome-temp-{session_id}")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)
            
            chrome_options.add_argument(f"--user-data-dir={temp_dir}")
            
            # Try different possible Chrome binary locations
            chrome_binary_paths = [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
                "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
            ]
            
            chrome_binary = None
            for path in chrome_binary_paths:
                if os.path.exists(path):
                    chrome_binary = path
                    break
            
            if chrome_binary:
                logger.info(f"Found Chrome binary at: {chrome_binary}")
                chrome_options.binary_location = chrome_binary
            else:
                logger.warning("Chrome binary not found in common locations, will try to use system default")
            
            # Try different possible chromedriver locations
            chromedriver_paths = [
                "./chromedriver",
                "./chromedriver.exe",
                "./chromedriver-linux64/chromedriver",
                "/usr/local/bin/chromedriver",
                "/usr/bin/chromedriver",
            ]
            
            chromedriver_path = None
            for path in chromedriver_paths:
                if os.path.exists(path):
                    chromedriver_path = path
                    break
            
            if not chromedriver_path:
                raise Exception("ChromeDriver not found in any of the expected locations")
            
            logger.info(f"Using ChromeDriver at: {chromedriver_path}")
            
            # Make sure chromedriver is executable
            if os.name != 'nt':  # Not Windows
                try:
                    os.chmod(chromedriver_path, 0o755)
                except Exception as e:
                    logger.warning(f"Failed to make chromedriver executable: {e}")
            
            service = Service(
                executable_path=chromedriver_path,
                log_path=os.path.join(temp_dir, "chromedriver.log")
            )
            
            logger.info("Creating Chrome webdriver instance...")
            session.browser = webdriver.Chrome(service=service, options=chrome_options)
            session.browser.set_window_size(1920, 1080)
            logger.info("Chrome webdriver instance created successfully")
            
            # Test with a simple navigation
            session.browser.set_page_load_timeout(30)
            session.browser.get("about:blank")
            logger.info("Initial navigation successful")
            
            # Store the temp directory for cleanup
            session.browser.temp_dir = temp_dir
            
            start_screenshot_thread(session_id)
            
            return session.browser
            
        except Exception as e:
            error_msg = f"Failed to initialize browser for session {session_id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            if session.browser:
                try:
                    session.browser.quit()
                except:
                    pass
                session.browser = None
            
            # Clean up temp directory
            try:
                if 'temp_dir' in locals():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except:
                pass
            
            raise Exception(error_msg)

def cleanup_old_screenshots(session_id):
    """Delete old screenshots for a session, keeping only the most recent ones."""
    session = session_manager.get_session(session_id)
    try:
        # Get all screenshot files sorted by modification time (newest first)
        files = sorted(
            glob.glob(os.path.join(session.screenshot_dir, "screenshot-*.png")),
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
    session = session_manager.get_session(session_id)
    
    if session.screenshot_thread is not None and session.screenshot_thread.is_alive():
        logger.info(f"Screenshot thread for session {session_id} already running")
        return
    
    logger.info(f"Starting screenshot thread for session {session_id}...")
    session.keep_taking_screenshots = True
    session.screenshot_thread = threading.Thread(
        target=take_screenshots, 
        args=(session_id,)
    )
    session.screenshot_thread.daemon = True
    session.screenshot_thread.start()
    logger.info(f"Screenshot thread started for session {session_id}")

def take_screenshots(session_id):
    """Continuously take screenshots for a specific session."""
    logger.info(f"Screenshot thread started for session {session_id}")
    
    session = session_manager.get_session(session_id)
    
    while session.keep_taking_screenshots:
        try:
            # Check if browser instance exists and is responsive
            if session.browser is None:
                logger.warning(f"Browser instance not available for session {session_id}")
                time.sleep(0.5)
                continue
            
            # Take screenshot
            screenshot_data = session.browser.get_screenshot_as_base64()
            if not screenshot_data:
                logger.error(f"Failed to capture screenshot for session {session_id}: No data returned")
                time.sleep(0.5)  # Wait a bit longer on error
                continue
            
            # Generate filename with timestamp
            timestamp = int(time.time() * 1000)
            filename = f"screenshot-{timestamp}.png"
            filepath = os.path.join(session.screenshot_dir, filename)
            
            # Save screenshot and update current data
            with session.screenshot_lock:
                # Save the file
                with open(filepath, 'wb') as f:
                    f.write(base64.b64decode(screenshot_data))
                
                # Update current screenshot information
                session.current_screenshot = filename
                session.current_screenshot_data = screenshot_data
                
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
    
    session = session_manager.get_session(session_id)
    session.keep_taking_screenshots = False
    
    with session.browser_lock:
        if session.browser:
            try:
                logger.info(f"Quitting browser for session {session_id}...")
                session.browser.quit()
                session.browser = None
                logger.info(f"Browser stopped for session {session_id}")
            except Exception as e:
                logger.error(f"Error quitting browser for session {session_id}: {str(e)}")
                session.browser = None

def check_session_timeouts():
    """Check for and close inactive browser sessions."""
    current_time = datetime.now()
    
    # Get a list of all sessions
    for session_id, session in session_manager.sessions.items():
        if session.browser is not None:
            if (current_time - session.last_activity) > timedelta(seconds=SESSION_TIMEOUT):
                logger.info(f"Session {session_id} timed out after {SESSION_TIMEOUT} seconds of inactivity")
                stop_session_browser(session_id)

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

def update_session_activity(session_id):
    """Update the last activity time for a session."""
    session = session_manager.get_session(session_id)
    session.update_activity()

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
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Navigate to URL
        logger.info(f"Navigating to {url} for session {session_id}...")
        session.browser.get(url)
        logger.info(f"Successfully navigated to {url} for session {session_id}")
        
        return jsonify({"status": "success", "message": f"Navigated to {url}", "session_id": session_id})
    except Exception as e:
        logger.error(f"Error during navigation for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Navigation error: {str(e)}"})

@app.route('/click', methods=['POST'])
def click():
    """Perform a click at the specified coordinates with auto-start if needed."""
    try:
        # Get session ID from request or Flask session
        session_id = get_session_id()  # Always use the Flask session ID
        
        x = request.json.get('x')
        y = request.json.get('y') 
        logger.info(f"Received click request at coordinates ({x}, {y}) for session {session_id}")
        
        if x is None or y is None:
            logger.warning("Click request missing coordinates")
            return jsonify({"status": "error", "message": "X and Y coordinates are required"})
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Get the current window size
        window_size = session.browser.get_window_size()
        logger.info(f"Current window size for session {session_id}: {window_size}")
        
        # Ensure coordinates are within bounds
        x = max(0, min(x, window_size['width']))
        y = max(0, min(y, window_size['height']))
        
        # Add visual click indicator before performing the actual click
        script = f"""
            // Create and append the click indicator
            (function() {{
                const clickIndicator = document.createElement('div');
                clickIndicator.style.position = 'fixed';
                clickIndicator.style.left = '{x}px';
                clickIndicator.style.top = '{y}px';
                clickIndicator.style.width = '20px';
                clickIndicator.style.height = '20px';
                clickIndicator.style.borderRadius = '50%';
                clickIndicator.style.backgroundColor = 'rgba(255, 0, 0, 0.7)';
                clickIndicator.style.transform = 'translate(-50%, -50%)';
                clickIndicator.style.pointerEvents = 'none';
                clickIndicator.style.zIndex = '99999';
                clickIndicator.style.transition = 'all 0.5s ease-out';
                
                document.body.appendChild(clickIndicator);
                
                // Animate and remove
                setTimeout(() => {{
                    clickIndicator.style.width = '40px';
                    clickIndicator.style.height = '40px';
                    clickIndicator.style.opacity = '0';
                }}, 50);
                
                setTimeout(() => {{
                    document.body.removeChild(clickIndicator);
                }}, 600);
            }})();
        """
        session.browser.execute_script(script)
        
        # Method 1: Try using elementFromPoint with direct click AND focus
        try:
            logger.info(f"Attempting direct element click at ({x}, {y}) for session {session_id}...")
            script = f"""
                try {{
                    const element = document.elementFromPoint({x}, {y});
                    const info = element ? {{
                        tagName: element.tagName,
                        id: element.id,
                        className: element.className,
                        text: element.innerText ? element.innerText.substring(0, 20) : ''
                    }} : null;
                    
                    if (element) {{
                        if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || 
                            element.tagName === 'SELECT' || element.hasAttribute('contenteditable')) {{
                            element.focus();
                            console.log('Element focused:', element.tagName);
                        }}
                        
                        element.click();
                        
                        if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || 
                            element.tagName === 'SELECT' || element.hasAttribute('contenteditable')) {{
                            setTimeout(() => element.focus(), 50);
                        }}
                        
                        return {{success: true, element: info}};
                    }}
                    return {{success: false, message: 'No element found at position'}};
                }} catch (e) {{
                    return {{success: false, error: e.message}};
                }}
            """
            result = session.browser.execute_script(script)
            logger.info(f"JavaScript click result for session {session_id}: {result}")
            
            if result and result.get('success'):
                return jsonify({
                    "status": "success", 
                    "message": f"Clicked element at ({x}, {y}): {result.get('element')}"
                })
            
            # Method 2: Fall back to ActionChains with additional focus handling
            logger.info(f"Trying ActionChains click at ({x}, {y}) for session {session_id}...")
            actions = ActionChains(session.browser)
            actions.move_by_offset(-10000, -10000)  # Move far out to reset position
            actions.perform()
            
            actions = ActionChains(session.browser)
            actions.move_by_offset(x, y)
            actions.click()
            actions.perform()
            
            # Try to focus the element again after click
            session.browser.execute_script(f"""
                const element = document.elementFromPoint({x}, {y});
                if (element && (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || 
                    element.tagName === 'SELECT' || element.hasAttribute('contenteditable'))) {{
                    element.focus();
                    console.log('Focus applied after ActionChains click');
                }}
            """)
            
            logger.info(f"Click performed with ActionChains for session {session_id}")
            return jsonify({
                "status": "success", 
                "message": f"Clicked at coordinates ({x}, {y}) using ActionChains"
            })
                
        except Exception as e:
            logger.error(f"Click operation failed for session {session_id}: {str(e)}", exc_info=True)
            return jsonify({"status": "error", "message": f"Click error: {str(e)}"})
            
    except Exception as e:
        logger.error(f"Error during click operation: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Click error: {str(e)}"})

@app.route('/scroll', methods=['POST'])
def scroll():
    """Perform a scroll action in the browser."""
    session_id = get_session_id()
    
    try:
        delta_x = request.json.get('deltaX', 0)
        delta_y = request.json.get('deltaY', 0)
        logger.info(f"Received scroll request with deltaX={delta_x}, deltaY={delta_y} for session {session_id}")
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Validate scroll values
        try:
            delta_x = float(delta_x)
            delta_y = float(delta_y)
        except (TypeError, ValueError):
            return jsonify({"status": "error", "message": "Invalid scroll values"})
        
        # Apply scroll speed factor based on the magnitude
        # This provides smoother scrolling for both small and large scroll events
        def apply_scroll_factor(delta):
            # Use different factors for different magnitudes
            if abs(delta) < 50:
                return delta * 0.5  # Smooth for small scrolls
            elif abs(delta) < 100:
                return delta * 0.3  # Medium scroll speed
            else:
                return delta * 0.2  # Slower for large scrolls
        
        scroll_x = apply_scroll_factor(delta_x)
        scroll_y = apply_scroll_factor(delta_y)
        
        # Cap maximum scroll amount
        MAX_SCROLL = 300
        scroll_x = max(min(scroll_x, MAX_SCROLL), -MAX_SCROLL)
        scroll_y = max(min(scroll_y, MAX_SCROLL), -MAX_SCROLL)
        
        # Execute JavaScript to scroll the page and get the new position
        script = """
            // Get current scroll position
            const oldX = window.scrollX;
            const oldY = window.scrollY;
            
            // Perform scroll
            window.scrollBy(%f, %f);
            
            // Get new position and bounds
            const maxX = Math.max(0, document.documentElement.scrollWidth - window.innerWidth);
            const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
            
            // Return scroll info
            return {
                position: [window.scrollX, window.scrollY],
                delta: [window.scrollX - oldX, window.scrollY - oldY],
                bounds: [maxX, maxY]
            };
        """ % (scroll_x, scroll_y)
        
        scroll_info = session.browser.execute_script(script)
        
        logger.info(f"Scroll result for session {session_id}: {scroll_info}")
        
        return jsonify({
            "status": "success",
            "message": f"Scrolled by ({scroll_x}, {scroll_y})",
            "scroll_info": scroll_info,
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
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Use ActionChains to send the text to the active element
        actions = ActionChains(session.browser)
        actions.send_keys(text)
        actions.perform()
        
        logger.info(f"Text input sent: '{text}' for session {session_id}")
        
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
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Map the key to Selenium Keys
        selenium_key = KEY_MAPPING.get(key)
        
        # Use ActionChains to send the key with shift modifier only
        actions = ActionChains(session.browser)
        
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
    session = session_manager.get_session(session_id)
    
    with session.screenshot_lock:
        return jsonify({"filename": session.current_screenshot})

@app.route('/get_screenshot_data')
def get_screenshot_data():
    """Get the base64 encoded data of the latest screenshot for direct streaming."""
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    
    with session.screenshot_lock:
        return jsonify({"data": session.current_screenshot_data})

@app.route('/screenshots/<filename>')
def serve_screenshot(filename):
    """Serve a screenshot file."""
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    return send_from_directory(session.screenshot_dir, filename)

@app.route('/browser_status')
def browser_status():
    """Check if browser is running for the current session."""
    session_id = get_session_id()
    session = session_manager.get_session(session_id)
    is_running = session.browser is not None
    logger.info(f"Browser status check for session {session_id}: {'running' if is_running else 'not running'}")
    return jsonify({"running": is_running})

@app.route('/system_info')
def system_info():
    """Get system information for debugging."""
    import platform
    import sys
    
    # Count active sessions
    active_sessions = sum(1 for session in session_manager.sessions.values() if session.browser is not None)
    
    info = {
        "platform": platform.platform(),
        "python_version": sys.version,
        "selenium_version": webdriver.__version__,
        "flask_version": app.version,
        "screenshot_dir": SCREENSHOT_DIR,
        "active_sessions": active_sessions,
        "total_sessions_created": len(session_manager.sessions),
        "screenshot_interval": f"{SCREENSHOT_INTERVAL} seconds",
        "max_screenshots": MAX_SCREENSHOTS
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
        
        # Get session and browser
        session = session_manager.get_session(session_id)
        if session.browser is None:
            logger.info(f"Browser not started for session {session_id}, auto-starting...")
            try:
                session.browser = setup_browser(session_id)
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Get current URL
        current_url = session.browser.current_url
        
        # Get current HTML content
        html_content = session.browser.page_source
        
        # Get screenshot
        screenshot_data = session.browser.get_screenshot_as_base64()
        
        # Create timestamp
        timestamp = datetime.now().isoformat()
        
        # Generate filename base
        filename_base = f"page_capture_{timestamp.replace(':', '-').replace('.', '_')}"
        
        # Create a ZIP file in memory
        memory_zip = BytesIO()
        with zipfile.ZipFile(memory_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add HTML content
            zf.writestr(f"{filename_base}.html", html_content)
            
            # Add screenshot
            zf.writestr(f"{filename_base}.png", base64.b64decode(screenshot_data))
            
            # Create and add metadata
            metadata = {
                'url': current_url,
                'timestamp': timestamp,
                'wallet_address': wallet_address,
                'html_file': f"{filename_base}.html",
                'screenshot_file': f"{filename_base}.png",
                'session_id': session_id
            }
            zf.writestr(f"{filename_base}.json", json.dumps(metadata, indent=2))
        
        # Prepare the zip file for download
        memory_zip.seek(0)
        
        logger.info(f"Page info saved for session {session_id}: URL={current_url}, Timestamp={timestamp}")
        
        return send_file(
            memory_zip,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{filename_base}.zip"
        )
        
    except Exception as e:
        logger.error(f"Error saving page info for session {session_id}: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error saving page info: {str(e)}"})

@app.route('/list_saved_pages')
def list_saved_pages():
    """List all saved pages for the current session."""
    session_id = get_session_id()
    
    try:
        # Get the saved pages directory for this session
        save_dir = os.path.join(SCREENSHOT_DIR, session_id, 'saved_pages')
        if not os.path.exists(save_dir):
            return jsonify({
                "status": "success",
                "message": "No saved pages found",
                "pages": []
            })
        
        # Find all JSON metadata files
        metadata_files = glob.glob(os.path.join(save_dir, "page_capture_*.json"))
        pages = []
        
        for metadata_file in metadata_files:
            try:
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                    # Add file paths to metadata
                    metadata['files'] = {
                        'html': os.path.basename(metadata_file).replace('.json', '.html'),
                        'screenshot': os.path.basename(metadata_file).replace('.json', '.png'),
                        'metadata': os.path.basename(metadata_file)
                    }
                    pages.append(metadata)
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_file}: {str(e)}")
        
        # Sort pages by timestamp, newest first
        pages.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return jsonify({
            "status": "success",
            "message": f"Found {len(pages)} saved pages",
            "pages": pages
        })
        
    except Exception as e:
        logger.error(f"Error listing saved pages for session {session_id}: {str(e)}")
        return jsonify({"status": "error", "message": f"Error listing saved pages: {str(e)}"})

@app.route('/download_saved_page/<filename>')
def download_saved_page(filename):
    """Download a saved page file (HTML, screenshot, or metadata)."""
    session_id = get_session_id()
    
    try:
        # Get the saved pages directory for this session
        save_dir = os.path.join(SCREENSHOT_DIR, session_id, 'saved_pages')
        
        # Ensure the file exists
        file_path = os.path.join(save_dir, filename)
        if not os.path.exists(file_path):
            return jsonify({
                "status": "error",
                "message": "File not found"
            }), 404
        
        # Determine content type based on file extension
        content_type = 'application/json'  # default
        if filename.endswith('.html'):
            content_type = 'text/html'
        elif filename.endswith('.png'):
            content_type = 'image/png'
        
        return send_from_directory(
            save_dir,
            filename,
            mimetype=content_type,
            as_attachment=True
        )
        
    except Exception as e:
        logger.error(f"Error downloading file {filename} for session {session_id}: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error downloading file: {str(e)}"
        }), 500

def cleanup_temp_files():
    """Clean up temporary files on application exit."""
    try:
        logger.info(f"Cleaning up temporary directory: {SCREENSHOT_DIR}")
        # Clean up screenshot directory
        shutil.rmtree(SCREENSHOT_DIR, ignore_errors=True)
        
        # Clean up any remaining sessions
        for session_id, session in session_manager.sessions.items():
            try:
                session.cleanup()
                logger.info(f"Cleaned up session {session_id}")
            except Exception as e:
                logger.error(f"Error cleaning up session {session_id}: {str(e)}")
                
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