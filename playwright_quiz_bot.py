import os
import sys
import json
import time
from playwright.sync_api import sync_playwright

# Safe print wrapper to handle Unicode encoding errors in Windows terminal
def safe_print(*args, **kwargs):
    import builtins
    safe_args = []
    for arg in args:
        if isinstance(arg, str):
            safe_args.append(arg.encode('ascii', 'backslashreplace').decode('ascii'))
        else:
            safe_args.append(str(arg).encode('ascii', 'backslashreplace').decode('ascii'))
    builtins.print(*safe_args, **kwargs)

print = safe_print

# Global dictionary to store correct option indices mapped by 1-based question number
correct_options = {}

def decode_string(encoded_str, key):
    if not encoded_str or not isinstance(encoded_str, str):
        return encoded_str

    decoded = []

    for i, char in enumerate(encoded_str):
        cp = ord(char)
        kc = ord(key[i % len(key)])

        decoded_char = chr((cp - kc + 65536) % 65536)
        decoded.append(decoded_char)

    return ''.join(decoded)

def get_option_index(decoded_ans):
    ans = decoded_ans.strip().upper()
    if not ans:
        return 0
        
    # Map options (A -> 0, B -> 1, C -> 2, D -> 3)
    if "A" in ans:
        return 0
    if "B" in ans:
        return 1
    if "C" in ans:
        return 2
    if "D" in ans:
        return 3
        
    # Map numerical options (1 -> 0, 2 -> 1, 3 -> 2, 4 -> 3)
    if "1" in ans:
        return 0
    if "2" in ans:
        return 1
    if "3" in ans:
        return 2
    if "4" in ans:
        return 3
        
    # Fallback to first character check
    char = ans[0] if len(ans) > 0 else ''
    if char in ['A', '1']:
        return 0
    if char in ['B', '2']:
        return 1
    if char in ['C', '3']:
        return 2
    if char in ['D', '4']:
        return 3
        
    return 0

def handle_response(response):
    # Intercept the response of /exam/quick
    if "mujib.chorcha.net/exam/quick" in response.url and response.request.method == "POST":
        print("Intercepted /exam/quick response!")
        headers = response.headers
        x_chorcha_id = headers.get("x-chorcha-id")
        if not x_chorcha_id:
            print("x-chorcha-id not found in response headers.")
            return
            
        try:
            body = response.json()
            questions = body.get("data", {}).get("questions", [])
            print(f"Successfully loaded {len(questions)} questions from response.")
            
            notes_dict = {}
            
            # Use index of list for correct order since q.get("order") contains float rankings
            for index, q in enumerate(questions):
                encoded_ans = q.get("answer")
                decoded_ans = decode_string(encoded_ans, x_chorcha_id)
                
                # Determine correct option index (0 to 3)
                opt_idx = get_option_index(decoded_ans)
                
                # 1-based question number for mapping
                q_num = index + 1
                notes_dict[q_num] = decoded_ans.strip()
                correct_options[q_num] = opt_idx
                
            # Print the well-formatted JSON as requested by the user
            print("Decoded answers mapping [note 1]:")
            print(json.dumps(notes_dict, indent=4, ensure_ascii=False))
            
        except Exception as e:
            print(f"Error parsing quick practice response: {e}")

