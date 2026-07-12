import csv


class DataLogger:
    """Stores measurement rows and writes them to CSV."""

    def __init__(self, columns):
        self.columns = list(columns)
        self.rows = []

    def append(self, row):
        self.rows.append(row)

    def clear(self):
        self.rows.clear()

    def save_csv(self, path, columns=None):
        columns = list(columns or self.columns)
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)
