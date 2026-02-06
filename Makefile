.PHONY: format lint precommit build tag release

format:
	black src

lint:
	flake8 src

precommit:
	pre-commit run --all-files

build:
	uv build

tag:
	@test -n "$(VERSION)" || (echo "VERSION is required. Example: make tag VERSION=0.1.0" && exit 1)
	@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
	@git tag -a v$(VERSION) -m "v$(VERSION)"

release: build tag
