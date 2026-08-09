#!/usr/bin/env python3
import sys

try:
    import phonenumbers
    from phonenumbers import carrier
except ImportError:
    print("⚠️  'phonenumbers' not installed. Installing now...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "phonenumbers", "--break-system-packages"])
    import phonenumbers
    from phonenumbers import carrier

def get_carrier(number_str):
    if not number_str.startswith('+'):
        number_str = '+' + number_str
        
    try:
        parsed = phonenumbers.parse(number_str, "IN")
        if phonenumbers.is_valid_number(parsed):
            name = carrier.name_for_number(parsed, "en")
            return name if name else "Unknown"
        else:
            return "Invalid Number"
    except Exception as e:
        return f"Error: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check_carrier.py <phone_number>...")
        sys.exit(1)
        
    for num in sys.argv[1:]:
        print(f"📱 {num}: {get_carrier(num)}")
