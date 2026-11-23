import sys
import subprocess

# Check installed linters
for linter in ['flake8', 'pylint', 'pyflakes', 'ruff', 'mypy']:
    try:
        res = subprocess.run([sys.executable, '-m', linter, r'D:\HMS (1)\HMS_backend\hospital\Views\cashcounter.py'], capture_output=True, text=True)
        print(f"=== {linter} ===")
        # Print only errors
        out_lines = (res.stdout + res.stderr).splitlines()
        for l in out_lines:
            if 'error' in l.lower() or 'undefined' in l.lower() or 'syntax' in l.lower():
                print(" ", l)
    except Exception as e:
        print(f"{linter}: not available ({e})")
