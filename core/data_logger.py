import csv
from collections import deque


class DataLogger:
    """Keep a bounded measurement-row buffer and save it to CSV."""

    def __init__(self, columns, max_rows=10_000):
        self.columns = list(columns)
        self.max_rows = max(1, int(max_rows))
        self.rows = deque(maxlen=self.max_rows)

    def append(self, row):
        self.rows.append(row)

    def set_max_rows(self, max_rows):
        """Resize the buffer while retaining its newest rows."""
        max_rows = max(1, int(max_rows))
        if max_rows == self.max_rows:
            return
        self.max_rows = max_rows
        self.rows = deque(self.rows, maxlen=max_rows)

    def clear(self):
        self.rows.clear()

    def save_csv(self, path, columns=None):
        columns = list(columns or self.columns)
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(
                stream, fieldnames=columns, extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(self.rows)
