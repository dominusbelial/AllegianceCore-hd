#!/usr/bin/env python3
"""HD1 private add-on pipeline. No key, payload, or generated art is logged."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw

from glb import native_glb
from metrics import evaluate

HERE = Path(__file__).resolve().parent
import os
# The MIT code repo (native mesh decoding); expected next to this add-on repo unless ALLEGIANCE_CORE_REPO is set.
REPO = Path(os.environ.get('ALLEGIANCE_CORE_REPO', HERE.parent.parent / 'AllegianceCore')).resolve()
API = 'https://api.meshy.ai/openapi/v1'
JOB_CREDITS = 10  # 4K Retexture; https://docs.meshy.ai/en/api/pricing (2026-10-17)
SETTINGS = dict(ai_model='meshy-7', texture_resolution='4k', enable_pbr=True,
                enable_original_uv=True, remove_lighting=True, target_formats=['glb'])
VIEWS = ('front', 'three_quarter', 'side', 'top')


def external_root(path):
    path = Path(path).expanduser().resolve()
    if path == REPO or REPO in path.parents:
        raise ValueError('Generated assets must live outside AllegianceCore')
    return path


def write_json(path, value):
    temp = path.with_suffix(path.suffix+'.tmp')
    with temp.open('w') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def uri(path, maximum):
    if path.stat().st_size > maximum:
        raise ValueError('Input exceeds Meshy data URI size limit')
    mime = 'model/gltf-binary' if path.suffix == '.glb' else 'image/png'
    return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()


def request_body(inputs, variant, prompt):
    body = dict(SETTINGS, model_url=uri(inputs / 'native.glb', 100_000_000))
    if variant == 'text6':  # round 2 (Claude): Meshy 6 claims emission + honoured remove_lighting
        body['ai_model'] = 'meshy-6'
    if variant == 'multiview':
        body['multiview_image_urls'] = [uri(inputs / 'views' / (v+'.png'), 20_000_000) for v in VIEWS]
    else:
        body['text_style_prompt'] = prompt
    return body


class Meshy:
    def __init__(self, key_file):
        self.key = Path(key_file).expanduser().read_text().strip()
        if not self.key or '\n' in self.key:
            raise ValueError('Invalid credential file')

    def request(self, endpoint, body=None):
        request = urllib.request.Request(API+endpoint,
            data=json.dumps(body).encode() if body is not None else None,
            headers={'Authorization': 'Bearer '+self.key, 'Content-Type': 'application/json'})
        # Never retry POST: a timeout can mean the paid task was created.
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'Meshy HTTP {error.code}; request details suppressed') from None
        except (urllib.error.URLError, TimeoutError):
            raise RuntimeError('Meshy connection failed; POST outcome may be unknown') from None

    def balance(self):
        value = self.request('/balance')['balance']
        if not isinstance(value, int) or value < 0:
            raise ValueError('Invalid Meshy balance')
        return value


def reserved_credits(manifest):
    return sum(max(j['reserved_credits'], j.get('consumed_credits') or 0) for j in manifest['jobs'].values())


def submit(client, manifest, key, body, budget, save):
    if key in manifest['jobs']:
        return False
    before = client.balance()  # required even on the cap-stop path
    manifest['balance_checks'].append({'time': time.time(), 'before_job': key, 'balance': before})
    save()
    if reserved_credits(manifest)+JOB_CREDITS > budget or before < JOB_CREDITS:
        return False
    job = {'status': 'SUBMITTING', 'task_id': None, 'reserved_credits': JOB_CREDITS,
           'balance_before': before, 'settings': {**SETTINGS, 'ai_model': body.get('ai_model', SETTINGS['ai_model'])}, 'variant': key.split(':')[1]}
    job['conditioning'] = ({'text_style_prompt': body['text_style_prompt']} if 'text_style_prompt' in body
                           else {'native_reference_views': list(VIEWS)})
    manifest['jobs'][key] = job
    save()  # durable reservation before the charge, including uncertain network failures
    response = client.request('/retexture', body)
    job['task_id'] = response['result']
    job['status'] = 'PENDING'
    save()  # persist task ID BEFORE requesting balance or doing any other I/O
    job['balance_after_submit'] = client.balance()
    save()
    print(f'{key}: submitted; balance {before} -> {job["balance_after_submit"]}', flush=True)
    return True


def download(url, path, maximum=500_000_000):
    if not url.startswith('https://'):
        raise ValueError('Meshy asset URL must be HTTPS')
    temp = path.with_suffix(path.suffix+'.download')
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temp.open('wb') as out:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > maximum:
                    raise ValueError('Meshy asset exceeds download limit')
                out.write(chunk)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def extract(task, target):
    sets = task.get('texture_urls', [])
    if len(sets) != 1:
        raise ValueError('Pilot expects exactly one returned texture atlas')
    origins = {}
    for name, field in [('basecolor', 'base_color'), ('normal', 'normal'), ('metallic', 'metallic'), ('roughness', 'roughness'), ('emission', 'emission')]:
        destination = target / (name+'.png')
        url = sets[0].get(field)
        if url:
            download(url, destination)
            with Image.open(destination) as im:
                # Retain the provider's true resolution. The metrics size gate
                # rejects non-4K maps without discarding other completed jobs.
                im.save(destination, format='PNG')
            origins[name] = 'Meshy generated'
        elif name == 'emission':
            # Meshy 7 does not emit this map. An explicit neutral fallback, never
            # described as generated emission, keeps the five-file load contract.
            Image.new('RGB', (4096, 4096), (0, 0, 0)).save(destination)
            origins[name] = 'neutral black fallback; Meshy 7 supplies no emission'
        else:
            raise ValueError(f'Meshy omitted required {name} map')
    return origins


def render(blender, root, inputs, output, maps=None):
    config = {'glb': str(inputs / 'native.glb'), 'out': str(output), 'maps': str(maps) if maps else None}
    config_file = output.parent / (output.name+'-render.json')
    write_json(config_file, config)
    with (output.parent / (output.name+'-render.log')).open('w') as log:
        subprocess.run([blender, '--background', '--factory-startup', '--python', str(HERE / 'blender_preview.py'), '--', str(config_file)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    for view in VIEWS:
        with Image.open(output / (view+'.png')) as im:
            if im.size != (1024, 1024):
                raise ValueError('Reference render is not 1024 square')


def contact_sheet(native, hd, destination, label):
    sheet = Image.new('RGB', (2048, 1100), '#202020')
    draw = ImageDraw.Draw(sheet)
    draw.text((12, 10), label+' | native (top) / HD on native geometry (bottom)', fill='white')
    for column, view in enumerate(VIEWS):
        draw.text((column*512+12, 40), view, fill='white')
        for row, directory in enumerate((native, hd)):
            with Image.open(directory / (view+'.png')) as im:
                sheet.paste(im.convert('RGB').resize((512, 512)), (column*512, 76+row*512))
    sheet.save(destination)


def prepare(args, root, model):
    inputs = root / 'inputs' / model
    inputs.mkdir(parents=True, exist_ok=True)
    # Re-read and hash native inputs on every run. Previously submitted jobs
    # below must match these hashes; stale caches cannot submit changed meshes.
    with (inputs / 'decode.log').open('w') as log:
        subprocess.run(['dotnet', str(HERE / 'bin/Debug/net10.0/hd-native.dll'), model, str(inputs / 'native.json')],
                       stdout=log, stderr=subprocess.STDOUT, check=True, cwd=REPO)
    geometry = native_glb(inputs / 'native.json', inputs / 'native.glb')
    native = json.loads((inputs / 'native.json').read_text())
    source = {k: native[k] for k in ('Model', 'Texture', 'ModelSha256', 'TextureSha256', 'Hulls')}
    source['geometry'] = geometry
    fingerprint = hashlib.sha256((inputs / 'native.glb').read_bytes()).hexdigest()
    stamp = inputs / 'views-source.sha256'
    if not stamp.exists() or stamp.read_text() != fingerprint or not all((inputs / 'views' / (v+'.png')).exists() for v in VIEWS):
        render(args.blender, root, inputs, inputs / 'views')
        stamp.write_text(fingerprint)
    source['glb_sha256'] = fingerprint
    source['reference_sha256'] = {v: hashlib.sha256((inputs / 'views' / (v+'.png')).read_bytes()).hexdigest() for v in VIEWS}
    return source


def initialize(root):
    root.mkdir(parents=True, exist_ok=True)
    if not (root / '.git').exists():
        subprocess.run(['git', 'init', '--quiet', str(root)], check=True)
    remotes = subprocess.check_output(['git', '-C', str(root), 'remote'], text=True).strip()
    if remotes:
        raise ValueError('HD1 add-on must have no remote')
    (root / 'README.md').write_text('''# AllegianceCore HD texture pilot — PRIVATE

Meshy-generated private add-on. Do not redistribute through AllegianceCore.
Native geometry, UVs, hardpoints, scale and orientation remain authoritative.
`models/<nativeModelName>/` contains basecolor, normal, metallic, roughness and
emission PNGs. Meshy 7 omits emission: the manifest labels a neutral black
fallback, which does not preserve authored glow. Text comparisons, if funded,
live under `variants/text/` and never overwrite the multiview pilot.

The current client does not load this pack. HD-2 must implement an opt-in pack
path, validate native model/texture SHA256 against manifest.json, require an
accepted review, and bind these maps to native UVs. Basecolor is sRGB; normal,
metallic, roughness and emission fallback are data maps. Never load generated
geometry or replace the native hardpoints. Missing/rejected packs retain native
art. PBR previews under review/ demonstrate the material on native geometry.

`inputs/` contains decoded native assets, GLBs and four 1024-square references.
`tasks/` retains Meshy GLBs for audit only. `manifest.json` is a durable credit
and duplicate-submission ledger. Do not delete it to restart a run. A SUBMITTING
entry without a task ID needs manual account reconciliation; never resubmit it.
No commits, remotes or pushes were made by this pipeline.
''')


def run(args):
    root = external_root(args.addon)
    pilot = json.loads((HERE / 'pilot.json').read_text())
    known = {p['model']: p for p in pilot}
    models = args.models.split(',') if args.models else list(known)
    if not models or len(models) != len(set(models)) or any(m not in known for m in models):
        raise ValueError('--models must be unique names from pilot.json (ships only)')
    variants = ('multiview', 'text') if args.variant == 'both' else (args.variant,)
    plan = [(m, v) for v in variants for m in (models[:2] if v == 'text' and args.variant == 'both' else models)]
    if args.dry_run:
        print(json.dumps({'addon': str(root), 'budget': args.budget, 'credits_per_job': JOB_CREDITS,
                          'plan': [{'model': m, 'variant': v} for m, v in plan],
                          'maximum_new_jobs': args.budget//JOB_CREDITS, 'settings': SETTINGS}, indent=2))
        return
    os.umask(0o077)
    initialize(root)
    with (root / '.pipeline.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Reject pre-existing output symlinks which could route private art into
        # the public checkout or outside the designated private repository.
        for child in root.rglob('*'):
            if child.is_symlink():
                raise ValueError('Add-on contains symlinks; refusing unsafe output layout')
        manifest_path = root / 'manifest.json'
        manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
            'schema': 1, 'private': True, 'jobs': {}, 'models': {}, 'balance_checks': [],
            'api_limitations': ['Meshy 7 omits emission', 'Meshy 7 accepts but ignores remove_lighting'],
            'pricing_source': 'https://docs.meshy.ai/en/api/pricing'}
        save = lambda: write_json(manifest_path, manifest)
        manifest['budget'] = args.budget
        save()
        if not args.poll_only:
            for model in models:
                print(model+': preparing native GLB and references', flush=True)
                source = prepare(args, root, model)
                previous = manifest['models'].get(model)
                if previous and any(k.startswith(model+':') for k in manifest['jobs']) and source != previous['native']:
                    raise ValueError('Native source changed after submission; refusing stale or duplicate task')
                manifest['models'][model] = dict(known[model], native=source)
                save()
        if args.prepare_only:
            return
        client = Meshy(args.key_file)
        if not args.poll_only:
            for model, variant in plan:
                key = model+':'+variant
                if key in manifest['jobs']:
                    continue
                body = request_body(root / 'inputs' / model, variant, known[model]['prompt'])
                if not submit(client, manifest, key, body, args.budget, save):
                    print(key+': stopped before submission (credit cap or balance)', flush=True)
                    break
        deadline = time.monotonic()+args.timeout
        pending = [k for k in manifest['jobs'] if k in [m+':'+v for m, v in plan]]
        while pending:
            for key in pending[:]:
                job = manifest['jobs'][key]
                if job.get('complete') or not job.get('task_id') or job['status'] in ('FAILED', 'CANCELED'):
                    pending.remove(key)
                    continue
                task = client.request('/retexture/'+job['task_id'])
                job['status'] = task['status']
                job['consumed_credits'] = task.get('consumed_credits')
                save()
                print(f'{key}: {job["status"]} {task.get("progress", 0)}%', flush=True)
                if job['status'] in ('FAILED', 'CANCELED'):
                    job['balance_after'] = client.balance()
                    save()
                    pending.remove(key)
                elif job['status'] == 'SUCCEEDED':
                    model, variant = key.split(':')
                    target = root / ('models' if variant == 'multiview' else 'variants/'+variant) / model
                    target.mkdir(parents=True, exist_ok=True)
                    job['map_origins'] = extract(task, target)
                    tasks = root / 'tasks' / model / variant
                    tasks.mkdir(parents=True, exist_ok=True)
                    download(task['model_urls']['glb'], tasks / 'meshy.glb')
                    job['metrics'] = evaluate(root / 'inputs' / model / 'native.json', target)
                    job['map_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.glob('*.png')}
                    save()
                    preview = root / 'review' / model / variant
                    preview.parent.mkdir(parents=True, exist_ok=True)
                    render(args.blender, root, root / 'inputs' / model, preview, target)
                    contact_sheet(root / 'inputs' / model / 'views', preview, preview.parent / (variant+'-contact.png'), model)
                    job['balance_after'] = client.balance()
                    job['complete'] = True
                    save()
                    pending.remove(key)
            if pending:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Polling deadline reached; rerun --poll-only to resume existing tasks')
                time.sleep(args.poll_interval)
        print(f'Ledger reserves {reserved_credits(manifest)}/{args.budget} credits; outputs: {root}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', help='Comma-separated native ship names from pilot.json; default all ten')
    parser.add_argument('--variant', choices=('multiview', 'text', 'text6', 'both'), default='multiview')
    parser.add_argument('--budget', type=int, default=100, help='Cumulative ledger cap, not a fresh per-run allowance')
    parser.add_argument('--dry-run', action='store_true', help='Print plan only: no files, keys, rendering or API calls')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--poll-only', action='store_true', help='Resume tasks; never submit new jobs')
    parser.add_argument('--addon', default=str(Path.home() / 'Development/AllegianceCore-hd'))
    parser.add_argument('--key-file', default=str(Path.home() / 'meshyApi.txt'))
    parser.add_argument('--blender', default='blender', help='Headless Blender executable')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--poll-interval', type=int, default=20)
    args = parser.parse_args()
    if args.budget < 0 or args.poll_interval < 1 or args.timeout < 1 or (args.prepare_only and args.poll_only):
        parser.error('Invalid budget, timeout, polling interval or mode combination')
    try:
        run(args)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError, KeyError) as error:
        # Do not print remote bodies, signed URLs, request objects or credentials.
        print('HD1 stopped: '+str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
