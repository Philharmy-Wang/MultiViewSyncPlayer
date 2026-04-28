# 文件: K:\MultiViewSyncPlayer\packaging\icons\make_icon.py
# 功能: 程序化生成 mvsp.ico(多尺寸 16/32/48/64/128/256)
# 输入: 无
# 输出: K:\MultiViewSyncPlayer\packaging\icons\mvsp.ico
# 运行指令: cd /k/MultiViewSyncPlayer && python packaging/icons/make_icon.py
# 生成时间: 2026-04-27 16:05

from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT  = ROOT / "packaging" / "icons" / "mvsp.ico"

SIZE = 256
BG   = (24, 26, 32, 255)            # 深灰背景

# MVSP 6 方向配色中的 4 色(顺序:左上 / 右上 / 左下 / 右下)
COLORS = [
    (66, 165, 245, 255),             # front #42a5f5  蓝
    (102, 187, 106, 255),            # back  #66bb6a  绿
    (255, 167,  38, 255),            # left  #ffa726  橙
    (171,  71, 188, 255),            # right #ab47bc  紫
]

img  = Image.new("RGBA", (SIZE, SIZE), BG)
draw = ImageDraw.Draw(img)

# 2x2 圆角方格(8% 内边距 + 6% 间隙)
pad  = int(SIZE * 0.08)
gap  = int(SIZE * 0.06)
cell = (SIZE - 2 * pad - gap) // 2
for i, color in enumerate(COLORS):
    r, c = divmod(i, 2)
    x0 = pad + c * (cell + gap)
    y0 = pad + r * (cell + gap)
    x1 = x0 + cell
    y1 = y0 + cell
    draw.rounded_rectangle(
        [x0, y0, x1, y1],
        radius=int(cell * 0.12),
        fill=color,
    )

# 中央播放三角(白色,半透明叠加)
cx, cy = SIZE // 2, SIZE // 2
tri_r  = int(SIZE * 0.18)
tri = [
    (cx - tri_r // 2, cy - tri_r),
    (cx - tri_r // 2, cy + tri_r),
    (cx + tri_r,      cy),
]
draw.polygon(tri, fill=(255, 255, 255, 230))

# 导出多尺寸 .ico
sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(OUT, format="ICO", sizes=sizes)
print(f"[icon] wrote {OUT} ({OUT.stat().st_size} bytes)")
