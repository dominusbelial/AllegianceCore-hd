"""Objective texture diagnostics on the ORIGINAL UVs; no vision inference.

These are heuristic rejection gates, not proof of artistic quality or lighting.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

THRESHOLDS = {'coverage_iou_min': .98, 'edge_f1_min': .20,
              'palette_delta_e_max': 25., 'flat_panel_gradient_p95_max': .18}


def lab(rgb):
    rgb = np.where(rgb <= .04045, rgb / 12.92, ((rgb+.055)/1.055)**2.4)
    xyz = rgb @ np.array([[.4124564, .3575761, .1804375], [.2126729, .7151522, .0721750],
                          [.0193339, .1191920, .9503041]]).T / [.95047, 1, 1.08883]
    f = np.where(xyz > (6/29)**3, np.cbrt(xyz), xyz/(3*(6/29)**2)+4/29)
    return np.stack([116*f[..., 1]-16, 500*(f[..., 0]-f[..., 1]), 200*(f[..., 1]-f[..., 2])], axis=-1)


def edge_mask(rgb):
    lum = rgb @ [.2126, .7152, .0722]
    dx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1]))
    dy = np.abs(np.diff(lum, axis=0, prepend=lum[:1]))
    return np.hypot(dx, dy) > .10


def dilate(mask):
    return np.asarray(Image.fromarray(np.uint8(mask)*255).filter(ImageFilter.MaxFilter(3))) > 0


def evaluate(native_json, maps):
    doc = json.loads(Path(native_json).read_text())
    with Image.open(Path(native_json).with_name('native.png')) as image:
        native_image = image.convert('RGBA')
    with Image.open(maps / 'basecolor.png') as image:
        hd_image = image.convert('RGBA')
    # Compare at the native information scale, capped at 512 for repeatability.
    size = tuple(min(512, n) for n in native_image.size)
    w, h = size
    native = np.asarray(native_image.resize(size, Image.Resampling.BOX), dtype=float)/255
    hd = np.asarray(hd_image.resize(size, Image.Resampling.BOX), dtype=float)/255
    mask_image = Image.new('L', size)
    draw = ImageDraw.Draw(mask_image)
    panels = []
    uv_outside = 0
    for mesh in doc['Meshes']:
        uv = np.asarray(mesh['TexCoords']).reshape(-1, 2)
        for tri in np.asarray(mesh['Indices']).reshape(-1, 3):
            coords = uv[tri]
            if (coords < 0).any() or (coords > 1).any():
                uv_outside += 1
                continue  # cannot rasterize wrapped triangles by merely modulo-ing endpoints
            polygon = [(float(u*(w-1)), float(v*(h-1))) for u, v in coords]
            draw.polygon(polygon, fill=255)
            panels.append(polygon)
    mask = np.asarray(mask_image) > 0
    if not mask.any():
        raise ValueError('No native UV coverage within [0,1]')
    coverage_native, coverage_hd = mask & (native[..., 3] > .5), mask & (hd[..., 3] > .5)
    iou = float((coverage_native & coverage_hd).sum()/max(1, (coverage_native | coverage_hd).sum()))
    ne, he = edge_mask(native[..., :3]) & mask, edge_mask(hd[..., :3]) & mask
    precision = float((he & dilate(ne)).sum()/max(1, he.sum()))
    recall = float((ne & dilate(he)).sum()/max(1, ne.sum()))
    f1 = 2*precision*recall/max(1e-9, precision+recall)
    # Compare marginal Lab distributions, including their tails; all covered texels.
    quantiles = np.linspace(.05, .95, 19)
    nq = np.quantile(lab(native[..., :3])[mask], quantiles, axis=0)
    hq = np.quantile(lab(hd[..., :3])[mask], quantiles, axis=0)
    palette = float(np.linalg.norm(nq-hq, axis=1).mean())
    slopes = []
    nl, hl = native[..., :3] @ [.2126, .7152, .0722], hd[..., :3] @ [.2126, .7152, .0722]
    for polygon in panels:
        panel = Image.new('L', size)
        ImageDraw.Draw(panel).polygon(polygon, fill=255)
        interior = np.asarray(panel.filter(ImageFilter.MinFilter(3))) > 0
        yy, xx = np.where(interior)
        if len(xx) < 24 or np.std(nl[interior]) > .08:
            continue
        x = (xx-xx.mean())/max(1, np.ptp(xx))
        y = (yy-yy.mean())/max(1, np.ptp(yy))
        slope = np.linalg.lstsq(np.stack([x, y, np.ones(len(x))], axis=1), hl[interior], rcond=None)[0]
        slopes.append(float(np.hypot(*slope[:2])))
    gradient = float(np.quantile(slopes, .95)) if slopes else None
    sizes = {}
    for name in ('basecolor', 'normal', 'metallic', 'roughness', 'emission'):
        with Image.open(maps / (name+'.png')) as image:
            sizes[name] = list(image.size)
    checks = {'sizes': all(s == [4096, 4096] for s in sizes.values()),
              'coverage': iou >= THRESHOLDS['coverage_iou_min'],
              'edges': f1 >= THRESHOLDS['edge_f1_min'],
              'palette': palette <= THRESHOLDS['palette_delta_e_max'],
              'lighting': gradient is not None and gradient <= THRESHOLDS['flat_panel_gradient_p95_max'],
              'uv_range': uv_outside == 0}
    return {'map_sizes': sizes, 'uv_coverage_fraction': float(mask.mean()), 'coverage_iou': iou,
            'edge_precision': precision, 'edge_recall': recall, 'edge_f1': f1,
            'palette_delta_e': palette, 'flat_panel_samples': len(slopes),
            'flat_panel_gradient_p95': gradient, 'wrapped_triangles_unmeasured': uv_outside,
            'thresholds': THRESHOLDS, 'checks': checks, 'accepted': all(checks.values()),
            'limitations': 'Opaque coverage detects alpha holes only; edge/palette/gradient gates are heuristics. '
                           'UV preservation relies on native geometry being retained for preview/runtime.'}
