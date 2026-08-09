import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import os
import random
import time
import requests
import threading
from playwright.sync_api import sync_playwright

try:
    import graph_mail
except ImportError:
    pass

# ==========================================
# CONFIGURATION
# ==========================================
SMSPOOL_API_KEY = os.environ.get("SMSPOOL_API_KEY", "")

# Number of tabs (accounts) to create
NUM_TABS = 3
# ==========================================

# Thread-safe print lock
_print_lock = threading.Lock()

def tprint(msg):
    with _print_lock:
        print(msg)


def get_smspool_number(tag, max_retries=20, retry_delay=5):
    """
    Purchases a US number from SMSPool for ChatGPT.
    Returns (number, order_id). Thread-safe — no globals used.
    """
    tprint(f"[{tag}] Purchasing US number from SMSPool...")

    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.smspool.net/purchase/sms",
                data={"key": SMSPOOL_API_KEY, "country": "1", "service": "671"}
            )
            j = resp.json()
            if j.get("success") == 1:
                number = str(j.get("number"))
                order_id = str(j.get("order_id"))
                tprint(f"[{tag}] Purchased number {number} (Order: {order_id})")
                return number, order_id
            else:
                msg = str(j)
                if "No numbers available" in msg or "NO_NUMBERS" in msg or "low success rate" in msg.lower():
                    tprint(f"[{tag}] No numbers available. Retrying in {retry_delay}s... ({attempt+1}/{max_retries})")
                    time.sleep(retry_delay)
                else:
                    tprint(f"[{tag}] Failed to purchase number: {msg}")
                    return "", ""
        except Exception as e:
            tprint(f"[{tag}] Error purchasing number: {e}")
            time.sleep(retry_delay)

    tprint(f"[{tag}] Exhausted retries. Could not get a number.")
    return "", ""


def get_smspool_otp(tag, order_id):
    """
    Polls SMSPool for OTP for up to ~36 seconds.
    Thread-safe — uses order_id passed as argument.
    """
    tprint(f"[{tag}] Waiting for OTP (Order: {order_id})...")

    if not order_id:
        tprint(f"[{tag}] No order ID. Cannot check OTP.")
        return ""

    for _ in range(18):  # 18 x 2s = 36s
        try:
            resp = requests.get(
                f"https://api.smspool.net/sms/check?key={SMSPOOL_API_KEY}&orderid={order_id}"
            )
            j = resp.json()
            if j.get("status") == 3:
                return str(j.get("sms"))
        except Exception:
            pass
        time.sleep(2)

    tprint(f"[{tag}] Timed out waiting for OTP (36 seconds).")
    return ""

def cancel_smspool_order(tag, order_id):
    """
    Cancels an SMSPool order so you don't get overcharged if the tab is closed.
    """
    if not order_id:
        return
    try:
        requests.get(f"https://api.smspool.net/sms/cancel?key={SMSPOOL_API_KEY}&orderid={order_id}")
        tprint(f"[{tag}] Cancelled SMSPool order {order_id} to prevent charges.")
    except Exception as e:
        tprint(f"[{tag}] Failed to cancel order: {e}")


def get_random_name():
    first = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Sam", "Jamie", "Riley"]
    last = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis"]
    return random.choice(first), random.choice(last)


def check_and_wait_for_captcha(page, tag):
    captcha = page.locator(
        'iframe[src*="arkose"], iframe[src*="cloudflare"], '
        'iframe[title*="challenge"], iframe[src*="v2/api.js"]'
    )
    if captcha.count() > 0:
        for i in range(captcha.count()):
            el = captcha.nth(i)
            if el.is_visible():
                tprint(f"[{tag}] CAPTCHA detected! Please solve it manually in the browser.")
                tprint(f"[{tag}] Waiting up to 5 minutes...")
                try:
                    el.wait_for(state="hidden", timeout=300000)
                    tprint(f"[{tag}] CAPTCHA solved. Proceeding...")
                    time.sleep(2)
                except Exception as e:
                    tprint(f"[{tag}] CAPTCHA timed out: {e}")
                return

