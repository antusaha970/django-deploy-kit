.PHONY: install-dev test coverage build publish-test publish clean

install-dev:
	pip install -e ".[dev]"

test:
	pytest tests/ -v

coverage:
	coverage run -m pytest tests/ -v
	coverage report
	coverage html

build: clean
	python -m build

publish-test: build
	twine upload --repository testpypi dist/*

publish: build
	twine upload dist/*

clean:
	rm -rf dist/ build/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
