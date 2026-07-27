#데이터의 애니메이션화

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# 1. 데이터 불러오기
data = np.load("test_rheed.npy") #파일 경로를 입력하셔야 됩니다 예:/Users/leetaehan/Downloads/test_rheed.npy

# 2. 그래프 기본 세팅
fig, ax = plt.subplots(figsize=(10, 4))
line, = ax.plot(data[0], color='green')

# Y축 높이를 전체 데이터의 최대값에 맞춰서 고정 (그래프가 위아래로 뛰는 것 방지)
ax.set_ylim(0, np.max(data) * 1.1) 
ax.set_xlabel("X Pixel Position")
ax.set_ylabel("Brightness")
plt.grid(True, alpha=0.3)

# 3. 애니메이션 업데이트 함수
def update(frame_idx):
    line.set_ydata(data[frame_idx]) # 데이터 교체
    ax.set_title(f"RHEED Profile Evolution - Time: {frame_idx} sec")
    return line,

# 4. 애니메이션 실행 (interval=50은 0.05초마다 다음 데이터 보여줌, 배속 재생)
ani = FuncAnimation(fig, update, frames=len(data), interval=50, blit=True)

plt.show()