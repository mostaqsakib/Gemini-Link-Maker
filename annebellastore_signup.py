import asyncio
import random
import string
import argparse
from playwright.async_api import async_playwright

DOMAIN = "cheapgptnepal.site"
URL = "https://annebellastore.shop?ref=Khalid"

def generate_random_string(length=10):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

async def browser_worker(worker_id, p, total_runs):
    """Worker function that launches its own browser and reloads the page multiple times."""
    successful = []
    
    # Launch in headless mode to save massive amounts of RAM/CPU
    browser = await p.chromium.launch(
        headless=True, 
        args=["--disable-blink-features=AutomationControlled"]
    )
    
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080}
    )
    
    page = await context.new_page()
    
    for i in range(total_runs):
        random_user = generate_random_string(8)
        email = f"{random_user}@{DOMAIN}"
        password = generate_random_string(12) + "A1!"
        
        print(f"[Browser {worker_id}] ({i+1}/{total_runs}) Automating: {email}")

        try:
            # VERY IMPORTANT: Clear cookies and local storage so the site doesn't remember we are logged in!
            await context.clear_cookies()
            try:
                # Try to clear local storage if we are already on a page that allows it
                await page.evaluate("window.localStorage.clear(); window.sessionStorage.clear();")
            except Exception:
                pass
            
            # Reload the page for a fresh session in the same browser
            await page.goto(URL, wait_until="domcontentloaded")
            # Wait for splash animation (Dynamic wait for the button to appear)
            await page.wait_for_selector('#splashEnterBtn', state='attached', timeout=10000)

            # Bypass splash
            try:
                await page.evaluate("dismissSplash()")
            except Exception:
                await page.locator('#splashEnterBtn').click(force=True)
                
            # Wait for the Sign Up tab to become visible
            await page.wait_for_selector('text="Sign Up"', state='visible')

            # Click Sign Up
            await page.locator('text="Sign Up"').click()
            
            # Wait for the email input to become visible
            await page.wait_for_selector('#authUsername', state='visible')

            # Fill Form
            await page.locator('#authUsername').fill(email)
            await page.locator('#authPassword').fill(password)

            # Captcha - Wait for it and click it forcefully
            captcha_checkbox = page.locator('#captchaCheckbox')
            await captcha_checkbox.wait_for(state="visible")
            await captcha_checkbox.click(force=True)
            
            # Wait for the tick SVG to actually display (means captcha finished spinning)
            try:
                await page.locator('#captchaTick').wait_for(state="visible", timeout=8000)
            except Exception:
                pass # Just in case it's fast or doesn't show
                
            # Give the captcha a mandatory extra 2 seconds to ensure backend token generation is completely finished
            await page.wait_for_timeout(2000)

            # Submit
            await page.locator('#authSubmitBtn').click(force=True)

            # Wait dynamically for EITHER a redirect OR an error message (max 8 seconds)
            try:
                await page.wait_for_function(
                    "window.location.href.indexOf('?ref=Khalid') === -1 || "
                    "document.body.innerText.toLowerCase().includes('error') || "
                    "document.body.innerText.toLowerCase().includes('already exists') || "
                    "document.body.innerText.toLowerCase().includes('invalid')",
                    timeout=12000
                )
            except Exception:
                pass # It timed out, meaning it probably hung. The validation below will catch it.
            
            # STRCIT VALIDATION:
            # 1. Did we leave the auth page OR did the auth form disappear?
            # 2. Are there any error messages?
            current_url = page.url
            body_text = await page.evaluate("document.body.innerText")
            failure_keywords = ["error", "invalid", "already exists", "failed", "incorrect"]
            
            # Check if the submit button is still visible on the screen
            form_still_visible = await page.locator('#authSubmitBtn').is_visible()
            
            has_error_word = any(word in body_text.lower() for word in failure_keywords)
            
            # If the form is still visible AND the URL hasn't changed, OR there's an error word
            if (("?ref=Khalid" in current_url and form_still_visible) or has_error_word):
                print(f"[-] ❌ [Browser {worker_id}] Failed for {email} (Either errors present, or did not redirect)")
                print(f"    DEBUG: URL is {current_url}")
                print(f"    DEBUG: Form still visible? {form_still_visible}")
                print(f"    DEBUG: Body contains error keyword? {has_error_word}")
            else:
                print(f"[+] ✅ [Browser {worker_id}] Success: {email}")
                successful.append(email)
                # Give the browser 2 extra seconds to ensure background tracking/referral API calls finish before reloading
                await page.wait_for_timeout(2000)

        except Exception as e:
            print(f"[-] ❌ [Browser {worker_id}] Error: {e}")
            
    # Clean up the browser only after ALL runs are complete
    await browser.close()
    return successful

async def main(total_accounts, concurrency):
    print(f"🚀 Starting Mass Signup Automation")
    print(f"🎯 Total Accounts: {total_accounts}")
    print(f"⚡ Simultaneous Browsers: {concurrency}")
    print("-" * 50)

    async with async_playwright() as p:
        tasks = []
        
        # Calculate how many runs each browser should do
        runs_per_browser = total_accounts // concurrency
        remainder = total_accounts % concurrency
        
        for i in range(concurrency):
            # Distribute the load evenly across browsers
            runs = runs_per_browser + (1 if i < remainder else 0)
            if runs > 0:
                tasks.append(browser_worker(i + 1, p, runs))
                
        # Run all isolated browsers concurrently
        results = await asyncio.gather(*tasks)

    # Flatten results
    all_successful = [email for sublist in results for email in sublist]
    
    print("-" * 50)
    print(f"🎉 Completed {len(all_successful)}/{total_accounts} signups!")
    for email in all_successful:
        print(f"  - {email}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mass Automate Signups")
    parser.add_argument("--count", type=int, default=1, help="Total number of accounts to create")
    parser.add_argument("--concurrency", type=int, default=1, help="How many browsers to open at once")
    args = parser.parse_args()

    asyncio.run(main(args.count, args.concurrency))
