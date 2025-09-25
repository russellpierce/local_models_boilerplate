#!/usr/bin/env python3
"""
Linkedin capture utility with inline package metadata for uv.

The purpose of this script is to capture a linkedin profile on the right half of the screen, convert it to text using a multi-modal model and then use that information, ultimately to populate a hubspot profile.

This script captures the right half of the screen and saves it to a temporary file.
It passes that image to Ollama for processing by gemma3.
It takes Gemma's reponse...
"""

# /// script
# dependencies = [
#     "pillow>=10.0.0",
#     "mss>=9.0.0",
#     "requests>=2.31.0",
#     "python-dotenv>=1.0.0",
#     "pyautogui>=0.9.54",
#     "pyperclip>=1.8.2",
#     "selenium>=4.15.0",
#     "webdriver-manager>=4.0.0",
# ]
# ///

import os
import tempfile
import requests
import base64
import time
import signal
import sys
import glob
import webbrowser
import subprocess

try:
    from PIL import Image
    import mss
    import pyautogui
    import pyperclip
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError as e:
    print(f"Missing required dependencies: {e}")
    print("Please install with: uv run linkedin_capture.py")
    exit(1)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


claude_prompt = """Please create a HubSpot contact with this LinkedIn profile data I just extracted. Use the HubSpot native integration (if possible) to populate all relevant fields.  If the native integration is not possible, then use Zapier Gmail to work with hubspot.

If we don't have the email address, then use the email address that matches the person's full name like fullname@unknown.org.  If you run into issues with getting the information into hubspot, then then create a task with the relevant information in Jira in the CT project and tag with 'claude' and set the priority to 'lowest'
"""

# Text extraction prompt - optimized for individual image captures
text_extraction_prompt = """You are viewing a section of a LinkedIn profile. Extract all visible information that would be useful for creating a contact record in HubSpot CRM. Focus on:

REQUIRED FIELDS (if visible):
- Full name
- Current job title
- Current company/employer and how long they've been there (combine across roles)
- Location (city, state, country)

ADDITIONAL FIELDS (if visible):
- Whether I worked with them previously
- The contacts we have in common
- Contact information (email, phone - though rarely visible)

OUTPUT FORMAT:
- Extract information exactly as shown
- If information is partially visible, note what you can see
- If no relevant information is visible in this section, respond with "No info extracted"
- Do not infer or assume information not explicitly shown"""

summarize_capture_prompt = """You have multiple overlapping text extracts from different sections of the same LinkedIn profile. Create a comprehensive, deduplicated contact record suitable for HubSpot CRM.

INSTRUCTIONS:
1. Combine all information, removing duplicates and overlaps
2. Prioritize the most recent/current information
3. Structure the output in clear categories
4. Only include information that was explicitly extracted

OUTPUT FORMAT:
=== CONTACT SUMMARY ===
Name: [Full name]
Current Title: [Most recent job title]
Current Company: [Most recent employer]
Location: [City, State/Country]
Duration at Current Company: [How long they've been at their current company]

ADDITIONAL FIELDS (if visible):
- Whether I worked with them previously
- The contacts we have in common
- Contact information (email, phone - though rarely visible)
"""

# Global list to track temporary files for cleanup
temp_files = []

# Claude project URL
CLAUDE_PROJECT_URL = "https://claude.ai/project/0199823f-58b3-7226-80ef-1282b923fe68"

def cleanup_temp_files():
    """Clean up all temporary screenshot files."""
    global temp_files
    print("\nCleaning up temporary files...")

    # Clean up tracked files
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
                print(f"Deleted: {temp_file}")
        except Exception as e:
            print(f"Warning: Could not delete {temp_file}: {e}")

    # Also clean up any remaining temp files with our pattern
    try:
        temp_pattern = "/tmp/right_half_screen_*.png"
        for temp_file in glob.glob(temp_pattern):
            try:
                os.unlink(temp_file)
                print(f"Deleted: {temp_file}")
            except Exception as e:
                print(f"Warning: Could not delete {temp_file}: {e}")
    except Exception as e:
        print(f"Warning: Could not clean up temp files: {e}")

    temp_files.clear()

