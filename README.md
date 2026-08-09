# JIO-CHATGPT

An automated dashboard and sniping toolkit for registering and verifying ChatGPT accounts using various SMS provider APIs and Microsoft Graph API for Outlook verification.

## Project Structure

* **Dashboard**: A web interface to monitor snipers, check provider balances, manage API keys, and launch the ChatGPT automated login flows.
* **Snipers**: Automated scripts (`grizzly_sniper.py`, `tiger_sniper.py`, `meowsms_sniper.py`, `uotp_sniper.py`, etc.) that actively poll/monitor SMS providers for phone numbers.
* **ChatGPT Login Automation**: Located in `outlook-chatgpt-auto-login/`. Uses Playwright to create ChatGPT accounts, bypass modals, add an Outlook email for verification, fetch the OTP via Microsoft Graph API, and automatically save the session token.

## Getting Started

### 1. Set up the Environment
This project requires Python 3. Make sure to activate the virtual environment and install the required dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r outlook-chatgpt-auto-login/requirements.txt
# Additionally install playwright browsers:
playwright install
```

### 2. Run the Dashboard
The easiest way to manage everything is through the built-in dashboard.

```bash
# From the project root
venv/bin/python dashboard/server.py
```
Open your browser and navigate to the URL provided in the console (usually `http://localhost:8000`).

### 3. Usage
- **Start Snipers**: Use the dashboard UI to start polling your desired SMS provider.
- **Login ChatGPT**: Use the `Login ChatGPT` button in the UI, provide the emails/credentials, and it will spawn the automation headless browsers.
- **API Keys**: We securely use a `.env` file to store all API keys (see `.env.example`). Do not hardcode your keys in the Python files. Ensure your keys are added to `.env` before running any scripts.

## Features
- **Auto-Retry & Timers**: Cleans up zombie browsers and handles sluggish UI loads automatically.
- **Direct UI Login**: Navigates through the ChatGPT pricing page to trigger and process Outlook verifications efficiently without getting stuck in settings.
- **In-Memory Sessions**: Runs Playwright instances asynchronously without retaining tracking cookies across fresh account creations.

## Manual HTTP Tracer

Use the reusable Playwright tracer to inspect your own manual browser flows:

```bash
venv/bin/python scripts/utils/master_http_tracer.py jio
venv/bin/python scripts/utils/master_http_tracer.py chatgpt
venv/bin/python scripts/utils/master_http_tracer.py flipkart
venv/bin/python scripts/utils/master_http_tracer.py flipkart --include-json-responses
venv/bin/python scripts/utils/master_http_tracer.py custom \
  --url https://example.com/login \
  --domain example.com
```

Add `--all-domains` when a flow redirects to a third-party identity provider,
or repeat `--domain` to include only the additional provider domains.
Close the browser when the flow is complete. Traces are saved under
`data/http_traces/`. Cookies, authorization headers, passwords, OTPs, and token
fields are redacted before they are written.

Use `--include-json-responses` when account-state fields are needed. Only JSON
responses up to 500 KB are included, and recognized credentials, phone numbers,
email addresses, and OTP values are redacted before saving.

## Authorized Flipkart Black Checker

Use the browser checker only with a Flipkart account and mobile number you own
or are authorized to access:

```bash
venv/bin/python scripts/flipkart_black_checker.py
```

The checker prompts for the phone number and then requests the OTP through
Flipkart's normal login page. Enter the OTP privately in the terminal. After
login, it reads the membership state returned by Flipkart and appends a result
to `data/flipkart_black_results.csv`.

By default, the CSV stores only a masked phone number. Pass
`--include-full-phone` only when retaining the complete number is required and
the output file is protected appropriately. OTPs, cookies, and session tokens
are never written to the CSV.
"# Gemini-Link-Maker" 
