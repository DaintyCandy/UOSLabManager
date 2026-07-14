import csv
import numpy as np # <-- 추가
from pathlib import Path

class DataLogger:
    """Stores measurement rows and writes them to CSV & NPY."""

    def __init__(self, columns):
        self.columns = list(columns)
        self.rows = []
        self.rheed_profiles = [] # [추가] 1D 프로파일 저장 리스트

    def append(self, row, rheed_profile=None):
        self.rows.append(row)
        self.rheed_profiles.append(rheed_profile) # 같이 넣어서 개수(Time)를 완벽히 맞춤

    def clear(self):
        self.rows.clear()
        self.rheed_profiles.clear()

    def save_csv(self, path, columns=None):
        columns = list(columns or self.columns)
        
        # 1. 온도/전압 CSV 저장
        with open(path, "w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.rows)

        # 2. RHEED 1D 배열 .npy 저장 (딥러닝 팀 용)
        valid_profiles = [p for p in self.rheed_profiles if p is not None]
        if valid_profiles:
            width = len(valid_profiles[0])
            # 카메라가 꺼져있던 시간의 데이터는 0으로 채워서 CSV의 행 개수와 완벽히 1:1로 맞춤!
            sync_profiles = [p if p is not None else np.zeros(width) for p in self.rheed_profiles]
            
            # .csv 확장자를 떼고 _rheed.npy 로 저장
            npy_path = str(Path(path).with_suffix('')) + "_rheed.npy"
            np.save(npy_path, np.array(sync_profiles))
