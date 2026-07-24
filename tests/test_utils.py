import asyncio
import unittest

from ttne import utils


class PeriodicTaskTest(unittest.IsolatedAsyncioTestCase):

    async def test_periodic_task_continues_after_transient_exception(self):
        completed = asyncio.Event()
        calls = 0

        async def flaky_task():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("transient failure")
            completed.set()

        task = utils.periodic_task(flaky_task, 0.01)
        try:
            await asyncio.wait_for(completed.wait(), timeout=0.5)
        finally:
            task.cancel()
            await task

        self.assertGreaterEqual(calls, 2)

    async def test_exec_command_does_not_interpret_shell_syntax(self):
        literal = "$(printf unsafe); 'quoted'"
        retval, output = await utils.exec_command("/usr/bin/printf", "%s", literal)

        self.assertEqual(retval, 0)
        self.assertEqual(output, literal)
