"""Gathers the live PDU state and refreshes the alarm store."""
import logging
import time

from ttne.app.network import functions as nw_functions
from . import engine

logger = logging.getLogger(__name__)

store = engine.AlarmStore()

# Power readings older than this mean the PMB stopped reporting.
STALE_AFTER_S = 15.0
# After start-up, no reading at all is only an error once this time passed.
STARTUP_GRACE_S = 60.0
_START = time.monotonic()


def power_comm_error(pmb, n_inputs: int, now: float) -> bool:
    """True if the PMB is missing or stopped reporting measurements."""
    if pmb is None or pmb.branch is None or pmb.sys_type is None:
        return now - _START > STARTUP_GRACE_S
    if not pmb.measure_flag:
        return True
    data = pmb.get_pmb_data()
    last = [data[i].get("last_time", 0) for i in range(n_inputs) if i in data]
    if not last or max(last) == 0:
        return now - _START > STARTUP_GRACE_S
    return now - max(last) > STALE_AFTER_S


async def refresh():
    """Re-evaluate all alarm rules and update the store."""
    from ttne import server
    from ttne.app.settings import routers as settings_routers

    now = time.monotonic()
    pmb = server.PDU.get_pmb() if server.PDU is not None else None
    branch = getattr(pmb, "branch", None)
    sys_type = getattr(pmb, "sys_type", None)
    n_inputs = (engine.branches_from_branch(branch) *
                engine.phases_from_sys_type(sys_type))
    comm_error = power_comm_error(pmb, n_inputs, now)
    data = pmb.get_pmb_data() if pmb is not None else {}
    inputs = [data[i] for i in sorted(data)]

    connected = None
    try:
        info = await nw_functions.get_network_info()
        connected = info.connected if info is not None else None
    except Exception:  # network state is best effort
        logger.exception("Could not read network state for alarms")

    rated = float(settings_routers.pdu_info_state.rated_current)
    alarms = engine.evaluate(inputs, branch, sys_type, rated, connected,
                             comm_error)
    store.update(alarms, time.time())
