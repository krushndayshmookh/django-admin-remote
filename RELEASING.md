# Releasing

1. Update `version` in `pyproject.toml` and `__version__` in `src/django_admin_remote/__init__.py`. They must match.
2. Add the release to `CHANGELOG.md`.
3. Run the tests: `python -m pytest -q`.
4. Build and check:

   ```bash
   python -m pip install --upgrade build twine
   rm -rf dist && python -m build && python -m twine check dist/*
   ```
5. Upload with a PyPI API token scoped to this project: `python -m twine upload dist/*`.
6. Tag and publish the GitHub release: `git tag vX.Y.Z && git push --tags`, then `gh release create vX.Y.Z --generate-notes`.

Never commit a token. A released version number cannot be reused on PyPI.
