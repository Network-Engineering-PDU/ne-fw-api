import importlib.util
import os
import unittest

# Load the pure engine directly so the test does not need FastAPI/PDU imports.
_path = os.path.join(os.path.dirname(__file__), "..", "ttne", "app", "alarms",
                     "engine.py")
_spec = importlib.util.spec_from_file_location("alarm_engine", _path)
engine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engine)


def inputs(v=230.0, i=5.0, n=6):
    return [{"v": v, "i": i} for _ in range(n)]


def ids(alarms):
    return {a.id for a in alarms}


class EvaluateTest(unittest.TestCase):
    def evaluate(self, data, branch=1, sys_type=2, rated=16.0, net=True,
                 comm=False):
        return engine.evaluate(data, branch, sys_type, rated, net, comm)

    def test_healthy_pdu_has_no_alarms(self):
        self.assertEqual([], self.evaluate(inputs()))

    def test_overcurrent_and_near_limit(self):
        data = inputs()
        data[1]["i"] = 17.0
        data[4]["i"] = 15.0
        alarms = self.evaluate(data)
        self.assertEqual({"#201:/PDU/Main/L2", "#202:/PDU/Aux/L2"}, ids(alarms))
        by_id = {a.id: a for a in alarms}
        self.assertEqual(engine.SEVERITY_ERROR, by_id["#201:/PDU/Main/L2"].severity)
        self.assertEqual(engine.SEVERITY_WARNING, by_id["#202:/PDU/Aux/L2"].severity)

    def test_current_exactly_at_thresholds_does_not_alarm(self):
        data = inputs(i=16.0)
        self.assertEqual({f"#202:/PDU/{b}/L{p}" for b in ("Main", "Aux")
                          for p in (1, 2, 3)}, ids(self.evaluate(data)))
        self.assertEqual([], self.evaluate(inputs(i=14.4)))

    def test_no_voltage(self):
        data = inputs()
        data[2]["v"] = 0.0
        self.assertEqual({"#203:/PDU/Main/L3"}, ids(self.evaluate(data)))

    def test_only_existing_inputs_are_checked(self):
        data = inputs(v=0.0)
        # single-phase, main branch only: L1 exists, the rest are unused
        self.assertEqual({"#203:/PDU/Main/L1"},
                         ids(self.evaluate(data, branch=0, sys_type=0)))
        # bi-phase with aux: inputs 0-3
        self.assertEqual(4, len(self.evaluate(data, branch=1, sys_type=1)))
        # unknown switch values: nothing to check
        self.assertEqual([], self.evaluate(data, branch=None, sys_type=None))

    def test_rated_current_unknown_disables_current_alarms(self):
        self.assertEqual([], self.evaluate(inputs(i=99.0), rated=0))

    def test_comm_error_replaces_input_alarms(self):
        alarms = self.evaluate(inputs(v=0.0), comm=True)
        self.assertEqual({"#101:/PDU/Power"}, ids(alarms))

    def test_network(self):
        self.assertEqual({"#301:/PDU/Network"}, ids(self.evaluate(inputs(), net=False)))
        self.assertEqual([], self.evaluate(inputs(), net=None))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = engine.AlarmStore()
        self.a = engine.Alarm("#201", engine.SEVERITY_ERROR, "/PDU/Main/L1", "x")
        self.b = engine.Alarm("#301", engine.SEVERITY_WARNING, "/PDU/Network", "y")

    def test_not_evaluated_until_first_update(self):
        self.assertFalse(self.store.evaluated)
        self.store.update([], 1)
        self.assertTrue(self.store.evaluated)

    def test_keeps_time_and_ack_while_active(self):
        self.store.update([self.a], 100)
        self.assertTrue(self.store.ack(self.a.id))
        self.store.update([self.a, self.b], 200)
        by_id = {x["id"]: x for x in self.store.snapshot()}
        self.assertEqual(100, by_id[self.a.id]["first_seen"])
        self.assertTrue(by_id[self.a.id]["ack"])
        self.assertEqual(200, by_id[self.b.id]["first_seen"])
        self.assertFalse(by_id[self.b.id]["ack"])

    def test_cleared_alarm_is_dropped_and_returns_unacked(self):
        self.store.update([self.a], 100)
        self.store.ack(self.a.id)
        self.store.update([], 150)
        self.assertEqual([], self.store.snapshot())
        self.store.update([self.a], 300)
        alarm = self.store.snapshot()[0]
        self.assertEqual(300, alarm["first_seen"])
        self.assertFalse(alarm["ack"])

    def test_ack_unknown_and_ack_all(self):
        self.assertFalse(self.store.ack("nope"))
        self.store.update([self.a, self.b], 1)
        self.assertEqual(2, self.store.ack_all())
        self.assertEqual(0, self.store.ack_all())

    def test_sorted_errors_first(self):
        self.store.update([self.b, self.a], 1)
        self.assertEqual(["#201:/PDU/Main/L1", "#301:/PDU/Network"],
                         [x["id"] for x in self.store.snapshot()])


if __name__ == "__main__":
    unittest.main()
