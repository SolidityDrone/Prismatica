from flask import Flask, request, render_template, jsonify, send_from_directory
import subprocess
import os
import time
import threading
import logging
import tempfile
import glob
import base64
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

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('remote_browser')

app = Flask(__name__)
# Enable CORS for all routes
CORS(app, resources={r"/*": {"origins": "*"}})

# Create a temporary directory for screenshots
SCREENSHOT_DIR = tempfile.mkdtemp(prefix="browser_screenshots_")
logger.info(f"Using temporary directory for screenshots: {SCREENSHOT_DIR}")

# Global variables
browser = None
screenshot_thread = None
keep_taking_screenshots = True
current_screenshot = "placeholder.png"
current_screenshot_data = None  # Base64 encoded screenshot data
screenshot_lock = threading.Lock()
browser_lock = threading.Lock()
MAX_SCREENSHOTS = 3  # Keep fewer screenshots to reduce disk I/O
SCREENSHOT_INTERVAL = 0.05  # Take screenshots every 0.05 seconds (20 FPS)

# Simplified key mapping with only the allowed keys
KEY_MAPPING = {
    'ENTER': Keys.ENTER,
    'BACK_SPACE': Keys.BACK_SPACE
}

def setup_browser():
    """Initialize the headless browser with detailed logging."""
    global browser
    
    with browser_lock:
        if browser is not None:
            logger.info("Browser already running, reusing existing instance")
            return browser
        
        try:
            logger.info("Setting up Chrome browser...")
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--disable-extensions")
            chrome_options.add_argument("--disable-dev-tools")
            chrome_options.add_argument("--remote-debugging-port=9222")  # Add debugging port
            
            # Use the system Chrome binary
            chrome_binary_path = "/snap/bin/chromium"  # Path to Chrome binary
            chrome_options.binary_location = chrome_binary_path
            
            # Set path to chromedriver - use the local chromedriver in the project
            chromedriver_path = "./chromedriver-linux64/chromedriver"  # Local chromedriver path
            service = Service(chromedriver_path)
            
            logger.info("Creating Chrome webdriver instance...")
            browser = webdriver.Chrome(service=service, options=chrome_options)
            browser.set_window_size(1920, 1080)
            logger.info("Chrome webdriver instance created successfully")
            
            logger.info("Navigating to initial page (Google)...")
            browser.get("https://www.google.com")
            logger.info("Initial navigation successful")
            
            # Start screenshot thread if not already running
            start_screenshot_thread()
            
            return browser
        except Exception as e:
            logger.error(f"Failed to initialize browser: {str(e)}", exc_info=True)
            if browser:
                try:
                    browser.quit()
                except:
                    pass
                browser = None
            raise

def cleanup_old_screenshots():
    """Delete old screenshots, keeping only the most recent ones."""
    try:
        # Get all screenshot files sorted by modification time (newest first)
        files = sorted(
            glob.glob(os.path.join(SCREENSHOT_DIR, "screenshot-*.png")),
            key=os.path.getmtime,
            reverse=True
        )
        
        # Keep only the MAX_SCREENSHOTS most recent files
        for old_file in files[MAX_SCREENSHOTS:]:
            try:
                os.remove(old_file)
                logger.debug(f"Deleted old screenshot: {old_file}")
            except Exception as e:
                logger.warning(f"Failed to delete old screenshot {old_file}: {str(e)}")
    except Exception as e:
        logger.error(f"Error cleaning up old screenshots: {str(e)}")

def start_screenshot_thread():
    """Start the screenshot thread if not already running."""
    global screenshot_thread, keep_taking_screenshots
    
    if screenshot_thread is None or not screenshot_thread.is_alive():
        logger.info("Starting screenshot thread...")
        keep_taking_screenshots = True
        screenshot_thread = threading.Thread(target=take_screenshots)
        screenshot_thread.daemon = True
        screenshot_thread.start()
        logger.info("Screenshot thread started")

