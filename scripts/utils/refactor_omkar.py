import re

with open("dashboard/server.py", "r") as f:
    content = f.read()

# We need to find `async def process_omkar_generation(sid, accounts):`
# and everything down to the end of the `for account_line in accounts:` loop.

pattern = r"async def process_omkar_generation\(sid, accounts\):(.*?)for account_line in accounts:(.*?)(?=^\s*await sio.emit\('omkar_gen_log', \{'msg': 'Automation sequence completed\.)"

match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
if not match:
    print("Pattern not found!")
    exit(1)

pre_loop = match.group(1)
loop_body = match.group(2)

# Indentation adjustment: loop_body is indented by 8 spaces. We need it indented by 4 spaces for the new function, or we can leave it as is if we wrap it in a function that is indented at 0.
# Let's create the new helper function.

helper_func = """
async def _process_single_omkar_account(sid, account_line, omkar_txt_path, sem):
    async with sem:
""" + loop_body

new_main_func = """
async def process_omkar_generation(sid, accounts):
    omkar_txt_path = os.path.join(PROJECT_DIR, "omkar.txt")
    
    if not state.pw:
        from playwright.async_api import async_playwright
        state.pw = await async_playwright().start()
        state.browser = await state.pw.chromium.launch(headless=False)
        
    sem = asyncio.Semaphore(15)
    
    tasks = []
    for account_line in accounts:
        tasks.append(asyncio.create_task(_process_single_omkar_account(sid, account_line, omkar_txt_path, sem)))
        
    await asyncio.gather(*tasks)
    
"""

new_content = content[:match.start()] + helper_func + new_main_func + content[match.end():]

with open("dashboard/server.py", "w") as f:
    f.write(new_content)

print("Refactored successfully!")
