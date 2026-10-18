"""Hybrid v4 (Claude, 2026-10-18): fix invented features seen in the slice-20 close-ups (stencil text on wc_icfig,
canopy frames on fig03, glowing rings on bom04, greebles on cap06a/utl102).

v3 added Meshy's albedo high-pass everywhere; Meshy invents markings and panels where the native texture is flat.
v4 keeps the native look and lets Meshy only *refine existing structure*:
  - base colour  = native ESRGAN x4, unchanged (no Meshy albedo at all: no painted text, decals or rings);
  - structure    S = local edge energy of the native texture (blurred), 0 on flat areas, 1 on panelled areas;
  - glass/glow   G = bright + saturated native areas (canopies, lights, engine glows), dilated;
  - normal       = flat + (Meshy - flat) * S * (1 - G)      (relief only where the original has panels/edges);
  - roughness/metallic = ESRGAN-derived maps on flat areas, Meshy's on structured areas, matte non-metal on G.
Usage: python hybrid_v4.py model:meshyVariant [...]   (env HYBRID_V4_STRENGTH, default 1.0)
Writes <addon>/variants/hybrid-<variant>-v4/<model>/{basecolor,normal,roughness,metallic,emission}.png"""
import os, sys, numpy as np
from pathlib import Path
from PIL import Image, ImageFilter
root = Path.home()/'Development/AllegianceCore-hd'
K = float(os.environ.get('HYBRID_V4_STRENGTH', '1.0'))
def img(p, mode, size):
    return np.asarray(Image.open(p).convert(mode).resize(size, Image.LANCZOS), np.float32)/255
def blur(a, r):
    return np.asarray(Image.fromarray((np.clip(a,0,1)*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(r)), np.float32)/255
for spec in sys.argv[1:]:
    m, v = spec.split(':')[:2]
    esr, msh = root/'variants/esrgan'/m, root/'variants'/v/m
    dst = root/'variants'/f'hybrid-{v}-v4'/m; dst.mkdir(parents=True, exist_ok=True)
    N = (4096, 4096)
    nat = img(esr/'basecolor.png', 'RGB', N)
    Image.fromarray((nat*255).astype(np.uint8)).save(dst/'basecolor.png')
    lum = nat @ np.array([0.299, 0.587, 0.114], np.float32)
    gy, gx = np.gradient(blur(lum, 2))
    edge = np.sqrt(gx*gx + gy*gy)
    S = blur(np.clip(edge / (np.percentile(edge, 90) + 1e-6), 0, 1), 12)     # where the native has panels/edges
    hsv = np.asarray(Image.fromarray((nat*255).astype(np.uint8)).convert('HSV'), np.float32)/255
    G = ((hsv[...,1] > 0.35) & (hsv[...,2] > 0.45)).astype(np.float32)
    G = np.clip(blur(G, 10)*1.6, 0, 1)                                        # glass/glow, dilated
    W = np.clip(S*(1-G)*K, 0, 1)
    flat = np.array([0.5, 0.5, 1.0], np.float32)
    n = flat + (img(msh/'normal.png', 'RGB', N) - flat) * W[..., None]
    v3 = n*2-1; v3 /= np.linalg.norm(v3, axis=-1, keepdims=True) + 1e-6
    Image.fromarray(((v3*0.5+0.5)*255).astype(np.uint8)).save(dst/'normal.png')
    H = (2048, 2048); w2 = np.asarray(Image.fromarray((W*255).astype(np.uint8)).resize(H), np.float32)/255
    g2 = np.asarray(Image.fromarray((G*255).astype(np.uint8)).resize(H), np.float32)/255
    for name, glow_val in (('roughness', 0.9), ('metallic', 0.0)):
        a = img(esr/f'{name}.png', 'L', H); b = img(msh/f'{name}.png', 'L', H)
        out = (a*(1-w2) + b*w2)*(1-g2) + glow_val*g2
        Image.fromarray((np.clip(out,0,1)*255).astype(np.uint8)).save(dst/f'{name}.png')
    Image.open(esr/'emission.png').save(dst/'emission.png')
    print(m, v, f'v4 written (structure mean {S.mean():.2f}, glass/glow {G.mean():.2f})', flush=True)
