"""Hybrid (Claude, HD round 2): native identity + Meshy detail. Base colour = ESRGAN-upscaled NATIVE colour
(low frequencies and chroma), plus the Meshy texture's high-frequency luminance detail (seams, rivets, wear),
plus Meshy's normal map. Free post-process on outputs already paid for."""
import sys, numpy as np
from pathlib import Path
from PIL import Image, ImageFilter
root = Path.home()/'Development/AllegianceCore-hd'
import os
CLAMP = float(os.environ.get('HYBRID_CLAMP', '1.0'))
SUFFIX = os.environ.get('HYBRID_SUFFIX', '')
def arr(p, mode='RGB'): return np.asarray(Image.open(p).convert(mode).resize((4096,4096), Image.LANCZOS), np.float32)/255
for spec in sys.argv[1:]:                     # model:meshyVariant[:detailStrength]
    m, v, *k = spec.split(':'); k = float(k[0]) if k else 1.0
    nat = arr(root/'variants/esrgan'/m/'basecolor.png')
    msh = root/'variants'/v/m
    ml = arr(msh/'basecolor.png', 'L')
    blur = np.asarray(Image.fromarray((ml*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(10)), np.float32)/255
    detail = (ml - blur)                        # high-pass: seams/rivets/wear, no colour or large shading
    detail = np.clip(detail, -CLAMP, CLAMP)     # v2: cap so Meshy's glowing/bright patches can't become blotches
    out = np.clip(nat * (1.0 + k*detail[...,None]*1.6), 0, 1)
    dst = root/'variants'/f'hybrid-{v}{SUFFIX}'/m; dst.mkdir(parents=True, exist_ok=True)
    Image.fromarray((out*255).astype(np.uint8)).save(dst/'basecolor.png')
    # v3: glowing native areas (bright + saturated, e.g. emerald panels, engine glow) must stay matte, non-metal and
    # flat, otherwise Meshy's PBR maps turn them into shiny blotches. Elsewhere use Meshy's PBR maps.
    hsv = np.asarray(Image.fromarray((nat*255).astype(np.uint8)).convert('HSV'), np.float32)/255
    glow = ((hsv[...,1] > 0.45) & (hsv[...,2] > 0.40)).astype(np.float32)
    glow = np.asarray(Image.fromarray((glow*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(6)), np.float32)/255
    def load(n, size):
        return np.asarray(Image.open(msh/f'{n}.png').convert('RGB' if n=='normal' else 'L').resize(size, Image.LANCZOS), np.float32)/255
    g2 = np.asarray(Image.fromarray((glow*255).astype(np.uint8)).resize((2048,2048)), np.float32)/255
    rough = load('roughness', (2048,2048)); rough = rough*(1-g2) + 0.9*g2
    metal = load('metallic', (2048,2048)); metal = metal*(1-g2)
    nrm = load('normal', (4096,4096)); flat = np.array([0.5,0.5,1.0],np.float32); nrm = nrm*(1-glow[...,None]) + flat*glow[...,None]
    Image.fromarray((rough*255).astype(np.uint8)).save(dst/'roughness.png')
    Image.fromarray((metal*255).astype(np.uint8)).save(dst/'metallic.png')
    Image.fromarray((nrm*255).astype(np.uint8)).save(dst/'normal.png')
    Image.open(root/'variants/esrgan'/m/'emission.png').save(dst/'emission.png')
    print(m, v, 'hybrid written', flush=True)
