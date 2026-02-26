.PHONY: format lint precommit build bump tag release

VERSION_STRIPPED = $(patsubst v%,%,$(VERSION))

format:
	black src

lint:
	flake8 src

precommit:
	pre-commit run --all-files

build:
	uv build

bump:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make bump VERSION=0.1.0 (leading v optional)" && exit 1)
	@python scripts/bump_version.py "$(VERSION)"

tag:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make tag VERSION=0.1.0 (leading v optional)" && exit 1)
	@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
	@git tag -a v$(VERSION_STRIPPED) -m "v$(VERSION_STRIPPED)"

release:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make release VERSION=0.1.0 (leading v optional)" && exit 1)
	@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
	@$(MAKE) bump VERSION=$(VERSION_STRIPPED)
	@git add pyproject.toml src/trailgen/__init__.py
	@git commit -m "Bump version to v$(VERSION_STRIPPED)"
	@$(MAKE) build
	@$(MAKE) tag VERSION=$(VERSION_STRIPPED)
	@git push origin HEAD
	@git push origin v$(VERSION_STRIPPED)
