lines = []
with open("dashboard/server.py", "r") as f:
    lines = f.readlines()

for i in [582, 654, 726, 731, 1032, 1037, 1039]:
    lines[i] = lines[i].replace("return", "break")

with open("dashboard/server.py", "w") as f:
    f.writelines(lines)
print("Fixed!")
