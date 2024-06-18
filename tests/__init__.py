import os

if os.path.exists(".env"):
    with open(".env") as f:
        for line in f.readlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            key, value = line.split("=")
            os.environ[key] = value
