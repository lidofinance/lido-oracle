import os

if os.path.exists(".env"):
    with open(".env", "r") as f:
        for line in f.readlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            key, value = line.split("=", maxsplit=1)
            os.environ[key] = value
