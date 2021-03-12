# LightHouse version checker
## Run
```bash
docker build -t lighthouse_version_checker .
export GITHUB_USERNAME='vsmelov'
# create OAuth token in GitHub developer settings for your account
export GITHUB_TOKEN='secret'
docker volume create lighthouse_version_checker_volume
docker run -d -v lighthouse_version_checker_volume:/volume -e GITHUB_USERNAME -e GITHUB_TOKEN --name lighthouse_version_checker lighthouse_version_checker
```