def process_account(account_index, total):
    """
    Full ChatGPT account creation for one thread.
    Runs in its own thread with its own sync_playwright() instance.
    Retries with a fresh tab if phone/password error or OTP failure.
    """
    tag = f"Tab {account_index}/{total}"

    tprint(f"\n[{tag}] ========== Starting Tab ==========")

    launch_args = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
    
    # Configure window position based on index (quarters + center)
    w, h = 800, 800
    positions = {
        1: (0, 0),           # Top-Left
        2: (800, 0),         # Top-Right
        3: (0, 500),         # Bottom-Left
        4: (800, 500),       # Bottom-Right
        5: (400, 250)        # Center
    }
    x, y = positions.get(account_index, (50 * account_index, 50 * account_index))
    launch_args.extend([f"--window-position={x},{y}", f"--window-size={w},{h}"])

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=launch_args
        )

        context = browser.new_context(viewport={'width': w, 'height': h})
        page = context.new_page()

        while True:  # retry loop — reuses the same context and page

            otp_received = False

            try:
                tprint(f"[{tag}] Navigating to ChatGPT login page...")
                page.goto("https://chatgpt.com/auth/login")

                tprint(f"[{tag}] Clicking 'Continue with phone'...")
                page.get_by_text("Continue with phone").click()
                time.sleep(2)
                check_and_wait_for_captcha(page, tag)

                # Detect early error page (wrong phone/pass)
                if page.locator("text=/Incorrect phone number or password/i").count() > 0:
                    tprint(f"[{tag}] 'Incorrect phone number or password' shown early. Retrying in same tab...")
                    continue

                tprint(f"[{tag}] Selecting country USA...")
                combo = page.locator('button[role="combobox"][aria-label="Phone number country code"]')
                combo.wait_for(state="visible")
                combo.click()
                time.sleep(1)
                page.locator('[role="option"]', has_text="United States").first.click()
                time.sleep(1)

                # Purchase number — retry loop inside already handles retries
                number, order_id = get_smspool_number(tag)
                if not number:
                    tprint(f"[{tag}] Could not get a number. Retrying in same tab...")
                    continue

                tprint(f"[{tag}] Entering phone number: {number}")
                phone_input = page.locator('input[type="tel"]')
                phone_input.type(number, delay=100)
                phone_input.press("Enter")

                tprint(f"[{tag}] Waiting for password field...")
                pw = page.locator('input[placeholder="Password"], input[name="new-password"], input[type="password"]')
                pw.first.wait_for(state="visible")
                time.sleep(1)
                pw.first.type("PixVerifyBot123@", delay=50)
                pw.first.press("Enter")

                # Check for wrong password error after submit
                time.sleep(3)
                if page.locator(
                    'text=/Incorrect phone number or password/i, text=/wrong password/i, text=/invalid.*password/i'
                ).count() > 0:
                    tprint(f"[{tag}] 'Incorrect phone number or password' shown. Cancelling order and retrying in same tab...")
                    cancel_smspool_order(tag, order_id)
                    continue

                tprint(f"[{tag}] Waiting for OTP (up to 36 seconds)...")
                otp = get_smspool_otp(tag, order_id)
                if not otp:
                    tprint(f"[{tag}] No OTP received. Cancelling order and retrying in same tab...")
                    cancel_smspool_order(tag, order_id)
                    continue

                # --- OTP received ---
                otp_received = True
                tprint(f"[{tag}] Entering OTP: {otp}")
                otp_input = page.locator(
                    'input[placeholder="Code"], input[name="code"], input[autocomplete="one-time-code"]'
                )
                otp_input.first.wait_for(state="visible")
                otp_input.first.type(otp, delay=50)

                tprint(f"[{tag}] Clicking Continue on OTP screen...")
                btn = page.locator(
                    'button[type="submit"][name="intent"][value="validate"], button:has-text("Continue")'
                )
                if btn.count() > 0:
                    btn.first.click()
                else:
                    page.keyboard.press("Enter")

                time.sleep(2)
                check_and_wait_for_captcha(page, tag)

                # Profile setup (may or may not appear)
                tprint(f"[{tag}] Checking for profile setup page...")
                try:
                    page.get_by_text("Full name").wait_for(state="visible", timeout=30000)
                    try:
                        name_input = page.get_by_label("Full name")
                        age_input = page.get_by_label("Age")
                    except Exception:
                        name_input = page.locator('input[name="fullname"], input[autocomplete="name"]')
                        age_input = page.locator('input[name="age"], input[placeholder*="Age"]')

                    fn, ln = get_random_name()
                    full_name = f"{fn} {ln}"
                    age = str(random.randint(21, 25))
                    tprint(f"[{tag}] Entering profile: {full_name}, Age: {age}")
                    name_input.first.type(full_name, delay=50)
                    age_input.first.type(age, delay=50)

                    page.locator('button[type="submit"]:has-text("Finish creating account")').click()
                    time.sleep(2)
                    check_and_wait_for_captcha(page, tag)
                except Exception:
                    tprint(f"[{tag}] No profile page. Proceeding...")

                tprint(f"[{tag}] Waiting for site to fully load...")
                page.wait_for_url(
                    lambda url: "chatgpt.com" in url and "auth" not in url and "onboarding" not in url,
                    timeout=60000
                )
                time.sleep(5)

                tprint(f"[{tag}] Grabbing session token...")
                page.goto("https://chatgpt.com/api/auth/session")
                session_json = page.locator("body").inner_text()

                save_path = os.path.abspath(
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", f"account_{account_index}_session.txt")
                )
                with open(save_path, "w") as f:
                    f.write(session_json)
                tprint(f"[{tag}] Session token saved to {save_path}")

                # Navigate to pricing and claim free trial
                tprint(f"[{tag}] Opening pricing page...")
                new_page = context.new_page()
                new_page.goto("https://chatgpt.com/#pricing")
                time.sleep(3)

                # Try "Claim free trial of Plus" first, fall back to "Upgrade to Plus"
                tprint(f"[{tag}] Looking for 'Claim free trial of Plus' button...")
                claim_btn = new_page.locator(
                    'button:has-text("Claim free trial"), '
                    'a:has-text("Claim free trial"), '
                    '[data-testid*="free-trial"], '
                    'button:has-text("Start free trial")'
                )
                upgrade_btn = new_page.locator(
                    '[data-testid="select-plan-button-plus-upgrade"], '
                    'button:has-text("Upgrade to Plus"), '
                    'button:has-text("Get Plus")'
                )
                # Wait for either button to appear
                tprint(f"[{tag}] Waiting for plan button to appear...")
                for _ in range(15):  # wait up to 15s
                    if claim_btn.count() > 0 and claim_btn.first.is_visible():
                        tprint(f"[{tag}] Clicking 'Claim free trial of Plus'...")
                        claim_btn.first.click()
                        break
                    elif upgrade_btn.count() > 0 and upgrade_btn.first.is_visible():
                        tprint(f"[{tag}] Clicking 'Upgrade to Plus'...")
                        upgrade_btn.first.click()
                        break
                    time.sleep(1)
                else:
                    tprint(f"[{tag}] No plan button found — trying direct Plus URL...")
                    new_page.goto("https://chatgpt.com/subscribe?plan=plus")

                time.sleep(3)
                
                tprint(f"[{tag}] Reached Plus subscription page. Leaving tab open for manual entry.")
                raise Exception("Waiting for manual verification submission")

            except Exception as e:
                tprint(f"[{tag}] {e}")

            # --- Lifecycle decision ---
            if otp_received:
                tprint(f"[{tag}] OTP was received. Keeping tab open. Close browser when done.")
                # Wait until context is closed by user
                try:
                    while True:
                        time.sleep(5)
                        try:
                            _ = context.pages
                        except Exception:
                            break
                except Exception:
                    pass
                break  # done with this account
            else:
                tprint(f"[{tag}] Retrying in the same tab...")
                # while True continues and page.goto happens again

        try:
            browser.close()
        except Exception:
            pass

    tprint(f"[{tag}] Done.")


def main():
    print("Starting Playwright automation...")

    num_tabs_str = os.getenv("NUM_TABS", str(NUM_TABS))
    try:
        total = int(num_tabs_str)
    except ValueError:
        total = 3

    print(f"Opening {total} browser tab(s) simultaneously...")

    threads = []
    for index in range(total):
        t = threading.Thread(
            target=process_account,
            args=(index + 1, total),
            daemon=True,
            name=f"account-{index+1}"
        )
        threads.append(t)

    # Start ALL threads at the same time
    for t in threads:
        t.start()

    # Wait for all to finish
    for t in threads:
        t.join()

    print("\nAll accounts processed.")


if __name__ == "__main__":
    main()