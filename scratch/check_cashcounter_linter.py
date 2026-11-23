import ast

with open(r"D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py", "r", encoding="utf-8") as f:
    code = f.read()

tree = ast.parse(code)
print("AST parsed successfully!")

# Let's check imports and undefined names, or run flake8 / pylint if available
import subprocess
res = subprocess.run(["flake8", r"D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py", "--select=E9,F821,F822,F823,F831,F406,F407"], capture_output=True, text=True)
print("Flake8 errors (undefined names/syntax):")
print(res.stdout or "None found with flake8")

res2 = subprocess.run(["flake8", r"D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py", "--select=F"], capture_output=True, text=True)
lines = [l for l in (res2.stdout or "").splitlines() if "F821" in l or "F841" in l or "F401" not in l]
print("Other F errors:")
for l in lines[:20]:
    print(" ", l)
