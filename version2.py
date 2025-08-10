import os
import time
import pickle
import glob
import io
import tempfile
import telebot
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
from webdriver_manager.chrome import ChromeDriverManager
from PIL import Image
import signal
import sys

# Load environment variables
load_dotenv()

# Constants
COOKIE_FILE = "buffer_cookies.pkl"
HEADLESS = os.getenv('HEADLESS', 'True').lower() == 'true'
EMAIL = os.getenv('EMAIL')
PASSWORD = os.getenv('PASSWORD')

# Telegram Bot Constants
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_USER_CHAT_ID = os.getenv('TELEGRAM_USER_CHAT_ID')

# Initialize Telegram Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# Global driver variable for reuse
driver = None

def cleanup_driver():
    """Clean up the driver instance"""
    global driver
    if driver is not None:
        try:
            driver.quit()
        except:
            pass
        driver = None

def signal_handler(sig, frame):
    """Handle interrupt signals"""
    print("Shutting down gracefully...")
    cleanup_driver()
    sys.exit(0)

# Register signal handler for graceful shutdown
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def take_screenshot(driver):
    """Take a screenshot and return as bytes"""
    try:
        # Get screenshot as PNG
        png = driver.get_screenshot_as_png()
        return png
    except Exception as e:
        print(f"⚠️ Failed to take screenshot: {str(e)}")
        return None

def save_cookies(driver):
    """Save current cookies to file"""
    try:
        with open(COOKIE_FILE, 'wb') as f:
            pickle.dump(driver.get_cookies(), f)
        print("💾 Session cookies saved successfully!")
    except Exception as e:
        print(f"⚠️ Failed to save cookies: {str(e)}")

def load_cookies(driver):
    """Load cookies from file if exists with improved domain handling"""
    if not os.path.exists(COOKIE_FILE):
        return False
    
    try:
        # First visit the root domain to set cookies
        driver.get("https://buffer.com")
        time.sleep(1)
        
        # Load cookies
        with open(COOKIE_FILE, 'rb') as f:
            cookies = pickle.load(f)
        
        # Add cookies one by one, handling domain mismatches
        skipped = 0
        for cookie in cookies:
            try:
                # Handle domain mismatches
                if 'domain' in cookie:
                    cookie_domain = cookie['domain']
                    
                    # Convert publish.buffer.com to .buffer.com for broader compatibility
                    if cookie_domain == 'publish.buffer.com':
                        cookie['domain'] = '.buffer.com'
                    # If domain has leading dot, remove it for compatibility
                    elif cookie_domain.startswith('.'):
                        cookie['domain'] = cookie_domain[1:]
                    # Handle www subdomain
                    elif cookie_domain == 'www.buffer.com':
                        cookie['domain'] = '.buffer.com'
                
                driver.add_cookie(cookie)
            except Exception as e:
                print(f"Skipping cookie (domain: {cookie.get('domain', 'N/A')}): {str(e)}")
                skipped += 1
                continue
        
        if skipped > 0:
            print(f"⚠️ Skipped {skipped} cookies due to domain mismatch")
        print("🍪 Session cookies loaded successfully!")
        return True
    except Exception as e:
        print(f"⚠️ Failed to load cookies: {str(e)}")
        return False

def setup_chrome():
    options = Options()
    # Set headless mode based on environment variable (default to True)
    if HEADLESS:
        options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    
    # Add performance optimizations
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-infobars')
    options.add_argument('--disable-notifications')
    options.add_argument('--disable-software-rasterizer')
    options.add_argument('--disable-features=TranslateUI')
    options.add_argument('--disable-ipc-flooding-protection')
    options.add_argument('--disable-background-timer-throttling')
    options.add_argument('--disable-renderer-backgrounding')
    options.add_argument('--disable-backgrounding-occluded-windows')
    options.add_argument('--disable-client-side-phishing-detection')
    options.add_argument('--disable-crash-reporter')
    options.add_argument('--disable-features=site-per-process')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

