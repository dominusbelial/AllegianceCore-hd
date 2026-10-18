"""Free baseline (Claude, HD round 2): ESRGAN x4 of the native atlas + derived normal/roughness/metallic maps.
Writes <addon>/variants/esrgan/<model>/{basecolor,normal,metallic,roughness,emission}.png (same layout as Meshy)."""
import sys, numpy as np, torch
from pathlib import Path
from PIL import Image, ImageFilter
from spandrel import ModelLoader
addon = Path.home()/'Development/AllegianceCore-hd'
weights = Path.home()/'Development/allegiance-tools/reference/esrgan-work/RealESRGAN_x4plus.pth'
model = ModelLoader().load_from_file(str(weights)).eval()
def up4(img):
    x = torch.from_numpy(np.asarray(img.convert('RGB'), np.float32)/255).permute(2,0,1)[None]
    out = []
    T = 256  # tile to bound memory
    _, _, H, W = x.shape
    y = torch.zeros(1, 3, H*4, W*4)
    with torch.no_grad():
        for i in range(0, H, T):
            for j in range(0, W, T):
                p = 8; i0, j0 = max(i-p,0), max(j-p,0); i1, j1 = min(i+T+p,H), min(j+T+p,W)
                t = model(x[:, :, i0:i1, j0:j1])
                y[:, :, i*4:min(i+T,H)*4, j*4:min(j+T,W)*4] = t[:, :, (i-i0)*4:(i-i0+min(T,H-i))*4, (j-j0)*4:(j-j0+min(T,W-j))*4]
    a = (y[0].permute(1,2,0).clamp(0,1).numpy()*255).round().astype(np.uint8)
    return Image.fromarray(a)
for name in sys.argv[1:]:
    src = Image.open(addon/'inputs'/name/'native.png')
    base = src.convert('RGB')
    while base.size[0] < 4096:  # 128 → 512 → 2048 → 4096 (ESRGAN until ≥2048, then Lanczos to 4096)
        base = up4(base) if base.size[0] < 2048 else base.resize((4096, 4096), Image.LANCZOS)
    base = base.resize((4096, 4096), Image.LANCZOS)
    out = addon/'variants/esrgan'/name; out.mkdir(parents=True, exist_ok=True)
    base.save(out/'basecolor.png')
    # height from luminance (blurred), normal via Sobel; moderate strength
    lum = np.asarray(base.convert('L').filter(ImageFilter.GaussianBlur(2)), np.float32)/255
    gx = np.zeros_like(lum); gy = np.zeros_like(lum)
    gx[:,1:-1] = (lum[:,2:]-lum[:,:-2]); gy[1:-1,:] = (lum[2:,:]-lum[:-2,:])
    s = 6.0; n = np.dstack([-gx*s, -gy*s, np.ones_like(lum)]); n /= np.linalg.norm(n, axis=2, keepdims=True)
    Image.fromarray(((n*0.5+0.5)*255).astype(np.uint8)).save(out/'normal.png')
    # roughness: painted metal ~0.55, darker/cavities rougher; metallic: low-saturation greys read as metal
    hsv = np.asarray(base.convert('HSV'), np.float32)/255
    rough = np.clip(0.75-0.35*lum, 0.25, 0.95)
    metal = np.clip((0.35-hsv[...,1])*2.2, 0, 0.8)*(lum > 0.15)
    Image.fromarray((rough*255).astype(np.uint8)).resize((2048,2048)).save(out/'roughness.png')
    Image.fromarray((metal*255).astype(np.uint8)).resize((2048,2048)).save(out/'metallic.png')
    Image.new('RGB', (4096,4096), 0).save(out/'emission.png')
    print(name, src.size, '->', base.size, flush=True)
