import sys

def process_emails(input_file, output_file):
    # Link format using {email}, {password}, {refresh_token}, and {client_id} as placeholders.
    LINK_FORMAT = "https://pixverify.shop/graphapi/{email}%7C{password}%7C{refresh_token}%7C{client_id}"

    with open(input_file, 'r') as f:
        lines = f.readlines()

    processed_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        parts = line.split('|')
        if len(parts) >= 4:
            email = parts[0].strip()
            password = parts[1].strip()
            refresh_token = parts[2].strip()
            client_id = parts[3].strip()
            
            # Generate the link using the provided format
            generated_link = LINK_FORMAT.format(
                email=email,
                password=password,
                refresh_token=refresh_token,
                client_id=client_id
            )
            
            processed_lines.append(f"{email} | {password} | {generated_link}")
        else:
            print(f"Skipping invalid line: {line}")

    with open(output_file, 'w') as f:
        f.write("\n".join(processed_lines) + "\n")
        
    print(f"Successfully converted {len(processed_lines)} accounts.")
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 convert_emails.py <input.txt> <output.txt>")
        sys.exit(1)
        
    process_emails(sys.argv[1], sys.argv[2])