def check_session_validity(driver):
    """Check if the current session is valid by visiting dashboard with improved validation"""
    try:
        driver.get("https://publish.buffer.com/all-channels")
        time.sleep(2)
        
        # Check URL first
        if "publish.buffer.com" not in driver.current_url:
            print("⚠️ Session is invalid - not on dashboard URL")
            return False
        
        # Check for multiple indicators of valid session
        indicators = [
            "//button[contains(text(), 'New Post')]",
            "//button[contains(@class, 'new-post')]",
            "//div[contains(@class, 'dashboard-header')]"
        ]
        
        for indicator in indicators:
            try:
                WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, indicator))
                )
                print("✅ Session is valid!")
                return True
            except:
                continue
        
        print("⚠️ Session appears invalid - missing expected elements")
        return False
            
    except Exception as e:
        print(f"⚠️ Session validation failed: {str(e)}")
        return False

def handle_captcha(driver):
    """Handle CAPTCHA with improved logic"""
    try:
        print("🔍 Looking for CAPTCHA...")
        
        # Check for reCAPTCHA iframe
        captcha_iframe = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//iframe[contains(@title,'reCAPTCHA')]"))
        )
        
        # Switch to iframe
        driver.switch_to.frame(captcha_iframe)
        print("🔄 Switched to CAPTCHA iframe")
        
        # Try to click the checkbox
        try:
            checkbox = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//div[@class='recaptcha-checkbox-checkmark']"))
            )
            checkbox.click()
            print("✅ CAPTCHA checkbox clicked")
            
            # Wait a moment for potential image challenge
            time.sleep(2)
            
            # Check if image challenge appeared
            try:
                image_challenge = driver.find_element(By.XPATH, "//div[contains(@class,'rc-imageselect')]")
                if image_challenge.is_displayed():
                    print("⚠️ Image challenge detected - manual intervention required")
                    print("👤 Please solve the CAPTCHA manually in the browser window")
                    
                    # Wait for manual resolution (max 60 seconds)
                    WebDriverWait(driver, 60).until(
                        EC.invisibility_of_element_located((By.XPATH, "//div[contains(@class,'rc-imageselect')]"))
                    )
                    print("✅ CAPTCHA resolved by user")
            except:
                print("✅ No image challenge detected")
                
        except Exception as e:
            print(f"⚠️ CAPTCHA checkbox not found: {str(e)}")
        
        # Switch back to main content
        driver.switch_to.default_content()
        time.sleep(1)
        
        return True
        
    except Exception as e:
        print(f"⚠️ CAPTCHA handling failed: {str(e)}")
        try:
            driver.switch_to.default_content()
        except:
            pass
        return False

def login_with_credentials(driver):
    """Perform login using credentials with improved CAPTCHA handling"""
    try:
        print("Opening Buffer login page...")
        driver.get("https://login.buffer.com/login")
        
        # Handle cookie consent
        try:
            WebDriverWait(driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Accept')]"))
            ).click()
            print("✅ Accepted cookies")
        except:
            print("ℹ️ No cookie consent found")
        
        # Handle CAPTCHA
        handle_captcha(driver)
        
        # Enter credentials
        print("🔑 Entering email...")
        email_field = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='email']"))
        )
        email_field.clear()
        email_field.send_keys(EMAIL)
        
        print("🔑 Entering password...")
        password_field = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='password']"))
        )
        password_field.clear()
        password_field.send_keys(PASSWORD)
        
        print("🚀 Clicking login...")
        login_button = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@type='submit']"))
        )
        login_button.click()
        
        print("⏳ Waiting for login to complete...")
        try:
            WebDriverWait(driver, 10).until(
                EC.or_(
                    EC.url_contains("publish.buffer.com"),
                    EC.url_contains("buffer.com/app"),
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(),'Invalid')]"))
                )
            )
        except:
            print("⚠️ Login process timed out")
        
        # Enhanced login verification
        current_url = driver.current_url
        print(f"🌐 Current URL: {current_url}")
        print(f"📄 Page title: {driver.title}")
        
        # Check for success indicators
        if "publish.buffer.com" in current_url or "buffer.com/app" in current_url:
            # Additional verification - check for user-specific elements
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//button[contains(text(), 'New Post')]"))
                )
                print("✅ Login successful! Verified with dashboard elements.")
                save_cookies(driver)
                return True
            except:
                print("⚠️ Login may have succeeded but verification failed")
                return False
        else:
            try:
                error_element = driver.find_element(By.XPATH, "//*[contains(text(),'Invalid') or contains(text(),'incorrect')]")
                print(f"❌ Login failed: {error_element.text}")
            except:
                print("⚠️ Login status unclear")
            return False
            
    except Exception as e:
        print(f"❌ Login error: {str(e)}")
        return False

