.PHONY: format lint precommit build bump tag release

format:
	black src

lint:
	flake8 src

precommit:
	pre-commit run --all-files

build:
	uv build

bump:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make bump VERSION=0.1.0" && exit 1)
	@python - <<'PY'
import os
import re
from pathlib import Path

version = os.environ.get("VERSION")
if not version:
    raise SystemExit("VERSION is required.")

pyproject = Path("pyproject.toml")
text = pyproject.read_text(encoding="utf-8")
new_text, count = re.subn(
    r'(?m)^version\\s*=\\s*\"[^\"]+\"',
    f'version = \"{version}\"',
    text,
    count=1,
)
if count != 1:
    raise SystemExit("Failed to update version in pyproject.toml")
pyproject.write_text(new_text, encoding="utf-8")

init_path = Path("src/trailgen/__init__.py")
text = init_path.read_text(encoding="utf-8")
new_text, count = re.subn(
    r'(?m)^__version__\\s*=\\s*\"[^\"]+\"',
    f'__version__ = \"{version}\"',
    text,
    count=1,
)
if count != 1:
    raise SystemExit("Failed to update version in src/trailgen/__init__.py")
init_path.write_text(new_text, encoding="utf-8")
print(f\"Bumped version to {version}\")
PY

tag:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make tag VERSION=0.1.0" && exit 1)
	@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
	@git tag -a v$(VERSION) -m "v$(VERSION)"

release:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make release VERSION=0.1.0" && exit 1)
	@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
	@$(MAKE) bump VERSION=$(VERSION)
	@git add pyproject.toml src/trailgen/__init__.py
	@git commit -m "Bump version to v$(VERSION)"
	@$(MAKE) build
	@$(MAKE) tag VERSION=$(VERSION)
	@git push origin HEAD
	@git push origin v$(VERSION)
