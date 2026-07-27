# 시간-공간 맵, 시간에 따른 RHEED 패턴의 변화를 시각화하는 히트맵을 그리는 코드입니다.

import numpy as np
import matplotlib.pyplot as plt

# 1. 데이터 불러오기
data = np.load("test_rheed.npy") #파일 경로를 입력하셔야 됩니다 예:/Users/leetaehan/Downloads/test_rheed.npy

# 2. 히트맵(Heatmap) 그리기
plt.figure(figsize=(10, 6))

# aspect='auto'는 화면 비율에 맞게 꽉 채워줌
# cmap='viridis'는 어두우면 보라색, 밝으면 노란색으로 보여주는 예쁜 컬러맵
plt.imshow(data, aspect='auto', cmap='viridis', interpolation='none')

plt.colorbar(label='Brightness (Intensity)')
plt.title("RHEED Time Evolution (Kymograph)")
plt.xlabel("X Pixel Position")
plt.ylabel("Time (Seconds -> Down)")

plt.show()