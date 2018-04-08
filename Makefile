SHELL=/bin/bash

help:
	@egrep '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dependencies: ## Install dependencies into a local virtualenv
	if [[ ! -e .venv ]]; then virtualenv .venv; fi
	. .venv/bin/activate && pip install -r requirements.txt pyyaml pykwalify nose

test: dependencies ## Test the code
	pykwalify -d resources.yaml -s schema.yaml
	nosetests tests.py -s

run: ## Execute the update of our services. There is NO dry run mode, this will make production changes.
	python ensure_enough.py
