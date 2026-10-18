"""Paid API safety, genuine loopback requests, extraction and native UV tests."""
import base64
import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

import hd
from glb import native_glb
from metrics import evaluate


class FakeClient:
    def __init__(self, balance=100, fail=False):
        self.value, self.posts, self.fail = balance, 0, fail

    def balance(self):
        return self.value

    def request(self, endpoint, body):
        self.posts += 1
        if self.fail:
            raise RuntimeError('uncertain POST')
        self.value -= 10
        return {'result': 'test-task'}


def fixture(root):
    rgba = np.full((64, 64, 4), 255, dtype=np.uint8)
    rgba[..., :3] = 120
    rgba[16:48, 30:34, :3] = 200
    doc = {'Width': 64, 'Height': 64, 'Rgba': base64.b64encode(rgba.tobytes()).decode(), 'Frames': [],
           'Meshes': [{'Positions': [0, 0, 0, 1, 0, 0, 0, 1, 0], 'Normals': [0, 0, 1]*3,
                       'TexCoords': [0, 0, 1, 0, 0, 1], 'Indices': [0, 1, 2], 'VertexCount': 3, 'TriangleCount': 1}]}
    source = root / 'native.json'
    source.write_text(json.dumps(doc))
    native_glb(source, root / 'native.glb')
    return source, doc