def signal_handler(signum, frame):
    """Handle interrupt signals (Ctrl-C, etc.) and clean up."""
    print(f"\nReceived signal {signum}. Cleaning up and exiting...")
    cleanup_temp_files()
    sys.exit(0)

# Set up signal handlers
signal.signal(signal.SIGINT, signal_handler)   # Ctrl-C
signal.signal(signal.SIGTERM, signal_handler)  # Termination signal


def run_applescript(script: str) -> bool:
    """
    Execute AppleScript and return success status.

    Args:
        script (str): The AppleScript code to execute

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"AppleScript error: {e.stderr}")
        return False
    except Exception as e:
        print(f"Error running AppleScript: {e}")
        return False


def open_chrome_new_tab_and_navigate(url: str):
    """
    Open a new tab in existing Chrome instance and navigate to URL (Mac only).

    Args:
        url (str): The URL to navigate to
    """
    print("Opening new Chrome tab...")

    # AppleScript to open new tab and navigate
    applescript = f'''
    tell application "Google Chrome"
        activate
        delay 0.5

        -- Open new tab
        tell application "System Events"
            keystroke "t" using command down
        end tell

        delay 1

        -- Type the URL
        tell application "System Events"
            keystroke "{url}"
            delay 0.5
            key code 36
        end tell

        delay 2
    end tell
    '''

    if run_applescript(applescript):
        print("✓ New Chrome tab opened and navigated to Claude")
        return True
    else:
        print("⚠ AppleScript failed, trying fallback...")
        # Fallback to opening in default browser
        try:
            webbrowser.open(url)
            print("✓ Opened Claude in default browser")
            return True
        except Exception as e:
            print(f"Fallback failed: {e}")
            return False


def paste_text_to_active_window(text: str):
    """
    Paste text to the currently active window (Mac only).

    Args:
        text (str): The text to paste
    """
    # Copy to clipboard first
    pyperclip.copy(text)
    print("✓ Text copied to clipboard")

    # Use AppleScript to paste
    print("Pasting text using AppleScript...")

    applescript = '''
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''

    if run_applescript(applescript):
        print("✓ Text pasted successfully!")
        return True
    else:
        print("⚠ Auto-paste failed")
        print("\n📋 Manual paste: Use Cmd+V to paste the text")
        return False


def find_and_click_claude_text_field():
    """
    Try to automatically find and click Claude's text input field.

    Returns:
        bool: True if successful, False otherwise
    """
    print("Attempting to find Claude text field...")

    # AppleScript to find and click the text field
    applescript = '''
    tell application "Google Chrome"
        activate
        delay 1

        -- Try to find and click the text input area
        tell application "System Events"
            -- Click towards bottom of window where text field usually is
            tell process "Google Chrome"
                set windowSize to size of front window
                set windowPos to position of front window
                set windowWidth to item 1 of windowSize
                set windowHeight to item 2 of windowSize
                set windowX to item 1 of windowPos
                set windowY to item 2 of windowPos

                -- Click in the lower portion where text field typically is
                set clickX to windowX + (windowWidth / 2)
                set clickY to windowY + windowHeight - 100

                click at {clickX, clickY}
                delay 0.5
            end tell
        end tell
    end tell
    '''

    return run_applescript(applescript)


def open_claude_and_paste(summary_text: str):
    """
    Open Claude web interface and paste the summary text (Mac only).

    Args:
        summary_text (str): The LinkedIn profile summary to paste
    """
    print("Opening Claude web interface...")

    # Prepare the full text to paste
    full_text = claude_prompt + summary_text

    # Step 1: Open new Chrome tab and navigate to Claude
    if not open_chrome_new_tab_and_navigate(CLAUDE_PROJECT_URL):
        print("Failed to open Claude. Please open manually and paste from clipboard.")
        pyperclip.copy(full_text)
        return

    # Step 2: Wait for page to load
    print("Waiting for page to load...")
    time.sleep(4)

    # Step 3: Try to automatically click the text field
    print("\nAttempting to auto-click the text field...")
    if find_and_click_claude_text_field():
        print("✓ Text field clicked")
        time.sleep(1)

        # Step 4: Paste the text
        if paste_text_to_active_window(full_text):
            print("\n📝 Text pasted! Press Enter in Claude to submit the request.")
        else:
            print("\n📋 Auto-paste failed. Manual paste with Cmd+V")
    else:
        print("\n📋 Could not auto-click text field.")
        print("Manual steps:")
        print("1. Click in the Claude message text field")
        print("2. Press Cmd+V to paste")
        print("3. Press Enter to send")

        # Still copy to clipboard for manual paste
        pyperclip.copy(full_text)
        print("✓ Text copied to clipboard for manual paste")


def capture_right_half_screen() -> str:
    """
    Capture the right half of the screen and save it to a temporary image file.

    Returns:
        str: The full path to the saved temporary image file

    Raises:
        Exception: If screen capture fails
    """
    try:
        # Get screen dimensions
        with mss.mss() as sct:
            # Get the primary monitor
            monitor = sct.monitors[1]  # monitors[0] is all monitors combined, [1] is primary

            # Calculate right half dimensions
            screen_width = monitor['width']
            screen_height = monitor['height']

            # Define the right half region
            right_half_region = {
                'top': monitor['top'],
                'left': monitor['left'] + screen_width // 2,
                'width': screen_width // 2,
                'height': screen_height
            }

            # Capture the right half of the screen
            screenshot = sct.grab(right_half_region)

            # Convert to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(
                suffix='.png',
                prefix='right_half_screen_',
                dir='/tmp',
                delete=False
            )
            temp_filename = temp_file.name
            temp_file.close()

            # Save the image
            img.save(temp_filename, 'PNG')

            # Track the temp file for cleanup
            global temp_files
            temp_files.append(temp_filename)

            print(f"Screen capture saved to: {temp_filename}")
            return temp_filename

    except Exception as e:
        raise Exception(f"Failed to capture screen: {e}")


def scroll_right_side_down(scroll_amount: int = 10):
    """
    Scroll down on the right side of the screen to capture more content.

    Args:
        scroll_amount (int): Number of scroll wheel clicks (default: 10)
    """
    try:
        # Get screen dimensions
        screen_width, screen_height = pyautogui.size()

        # Calculate the center of the right half of the screen
        right_center_x = screen_width * 0.75  # 75% across the screen (right side)
        right_center_y = screen_height // 2   # Middle of screen height

        # Move mouse to the right side and scroll down
        pyautogui.moveTo(right_center_x, right_center_y)
        time.sleep(0.5)  # Brief pause to ensure mouse is positioned

        # Scroll down
        pyautogui.scroll(-scroll_amount)  # Negative for scrolling down
        time.sleep(1)  # Wait for scroll to complete

        print(f"Scrolled down {scroll_amount} clicks on right side of screen")

    except Exception as e:
        print(f"Warning: Failed to scroll: {e}")


def process_image_with_ollama(temp_filename: str) -> str:
    """
    Process an image file with Ollama for text extraction.

    Args:
        temp_filename (str): Path to the temporary image file

    Returns:
        str: The extracted text from Ollama

    Raises:
        Exception: If the API call fails or LOCAL_MODEL_API is not set
    """
    # Get the Ollama API URL from environment
    local_model_api = os.getenv('LOCAL_MODEL_API')
    if not local_model_api:
        raise Exception("LOCAL_MODEL_API environment variable is not set")

    # Read and encode the image
    with open(temp_filename, 'rb') as image_file:
        image_data = base64.b64encode(image_file.read()).decode('utf-8')

    # Prepare the request payload for Ollama
    payload = {
        "model": "gemma3:27b",  # Using gemma3 for vision capabilities
        "prompt": text_extraction_prompt,
        "images": [image_data],
        "stream": False
    }

    try:
        # Make the API call to Ollama
        print(f"Making request to: {local_model_api}/api/generate")

        # Create a copy of payload for debugging without the large base64 image
        debug_payload = payload.copy()
        if 'images' in debug_payload:
            debug_payload['images'] = [f"[base64 image data - {len(payload['images'][0])} characters]"]
        print(f"Payload: {debug_payload}")

        response = requests.post(
            f"{local_model_api}/api/generate",
            json=payload,
            timeout=60
        )

        print(f"Response status code: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")

        if response.status_code != 200:
            print(f"Response content: {response.text}")
            raise Exception(f"Ollama API returned status {response.status_code}: {response.text}")

        response.raise_for_status()

        # Extract the response text
        result = response.json()
        print(f"Response JSON: {result}")
        return result.get('response', '')

    except requests.exceptions.RequestException as e:
        raise Exception(f"Failed to process image with Ollama: {e}")
    except Exception as e:
        raise Exception(f"Unexpected error processing image: {e}")


def linkedin_capture_workflow():
    """Complete workflow to capture and extract text from multiple LinkedIn profile sections."""
    try:
        # Test Ollama server connectivity
        print("Testing Ollama server connectivity...")
        local_model_api = os.getenv('LOCAL_MODEL_API')
        if not local_model_api:
            print("Error: LOCAL_MODEL_API environment variable is not set")
            return 1

        try:
            response = requests.get(f"{local_model_api}/api/tags", timeout=10)
            response.raise_for_status()
            print("✓ Ollama server is reachable")
        except requests.exceptions.RequestException as e:
            print(f"✗ Ollama server not reachable: {e}")
            return 1

        # Accumulate all extracted text
        all_extracted_text = []
        num_captures = 5  # Number of captures to make

        print(f"Starting LinkedIn profile capture with {num_captures} sections...")

        for i in range(num_captures):
            print(f"\n--- Capture {i+1}/{num_captures} ---")

            # Capture the right half of screen
            print("Capturing right half of screen...")
            filename = capture_right_half_screen()
            print(f"Success! Image saved to: {filename}")

            # Verify the file exists
            if not os.path.exists(filename):
                print("Warning: File was not created successfully")
                continue

            # Process the image with Ollama for text extraction
            print("Processing image with Ollama for text extraction...")
            try:
                extracted_text = process_image_with_ollama(filename)
                if extracted_text.strip():
                    all_extracted_text.append(extracted_text)
                    print(f"✓ Extracted {len(extracted_text)} characters")
                else:
                    print("⚠ No text extracted from this section")
            except Exception as e:
                print(f"✗ Error processing image: {e}")

            # Clean up the temporary file
            try:
                os.unlink(filename)
            except:
                pass

            # Scroll down for next capture (except on the last iteration)
            if i < num_captures - 1:
                print("Scrolling down for next capture...")
                scroll_right_side_down()
                time.sleep(2)  # Wait for page to settle

        # Display all accumulated results
        print("\n" + "="*60)
        print("COMPLETE LINKEDIN PROFILE EXTRACTION")
        print("="*60)

        if all_extracted_text:
            print(f"Successfully extracted text from {len(all_extracted_text)} sections. Creating summary...")

            # Combine all extracted text for summarization
            combined_text = "\n\n".join(all_extracted_text)
            final_prompt = summarize_capture_prompt + "\n\n" + combined_text

            # Create a temporary file with the combined text for processing
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.txt',
                prefix='combined_profile_',
                dir='/tmp',
                delete=False
            )
            temp_filename = temp_file.name
            temp_file.write(final_prompt)
            temp_file.close()

            try:
                # Process the combined text for final summary
                print("Generating final profile summary...")

                # Prepare the request payload for Ollama (text-only, no image)
                payload = {
                    "model": "gemma3:27b",
                    "prompt": final_prompt,
                    "stream": False
                }

                response = requests.post(
                    f"{local_model_api}/api/generate",
                    json=payload,
                    timeout=60
                )

                if response.status_code != 200:
                    print(f"Error in summarization: {response.status_code}: {response.text}")
                    # Fall back to showing individual sections
                    for i, text in enumerate(all_extracted_text, 1):
                        print(f"--- Section {i} ---")
                        print(text)
                        print()
                else:
                    result = response.json()
                    summary = result.get('response', '')

                    print("\n" + "="*60)
                    print("LINKEDIN PROFILE SUMMARY FOR HUBSPOT CRM")
                    print("="*60)
                    print(summary)
                    print("="*60)

                    # Open Claude and paste the data
                    print("\n" + "="*50)
                    print("OPENING CLAUDE FOR HUBSPOT INTEGRATION")
                    print("="*50)
                    open_claude_and_paste(summary)

            except Exception as e:
                print(f"Error generating summary: {e}")
                print("Falling back to individual sections:")
                for i, text in enumerate(all_extracted_text, 1):
                    print(f"--- Section {i} ---")
                    print(text)
                    print()
            finally:
                # Clean up the temporary text file
                try:
                    os.unlink(temp_filename)
                except:
                    pass
        else:
            print("No text was extracted from any sections.")
            return 1

    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        # Clean up any remaining temp files
        cleanup_temp_files()

    return 0


def debug_chrome_automation():
    """Debug function for testing Chrome automation (Mac only)."""
    print("=== Mac Chrome Automation Debug ===")

    # Test text for debugging
    test_text = "Hello Claude! This is a test message from the LinkedIn capture automation."

    print("\nStep 1: Testing Chrome tab opening...")
    if not open_chrome_new_tab_and_navigate(CLAUDE_PROJECT_URL):
        print("Failed to open Chrome tab")
        return 1

    print("\nStep 2: Testing auto-click text field...")
    time.sleep(3)  # Wait for page load

    if find_and_click_claude_text_field():
        print("✓ Auto-click successful")

        print("\nStep 3: Testing text pasting...")
        time.sleep(1)

        if paste_text_to_active_window(test_text):
            print("✓ Auto-paste successful")
            print("\n📝 Debug complete! Check Claude to see if the test message appeared.")
        else:
            print("⚠ Auto-paste failed")
    else:
        print("⚠ Auto-click failed")
        print("\nFallback test: Manual click and paste")
        print("1. Click in Claude text field manually")
        input("2. Press Enter here when ready...")
        paste_text_to_active_window(test_text)

    print("\n=== Debug Results ===")
    print("If the test message appeared in Claude, the automation is working!")

    return 0


def main():
    """Main function - Complete LinkedIn capture and Claude automation workflow."""
    print("\n" + "="*60)
    print("LINKEDIN PROFILE CAPTURE & HUBSPOT AUTOMATION")
    print("="*60)
    print("This will:")
    print("1. Capture LinkedIn profile sections from right half of screen")
    print("2. Extract text using Ollama vision model")
    print("3. Summarize for HubSpot CRM format")
    print("4. Open Claude and auto-paste for HubSpot integration")
    print("\nMake sure:")
    print("- LinkedIn profile is open on RIGHT HALF of screen")
    print("- Ollama server is running with vision model")
    print("- Chrome browser is available")
    print("="*60)
    print("\n🚀 Starting capture workflow...")

    try:
        # Run the complete LinkedIn capture workflow
        result = linkedin_capture_workflow()

        if result == 0:
            print("\n🎉 Complete workflow finished successfully!")
            print("Check Claude for the HubSpot contact creation request.")
        else:
            print("\n⚠ Workflow completed with errors. Check output above.")

        return result

    except KeyboardInterrupt:
        print("\n\n⏹ Workflow interrupted by user")
        cleanup_temp_files()
        return 0
    except Exception as e:
        print(f"\n\n❌ Unexpected error in main workflow: {e}")
        cleanup_temp_files()
        return 1


if __name__ == "__main__":
    exit(main())