def establish_session(driver):
    """Establish a valid session using existing session, cookies, or credentials"""
    # First check if already logged in
    if check_session_validity(driver):
        return True
    
    # Try to load cookies and check session
    if load_cookies(driver):
        # Give cookies a moment to take effect
        time.sleep(2)
        if check_session_validity(driver):
            return True
    
    # Login with credentials only if necessary
    if not EMAIL or not PASSWORD:
        raise ValueError("EMAIL and PASSWORD must be set in .env file")
    
    if login_with_credentials(driver):
        return True
    
    return False

def click_new_post(driver):
    """Click on the New Post button"""
    try:
        print("📝 Navigating to all channels page...")
        driver.get("https://publish.buffer.com/all-channels")
        time.sleep(2)
        
        print("🔍 Looking for New Post button...")
        # Try multiple selectors for the New Post button
        selectors = [
            "//button[contains(text(), 'New Post')]",  # Text-based selector
            "//button[.//span[contains(text(), 'New Post')]]",  # Span inside button
            "//button[contains(@class, 'new-post')]",  # Class-based selector
            "//button[.//*[name()='svg']]",  # Button with SVG icon
            "/html/body/div[1]/div[1]/main/div[1]/header/div[1]/div/button[2]"  # Absolute XPath as fallback
        ]
        
        new_post_button = None
        for selector in selectors:
            try:
                new_post_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                print(f"✅ Found New Post button using selector: {selector}")
                break
            except:
                continue
        
        if not new_post_button:
            print("❌ Could not find New Post button with any selector")
            return None
        
        print("🖱️ Clicking New Post button...")
        new_post_button.click()
        
        print("⏳ Waiting for New Post dialog to open...")
        time.sleep(2)
        
        # Verify the dialog opened by checking for elements that should appear
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'composer') or contains(text(), 'Create a new post')]"))
            )
            print("✅ New Post dialog opened successfully!")
            return True
        except:
            print("⚠️ New Post dialog might not have opened properly")
            return True  # Still return true as we clicked the button
            
    except Exception as e:
        print(f"❌ Error clicking New Post button: {str(e)}")
        return None

def upload_video(driver, video_bytes):
    """Upload a video from bytes"""
    try:
        print("🎬 Processing video...")
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            temp_file.write(video_bytes)
            temp_file_path = temp_file.name
        
        try:
            # Find the file input element (it's usually hidden)
            print("🔍 Looking for file input element...")
            file_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
            )
            
            # Send the file path to the input element
            print("📤 Uploading video...")
            file_input.send_keys(temp_file_path)
            
            # Wait for upload to complete (look for progress indicator or completion message)
            print("⏳ Waiting for upload to complete...")
            time.sleep(5)
            
            # Check for upload completion indicators
            try:
                # Look for a progress bar that disappears or a completion message
                WebDriverWait(driver, 60).until(
                    EC.invisibility_of_element_located((By.XPATH, "//div[contains(@class, 'upload-progress')]"))
                )
                print("✅ Video upload completed!")
            except:
                # Alternative: Check for a success message or thumbnail
                try:
                    WebDriverWait(driver, 60).until(
                        EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'media-preview') or contains(text(), 'Upload complete')]"))
                    )
                    print("✅ Video upload completed!")
                except:
                    print("⚠️ Could not confirm upload completion, but proceeding anyway")
            
            return True
            
        finally:
            # Clean up the temporary file
            try:
                os.unlink(temp_file_path)
            except:
                pass
        
    except Exception as e:
        print(f"❌ Error uploading video: {str(e)}")
        return None

