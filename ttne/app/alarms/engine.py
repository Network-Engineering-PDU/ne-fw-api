"""Alarm rules for the PDU.

Pure logic with no I/O so it can be unit tested. The router gathers the live
PDU state and feeds it to ``evaluate``; ``AlarmStore`` keeps the first-seen
time and the acknowledged flag of alarms that stay active.
"""
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

SEVERITY_WARNING = 1
SEVERITY_ERROR = 2
LEVEL_NAMES = {SEVERITY_WARNING: "warning", SEVERITY_ERROR: "error"}

# Below this an input is considered dead (lost phase / feed failure).
VOLTAGE_MIN_V = 20.0
# Warning above this fraction of the rated current.
CURRENT_WARN_RATIO = 0.9

CODE_COMM = "#101"
CODE_OVERCURRENT = "#201"
CODE_NEAR_LIMIT = "#202"
CODE_NO_VOLTAGE = "#203"
CODE_NETWORK = "#301"

BRANCH_NAMES = ("Main", "Aux")


@dataclass(frozen=True)
class Alarm:
    code: str
    severity: int
    path: str
    desc: str

    @property
    def id(self) -> str:
        return f"{self.code}:{self.path}"


def phases_from_sys_type(sys_type: Optional[int]) -> int:
    """0=single, 1=bi, 2/3=three-phase without/with N."""
    return {0: 1, 1: 2, 2: 3, 3: 3}.get(sys_type, 0)


def branches_from_branch(branch: Optional[int]) -> int:
    """0=Main only, 1=Main and Aux."""
    return {0: 1, 1: 2}.get(branch, 0)


def evaluate(
    inputs: Sequence[dict],
    branch: Optional[int],
    sys_type: Optional[int],
    rated_current: float,
    network_connected: Optional[bool],
    comm_error: bool,
) -> List[Alarm]:
    """Return the alarms that are active for the given PDU state.

    ``inputs`` are the PMB readings (dicts with ``v`` and ``i``) in input
    order: branch-major, phase-minor. Only inputs that exist for the PDU type
    (branches x phases) are checked. ``network_connected`` is None when the
    state is unknown.
    """
    alarms: List[Alarm] = []

    if comm_error:
        alarms.append(Alarm(CODE_COMM, SEVERITY_ERROR, "/PDU/Power",
                            "Power data unavailable"))
    else:
        n_phases = phases_from_sys_type(sys_type)
        n_branches = branches_from_branch(branch)
        for b in range(n_branches):
            for p in range(n_phases):
                idx = b * n_phases + p
                if idx >= len(inputs):
                    continue
                data = inputs[idx]
                path = f"/PDU/{BRANCH_NAMES[b]}/L{p + 1}"
                voltage = float(data.get("v", 0) or 0)
                current = float(data.get("i", 0) or 0)
                if voltage < VOLTAGE_MIN_V:
                    alarms.append(Alarm(CODE_NO_VOLTAGE, SEVERITY_ERROR, path,
                                        "No voltage on input"))
                if rated_current and rated_current > 0:
                    if current > rated_current:
                        alarms.append(Alarm(
                            CODE_OVERCURRENT, SEVERITY_ERROR, path,
                            "Current above rated current"))
                    elif current > rated_current * CURRENT_WARN_RATIO:
                        alarms.append(Alarm(
                            CODE_NEAR_LIMIT, SEVERITY_WARNING, path,
                            "Current close to rated current"))

    if network_connected is False:
        alarms.append(Alarm(CODE_NETWORK, SEVERITY_WARNING, "/PDU/Network",
                            "Network disconnected"))
    return alarms


class AlarmStore:
    """Tracks active alarms with first-seen time and acknowledged state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active: Dict[str, dict] = {}
        self._evaluated = False

    def update(self, alarms: Sequence[Alarm], now: float) -> None:
        """Replace the active set. Alarms that stay active keep their time and
        ack flag; alarms whose condition cleared are dropped."""
        with self._lock:
            active = {}
            for alarm in alarms:
                previous = self._active.get(alarm.id)
                active[alarm.id] = {
                    "id": alarm.id,
                    "code": alarm.code,
                    "severity": alarm.severity,
                    "level": LEVEL_NAMES[alarm.severity],
                    "path": alarm.path,
                    "desc": alarm.desc,
                    "first_seen": previous["first_seen"] if previous else int(now),
                    "ack": previous["ack"] if previous else False,
                }
            self._active = active
            self._evaluated = True

    @property
    def evaluated(self) -> bool:
        with self._lock:
            return self._evaluated

    def snapshot(self) -> List[dict]:
        """Active alarms, most severe first, then oldest first."""
        with self._lock:
            items = [dict(a) for a in self._active.values()]
        items.sort(key=lambda a: (-a["severity"], a["first_seen"], a["id"]))
        return items

    def ack(self, alarm_id: str) -> bool:
        with self._lock:
            alarm = self._active.get(alarm_id)
            if alarm is None:
                return False
            alarm["ack"] = True
            return True

    def ack_all(self) -> int:
        with self._lock:
            count = 0
            for alarm in self._active.values():
                if not alarm["ack"]:
                    alarm["ack"] = True
                    count += 1
            return count
