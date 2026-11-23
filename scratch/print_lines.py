with open(r"D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for i in range(2475, 2495):
    print(f"{i+1}: {repr(lines[i])}")
