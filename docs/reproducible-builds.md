# Reproducible Builds (experimental)

This document outlines the process for creating reproducible Docker builds for the Lido Oracle. 
Reproducible builds ensure that the same source code and build environment consistently produce identical 
container images, which can be used for security auditing and deployment consistency.

## Tested Build Environment

The instructions in this guide have been tested with the following versions of Docker and BuildKit:

- **Docker**: Version 28.0.1, build 068a01e.
- **Buildx**: Version v0.21.1-desktop.2 (available at [github.com/docker/buildx](https://github.com/docker/buildx))

### Verifying Your Environment

To ensure compatibility, verify your installed versions match the ones tested. Use the following terminal commands:

```bash
# Check Docker version
docker --version
# Expected output: Docker version 28.0.1, build 068a01e

# Check Buildx version
docker buildx version
# Expected output: github.com/docker/buildx v0.21.1-desktop.2
```

⚠️ Note: Reproducible builds depend on the exact versions of Docker and Buildx, as differences in the build engine or
its configuration (e.g., BuildKit features, Docker storage driver) can lead to variations in the resulting image.

### Step-by-Step Instructions
1. **Make sure that previous reproducible oracle and buildkit images, containers, and vaults are removed**
2. **Set the Correct Umask**

   The `umask` defines default file permissions. They are applied to every file created from now on (including the
   cloned sources) and become part of the image layers. A wrong value produces different layer hashes and breaks
   reproducibility. Set it to `0022`, matching GitHub Actions, before cloning the repository.

   ```bash
   umask        # check current value, expected: 0022
   umask 0022   # set it if the value differs (applies to the current shell only)
   ```
3. **Clone the Repository into a new fresh directory**
   ```bash
   mkdir lido-oracle-build
   cd lido-oracle-build
   git clone https://github.com/lidofinance/lido-oracle.git
   cd lido-oracle
   ```
   ⚠️ Note: Do not open the directory in an IDE (e.g., VS Code, PyCharm) or run any scripts from the repository at 
   this stage. Tools like IDEs may generate hidden files (e.g., .vscode/, .idea/) or trigger automatic 
   dependency resolution, which can introduce non-deterministic elements into the build.
4. **Checkout to the Target Branch**
   ```bash
   git checkout master  # or the specific branch/tag you want to build
   ```

5. **Perform the Build**
   ```bash
   make reproducible-build-oracle
   ```

   This command will automatically:
   - Generate `build-info.json` with current version, branch, and commit information
   - Build the reproducible Docker image using the generated build info
   - Output the image hash for comparison

   As a result, `oracle-reproducible-container:local` image and its hash will be produced.

   ⚠️ Note: The `build-info.json` file is automatically generated and included in `.gitignore`.
   You do not need to manually create or manage this file.

6. **Compare with an Image from Docker Registry**
   ```bash
   # Pull the image from the registry (replace <registry> and <tag> as needed)
   docker pull lidofinance/oracle:<tag>
   
   # Get the hash of the pulled image
   docker inspect lidofinance/oracle:<tag> --format 'Image hash: {{.Id}}'
   ```
   Now, you can compare it with the hash from the previous step.

### Troubleshooting

The feature is in the experimental phase and is also heavily affected by the environment 
(Docker version, local configuration, etc.), so there is a probability that some layers may differ.
If the digests of your local (oracle-reproducible-container:local) and registry images differ, 
you can audit the differences:

1. **Inspect Both Images**
   ```bash
   docker inspect oracle-reproducible-container:local > local.json
   docker pull lidofinance/oracle:<tag>
   docker inspect lidofinance/oracle:<tag> > registry.json
   ```
   Look for "Layers" in the JSON under "RootFS". Compare the sha256 hashes:
   Same order and values = identical images.
   Differences = check Dockerfile or build context (e.g., unpinned deps, etc).
2. **Using diffoci**

   For a detailed diff, use ([diffoci](https://github.com/reproducible-containers/diffoci)):
   ```bash
   diffoci diff docker://lido-oracle:reproducible lidofinance/oracle:<tag>
   ```
   Then review Dockerfile steps for mismatches.