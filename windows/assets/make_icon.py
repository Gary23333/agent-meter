"""重新生成项目的托盘图标，需要安装 Pillow。"""
from pathlib import Path
from PIL import Image, ImageDraw

SIZE = 1024
image = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((48, 48, 976, 976), radius=225, fill=(23, 31, 45, 255))
draw.arc((198, 182, 826, 810), 145, 395, fill=(67, 87, 101, 255), width=92)
draw.arc((198, 182, 826, 810), 145, 335, fill=(112, 224, 194, 255), width=92)
draw.line((512, 500, 693, 316), fill=(239, 250, 247, 255), width=70)
draw.ellipse((445, 433, 579, 567), fill=(239, 250, 247, 255))
image.resize((256, 256), Image.Resampling.LANCZOS).save(
    Path(__file__).with_name('agent-meter.ico'), sizes=[(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)])
