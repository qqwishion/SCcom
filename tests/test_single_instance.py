import unittest
from uuid import uuid4

from single_instance import single_instance


class SingleInstanceTests(unittest.TestCase):
    def test_second_instance_blocked_and_lock_released_on_exit(self):
        name = "Local\\VDchecker.Test." + uuid4().hex
        with single_instance(name) as first:
            self.assertTrue(first)
            with single_instance(name) as second:
                self.assertFalse(second)
        with single_instance(name) as after_exit:
            self.assertTrue(after_exit)
