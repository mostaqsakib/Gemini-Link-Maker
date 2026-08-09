REST API · v1
UOTP API Docs
Integrate virtual numbers and OTP retrieval into your apps. Drop-in compatible with the standard handler_api spec.

API Key Auth
30 req/sec
Plain text response
4 endpoints
Operational
99.9% uptime
Quickstart
01
Grab your API key
Copy it from the card below. Pass it as the api_key query param on every request.
02
Buy a number
Call getNumber with a service & country code to receive an activationId and phone number.
03
Poll for SMS
Call getStatus with the activationId until you get STATUS_OK with the OTP code.

Base URL
https://uotp.store/api/stubs/handler_api.php
All requests must include your api_key as a query parameter.

Your API Key
Keep private
qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU


Copy Key
Regenerate
Pass it as the api_key query param.
Never commit your key to public repos.
Regenerate immediately if compromised.
Jump to
Balance Check
Number Purchase
Request SMS / Status
Change Activation Status
GET
Balance Check
#balance
Fetch your current wallet balance.

Request URL
https://uotp.store/api/stubs/handler_api.php?action=getBalance&api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU

Code Sample
cURL
JavaScript
Python
PHP
curl -X GET "https://uotp.store/api/stubs/handler_api.php?action=getBalance&api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU"

Example Response
ACCESS_BALANCE:$yourBalance
Parameters
api_key
Required
Your API Key

Success
ACCESS_BALANCE:$yourBalance
Returns your balance

Errors
BAD_KEY
Invalid API key

GET
Number Purchase
#buy
Purchase a phone number for SMS verification.

Request URL
https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=getNumber&service=$service&country=$country&operator=$operator

Code Sample
cURL
JavaScript
Python
PHP
curl -X GET "https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=getNumber&service=$service&country=$country&operator=$operator"

Example Response
ACCESS_NUMBER:$activationId:$phoneNumber
Parameters
api_key
Required
Your API Key

service
Required
Service code (e.g. wa, tg)

country
Required
Country code

operator
Optional
Operator code (optional)

Success
ACCESS_NUMBER:$activationId:$phoneNumber
Returns activation ID and number

Errors
BAD_KEY
Invalid API key

BAD_ACTION
Incorrect action

BAD_SERVICE
Incorrect service

BAD_COUNTRY
Incorrect country

BAD_OPERATOR
Incorrect operator

ACCOUNT_BAN
Account banned

NO_CONNECTION
No connection

NO_BALANCE
Insufficient balance

ERROR_DATABASE
Database error

GET
Request SMS / Status
#sms
Poll the status of an active verification.

Request URL
https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=getStatus&id=$id

Code Sample
cURL
JavaScript
Python
PHP
curl -X GET "https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=getStatus&id=$id"

Example Response
STATUS_WAIT_CODE
Parameters
api_key
Required
Your API Key

id
Required
Activation ID

Success
STATUS_WAIT_CODE
Waiting for SMS

STATUS_WAIT_RESEND
Waiting for resend

STATUS_CANCEL
Activation canceled

STATUS_OK:'code'
SMS received

Errors
BAD_KEY
Invalid API key

BAD_ACTION
Incorrect action

NO_ACTIVATION
Invalid activation ID

ACCOUNT_BAN
Account banned

GET
Change Activation Status
#status
Cancel, complete, or request another code for an activation.

Request URL
https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=setStatus&status=$status&id=$id

Code Sample
cURL
JavaScript
Python
PHP
curl -X GET "https://uotp.store/api/stubs/handler_api.php?api_key=qSkMMcEsXPALYLJUyt4OLCShhPiRlm9qrm2qqiIU&action=setStatus&status=$status&id=$id"

Example Response
ACCESS_READY
Parameters
api_key
Required
Your API Key

id
Required
Activation ID

status
Required
3 = Request new code, 8 = Cancel/Complete

Success
ACCESS_READY
Number ready

ACCESS_RETRY_GET
Waiting for new SMS

ACCESS_ACTIVATION
Service activated

ACCESS_CANCEL
Activation canceled

Errors
NO_ACTIVATION
Invalid activation ID

BAD_STATUS
Incorrect status

BAD_KEY
Invalid API key

BAD_ACTION
Incorrect action

EARLY_CANCEL_DENIED
Too early to cancel

Reference Data
Lookup tables for codes used across endpoints.

Countries
Services
Servers
Countries
Load the full list of supported countries with their codes and flags.

Load Countries
Activation Status Codes
Use these status values when calling setStatus.

1
Number received
Confirm SMS receiver is ready.
3
Request another code
Ask provider to resend a fresh OTP.
6
Complete activation
Mark the activation as finished.
8
Cancel activation
Cancel and refund (if eligible).

Common Errors
Code	Description	Resolution
BAD_KEY	Invalid or revoked API key.	Regenerate your key and update integrations.
NO_BALANCE	Insufficient wallet balance.	Top up your account on the Wallet page.
NO_NUMBERS	No numbers available for the selection.	Try a different country, service, or operator.
BAD_SERVICE	Service code does not exist.	Use the Services reference table above.
BAD_COUNTRY	Country code does not exist.	Use the Countries reference table above.
ACCOUNT_BAN	Account has been suspended.	Contact support to resolve.
EARLY_CANCEL_DENIED	Cancellation requested too soon after purchase.	Wait at least 2 minutes before cancelling.