def take_screenshots():
    """Take screenshots continuously at a higher frame rate with optimizations for lower latency."""
    global keep_taking_screenshots, current_screenshot, current_screenshot_data, browser
    
    logger.info("Screenshot thread running")
    last_cleanup_time = time.time()
    
    while keep_taking_screenshots:
        try:
            if browser is None:
                logger.warning("Browser is None, cannot take screenshot")
                time.sleep(0.5)
                continue
                
            start_time = time.time()
            
            # Take screenshot directly as PNG bytes
            screenshot_png = browser.get_screenshot_as_png()
            
            # Generate a timestamp for the filename
            timestamp = time.strftime("%Y%m%d-%H%M%S-%f")[:19]
            filename = f"screenshot-{timestamp}.png"
            filepath = os.path.join(SCREENSHOT_DIR, filename)
            
            # Process in parallel: update the base64 data immediately
            # while also writing to disk in the background
            base64_data = base64.b64encode(screenshot_png).decode('utf-8')
            
            # Update current screenshot data immediately for low latency
            with screenshot_lock:
                current_screenshot = filename
                current_screenshot_data = base64_data
            
            # Write to disk (this can be slow)
            with open(filepath, "wb") as f:
                f.write(screenshot_png)
            
            # Only clean up old screenshots periodically to reduce disk I/O
            current_time = time.time()
            if current_time - last_cleanup_time > 5.0:  # Clean up every 5 seconds
                cleanup_old_screenshots()
                last_cleanup_time = current_time
            
            # Adaptive sleep to maintain target frame rate
            elapsed = time.time() - start_time
            sleep_time = max(0.001, SCREENSHOT_INTERVAL - elapsed)  # Ensure at least 1ms sleep
            time.sleep(sleep_time)
            
        except Exception as e:
            logger.error(f"Error taking screenshot: {str(e)}", exc_info=True)
            time.sleep(0.5)

@app.route('/')
def index():
    """Render the main page."""
    return render_template('index.html')

@app.route('/start_browser', methods=['POST'])
def start_browser():
    """Start the browser and screenshot thread."""
    global browser
    
    try:
        logger.info("Received request to start browser")
        browser = setup_browser()
        return jsonify({"status": "success", "message": "Browser started"})
    except Exception as e:
        logger.error(f"Error starting browser: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})

@app.route('/stop_browser', methods=['POST'])
def stop_browser():
    """Stop the browser and screenshot thread."""
    global browser, keep_taking_screenshots
    
    try:
        logger.info("Received request to stop browser")
        keep_taking_screenshots = False
        
        with browser_lock:
            if browser:
                logger.info("Quitting browser...")
                browser.quit()
                browser = None
                logger.info("Browser stopped")
        
        return jsonify({"status": "success", "message": "Browser stopped"})
    except Exception as e:
        logger.error(f"Error stopping browser: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error stopping browser: {str(e)}"})

@app.route('/navigate', methods=['POST'])
def navigate():
    """Navigate to a URL with auto-start if browser not running."""
    global browser
    
    try:
        url = request.json.get('url')
        logger.info(f"Received navigation request to: {url}")
        
        if not url:
            logger.warning("Navigation request missing URL")
            return jsonify({"status": "error", "message": "URL is required"})
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Navigate to URL
        logger.info(f"Navigating to {url}...")
        browser.get(url)
        logger.info(f"Successfully navigated to {url}")
        
        return jsonify({"status": "success", "message": f"Navigated to {url}"})
    except Exception as e:
        logger.error(f"Error during navigation: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Navigation error: {str(e)}"})

