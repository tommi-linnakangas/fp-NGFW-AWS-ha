# Changelog

All notable changes to this project will be documented in this file.

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
