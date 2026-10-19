"""Export native atlases by stem (2026-10-19) into inputs/<stem>/native.png for the mini's ESRGAN worker.
Usage: python export_atlases.py atlases-todo.txt   (env ALLEGIANCE_CORE_REPO = AllegianceCore checkout with local.env)"""
import base64, json, os, subprocess, sys
from pathlib import Path
from PIL import Image
HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
REPO = Path(os.environ.get('ALLEGIANCE_CORE_REPO', HERE.parent.parent / 'AllegianceCore')).resolve()
ok = failed = 0
for stem in [l.strip() for l in Path(sys.argv[1]).read_text().splitlines() if l.strip()]:
    # The core sometimes names an atlas without the file's 'bmp' suffix (tf2 -> tf2bmp.mdl); the runtime resolves it,
    # so try the stem as given, then with 'bmp', and key the atlas by the real file stem.
    for cand in (stem, stem + 'bmp'):
        out = ROOT / 'inputs' / cand
        if (out / 'native.png').exists(): r = None; break
        out.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(['dotnet', str(HERE / 'bin/Debug/net10.0/hd-native.dll'), '--stem', cand, str(out / 'native.json')],
                           cwd=REPO, capture_output=True, text=True, timeout=300)
        if r.returncode == 0: break
        try: out.rmdir()
        except OSError: pass
    if r is None: continue
    if r.returncode != 0:
        # Text MDL that imports an image (e.g. ss94bmp.mdl: ImportImageFromFile("ss94.png", false)): use that image.
        import re
        art = Path(os.environ.get('ALLEGIANCE_ARTWORK_PATH') or [l.split('=',1)[1].strip() for l in (REPO/'local.env').read_text().splitlines() if l.startswith('ALLEGIANCE_ARTWORK_PATH=')][0])
        for cand in (stem, stem + 'bmp'):
            mdl = art / (cand + '.mdl')
            if not mdl.exists(): continue
            m = re.search(r'ImportImageFromFile\("([^"]+)"', mdl.read_text(errors='ignore'))
            if m and (art / m.group(1)).exists():
                out = ROOT / 'inputs' / cand; out.mkdir(parents=True, exist_ok=True)
                Image.open(art / m.group(1)).convert('RGBA').save(out / 'native.png')
                (out / 'native.json').write_text(json.dumps({'Texture': cand, 'ImportedImage': m.group(1)}))
                r = None; ok += 1; break
        if r is None: continue
    if r.returncode != 0:
        failed += 1; print(f'{stem}: FAILED {(r.stderr or r.stdout).strip().splitlines()[-1][:150]}'); continue
    d = json.loads((out / 'native.json').read_text())
    Image.frombytes('RGBA', (d['Width'], d['Height']), base64.b64decode(d['Rgba'])).save(out / 'native.png')
    ok += 1
print(f'exported {ok}, failed {failed}')
