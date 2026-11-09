PYTHON ?= python3
PROFILE ?=

.PHONY: install uninstall install-mod uninstall-mod test help check-profile

help:
	@printf '%s\n' 'Targets:' '  make install PROFILE="/path/to/profile"       Install the legacy CSS mod' '  make uninstall PROFILE="/path/to/profile"    Remove the legacy CSS mod' '  make install-mod PROFILE="/path/to/profile"  Install in Zen Mods' '  make uninstall-mod PROFILE="/path/to/profile" Remove from Zen Mods' '  make test'

check-profile:
	@test -n "$(strip $(PROFILE))" || { printf '%s\n' 'Error: PROFILE is required. Find your profile directory via about:support in Zen.' 'Usage: make install-mod PROFILE="/full/path/to/profile"' >&2; exit 1; }

install: check-profile
	@$(PYTHON) install.py install --profile "$(PROFILE)"

uninstall: check-profile
	@$(PYTHON) install.py uninstall --profile "$(PROFILE)"

install-mod uninstall-mod: check-profile
	@$(PYTHON) native_install.py $(@:-mod=) --profile "$(PROFILE)"

test:
	@$(PYTHON) -m unittest -v test_native_install
