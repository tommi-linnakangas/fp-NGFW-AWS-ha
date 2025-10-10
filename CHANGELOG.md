# Changelog

All notable changes to this project will be documented in this file.

## [1.1.4] - 2025-10-10

- better exception handling
- send all error messages to SMC
- add dry_run mode, which makes it possible to run the script so that
  it does not change the system (node state or route tables)
- add new property:
  - dry_run
- fix installer to stop the running script more reliable
- check configured instance ids against real instance ids
- add more unit tests for configuration

## [1.1.3] - 2024-10-14

- code cleanup and refactoring
- first public release

## [1.1.2] - 2024-09-30

- code cleanup and refactoring

## [1.1.0] - 2024-01-17

- python 3.7
- now using pipenv to manage dependencies
- code cleanup, refactoring, modularization, ruff/flake8 linting
- added typing
- added ut with 'moto' library
- fix script incorrectly changing all the routes
- new mandatory property 'secondary_instance_id'
- code for vpnbroker removed
- deprecated properties (now ignored):
    - vpn_broker_url
    - vpn_broker_password
    - primary_engine_name
    - secondary_engine_name
    - request_timeout_sec
    - change_metrics_enabled
- new properties:
  - probe_ip
  - remote_probe_enabled
  - remote_probe_ip
  - remote_probe_port
