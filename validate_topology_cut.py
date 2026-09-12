"""Valida o fallback simples: cortar, tampar a borda e nunca remalhar."""

import json
import sys
from types import SimpleNamespace

import bmesh
import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import cutter_engine


Cut3D.register()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Prisma com anéis dos dois lados do corte. Só as quatro faces centrais devem
# desaparecer; as tampas usam os vértices existentes e todo o resto é idêntico.
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

mesh = bpy.data.meshes.new("TopologySourceMesh")
mesh.from_pydata(vertices, [], faces)
mesh.update()
source = bpy.data.objects.new("TopologySource", mesh)
bpy.context.scene.collection.objects.link(source)

blade = bpy.data.objects.new("TopologyBlade", None)
bpy.context.scene.collection.objects.link(blade)
cut = SimpleNamespace(
    cut_type='STRAIGHT',
    blade_object=blade.name,
    profile_data=json.dumps([[-2.0, 0.0], [2.0, 0.0]]),
    depth_data=json.dumps([-2.0, 2.0]),
    unit_per_mm=0.001,
    blade_radius=0.1,
    cut_gap=0.02,
    pin_depth=0.05,
)

original_coordinates = {tuple(vertex.co) for vertex in source.data.vertices}
removed = cutter_engine._sever_surface_bridges(source, cut)
assert removed == 4, removed
bm = bmesh.new()
bm.from_mesh(source.data)
components = cutter_engine._face_components(bm)
boundary_edges = [edge for edge in bm.edges if len(edge.link_faces) == 1]
assert len(components) == 2, len(components)
assert not boundary_edges, len(boundary_edges)
bm.free()
assert all(tuple(vertex.co) in original_coordinates for vertex in source.data.vertices)
assert not source.get("cut3d_voxel_repaired")

# Abra de propósito uma face na tampa do corte e outra longe dela. O reparo
# deve fechar somente a abertura causada pelo Cut3D e preservar o defeito remoto.
bm = bmesh.new()
bm.from_mesh(source.data)
near = min(bm.faces, key=lambda face: abs(face.calc_center_median().z))
far = max(bm.faces, key=lambda face: face.calc_center_median().z)
bmesh.ops.delete(bm, geom=[near, far], context='FACES')
bm.to_mesh(source.data)
bm.free()
added, remaining_near = cutter_engine._cap_cut_boundaries(source, [cut])
assert added >= 1, added
assert remaining_near == 0, remaining_near
bm = bmesh.new()
bm.from_mesh(source.data)
remote_boundary = [
    edge for edge in bm.edges
    if len(edge.link_faces) == 1
    and ((edge.verts[0].co + edge.verts[1].co) * 0.5).z > 0.5
]
assert len(remote_boundary) == 4, len(remote_boundary)
bm.free()

Cut3D.unregister()
print("CUT3D_TOPOLOGY_CUT_OK", removed, len(components), len(source.data.polygons))
