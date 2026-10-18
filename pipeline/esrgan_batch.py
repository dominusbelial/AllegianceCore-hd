"""ESRGAN HD batch (Claude, 2026-10-18): the chosen HD method after the slice-20 review showed Meshy retextures
invent features (stencils, canopy frames, panel lines) and, once those are forbidden, add little over ESRGAN.
For each model: export the native mesh/texture (hd-native, cwd = AllegianceCore repo), then ESRGAN x4 + derived
PBR maps via esrgan_variant.py. Resumable: models with variants/esrgan/<m>/basecolor.png are skipped.
Usage: python esrgan_batch.py ships.txt [--export-only]   (export-only: native.png for the mini's ESRGAN worker)     (env ALLEGIANCE_CORE_REPO; set OMP_NUM_THREADS to cap CPU)"""
import json, os, subprocess, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = Path(os.environ.get('ALLEGIANCE_CORE_REPO', HERE.parent.parent / 'AllegianceCore')).resolve()
sys.path.insert(0, str(HERE))
from glb import native_glb
models = [l.split()[0] for l in Path(sys.argv[1]).read_text().splitlines() if l.strip() and not l.startswith('#')]
log = ROOT / 'esrgan-batch.jsonl'
done, failed = 0, []
for m in models:
    if (ROOT / 'variants/esrgan' / m / 'basecolor.png').exists() or ('--export-only' in sys.argv and (ROOT / 'inputs' / m / 'native.png').exists()):
        continue
    t = time.time(); inputs = ROOT / 'inputs' / m; inputs.mkdir(parents=True, exist_ok=True)
    try:
        with (inputs / 'decode.log').open('w') as dl:
            subprocess.run(['dotnet', str(HERE / 'bin/Debug/net10.0/hd-native.dll'), m, str(inputs / 'native.json')],
                           stdout=dl, stderr=subprocess.STDOUT, check=True, cwd=REPO, timeout=600)
        native_glb(inputs / 'native.json', inputs / 'native.glb')
        if '--export-only' in sys.argv:
            done += 1; status = 'exported'
            with log.open('a') as f: f.write(json.dumps({'model': m, 'status': status, 'seconds': round(time.time() - t)}) + '\n')
            print(f'{m}: {status}', flush=True); continue
        subprocess.run([sys.executable, str(HERE / 'esrgan_variant.py'), m], check=True, timeout=7200,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        done += 1; status = 'ok'
    except Exception as e:
        reason = (inputs / 'decode.log').read_text()[-300:] if (inputs / 'decode.log').exists() else str(e)
        failed.append(m); status = 'failed: ' + reason.strip().splitlines()[-1][:200] if reason.strip() else str(e)
    with log.open('a') as f:
        f.write(json.dumps({'model': m, 'status': status, 'seconds': round(time.time() - t)}) + '\n')
    print(f'{m}: {status} ({round(time.time()-t)} s)', flush=True)
print(f'done {done}, failed {len(failed)}: {" ".join(failed)}')
