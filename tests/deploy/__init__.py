# Deploy test package (Task 15.4 smoke tests + Task 15.5 integration tests).
#
# Smoke tests (test_smoke_deploy.py) run with NO containers and MUST pass now.
# Integration tests (test_integration_deploy.py) gate behind a short-timeout
# Docker/toolchain availability probe and SKIP CLEANLY when unavailable.
