import unittest
from hydros_sdk.core import calc_sum

class TestCore(unittest.TestCase):
    def test_sum_integers(self):
        self.assertEqual(calc_sum(1, 2), 3)

    def test_sum_floats(self):
        self.assertAlmostEqual(calc_sum(1.5, 2.5), 4.0)

    def test_sum_negative(self):
        self.assertEqual(calc_sum(-1, 1), 0)

if __name__ == '__main__':
    unittest.main()