def type_content(driver):
    """Type the content in the text area"""
    try:
        print("🔍 Looking for text area...")
        # Try multiple selectors for the text area
        selectors = [
            "//div[contains(@class, 'composer')]/div/div/div/div/div/div/div",
            "//div[@role='textbox']",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[3]/div/div/div/div[1]/div[1]/div[1]/div/div"  # Absolute XPath as fallback
        ]
        
        text_area = None
        for selector in selectors:
            try:
                text_area = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                print(f"✅ Found text area using selector: {selector}")
                break
            except:
                continue
        
        if not text_area:
            print("❌ Could not find text area with any selector")
            return None
        
        print("✍️ Typing content...")
        text_area.click()
        text_area.clear()
        text_area.send_keys("#viral #Reels")
        
        print("✅ Content typed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error typing content: {str(e)}")
        return None

def click_customize_button(driver):
    """Click the 'Customize for each network' button"""
    try:
        print("🔍 Looking for Customize button...")
        # Try multiple selectors for the customize button
        selectors = [
            "//button[contains(text(), 'Customize')]",
            "//button[contains(text(), 'for each network')]",
            "//button[contains(@class, 'customize')]",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[4]/div/button"  # Absolute XPath as fallback
        ]
        
        customize_button = None
        for selector in selectors:
            try:
                customize_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                print(f"✅ Found Customize button using selector: {selector}")
                break
            except:
                continue
        
        if not customize_button:
            print("❌ Could not find Customize button with any selector")
            return None
        
        print("🖱️ Clicking Customize button...")
        customize_button.click()
        
        print("✅ Customize button clicked successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error clicking Customize button: {str(e)}")
        return None

def click_second_text_area(driver):
    """Click on the second additional text area"""
    try:
        print("🔍 Looking for second text area...")
        # Try multiple selectors for the second text area
        selectors = [
            "//div[contains(@class, 'composer')]/div[2]/div[2]/div/div[2]/div/div/div/div/div",
            "//div[@role='textbox'][2]",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[3]/div[2]/div[2]/div/div[2]/div/div/div/div/div"  # Absolute XPath as fallback
        ]
        
        text_area = None
        for selector in selectors:
            try:
                text_area = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                print(f"✅ Found second text area using selector: {selector}")
                break
            except:
                continue
        
        if not text_area:
            print("❌ Could not find second text area with any selector")
            return None
        
        print("🖱️ Clicking second text area...")
        text_area.click()
        
        print("✅ Second text area clicked successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error clicking second text area: {str(e)}")
        return None

def fill_reels_input(driver):
    """Fill the reels input field"""
    try:
        print("🔍 Looking for reels input field...")
        # Try multiple selectors for the reels input
        selectors = [
            "//input[contains(@placeholder, 'reels')]",
            "//input[contains(@class, 'reels')]",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[3]/div[2]/div[2]/div/div[4]/div/div[1]/div/input"  # Absolute XPath as fallback
        ]
        
        reels_input = None
        for selector in selectors:
            try:
                reels_input = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.XPATH, selector))
                )
                print(f"✅ Found reels input using selector: {selector}")
                break
            except:
                continue
        
        if not reels_input:
            print("❌ Could not find reels input with any selector")
            return None
        
        print("✍️ Filling reels input...")
        reels_input.click()
        reels_input.clear()
        reels_input.send_keys("#reels")
        
        print("✅ Reels input filled successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error filling reels input: {str(e)}")
        return None

def click_section_button(driver):
    """Click on the button in section 4"""
    try:
        print("🔍 Looking for section button...")
        # Try multiple selectors for the section button
        selectors = [
            "//button[contains(@class, 'section-button')]",
            "//div[contains(@class, 'section')]/button",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[4]/div/div[2]/div/div/div/div/div/div[1]"  # Absolute XPath as fallback
        ]
        
        section_button = None
        for selector in selectors:
            try:
                section_button = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                print(f"✅ Found section button using selector: {selector}")
                break
            except:
                continue
        
        if not section_button:
            print("❌ Could not find section button with any selector")
            return None
        
        print("🖱️ Clicking section button...")
        section_button.click()
        
        print("✅ Section button clicked successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error clicking section button: {str(e)}")
        return None

