"""Headless native-geometry PBR references/previews. Invoked by hd.py."""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def main():
    config = json.loads(Path(sys.argv[sys.argv.index('--')+1]).read_text())
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=config['glb'])
    hulls = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    if config.get('maps'):
        maps = Path(config['maps'])
        mat = bpy.data.materials.new('HD native UV material')
        mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bsdf = nodes.get('Principled BSDF')
        for name, socket in [('basecolor', 'Base Color'), ('metallic', 'Metallic'), ('roughness', 'Roughness'), ('emission', 'Emission Color'), ('normal', 'Normal')]:
            tex = nodes.new('ShaderNodeTexImage')
            tex.image = bpy.data.images.load(str(maps / (name+'.png')))
            if name != 'basecolor':
                tex.image.colorspace_settings.name = 'Non-Color'
            if name == 'normal':
                normal = nodes.new('ShaderNodeNormalMap')
                links.new(tex.outputs['Color'], normal.inputs['Color'])
                links.new(normal.outputs['Normal'], bsdf.inputs[socket])
            else:
                links.new(tex.outputs['Color'], bsdf.inputs[socket])
        bsdf.inputs['Emission Strength'].default_value = 1
        for obj in hulls:
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            for face in obj.data.polygons:
                face.material_index = 0
    points = [o.matrix_world @ Vector(v) for o in hulls for v in o.bound_box]
    minimum = Vector(tuple(min(v[i] for v in points) for i in range(3)))
    maximum = Vector(tuple(max(v[i] for v in points) for i in range(3)))
    center, radius = (minimum+maximum)/2, (maximum-minimum).length/2
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 12
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 4
    scene.render.resolution_x = scene.render.resolution_y = int(config.get('res', 1024))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = 'PNG'
    scene.view_settings.view_transform = 'Standard'
    scene.world = bpy.data.worlds.new('Neutral studio')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (.16, .16, .16, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = .6
    for direction, power in [((2, -3, 4), 130), ((-3, -1, 2), 70), ((0, 3, 3), 90)]:
        bpy.ops.object.light_add(type='AREA', location=center+Vector(direction)*radius)
        light = bpy.context.object
        light.rotation_euler = (center-light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = power*radius**2
        light.data.shape = 'DISK'
        light.data.size = radius*3
    bpy.ops.object.camera_add()
    camera = bpy.context.object
    camera.data.type = 'ORTHO'
    camera.data.ortho_scale = radius*2.35*float(config.get('zoom', 1.0))  # zoom < 1 = close-up
    camera.data.clip_end = max(1000, radius*20)
    scene.camera = camera
    out = Path(config['out'])
    out.mkdir(parents=True, exist_ok=True)
    for name, direction in [('front', (0, -1, .05)), ('three_quarter', (1, -1, .55)), ('side', (1, 0, .05)), ('top', (0, 0, 1))]:
        camera.location = center+Vector(direction).normalized()*radius*5
        camera.rotation_euler = (center-camera.location).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(out / (name+'.png'))
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    main()
