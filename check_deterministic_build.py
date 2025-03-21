import subprocess
import hashlib
import os

os.environ["DOCKER_BUILDKIT"] = "1"

IMAGE_NAME = "my-deterministic-container:latest"


def build_and_get_hashes(build_num):
    print(f"Building image #{build_num}...")

    subprocess.run([
        "docker", "build",
        "--build-arg", "SOURCE_DATE_EPOCH=1",
        "--no-cache",
        "-t", IMAGE_NAME,
        "."
    ], check=True)

    result = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME, "--format", "{{join .RootFS.Layers \" \"}}"],
        capture_output=True,
        text=True,
        check=True
    )
    layers = result.stdout.strip()
    print(f"Layer hashes for build #{build_num}: {layers}")
    return layers


def compute_combined_hash(layers):
    return hashlib.sha256(layers.encode()).hexdigest()

print("Starting first build...")
layers1 = build_and_get_hashes(1)
combined_hash1 = compute_combined_hash(layers1)
print(f"Combined hash for build #1: {combined_hash1}")

print("\nStarting second build...")
layers2 = build_and_get_hashes(2)
combined_hash2 = compute_combined_hash(layers2)
print(f"Combined hash for build #2: {combined_hash2}")

print("\nComparing results...")
if layers1 == layers2:
    print(f"Layer hashes MATCH: {layers1}")
else:
    print("Layer hashes DO NOT MATCH!")
    print(f"Build #1: {layers1}")
    print(f"Build #2: {layers2}")

if combined_hash1 == combined_hash2:
    print(f"Combined hashes MATCH: {combined_hash1}")
else:
    print("Combined hashes DO NOT MATCH!")
    print(f"Build #1: {combined_hash1}")
    print(f"Build #2: {combined_hash2}")