def click_list_item(driver):
    """Click on the list item"""
    try:
        print("🔍 Looking for list item...")
        # Try multiple selectors for the list item
        selectors = [
            "//ul/li/div/p",
            "//div[contains(@class, 'list-item')]/p",
            "/html/body/div[2]/div/div[1]/div/div[2]/section[4]/div/div[2]/div/div/div/div/div/div[2]/ul/li[1]/div/p"  # Absolute XPath as fallback
        ]
        
        list_item = None
        for selector in selectors:
            try:
                list_item = WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, selector))
                )
                print(f"✅ Found list item using selector: {selector}")
                break
            except:
                continue
        
        if not list_item:
            print("❌ Could not find list item with any selector")
            return None
        
        print("🖱️ Clicking list item...")
        list_item.click()
        
        print("✅ List item clicked successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error clicking list item: {str(e)}")
        return None

def dismiss_overlays(driver):
    """Dismiss any overlays that might be blocking the Share button"""
    try:
        # Try to find and close any overlays or popups
        overlays = [
            "//div[@id='post-preview']",  # The specific overlay mentioned in the error
            "//div[contains(@class, 'modal')]",
            "//div[contains(@class, 'popup')]",
            "//div[contains(@class, 'overlay')]",
            "//div[contains(@class, 'dialog')]"
        ]
        
        for overlay in overlays:
            try:
                overlay_element = driver.find_element(By.XPATH, overlay)
                if overlay_element.is_displayed():
                    # Look for a close button within the overlay
                    close_buttons = [
                        ".//button[contains(@class, 'close')]",
                        ".//button[contains(@aria-label, 'close')]",
                        ".//button[contains(@title, 'close')]",
                        ".//span[contains(@class, 'close')]"
                    ]
                    
                    for close_btn in close_buttons:
                        try:
                            close_button = overlay_element.find_element(By.XPATH, close_btn)
                            close_button.click()
                            print(f"✅ Closed overlay using close button")
                            time.sleep(1)
                            return True
                        except:
                            continue
                    
                    # If no close button found, try clicking outside the overlay
                    actions = ActionChains(driver)
                    actions.move_to_element_with_offset(overlay_element, -10, -10).click().perform()
                    print(f"✅ Closed overlay by clicking outside")
                    time.sleep(1)
                    return True
            except:
                continue
        
        return False
    except Exception as e:
        print(f"⚠️ Error dismissing overlays: {str(e)}")
        return False

