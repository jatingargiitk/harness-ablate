# Releasing to PyPI

This project uses PyPI trusted publishing via GitHub Actions. No API tokens are stored anywhere.

## One-time setup (already completed)

To set up trusted publishing for the first time:

1. Sign in to [pypi.org](https://pypi.org) with 2FA enabled
2. Go to Account → Publishing → "Add a new pending publisher"
3. Enter:
   - PyPI project name: `harness-ablate`
   - Owner: `jatingargiitk`
   - Repository: `harness-ablate`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`
4. Save the pending publisher

The first release will create the PyPI project. Subsequent releases will publish automatically.

## Creating a release

1. Ensure all changes are merged to `main` and tests pass
2. Update the version in `pyproject.toml` if needed
3. Create and push a git tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. Create a GitHub release from the tag at https://github.com/jatingargiitk/harness-ablate/releases/new
5. The `publish.yml` workflow will automatically build and publish to PyPI

You can also trigger the workflow manually from the Actions tab.

## Verifying the release

After the workflow completes:
```bash
pip install --upgrade harness-ablate
harness-ablate --version
```
