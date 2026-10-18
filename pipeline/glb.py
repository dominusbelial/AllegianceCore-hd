"""Small GLB writer: native positions/normals/UV values, no unwrap or remesh."""
import base64
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def native_glb(source, destination):
    doc = json.loads(Path(source).read_text())
    texture = Image.frombytes('RGBA', (doc['Width'], doc['Height']), base64.b64decode(doc['Rgba']))
    texture.save(Path(source).with_name('native.png'))
    encoded = io.BytesIO()
    texture.save(encoded, format='PNG')
    binary = bytearray()
    views, accessors, primitives = [], [], []

    def view(data, target=None):
        while len(binary) % 4:
            binary.append(0)
        v = {'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(data)}
        if target:
            v['target'] = target
        views.append(v)
        binary.extend(data)
        return len(views) - 1

    def accessor(values, width, kind, component=5126):
        a = np.asarray(values, dtype='<f4' if component == 5126 else '<u2').reshape(-1, width)
        v = view(a.tobytes(), 34963 if component == 5123 else 34962)
        out = {'bufferView': v, 'componentType': component, 'count': len(a), 'type': kind}
        if kind == 'VEC3':
            out.update(min=a.min(axis=0).tolist(), max=a.max(axis=0).tolist())
        accessors.append(out)
        return len(accessors) - 1

    for mesh in doc['Meshes']:
        positions = np.asarray(mesh['Positions']).reshape(-1, 3)
        normals = np.asarray(mesh['Normals']).reshape(-1, 3)
        uv = np.asarray(mesh['TexCoords']).reshape(-1, 2)
        indices = np.asarray(mesh['Indices']).reshape(-1, 3)
        if not (np.isfinite(positions).all() and np.isfinite(normals).all() and np.isfinite(uv).all()):
            raise ValueError('Nonfinite native attributes')
        if indices.max() >= len(positions):
            raise ValueError('Invalid native indices')
        # glTF is CCW. Keep coordinates and UVs intact; make face normals agree
        # with the authored vertex normals (native DirectX streams can be CW).
        faces = positions[indices]
        alignment = np.sum(np.cross(faces[:, 1]-faces[:, 0], faces[:, 2]-faces[:, 0]) * normals[indices].mean(axis=1))
        if alignment < 0:
            indices = indices[:, ::-1]
        primitives.append({'attributes': {
            'POSITION': accessor(positions, 3, 'VEC3'),
            'NORMAL': accessor(normals, 3, 'VEC3'),
            'TEXCOORD_0': accessor(uv, 2, 'VEC2')},
            'indices': accessor(indices.ravel(), 1, 'SCALAR', 5123), 'material': 0})
    image_view = view(encoded.getvalue())
    gltf = {'asset': {'version': '2.0', 'generator': 'HD1 native decoder bridge'},
            'scene': 0, 'scenes': [{'nodes': [0]}],
            'nodes': [{'mesh': 0, 'extras': {'native_frames': doc['Frames']}}],
            'meshes': [{'primitives': primitives}], 'accessors': accessors,
            'bufferViews': views, 'buffers': [{'byteLength': len(binary)}],
            'images': [{'bufferView': image_view, 'mimeType': 'image/png'}],
            'samplers': [{'wrapS': 10497, 'wrapT': 10497}],
            'textures': [{'source': 0, 'sampler': 0}],
            'materials': [{'doubleSided': True, 'pbrMetallicRoughness': {
                'baseColorTexture': {'index': 0}, 'metallicFactor': 0, 'roughnessFactor': .65}}]}
    json_bytes = json.dumps(gltf, separators=(',', ':')).encode()
    json_bytes += b' ' * (-len(json_bytes) % 4)
    binary += b'\0' * (-len(binary) % 4)
    data = (struct.pack('<III', 0x46546c67, 2, 12+8+len(json_bytes)+8+len(binary)) +
            struct.pack('<II', len(json_bytes), 0x4e4f534a) + json_bytes +
            struct.pack('<II', len(binary), 0x004e4942) + binary)
    Path(destination).write_bytes(data)
    return {'vertices': sum(m['VertexCount'] for m in doc['Meshes']),
            'triangles': sum(m['TriangleCount'] for m in doc['Meshes']),
            'native_uv_min': np.concatenate([np.asarray(m['TexCoords']).reshape(-1, 2) for m in doc['Meshes']]).min(axis=0).tolist(),
            'native_uv_max': np.concatenate([np.asarray(m['TexCoords']).reshape(-1, 2) for m in doc['Meshes']]).max(axis=0).tolist()}
