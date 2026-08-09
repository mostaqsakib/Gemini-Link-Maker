lines = []
with open("dashboard/server.py", "r") as f:
    lines = f.readlines()

for i in [949]:
    lines[i] = lines[i].replace("continue", "return")

with open("dashboard/server.py", "w") as f:
    f.writelines(lines)
print("Fixed!")
