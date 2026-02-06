.PHONY: format lint precommit build tag release

format:
\tblack src

lint:
\tflake8 src

precommit:
\tpre-commit run --all-files

build:
\tuv build

tag:
\t@test -n "$(VERSION)" || (echo "VERSION is required. Example: make tag VERSION=0.1.0" && exit 1)
\t@git diff --quiet || (echo "Working tree is dirty. Commit or stash changes first." && exit 1)
\t@git tag -a v$(VERSION) -m "v$(VERSION)"

release: build tag
