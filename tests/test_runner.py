import threading
import time
import unittest

from awtrix_gpt.runner import DisplayRunner


class FakeManager:
    def __init__(self, host):
        self.host = host
        self.ticks = 0
        self.ticked = threading.Event()

    def tick(self):
        self.ticks += 1
        self.ticked.set()


class DisplayRunnerTests(unittest.TestCase):
    def test_start_runs_ticks_and_stop_ends_them(self):
        made = []

        def factory(host=None, debug=None):
            manager = FakeManager(host)
            made.append(manager)
            return manager

        runner = DisplayRunner(factory, poll_seconds=0.01)
        manager = runner.start(host="1.1.1.1")
        self.assertTrue(manager.ticked.wait(2))
        self.assertTrue(runner.running)
        runner.stop()
        self.assertFalse(runner.running)
        ticks = manager.ticks
        time.sleep(0.05)
        self.assertEqual(manager.ticks, ticks)

    def test_restart_replaces_manager_and_old_thread_really_stops(self):
        def factory(host=None, debug=None):
            return FakeManager(host)

        runner = DisplayRunner(factory, poll_seconds=0.01)
        first = runner.start(host="old")
        self.assertTrue(first.ticked.wait(2))
        second = runner.start(host="new")
        self.assertTrue(second.ticked.wait(2))
        self.assertIs(runner.manager, second)
        frozen = first.ticks
        time.sleep(0.05)
        self.assertEqual(first.ticks, frozen)        # the old loop is gone
        runner.stop()

    def test_exceptions_in_tick_do_not_kill_the_thread(self):
        class Exploding(FakeManager):
            def tick(self):
                super().tick()
                raise RuntimeError("boom")

        runner = DisplayRunner(lambda host=None, debug=None: Exploding(host), poll_seconds=0.01)
        manager = runner.start()
        deadline = time.time() + 2
        while manager.ticks < 3 and time.time() < deadline:
            time.sleep(0.01)
        self.assertGreaterEqual(manager.ticks, 3)
        runner.stop()


if __name__ == "__main__":
    unittest.main()