class HdTests(unittest.TestCase):
    def manifest(self):
        return {'jobs': {}, 'balance_checks': []}

    def test_cap_is_cumulative_and_prevents_eleventh_post(self):
        manifest, client, snapshots = self.manifest(), FakeClient(1000), []
        save = lambda: snapshots.append(json.loads(json.dumps(manifest)))
        for i in range(10):
            self.assertTrue(hd.submit(client, manifest, f'ship{i}:multiview', {}, 100, save))
        self.assertFalse(hd.submit(client, manifest, 'extra:text', {}, 100, save))
        self.assertEqual(10, client.posts)
        self.assertEqual(100, hd.reserved_credits(manifest))
        self.assertEqual('SUBMITTING', snapshots[1]['jobs']['ship0:multiview']['status'])

    def test_insufficient_balance_or_budget_never_posts(self):
        for balance, budget in [(9, 100), (100, 9), (100, 0)]:
            client = FakeClient(balance)
            self.assertFalse(hd.submit(client, self.manifest(), 'ship:multiview', {}, budget, lambda: None))
            self.assertEqual(0, client.posts)

    def test_ambiguous_post_is_durably_reserved_and_not_duplicated(self):
        manifest, client = self.manifest(), FakeClient(fail=True)
        snapshots = []
        with self.assertRaises(RuntimeError):
            hd.submit(client, manifest, 'ship:multiview', {}, 100, lambda: snapshots.append(json.loads(json.dumps(manifest))))
        persisted = snapshots[-1]
        self.assertIsNone(persisted['jobs']['ship:multiview']['task_id'])
        self.assertEqual(10, hd.reserved_credits(persisted))
        self.assertFalse(hd.submit(client, persisted, 'ship:multiview', {}, 100, lambda: None))
        self.assertEqual(1, client.posts)

    def test_task_id_saved_before_balance_failure(self):
        class AfterSubmitFailure(FakeClient):
            def balance(self):
                if self.posts:
                    raise RuntimeError('balance unavailable')
                return 100
        manifest, snapshots = self.manifest(), []
        with self.assertRaises(RuntimeError):
            hd.submit(AfterSubmitFailure(), manifest, 'ship:multiview', {}, 100,
                      lambda: snapshots.append(json.loads(json.dumps(manifest))))
        self.assertEqual('test-task', snapshots[-1]['jobs']['ship:multiview']['task_id'])

    def test_real_loopback_http_contract_and_no_post_retry(self):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                seen.append((self.command, self.path, self.headers.get('Authorization')))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"balance":100}')

            def do_POST(self):
                seen.append((self.command, self.path, self.headers.get('Authorization')))
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'server error containing confidential request details')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                key = Path(directory) / 'key'
                key.write_text('unit-test-key')
                client = hd.Meshy(key)
                with patch.object(hd, 'API', f'http://127.0.0.1:{server.server_port}'):
                    self.assertEqual(100, client.balance())
                    with self.assertRaisesRegex(RuntimeError, '^Meshy HTTP 500; request details suppressed$'):
                        client.request('/retexture', {'test': True})
            self.assertEqual([('GET', '/balance', 'Bearer unit-test-key'), ('POST', '/retexture', 'Bearer unit-test-key')], seen)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_glb_roundtrip_preserves_native_geometry_uv_normals_and_texture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, doc = fixture(root)
            data = (root / 'native.glb').read_bytes()
            magic, version, length = struct.unpack_from('<III', data)
            self.assertEqual((0x46546c67, 2, len(data)), (magic, version, length))
            size = struct.unpack_from('<I', data, 12)[0]
            gltf = json.loads(data[20:20+size])
            binary = data[28+size:]
            primitive = gltf['meshes'][0]['primitives'][0]
            for attribute, field in [('POSITION', 'Positions'), ('NORMAL', 'Normals'), ('TEXCOORD_0', 'TexCoords')]:
                accessor = gltf['accessors'][primitive['attributes'][attribute]]
                view = gltf['bufferViews'][accessor['bufferView']]
                actual = np.frombuffer(binary[view['byteOffset']:view['byteOffset']+view['byteLength']], dtype='<f4')
                np.testing.assert_array_equal(actual, doc['Meshes'][0][field])
            image = gltf['bufferViews'][gltf['images'][0]['bufferView']]
            with Image.open(io.BytesIO(binary[image['byteOffset']:image['byteOffset']+image['byteLength']])) as decoded:
                self.assertEqual(base64.b64decode(doc['Rgba']), decoded.tobytes())

    def test_variants_exclusive_and_data_uri_size_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'views').mkdir()
            (root / 'native.glb').write_bytes(b'glb')
            for view in hd.VIEWS:
                (root / 'views' / (view+'.png')).write_bytes(b'png')
            multi = hd.request_body(root, 'multiview', 'prompt')
            text = hd.request_body(root, 'text', 'prompt')
            self.assertEqual(4, len(multi['multiview_image_urls']))
            self.assertNotIn('text_style_prompt', multi)
            self.assertNotIn('multiview_image_urls', text)
            self.assertEqual('prompt', text['text_style_prompt'])
            self.assertTrue(multi['enable_original_uv'])
            with self.assertRaises(ValueError):
                hd.uri(root / 'native.glb', 2)

    def test_private_output_rejects_repo_and_symlink_into_repo(self):
        with self.assertRaises(ValueError):
            hd.external_root(hd.REPO / 'generated')
        with tempfile.TemporaryDirectory() as directory:
            link = Path(directory) / 'linked'
            link.symlink_to(hd.REPO, target_is_directory=True)
            with self.assertRaises(ValueError):
                hd.external_root(link / 'generated')

    def test_emission_fallback_is_explicit_and_missing_required_maps_rejected(self):
        def fake_download(url, destination):
            Image.new('RGB', (4096, 4096), 'gray').save(destination)
        with tempfile.TemporaryDirectory() as directory, patch.object(hd, 'download', fake_download):
            target = Path(directory)
            fields = {name: 'https://example.test/'+name for name in ('base_color', 'normal', 'metallic', 'roughness')}
            origins = hd.extract({'texture_urls': [fields]}, target)
            self.assertIn('fallback', origins['emission'])
            with Image.open(target / 'emission.png') as emission:
                self.assertEqual((0, 0, 0), emission.getpixel((0, 0)))
            del fields['normal']
            with self.assertRaisesRegex(ValueError, 'omitted required normal'):
                hd.extract({'texture_urls': [fields]}, target)

    def test_wrong_size_is_retained_and_fails_metrics_without_upscaling(self):
        def tiny(url, destination):
            Image.new('RGB', (1024, 1024)).save(destination)
        with tempfile.TemporaryDirectory() as directory, patch.object(hd, 'download', tiny):
            root = Path(directory)
            source, _ = fixture(root)
            fields = {name: 'https://example.test/'+name for name in ('base_color', 'normal', 'metallic', 'roughness')}
            hd.extract({'texture_urls': [fields]}, root)
            with Image.open(root / 'metallic.png') as im:
                self.assertEqual((1024, 1024), im.size)
            result = evaluate(source, root)
            self.assertFalse(result['checks']['sizes'])
            self.assertFalse(result['accepted'])

    def test_metrics_detect_palette_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = fixture(root)
            maps = root / 'maps'
            maps.mkdir()
            for name in ('normal', 'metallic', 'roughness', 'emission'):
                Image.new('RGB', (4096, 4096)).save(maps / (name+'.png'))
            with Image.open(root / 'native.png') as im:
                im.resize((4096, 4096), Image.Resampling.NEAREST).save(maps / 'basecolor.png')
            same = evaluate(source, maps)
            self.assertLess(same['palette_delta_e'], 1)
            self.assertEqual(1, same['coverage_iou'])
            self.assertGreater(same['edge_f1'], .99)
            Image.new('RGB', (4096, 4096), 'red').save(maps / 'basecolor.png')
            changed = evaluate(source, maps)
            self.assertFalse(changed['checks']['palette'])
            self.assertFalse(changed['accepted'])

    def test_metrics_detect_baked_gradient_and_unmeasured_wrapped_uv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, doc = fixture(root)
            Image.new('RGB', (64, 64), (120, 120, 120)).save(root / 'native.png')
            maps = root / 'maps'
            maps.mkdir()
            for name in ('normal', 'metallic', 'roughness', 'emission'):
                Image.new('RGB', (64, 64)).save(maps / (name+'.png'))
            gradient = np.broadcast_to(np.linspace(0, 255, 64, dtype=np.uint8)[None, :, None], (64, 64, 3)).copy()
            Image.fromarray(gradient).save(maps / 'basecolor.png')
            result = evaluate(source, maps)
            self.assertGreater(result['flat_panel_samples'], 0)
            self.assertGreater(result['flat_panel_gradient_p95'], .9)
            self.assertFalse(result['checks']['lighting'])
            doc['Meshes'].append(dict(doc['Meshes'][0], TexCoords=[-.5, 0, 1, 0, 0, 1]))
            source.write_text(json.dumps(doc))
            wrapped = evaluate(source, maps)
            self.assertEqual(1, wrapped['wrapped_triangles_unmeasured'])
            self.assertFalse(wrapped['checks']['uv_range'])

    def test_dry_run_never_reads_key_or_creates_addon(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'not-created'
            args = type('Args', (), dict(addon=str(root), models=None, variant='both', budget=100, dry_run=True))()
            with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(hd, 'Meshy', side_effect=AssertionError('key read')):
                hd.run(args)
            self.assertFalse(root.exists())
            plan = json.loads(output.getvalue())
            self.assertEqual(12, len(plan['plan']))
            self.assertEqual(10, plan['maximum_new_jobs'])


if __name__ == '__main__':
    unittest.main()
