import csv
import sys

# Read the provided panels
panels_text = """https://advance-3e0a9-default-rtdb.firebaseio.com
https://gdhxu-d4b7c-default-rtdb.firebaseio.com
https://hospital-5-default-rtdb.firebaseio.com
https://yellow-panel-rto-default-rtdb.firebaseio.com
https://admin-panel-client-a3ee5-default-rtdb.firebaseio.com
https://olamigo-41620-default-rtdb.firebaseio.com
https://novap7-725ff-default-rtdb.firebaseio.com
https://mman-433ae-default-rtdb.firebaseio.com
https://panel-wala-v70-default-rtdb.firebaseio.com
https://stsfk30aug-default-rtdb.firebaseio.com
https://radhe-d31aa-default-rtdb.firebaseio.com
https://mayor-6f08c-default-rtdb.firebaseio.com
https://hospital-8707c-default-rtdb.firebaseio.com
https://zxcv-b2d2a-default-rtdb.firebaseio.com
https://pawankumar92342038-8f702-default-rtdb.firebaseio.com
https://pm-india-07y-gu-default-rtdb.firebaseio.com
https://craxs-4c542-default-rtdb.firebaseio.com
https://rahul-54fe9-default-rtdb.firebaseio.com
https://komaljah-default-rtdb.firebaseio.com
https://kumaru-6eec1-default-rtdb.firebaseio.com
https://raaz-5287d-default-rtdb.firebaseio.com
https://pmkal-72db3-default-rtdb.firebaseio.com
https://hdmax1-58366-default-rtdb.firebaseio.com
https://kumu-f2257-default-rtdb.firebaseio.com
https://strom-90e84-default-rtdb.firebaseio.com
https://lalit-7b538-default-rtdb.firebaseio.com
https://painislv-default-rtdb.firebaseio.com
https://can-4-668a0-default-rtdb.firebaseio.com
https://u25428732-91bd9-default-rtdb.firebaseio.com
https://yellow-raat-yaj-default-rtdb.firebaseio.com
https://vecna-82db2-default-rtdb.firebaseio.com
https://gjhghjj-3d251-default-rtdb.firebaseio.com
https://u62751482-f5b46-default-rtdb.firebaseio.com
https://sanjee-9918a-default-rtdb.firebaseio.com
https://ruparamee-14f4b-default-rtdb.firebaseio.com
https://darknet-26b68-default-rtdb.firebaseio.com
https://customer-support-3c756-default-rtdb.firebaseio.com
https://strange-2e4aa-default-rtdb.firebaseio.com
https://jjjkfkd-b5a47-default-rtdb.firebaseio.com
https://fir-27c9e-default-rtdb.firebaseio.com
https://fpro3indus-default-rtdb.firebaseio.com
https://axisjames-default-rtdb.firebaseio.com
https://mpari-6a6e5-default-rtdb.firebaseio.com
https://access20-3fc38-default-rtdb.firebaseio.com
https://bandhan2-7jan-default-rtdb.firebaseio.com
https://chuchi-e90f8-default-rtdb.firebaseio.com
https://courier-sk-1-default-rtdb.firebaseio.com
https://rc-39-15-default-rtdb.firebaseio.com
https://smas-8bff8-default-rtdb.firebaseio.com
https://u24143844-c1b11-default-rtdb.firebaseio.com
https://kitter-34345-default-rtdb.firebaseio.com
https://fir-1fa16-default-rtdb.firebaseio.com
https://e13turnament2-default-rtdb.firebaseio.com
https://vyvggvvhhv-default-rtdb.firebaseio.com
https://mera5-a7138-default-rtdb.firebaseio.com
https://hdjdjdj-a73f2-default-rtdb.firebaseio.com
https://ckraj-7c86d-default-rtdb.firebaseio.com
https://chhnuk05-3188e-default-rtdb.firebaseio.com
https://raj254346kumar-84033-default-rtdb.firebaseio.com
https://u16714964-283ef-default-rtdb.firebaseio.com
https://pm-kisan-13gfh-default-rtdb.firebaseio.com
https://rahul-6bf55-default-rtdb.firebaseio.com
https://abcdef-3a37d-default-rtdb.firebaseio.com
https://hospital-14-default-rtdb.firebaseio.com
https://raki143aa-default-rtdb.firebaseio.com
https://rnd12-17508-default-rtdb.firebaseio.com
https://raja252525raj-4ee9a-default-rtdb.firebaseio.com"""

panels = [p.strip() for p in panels_text.split('\n') if p.strip()]

scraped_panels = set()

# Check extracted_links.csv
try:
    with open('data/extracted_links.csv', 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row:
                scraped_panels.add(row[0].strip())
except FileNotFoundError:
    pass

# Check failed_links.csv
try:
    with open('data/failed_links.csv', 'r') as f:
        reader = csv.reader(f)
        for row in reader:
            if row:
                scraped_panels.add(row[0].strip())
except FileNotFoundError:
    pass

found = []
missing = []

for panel in panels:
    if panel in scraped_panels:
        found.append(panel)
    else:
        missing.append(panel)

print("--- SCRAPED PANELS ---")
for p in found:
    print(p)
print("\n--- NOT SCRAPED (NEW) PANELS ---")
for p in missing:
    print(p)
