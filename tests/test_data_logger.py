import unittest

from core.data_logger import DataLogger


class TestDataLogger(unittest.TestCase):
    def test_buffer_retains_only_newest_rows(self):
        logger = DataLogger(["value"], max_rows=3)
        for value in range(5):
            logger.append({"value": value})

        self.assertEqual([row["value"] for row in logger.rows], [2, 3, 4])

    def test_resizing_discards_oldest_samples(self):
        logger = DataLogger(["value"], max_rows=4)
        for value in range(4):
            logger.append({"value": value})

        logger.set_max_rows(2)

        self.assertEqual([row["value"] for row in logger.rows], [2, 3])


if __name__ == "__main__":
    unittest.main()