@app.route('/click', methods=['POST'])
def click():
    """Perform a click at the specified coordinates with auto-start if needed."""
    global browser
    
    try:
        x = request.json.get('x')
        y = request.json.get('y') 
        logger.info(f"Received click request at coordinates ({x}, {y})")
        
        if x is None or y is None:
            logger.warning("Click request missing coordinates")
            return jsonify({"status": "error", "message": "X and Y coordinates are required"})
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Get the current window size
        window_size = browser.get_window_size()
        logger.info(f"Current window size: {window_size}")
        
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
        browser.execute_script(script)
        
        # Method 1: Try using elementFromPoint with direct click AND focus
        try:
            logger.info(f"Attempting direct element click at ({x}, {y})...")
            script = f"""
                try {{
                    // Get the element at the click position
                    const element = document.elementFromPoint({x}, {y});
                    // Log information about the element
                    const info = element ? {{
                        tagName: element.tagName,
                        id: element.id,
                        className: element.className,
                        text: element.innerText ? element.innerText.substring(0, 20) : ''
                    }} : null;
                    
                    if (element) {{
                        // First, try to focus the element if it's an input, textarea, or other focusable element
                        if (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || 
                            element.tagName === 'SELECT' || element.hasAttribute('contenteditable')) {{
                            element.focus();
                            console.log('Element focused:', element.tagName);
                        }}
                        
                        // Then perform the click
                        element.click();
                        
                        // Focus again after click for extra reliability
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
            result = browser.execute_script(script)
            logger.info(f"JavaScript click result: {result}")
            
            if result and result.get('success'):
                return jsonify({
                    "status": "success", 
                    "message": f"Clicked element at ({x}, {y}): {result.get('element')}"
                })
            
            # Method 2: Fall back to ActionChains with additional focus handling
            logger.info(f"Trying ActionChains click at ({x}, {y})...")
            from selenium.webdriver.common.action_chains import ActionChains
            
            # Reset position to (0,0) first to ensure consistent moves
            actions = ActionChains(browser)
            actions.move_by_offset(-10000, -10000)  # Move far out to reset position
            actions.perform()
            
            # Then move to the target and click
            actions = ActionChains(browser)
            actions.move_by_offset(x, y)
            actions.click()
            actions.perform()
            
            # Try to focus the element again after click
            browser.execute_script(f"""
                const element = document.elementFromPoint({x}, {y});
                if (element && (element.tagName === 'INPUT' || element.tagName === 'TEXTAREA' || 
                    element.tagName === 'SELECT' || element.hasAttribute('contenteditable'))) {{
                    element.focus();
                    console.log('Focus applied after ActionChains click');
                }}
            """)
            
            logger.info("Click performed with ActionChains")
            return jsonify({
                "status": "success", 
                "message": f"Clicked at coordinates ({x}, {y}) using ActionChains"
            })
                
        except Exception as e:
            logger.error(f"Click operation failed: {str(e)}", exc_info=True)
            return jsonify({"status": "error", "message": f"Click error: {str(e)}"})
            
    except Exception as e:
        logger.error(f"Error during click operation: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Click error: {str(e)}"})

@app.route('/scroll', methods=['POST'])
def scroll():
    """Perform a scroll action in the browser."""
    global browser
    
    try:
        delta_x = request.json.get('deltaX', 0)
        delta_y = request.json.get('deltaY', 0)
        logger.info(f"Received scroll request with deltaX={delta_x}, deltaY={delta_y}")
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
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
        scroll_position = browser.execute_script(script)
        
        logger.info(f"Scrolled by ({scroll_x}, {scroll_y}), new position: {scroll_position}")
        
        return jsonify({
            "status": "success",
            "message": f"Scrolled by ({scroll_x}, {scroll_y})",
            "position": scroll_position
        })
        
    except Exception as e:
        logger.error(f"Error during scroll operation: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Scroll error: {str(e)}"})

@app.route('/type_text', methods=['POST'])
def type_text():
    """Type text into the currently focused element."""
    global browser
    
    try:
        text = request.json.get('text', '')
        logger.info(f"Received text input: '{text}'")
        
        if not text:
            return jsonify({"status": "error", "message": "No text provided"})
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Use ActionChains to send the text to the active element
        actions = ActionChains(browser)
        actions.send_keys(text)
        actions.perform()
        
        logger.info(f"Text input sent: '{text}'")
        
        return jsonify({
            "status": "success",
            "message": f"Text input sent: '{text}'"
        })
        
    except Exception as e:
        logger.error(f"Error during text input: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Text input error: {str(e)}"})

@app.route('/send_key', methods=['POST'])
def send_key():
    """Send a special key to the browser (limited to Enter and Backspace)."""
    global browser
    
    try:
        key = request.json.get('key')
        modifiers = request.json.get('modifiers', {})
        logger.info(f"Received key input: {key} with modifiers: {modifiers}")
        
        if not key:
            return jsonify({"status": "error", "message": "No key provided"})
        
        # Only allow ENTER and BACK_SPACE
        if key not in KEY_MAPPING:
            return jsonify({"status": "error", "message": f"Unsupported key: {key}"})
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Map the key to Selenium Keys
        selenium_key = KEY_MAPPING.get(key)
        
        # Use ActionChains to send the key with shift modifier only
        actions = ActionChains(browser)
        
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
        
        logger.info(f"Key sent: {key} with modifiers: {modifiers}")
        
        return jsonify({
            "status": "success",
            "message": f"Key sent: {key}"
        })
        
    except Exception as e:
        logger.error(f"Error sending key: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Key input error: {str(e)}"})

@app.route('/get_latest_screenshot')
def get_latest_screenshot():
    """Get the filename of the latest screenshot."""
    with screenshot_lock:
        return jsonify({"filename": current_screenshot})

@app.route('/get_screenshot_data')
def get_screenshot_data():
    """Get the base64 encoded data of the latest screenshot for direct streaming."""
    with screenshot_lock:
        if current_screenshot_data:
            return jsonify({"data": current_screenshot_data})
        else:
            return jsonify({"data": None})

@app.route('/screenshots/<filename>')
def serve_screenshot(filename):
    """Serve a screenshot file."""
    return send_from_directory(SCREENSHOT_DIR, filename)

@app.route('/browser_status')
def browser_status():
    """Check if browser is running."""  
    is_running = browser is not None
    logger.info(f"Browser status check: {'running' if is_running else 'not running'}")
    return jsonify({"running": is_running})

@app.route('/system_info')
def system_info():
    """Get system information for debugging."""
    import platform
    import sys
    info = {
        "platform": platform.platform(),
        "python_version": sys.version,
        "selenium_version": webdriver.__version__,
        "flask_version": app.version,
        "screenshot_dir": SCREENSHOT_DIR,
        "screenshot_count": len(glob.glob(os.path.join(SCREENSHOT_DIR, "screenshot-*.png"))),
        "screenshot_interval": f"{SCREENSHOT_INTERVAL} seconds",
        "max_screenshots": MAX_SCREENSHOTS
    }
    logger.info(f"System info: {info}")
    return jsonify(info)

@app.route('/save_page_info', methods=['POST'])
def save_page_info():
    """Save the current page information including HTML content, URL, timestamp, and wallet address."""
    global browser
    
    try:
        # Get wallet address from request
        wallet_address = request.json.get('wallet_address', 'Not connected')
        logger.info(f"Saving page info with wallet address: {wallet_address}")
        
        # Auto-start browser if not running
        if browser is None:
            logger.info("Browser not started, auto-starting...")
            try:
                browser = setup_browser()
                logger.info("Browser auto-started successfully")
            except Exception as e:
                logger.error(f"Failed to auto-start browser: {str(e)}", exc_info=True)
                return jsonify({"status": "error", "message": f"Failed to start browser: {str(e)}"})
        
        # Get current URL
        current_url = browser.current_url
        
        # Get current HTML content
        html_content = browser.page_source
        
        # Get screenshot
        screenshot_data = browser.get_screenshot_as_base64()
        
        # Create timestamp
        timestamp = datetime.datetime.now().isoformat()
        
        # Create save directory if it doesn't exist
        save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_pages')
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
            'screenshot_file': f"{filename_base}.png"
        }
        
        metadata_path = os.path.join(save_dir, f"{filename_base}.json")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Page info saved: URL={current_url}, Timestamp={timestamp}")
        
        return jsonify({
            "status": "success",
            "message": "Page information saved successfully",
            "data": {
                "url": current_url,
                "timestamp": timestamp,
                "wallet_address": wallet_address,
                "files": {
                    "html": f"{filename_base}.html",
                    "screenshot": f"{filename_base}.png",
                    "metadata": f"{filename_base}.json"
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error saving page info: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"Error saving page info: {str(e)}"})

def cleanup_temp_files():
    """Clean up temporary files on application exit."""
    try:
        logger.info(f"Cleaning up temporary directory: {SCREENSHOT_DIR}")
        import shutil
        shutil.rmtree(SCREENSHOT_DIR, ignore_errors=True)
    except Exception as e:
        logger.error(f"Error cleaning up temporary directory: {str(e)}")

# Register cleanup function to run on exit
import atexit
atexit.register(cleanup_temp_files)

if __name__ == '__main__':
    # Create a placeholder screenshot
    placeholder_path = os.path.join(SCREENSHOT_DIR, "placeholder.png")
    if not os.path.exists(placeholder_path):
        img = Image.new('RGB', (1920, 1080), color='gray')
        img.save(placeholder_path)
    
    logger.info("Starting Flask application...")
    app.run(host='0.0.0.0', port=5000, debug=True)
