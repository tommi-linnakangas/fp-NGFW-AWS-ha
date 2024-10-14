import socket
from typing import List
from aws_ha_script.config import HAScriptConfig
from aws_ha_script.context import HAScriptContext
from aws_ha_script.log_utils import logger


def tcp_probe(config: HAScriptConfig, ip_addresses: List[str], port: int,
              ctx: HAScriptContext) -> bool:
    """Attempt to open a connection to the given IP addresses and port.

    The function uses config parameters:
    - probe_max_fail
    - config.probe_timeout_sec

    The function uses context parameter:
    - ctx.probe_fail_count to remember the number of consecutive past failures

    :param config: The configuration from the main program
    :param ip_addresses: the address to try to connect to
    :param port: the port to try to connect to
    :param ctx: dict with a probe_fail_count key

    :return: True
    - if at least one connection to any ip_addresses:port is successful or
    - if the number of max consecutive failure (10 by default)
      has not been reached.
    """
    for ip_address in ip_addresses:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(config.probe_timeout_sec)
        try:
            s.connect((ip_address, port))
            s.close()
            ctx.probe_fail_count = 0
            logger.debug("TCP probe ok, ip_address: %s, port: %d", ip_address, port)
        except OSError:
            # We typically receive a TimeoutError, which is a subclass of OSError
            # (see https://docs.python.org/3/library/socket.html).
            if ctx.probe_fail_count == 0:
                logger.exception("TCP probing failed, ip_address: %s, port: %d", ip_address, port)
        else:
            return True

    probe_fail_count = ctx.probe_fail_count
    probe_max_fail = config.probe_max_fail
    logger.debug("probe_fail_count: %d, probe_max_fail: %d", probe_fail_count, probe_max_fail)
    if probe_fail_count < probe_max_fail:
        probe_fail_count += 1
        ctx.probe_fail_count = probe_fail_count
        logger.debug("TCP probe failed, ip_addresses: %s, port: %d, attempts: %d", ip_addresses,
                     port, probe_fail_count)
        return True

    ctx.probe_fail_count = 0
    logger.warning("TCP probe failed, ip_addresses: %s, port: %d, attempts: %d", ip_addresses,
                   port, probe_max_fail)
    return False