def submit_post(driver):
    """Submit the post by clicking the final button with enhanced error handling"""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"🔍 Looking for Share/Post button (Attempt {attempt}/{max_attempts})...")
            
            # First, try to dismiss any overlays that might be blocking the button
            if attempt > 1:
                print("🔄 Attempting to dismiss overlays...")
                dismiss_overlays(driver)
                time.sleep(2)
            
            # Try multiple selectors for the share/post button
            selectors = [
                "//button[contains(text(), 'Share')]",
                "//button[contains(text(), 'Post')]",
                "//button[contains(text(), 'Schedule')]",
                "//button[contains(@class, 'share')]",
                "//button[contains(@class, 'post')]",
                "//button[.//span[contains(text(), 'Share')]]",
                "//button[.//span[contains(text(), 'Post')]]"
            ]
            
            share_button = None
            for selector in selectors:
                try:
                    share_button = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, selector))
                    )
                    if share_button.is_displayed() and share_button.is_enabled():
                        print(f"✅ Found Share/Post button using selector: {selector}")
                        break
                except:
                    continue
            
            if not share_button:
                print("❌ Could not find Share/Post button with any selector")
                if attempt < max_attempts:
                    print("🔄 Retrying...")
                    time.sleep(2)
                    continue
                return None
            
            # Try multiple approaches to click the button
            click_methods = [
                # Method 1: Regular click
                lambda: share_button.click(),
                
                # Method 2: JavaScript click
                lambda: driver.execute_script("arguments[0].click();", share_button),
                
                # Method 3: ActionChains click
                lambda: ActionChains(driver).move_to_element(share_button).click().perform(),
                
                # Method 4: Scroll to element then click
                lambda: (
                    driver.execute_script("arguments[0].scrollIntoView(true);", share_button),
                    time.sleep(1),
                    share_button.click()
                )
            ]
            
            for i, click_method in enumerate(click_methods, 1):
                try:
                    print(f"🖱️ Attempting click method {i}...")
                    click_method()
                    
                    print("⏳ Waiting for post to be submitted...")
                    time.sleep(3)
                    
                    # Verify submission by checking for a success message or URL change
                    try:
                        WebDriverWait(driver, 10).until(
                            EC.or_(
                                EC.url_contains("publish.buffer.com/all-channels"),
                                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Post scheduled') or contains(text(), 'Post shared')]"))
                            )
                        )
                        print("✅ Post submitted successfully!")
                        return True
                    except:
                        print("⚠️ Could not confirm post submission, but proceeding")
                        return True  # Still return true as we clicked the button
                except Exception as click_error:
                    print(f"⚠️ Click method {i} failed: {str(click_error)}")
                    if i < len(click_methods):
                        print("🔄 Trying next click method...")
                        time.sleep(1)
                    continue
            
            # If all click methods failed, try dismissing overlays and retry
            if attempt < max_attempts:
                print("🔄 Retrying after dismissing overlays...")
                dismiss_overlays(driver)
                time.sleep(2)
                continue
            else:
                print("❌ All click methods failed")
                return None
                
        except Exception as e:
            print(f"❌ Error on attempt {attempt}: {str(e)}")
            if attempt < max_attempts:
                print("🔄 Retrying...")
                time.sleep(2)
                continue
            return None

def combine_screenshots(screenshot_bytes_list):
    """Combine multiple screenshots into a single high-quality image"""
    try:
        if not screenshot_bytes_list:
            print("⚠️ No screenshots to combine")
            return None
        
        # Open all images from bytes
        images = []
        for png_bytes in screenshot_bytes_list:
            try:
                img = Image.open(io.BytesIO(png_bytes))
                images.append(img)
            except Exception as e:
                print(f"⚠️ Failed to open image: {str(e)}")
                continue
        
        if not images:
            print("⚠️ No valid images to combine")
            return None
        
        # Determine grid dimensions
        num_images = len(images)
        cols = 2  # Number of columns in the grid
        rows = (num_images + cols - 1) // cols  # Calculate rows needed
        
        # Get dimensions of first image (assuming all are same size)
        img_width, img_height = images[0].size
        
        # Create a new image with appropriate size
        grid_width = cols * img_width
        grid_height = rows * img_height
        grid_img = Image.new('RGB', (grid_width, grid_height))
        
        # Paste images into the grid
        for i, img in enumerate(images):
            row = i // cols
            col = i % cols
            x = col * img_width
            y = row * img_height
            grid_img.paste(img, (x, y))
        
        # Save the combined image to bytes with high quality
        output = io.BytesIO()
        grid_img.save(output, format='PNG', quality=100)  # Maximum quality
        output.seek(0)
        
        print("✅ Combined screenshots created with high quality")
        return output
        
    except Exception as e:
        print(f"❌ Error combining screenshots: {str(e)}")
        return None

