"""Valida rollback do Boolean destrutivo e fallback topológico local."""

import json
import sys
from types import SimpleNamespace

import bmesh
import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import cutter_engine


Cut3D.register()
levels = (-1.0, -0.1, 0.1, 1.0)
ring = ((-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
vertices = [(x, y, z) for z in levels for x, y in ring]
faces = []
for layer in range(len(levels) - 1):
    base = layer * 4
    following = base + 4
    for index in range(4):
        nxt = (index + 1) % 4
        faces.append((base + index, base + nxt, following + nxt, following + index))
faces.extend(((3, 2, 1, 0), (12, 13, 14, 15)))
mesh = bpy.data.meshes.new("TransactionalSourceMesh")
mesh.from_pydata(vertices, [], faces)
mesh.update()
source = bpy.data.objects.new("TransactionalSource", mesh)
bpy.context.scene.collection.objects.link(source)
blade = bpy.data.objects.new("TransactionalBlade", None)
bpy.context.scene.collection.objects.link(blade)
cut = SimpleNamespace(
    cut_id="transactional",
    cut_type='STRAIGHT',
    blade_object=blade.name,
    profile_data=json.dumps([[-2.0, 0.0], [2.0, 0.0]]),
    depth_data=json.dumps([-2.0, 2.0]),
    unit_per_mm=0.001,
    blade_radius=0.1,
    cut_gap=0.02,
    pin_depth=0.05,
)

real_boolean = cutter_engine.apply_boolean_safe


def destructive_boolean(_context, target, _cutter, _operation='DIFFERENCE'):
    # Closed octahedron: 8/14 faces (57%) with no boundary or non-manifold
    # edge.  The old 50% guard accepted this plausible-looking half-model.
    bad = bpy.data.meshes.new("DeliberatelyCorruptBoolean")
    bad.from_pydata(
        [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)],
        [],
        [
            (0, 2, 4), (2, 1, 4), (1, 3, 4), (3, 0, 4),
            (2, 0, 5), (1, 2, 5), (3, 1, 5), (0, 3, 5),
        ],
    )
    bad.update()
    previous = target.data
    target.data = bad
    if previous.users == 0:
        bpy.data.meshes.remove(previous)
    return True


cutter_engine.apply_boolean_safe = destructive_boolean
try:
    assert cutter_engine._apply_local_kerf(bpy.context, source, cut)
finally:
    cutter_engine.apply_boolean_safe = real_boolean

bm = bmesh.new()
bm.from_mesh(source.data)
components = cutter_engine._face_components(bm)
assert len(bm.faces) >= 4, len(bm.faces)
assert len(components) == 2, len(components)
assert not [edge for edge in bm.edges if len(edge.link_faces) == 1]
bm.free()
assert source.get("cut3d_transactional_fallbacks") == 1

Cut3D.unregister()
print("CUT3D_TRANSACTIONAL_BUILD_OK", len(source.data.polygons), len(components))