def load_auth_cookies(context, auth_file_path):
    if not os.path.exists(auth_file_path):
        print(f"Warning: Authentication file '{auth_file_path}' not found!")
        return False
        
    print(f"Loading authentication cookies from '{auth_file_path}'...")
    try:
        with open(auth_file_path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
            
        playwright_cookies = []
        for cookie in cookies:
            p_cookie = {
                "name": cookie["name"],
                "value": cookie["value"],
                "domain": cookie["domain"],
                "path": cookie["path"]
            }
            if "expirationDate" in cookie:
                p_cookie["expires"] = int(cookie["expirationDate"])
            if "httpOnly" in cookie:
                p_cookie["httpOnly"] = cookie["httpOnly"]
            if "secure" in cookie:
                p_cookie["secure"] = cookie["secure"]
            if "sameSite" in cookie and cookie["sameSite"] is not None:
                same_site = str(cookie["sameSite"]).capitalize()
                if same_site in ["Lax", "Strict", "None"]:
                    p_cookie["sameSite"] = same_site
            playwright_cookies.append(p_cookie)
            
        context.add_cookies(playwright_cookies)
        print("Cookies successfully injected!")
        return True
    except Exception as e:
        print(f"Error loading cookies: {e}")
        return False

def run_quiz():
    print("Starting Playwright quiz automation script...")
    
    # Path to auth.json
    auth_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth.json")
    
    with sync_playwright() as p:
        # Launch browser in headless mode if specified via environment variable or in CI/GitHub Actions
        is_headless = os.environ.get("HEADLESS", "false").lower() == "true" or os.environ.get("CI") is not None
        print(f"Launching browser (headless={is_headless})...")
        browser = p.chromium.launch(
            headless=is_headless,
            args=[] if is_headless else ["--start-maximized"]
        )
        
        # Create a new browser context
        if is_headless:
            # Set a standard desktop viewport size in headless mode
            context = browser.new_context(
                viewport={"width": 1280, "height": 800}
            )
        else:
            context = browser.new_context(
                no_viewport=True  # Allows the browser to maximize fully
            )
        
        # Load the cookies from auth.json
        load_auth_cookies(context, auth_file_path)
        
        page = context.new_page()
        
        # Register network response listener before click actions
        page.on("response", handle_response)
        
        # Navigate to practice exam page
        print("Navigating to practice exam page...")
        page.goto("https://chorcha.net/practice-exam", timeout=60000)
        
        # Give it a moment to render
        page.wait_for_load_state("networkidle")
        
        # Verify if we are logged in. If not, handle login.
        login_btn = page.locator('text="লগইন", text="Login"')
        if login_btn.first.is_visible():
            print("\n*** ACTION REQUIRED ***")
            print("The session cookies in auth.json may have expired or are invalid.")
            if is_headless:
                print("Error: Session expired/invalid, and cannot log in manually in headless environment.")
                browser.close()
                sys.exit(1)
            print("Please log into your Chorcha account manually in the browser window.")
            print("The script will wait for you to log in...")
            while login_btn.first.is_visible():
                page.wait_for_timeout(1000)
            print("Login detected! Proceeding with automation...\n")
            page.wait_for_timeout(2000)
            
        # Navigation and initialization loop
        failed_chapters = set() # set of (subject_name, chapter_name)
        failed_subjects = set() # set of subject_name
        
        quiz_started = False
        max_attempts = 10
        attempt = 0
        
        while not quiz_started and attempt < max_attempts:
            attempt += 1
            print(f"\n--- Navigation Attempt {attempt}/{max_attempts} ---")
            
            # Clear correct_options for a fresh attempt
            correct_options.clear()
            
            # Navigate to practice exam page
            print("Navigating to practice exam page...")
            page.goto("https://chorcha.net/practice-exam", timeout=60000)
            page.wait_for_load_state("networkidle")
            
            # Verify login status
            login_btn = page.locator('text="লগইন", text="Login"')
            if login_btn.first.is_visible():
                print("\n*** ACTION REQUIRED ***")
                print("The session cookies in auth.json may have expired or are invalid.")
                if is_headless:
                    print("Error: Session expired/invalid, and cannot log in manually in headless environment.")
                    browser.close()
                    sys.exit(1)
                print("Please log into your Chorcha account manually in the browser window.")
                print("The script will wait for you to log in...")
                while login_btn.first.is_visible():
                    page.wait_for_timeout(1000)
                print("Login detected! Proceeding with automation...\n")
                page.wait_for_timeout(2000)
                
            # 1. Click on target subject (Bangla/Krishi/Hisab) or fall back to ICT
            print("Locating subjects...")
            subjects = page.locator('main h3')
            try:
                subjects.first.wait_for(state="visible", timeout=10000)
            except Exception:
                print("Failed to locate subjects. Retrying...")
                continue
                
            sub_count = subjects.count()
            if sub_count == 0:
                print("No subjects found. Retrying...")
                continue
                
            # Search subject names to identify targets
            target_subjects = []
            ict_subject = None
            other_subjects = []
            
            for idx in range(sub_count):
                try:
                    text = subjects.nth(idx).inner_text().strip()
                    if "বাংলা" in text or "কৃষিশিক্ষা" in text or "হিসাববিজ্ঞান" in text:
                        target_subjects.append((idx, text))
                    elif "তথ্য ও যোগাযোগ প্রযুক্তি" in text:
                        ict_subject = (idx, text)
                    else:
                        other_subjects.append((idx, text))
                except Exception:
                    pass
            
            # Filter out fully failed subjects
            target_subjects = [s for s in target_subjects if s[1] not in failed_subjects]
            if ict_subject and ict_subject[1] in failed_subjects:
                ict_subject = None
            other_subjects = [s for s in other_subjects if s[1] not in failed_subjects]
            
            import random
            selected_sub_idx = None
            selected_sub_name = None
            
            if len(target_subjects) > 0:
                chosen = random.choice(target_subjects)
                selected_sub_idx = chosen[0]
                selected_sub_name = chosen[1]
                print(f"Found target subjects. Selected: {repr(selected_sub_name)} (index {selected_sub_idx})")
            elif ict_subject is not None:
                selected_sub_idx = ict_subject[0]
                selected_sub_name = ict_subject[1]
                print(f"Target subjects not found/failed. Selected ICT: {repr(selected_sub_name)} (index {selected_sub_idx})")
            elif len(other_subjects) > 0:
                chosen = random.choice(other_subjects)
                selected_sub_idx = chosen[0]
                selected_sub_name = chosen[1]
                print(f"Falling back to other subject: {repr(selected_sub_name)} (index {selected_sub_idx})")
            else:
                print("All available subjects/chapters failed. Resetting failure history...")
                failed_chapters.clear()
                failed_subjects.clear()
                continue
                
            selected_subject = subjects.nth(selected_sub_idx)
            selected_subject.scroll_into_view_if_needed()
            selected_subject.click()
            
            # Wait for the chapter list page to render (the subject name becomes an h2 title)
            try:
                page.locator('main h2').wait_for(state="visible", timeout=10000)
            except Exception:
                print("Failed to load chapters page (h2 not found). Retrying...")
                failed_subjects.add(selected_sub_name)
                continue
            page.wait_for_timeout(500)
            
            # 2. Click on a random chapter / expand accordion if needed
            print("Locating chapters...")
            try:
                page.locator('main h3').first.wait_for(state="visible", timeout=10000)
            except Exception:
                print("No chapters/groups visible for this subject. Retrying...")
                failed_subjects.add(selected_sub_name)
                continue
                
            top_h3s = page.locator('main h3').all()
            if len(top_h3s) == 0:
                print("Zero chapters/groups found. Retrying...")
                failed_subjects.add(selected_sub_name)
                continue
                
            selected_index = random.randint(0, len(top_h3s) - 1)
            selected_h3 = top_h3s[selected_index]
            selected_h3_text = selected_h3.inner_text().strip()
            
            selected_h3.scroll_into_view_if_needed()
            print(f"Clicking chapter/group '{repr(selected_h3_text)}' (index {selected_index})...")
            selected_h3.click()
            page.wait_for_timeout(1500)
            
            selected_chap_name = selected_h3_text
            
            # 3. Click on Quick Practice (দ্রুত প্র্যাকটিস) button
            print("Locating Mode selection dialog...")
            quick_practice_btn = page.locator('button:has-text("দ্রুত প্র্যাকটিস")')
            
            # Check if modal opened directly
            if not quick_practice_btn.is_visible():
                # If not visible, it might be an accordion that expanded.
                all_current_h3s = page.locator('main h3').all()
                sub_chapters = []
                top_header_texts = [h.inner_text().strip() for h in top_h3s]
                
                for h in all_current_h3s:
                    try:
                        h_text = h.inner_text().strip()
                        if h_text not in top_header_texts and h.is_visible():
                            # Check if this specific sub-chapter has failed previously
                            if (selected_sub_name, h_text) not in failed_chapters:
                                sub_chapters.append(h)
                    except Exception:
                        pass
                
                if len(sub_chapters) > 0:
                    sub_idx = random.randint(0, len(sub_chapters) - 1)
                    selected_sub = sub_chapters[sub_idx]
                    selected_chap_name = selected_sub.inner_text().strip()
                    selected_sub.scroll_into_view_if_needed()
                    print(f"Detected expanded accordion. Clicking sub-chapter '{repr(selected_chap_name)}' (index {sub_idx})...")
                    selected_sub.click()
                    page.wait_for_timeout(1500)
                else:
                    print("No unfailed sub-chapters found. Retrying with different subject/chapter...")
                    failed_chapters.add((selected_sub_name, selected_h3_text))
                    continue
            
            try:
                quick_practice_btn.wait_for(state="visible", timeout=8000)
                print("Clicking Quick Practice button...")
                quick_practice_btn.click()
                
                # Wait up to 5 seconds to receive the questions response and populate correct_options
                page.wait_for_timeout(2000)
                if len(correct_options) > 0:
                    quiz_started = True
                else:
                    print("Questions list is empty or not loaded yet. Waiting a bit more...")
                    page.wait_for_timeout(3000)
                    if len(correct_options) > 0:
                        quiz_started = True
                    else:
                        print("No questions loaded from API. Retrying with a different subject/chapter...")
                        failed_chapters.add((selected_sub_name, selected_chap_name))
                        
            except Exception:
                print("Quick Practice button not visible. Taking diagnostic screenshot...")
                page.screenshot(path=f"mode_error_attempt_{attempt}.png")
                print(f"Chapter '{repr(selected_chap_name)}' under subject '{repr(selected_sub_name)}' failed. Retrying...")
                failed_chapters.add((selected_sub_name, selected_chap_name))
                page.wait_for_timeout(1000)
                
        if not quiz_started:
            print("Error: Could not start the quiz after maximum navigation attempts.")
            browser.close()
            return
        
        # 4. Wait for quiz page to load and start answering questions
        page.wait_for_timeout(2000)
        print("Quiz started! Answering questions...")
        
        question_count = 0
        waiting_count = 0
        while True:
            # Check if quiz is finished (Skip / Finish stats screen or Go Ahead is visible)
            skip_btn = page.locator('button:has-text("স্কিপ করো")')
            go_ahead_btn = page.locator('button:has-text("এগিয়ে যাও")')
            
            if skip_btn.is_visible():
                print("\nQuiz completed! Reached the stats screen (with skip button).")
                break
            if go_ahead_btn.is_visible():
                print("\nQuiz completed! Reached the stats screen (directly to go ahead).")
                break
                
            # Locate option buttons on page
            options = page.locator('button.rounded-xl.border')
            
            if options.count() > 0:
                waiting_count = 0
                question_count += 1
                
                # Get the correct option index from the intercepted answers dictionary
                # Default to index 0 if not found
                target_idx = correct_options.get(question_count, 0)
                
                # Check for out-of-bounds safety
                if target_idx >= options.count():
                    target_idx = 0
                    
                print(f"Question {question_count}: Clicking option index {target_idx}...")
                options.nth(target_idx).click()
                page.wait_for_timeout(800) # delay to simulate human selection and let response load
                
                # Check for "পরের প্রশ্ন" (Next Question) or "শেষ করো" (Finish)
                next_btn = page.locator('button:has-text("পরের প্রশ্ন"), button:has-text("শেষ করো")')
                if next_btn.is_visible():
                    print("Clicking next / finish button...")
                    next_btn.click()
                    
                page.wait_for_timeout(1000) # transition delay between questions
            else:
                # If no options found, wait a bit or check if we finished
                page.wait_for_timeout(1000)
                waiting_count += 1
                
                if skip_btn.is_visible():
                    print("\nQuiz completed! Reached the stats screen (with skip button).")
                    break
                if go_ahead_btn.is_visible():
                    print("\nQuiz completed! Reached the stats screen (directly to go ahead).")
                    break
                
                # If we've been waiting too long, perform diagnostics
                if waiting_count >= 15:
                    print("Stuck waiting for 15 seconds. Checking status...")
                    if go_ahead_btn.is_visible():
                        print("Found 'এগিয়ে যাও' button during diagnostic check. Breaking.")
                        break
                    if skip_btn.is_visible():
                        print("Found 'স্কিপ করো' button during diagnostic check. Breaking.")
                        break
                    waiting_count = 0
                
                print("Waiting for options or quiz screen to load...")
                
        # 5. Click the "স্কিপ করো" button on the score screen if visible
        skip_btn = page.locator('button:has-text("স্কিপ করো")')
        if skip_btn.is_visible():
            print("Clicking skip button...")
            skip_btn.scroll_into_view_if_needed()
            skip_btn.click()
            page.wait_for_timeout(2000)
        
        # 6. Click the "এগিয়ে যাও" button to complete the flow and return to subject page
        print("Locating go ahead button...")
        go_ahead_btn = page.locator('button:has-text("এগিয়ে যাও")')
        go_ahead_btn.wait_for(state="visible", timeout=10000)
        print("Clicking go ahead button...")
        go_ahead_btn.click()
        page.wait_for_timeout(3000)
        
        print("\nAll steps completed successfully!")
        print("Closing browser...")
        browser.close()

if __name__ == "__main__":
    run_quiz()
