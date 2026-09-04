import os
import time
import pickle
import logging
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException, NoSuchElementException
from dotenv import load_dotenv

load_dotenv()

class FacebookManager:
    def __init__(self, headless=True):
        self.local_dir = os.path.dirname(os.path.realpath(__file__))
        self.setup_logging()
        self.driver = self.setup_driver(headless)
        self.email = os.getenv('FB_EMAIL')
        self.password = os.getenv('FB_PASSWORD')
        
    def setup_logging(self):
        """Setup logging configuration"""
        logfile = os.path.join(self.local_dir, 'facebook_manager.log')
        logging.basicConfig(
            filename=logfile,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
    @staticmethod
    def _find_browser():
        """Return (binary_path, driver_path) for the first usable Chrome/Chromium pair."""
        import shutil, subprocess
        candidates = [
            ("google-chrome", None),
            ("google-chrome-stable", None),
            ("chromium-browser", None),
            ("chromium", None),
            ("/snap/bin/chromium", "/snap/bin/chromium.chromedriver"),
            ("/usr/bin/chromium-browser", "/usr/bin/chromedriver"),
        ]
        for browser, driver in candidates:
            binary = shutil.which(browser) or (browser if os.path.exists(browser) else None)
            if not binary:
                continue
            drv = driver or shutil.which("chromedriver") or "/usr/bin/chromedriver"
            if os.path.exists(drv):
                return binary, drv
        raise RuntimeError("No compatible Chrome/Chromium browser found for Selenium")

    def setup_driver(self, headless):
        """Setup and return Chrome driver with auto-detected browser."""
        binary, drv_path = self._find_browser()
        chrome_options = Options()
        if headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument(f"--user-data-dir={os.path.join(self.local_dir, 'chrome_user_data')}")
        chrome_options.binary_location = binary
        logging.info(f"Using browser: {binary} | driver: {drv_path}")
        service = Service(drv_path)
        return webdriver.Chrome(service=service, options=chrome_options)

    def check_if_logged_in(self):
        """Check if already logged in to Facebook"""
        try:
            logging.info("Checking if already logged in...")
            self.driver.get("https://www.facebook.com")
            wait = WebDriverWait(self.driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Home"], [aria-label="Messenger"]')))
            logging.info("Already logged in!")
            return True
        except:
            logging.info("Not logged in.")
            return False

    def login_and_save_cookies(self):
        """Perform login with step-by-step screenshots"""
        self.driver.get("https://www.facebook.com")
        wait = WebDriverWait(self.driver, 20)
        
        try:
            # Initial page screenshot
            self.driver.save_screenshot(os.path.join(self.local_dir, "1_initial_page.png"))
            logging.info("1. Loaded initial page")
            time.sleep(5)
            
            # Enter email
            email_field = wait.until(EC.element_to_be_clickable((By.ID, "email")))
            email_field.clear()
            email_field.send_keys(self.email)
            self.driver.save_screenshot(os.path.join(self.local_dir, "2_after_email_entry.png"))
            logging.info("2. Entered email")
            time.sleep(5)
            
            # Click Continue
            continue_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="login"]')))
            continue_button.click()
            self.driver.save_screenshot(os.path.join(self.local_dir, "3_after_continue.png"))
            logging.info("3. Clicked continue")
            time.sleep(5)
            
            # Enter password
            pass_field = wait.until(EC.element_to_be_clickable((By.ID, "pass")))
            pass_field.clear()
            pass_field.send_keys(self.password)
            self.driver.save_screenshot(os.path.join(self.local_dir, "4_after_password.png"))
            logging.info("4. Entered password")
            time.sleep(5)
            
            # Final login click
            login_button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[name="login"]')))
            login_button.click()
            time.sleep(5)
            self.driver.save_screenshot(os.path.join(self.local_dir, "5_after_login_click.png"))
            logging.info("5. Clicked login")
            
            # Verify login success
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[aria-label="Home"], [aria-label="Messenger"]')))
            logging.info("Login successful!")
            
            # Save cookies
            with open(os.path.join(self.local_dir, 'facebook_cookies.pkl'), 'wb') as file:
                pickle.dump(self.driver.get_cookies(), file)
            logging.info("Saved cookies")
            
            return True
                
        except Exception as e:
            logging.error(f"Login failed: {str(e)}")
            self.driver.save_screenshot(os.path.join(self.local_dir, "login_error.png"))
            return False

    def load_cookies(self):
        """Load saved cookies and check login status"""
        try:
            cookie_file = os.path.join(self.local_dir, 'facebook_cookies.pkl')
            
            # First check if already logged in
            if self.check_if_logged_in():
                return True
                
            # If not logged in but cookies exist, try loading them
            if os.path.exists(cookie_file):
                self.driver.get('https://www.facebook.com/')
                logging.info("Opened Facebook for loading cookies")
                
                with open(cookie_file, 'rb') as file:
                    cookies = pickle.load(file)
                    for cookie in cookies:
                        self.driver.add_cookie(cookie)
                logging.info("Loaded cookies")
                
                self.driver.refresh()
                logging.info("Refreshed browser with loaded cookies")
                
                # Check if cookies worked
                if self.check_if_logged_in():
                    return True
            
            # If not logged in, try fresh login
            logging.info("Performing fresh login...")
            return self.login_and_save_cookies()
            
        except Exception as e:
            logging.error(f"Failed to load cookies: {e}")
            return self.login_and_save_cookies()

    def send_message(self, thread_id, message=None, file_path=None):
        """Send message and/or file to a Facebook thread"""
        try:
            # Navigate to thread
            self.driver.get(f'https://www.facebook.com/messages/t/{thread_id}')
            logging.info(f"Navigated to thread {thread_id}")

            # Handle potential popups
            try:
                close_popup = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//button[text()="Not Now"]'))
                )
                close_popup.click()
                logging.info("Dismissed popup")
            except TimeoutException:
                logging.info("No popup to dismiss")

            # FB rotates the composer's attributes frequently. Try several
            # selectors in order of specificity, then fall back to the last
            # contenteditable role=textbox on the page (Messenger composer is
            # below the chat search bar in the DOM, so the last match works).
            composer_selectors = [
                (By.CSS_SELECTOR, 'div[contenteditable="true"][data-lexical-editor="true"]'),
                (By.CSS_SELECTOR, 'div[role="textbox"][contenteditable="true"][aria-placeholder]'),
                (By.XPATH,
                 '//div[@role="textbox" and @contenteditable="true" and ('
                 'contains(@aria-label, "Message") or '
                 'contains(@aria-placeholder, "Message") or '
                 '@aria-label="Type a message..." or '
                 '@aria-placeholder="Aa" or @aria-label="Aa"'
                 ')]'),
                (By.CSS_SELECTOR, 'div[role="textbox"][contenteditable="true"]'),
            ]

            message_input = None
            wait = WebDriverWait(self.driver, 20)
            for by, sel in composer_selectors:
                try:
                    elements = wait.until(
                        lambda d, b=by, s=sel: d.find_elements(b, s) or False
                    )
                    if elements:
                        message_input = elements[-1]
                        logging.info(
                            f"Matched composer with {by}={sel} "
                            f"(found {len(elements)}, using last)"
                        )
                        break
                except TimeoutException:
                    continue

            if message_input is None:
                # Dump page source to disk for offline diagnosis of FB DOM.
                try:
                    src_path = os.path.join(self.local_dir, "message_error_page.html")
                    with open(src_path, "w", encoding="utf-8") as f:
                        f.write(self.driver.page_source)
                    logging.error(f"Composer not found; saved page source to {src_path}")
                except Exception as dump_err:
                    logging.error(f"Composer not found; failed to dump page source: {dump_err}")
                raise TimeoutException("Could not locate Messenger composer with any known selector")

            # Send file if provided
            if file_path:
                if not os.path.exists(file_path):
                    logging.error(f"File not found: {file_path}")
                    return False
                
                file_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="file"]')
                file_input.send_keys(os.path.abspath(file_path))
                logging.info(f"Attached file: {file_path}")
                time.sleep(3)  # Wait for file to upload

            # Send message if provided
            if message:
                self._type_unicode_message(message_input, message)
                message_input.send_keys(Keys.RETURN)
                logging.info("Sent message text")

            time.sleep(2)  # Wait for message to send
            logging.info(f"Successfully sent content to thread {thread_id}")
            return True

        except Exception as e:
            logging.error(f"Failed to send message: {e}")
            self.driver.save_screenshot(os.path.join(self.local_dir, "message_error.png"))
            return False

    def _type_unicode_message(self, element, text):
        """Type text into a focused contenteditable composer with full Unicode support.

        ChromeDriver's send_keys can't transmit non-BMP code points (most emojis
        live at U+1F000+ and would raise "ChromeDriver only supports characters
        in the BMP"). We therefore use the Chrome DevTools Protocol's
        Input.insertText for each line, which fires real input/beforeinput
        events and accepts arbitrary Unicode. Newlines are produced by
        Shift+Enter so Messenger inserts a line break instead of sending.
        """
        element.click()  # ensure composer has focus
        for i, line in enumerate(text.split("\n")):
            if i > 0:
                element.send_keys(Keys.SHIFT + Keys.ENTER)
            if line:
                self.driver.execute_cdp_cmd("Input.insertText", {"text": line})

    def close(self):
        """Close the browser"""
        try:
            self.driver.quit()
            logging.info("Closed browser")
        except Exception as e:
            logging.error(f"Error closing browser: {e}")

def init_facebook():
    """Initialize FacebookManager and ensure login"""
    fb = FacebookManager(headless=True)
    if fb.load_cookies():
        return fb
    fb.close()
    return None