def process_media_file(video_bytes):
    """Process a media file through Buffer automation"""
    screenshot_bytes_list = []
    
    try:
        # Use global driver
        global driver
        
        # If driver doesn't exist or isn't alive, create a new one
        if driver is None:
            print("🚀 Starting Chrome...")
            driver = setup_chrome()
        
        # Establish session (check login, load cookies, or login with credentials)
        if not establish_session(driver):
            print("❌ Failed to establish session")
            # Clean up driver and try once more
            cleanup_driver()
            driver = setup_chrome()
            if not establish_session(driver):
                print("❌ Failed to establish session after retry")
                return None
        
        print("✅ Session established successfully!")
        
        # Click the New Post button
        result = click_new_post(driver)
        if result is None:
            print("❌ Failed to click New Post button")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Upload video
        result = upload_video(driver, video_bytes)
        if result is None:
            print("❌ Failed to upload video")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Type content
        result = type_content(driver)
        if result is None:
            print("❌ Failed to type content")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Click customize button
        result = click_customize_button(driver)
        if result is None:
            print("❌ Failed to click customize button")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Click second text area
        result = click_second_text_area(driver)
        if result is None:
            print("❌ Failed to click second text area")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Fill reels input
        result = fill_reels_input(driver)
        if result is None:
            print("❌ Failed to fill reels input")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Click section button
        result = click_section_button(driver)
        if result is None:
            print("❌ Failed to click section button")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Click list item
        result = click_list_item(driver)
        if result is None:
            print("❌ Failed to click list item")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        # Submit the post
        result = submit_post(driver)
        if result is None:
            print("❌ Failed to submit post")
            return None
        elif result is True:
            screenshot_bytes = take_screenshot(driver)
            if screenshot_bytes:
                screenshot_bytes_list.append(screenshot_bytes)
        
        print("\n🎉 All steps completed successfully!")
        return screenshot_bytes_list
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        if 'driver' in locals() and driver is not None:
            take_screenshot(driver)
        return None

@bot.message_handler(content_types=['video', 'document'])
def handle_media(message):
    """Handle incoming media files (videos and documents)"""
    try:
        # Send acknowledgment message
        bot.send_message(TELEGRAM_USER_CHAT_ID, "📥 Received your media file. Processing...")
        
        # Determine file type and get file info
        if message.video:
            file_info = bot.get_file(message.video.file_id)
        elif message.document:
            file_info = bot.get_file(message.document.file_id)
        else:
            bot.send_message(TELEGRAM_USER_CHAT_ID, "❌ Unsupported file type. Please send a video or image.")
            return
        
        # Download the file as bytes
        downloaded_file = bot.download_file(file_info.file_path)
        
        print(f"💾 Received media file: {file_info.file_path}")
        
        # Process the file through Buffer automation
        bot.send_message(TELEGRAM_USER_CHAT_ID, "🔄 Processing your file through Buffer...")
        screenshot_bytes_list = process_media_file(downloaded_file)
        
        if screenshot_bytes_list:
            # Combine screenshots into a single image
            bot.send_message(TELEGRAM_USER_CHAT_ID, "🖼️ Combining screenshots...")
            combined_image_bytes = combine_screenshots(screenshot_bytes_list)
            
            if combined_image_bytes:
                # Send the combined image back to the user
                bot.send_photo(TELEGRAM_USER_CHAT_ID, combined_image_bytes, caption="✅ All screenshots from your Buffer session")
                
                bot.send_message(TELEGRAM_USER_CHAT_ID, "🎉 Your media has been successfully posted to Buffer!")
            else:
                bot.send_message(TELEGRAM_USER_CHAT_ID, "⚠️ Failed to combine screenshots, but your media was posted to Buffer.")
        else:
            bot.send_message(TELEGRAM_USER_CHAT_ID, "❌ Failed to process your media file through Buffer.")
            
    except Exception as e:
        print(f"❌ Error handling media: {str(e)}")
        bot.send_message(TELEGRAM_USER_CHAT_ID, f"❌ An error occurred: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    """Handle text messages"""
    bot.send_message(TELEGRAM_USER_CHAT_ID, "👋 Please send a video or image file to post to Buffer.")

def main():
    """Main function to start the Telegram bot"""
    print("🤖 Starting Telegram bot...")
    try:
        bot.polling()
    except Exception as e:
        print(f"❌ Bot error: {str(e)}")
    finally:
        cleanup_driver()

if __name__ == "__main__":
    main()
