import os

# The tests give Debian's answers on any computer (an Arch CI job included); distro tests ask for Arch themselves.
os.environ["TVWCS_FAMILY"] = "debian"
# Vendor and administrator presets (vendor.py) only where a test gives its own files.
os.environ["TVWCS_PACKAGE_FILE"] = "/nonexistent/tvwcs-tests/updates.json"
os.environ["TVWCS_VENDOR_FILE"] = "/nonexistent/tvwcs-tests/vendor.json"
os.environ["TVWCS_DEFAULTS_FILE"] = "/nonexistent/tvwcs-tests/defaults.json"
