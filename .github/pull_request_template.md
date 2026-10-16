## What does this add?

<!-- provider / core change — and why it's useful -->

## Checklist

- [ ] `metadata = ProviderMetadata(name=..., author="your-handle")` is set
- [ ] A class docstring or `metadata.description` says what it fetches
- [ ] Every `__init__` keyword is `Annotated[type, "description"]`
- [ ] Its extra is in `pyproject.toml` and its id in `_BUNDLED` (`src/heimdall/__init__.py`)
- [ ] A test module subclasses `heimdall.testing.ProviderContractTests`
- [ ] `uv run --extra all python -m heimdall` shows the entry as you want it in the docs
