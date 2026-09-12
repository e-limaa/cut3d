"""Valida centro geométrico, escala livre e âncora persistente do pino."""

import json
import math
import sys

import bpy
from mathutils import Euler, Matrix, Vector

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import cutter_engine, draft_engine


Cut3D.register()
bpy.ops.mesh.primitive_cube_add(size=2.0)
target = bpy.context.object
props = bpy.context.scene.cut3d_props
props.target_object = target
cut = draft_engine._new_cut_record(bpy.context, 'CURVED')
blade = draft_engine.create_cut_objects(bpy.context, cut, location=Vector())

# Retângulo propositalmente assimétrico. O seed fica perto da ponta direita;
# o centro correto da superfície continua sendo (-0.5, 1.0, 0.0).
front = [Vector((-2.0, -1.0, 0.0)), Vector((1.0, -1.0, 0.0))]
back = [Vector((-2.0, 3.0, 0.0)), Vector((1.0, 3.0, 0.0))]
draft_engine.store_surface_rails(cut, front, back)
cut.seed_data = json.dumps([0.9, -1.0, 0.0])
pin = bpy.data.objects[cut.pin_object]
pin.location = (9.0, -7.0, 4.0)
pin.rotation_euler = Euler((0.4, -0.7, 1.1))
pin.scale = (1.4, 1.6, 2.0)

matrix = draft_engine.center_pin_on_cut(cut)
local = blade.matrix_basis.inverted_safe() @ matrix
assert (local.translation - Vector((-0.5, 1.0, 0.0))).length < 1e-6, local.translation
scale = local.to_scale()
for actual, expected in zip(scale, (1.4, 1.6, 2.0)):
    assert math.isclose(actual, expected, rel_tol=1e-6), (scale[:], expected)
normal = local.to_3x3().col[2].normalized()
assert normal.dot(Vector((0.0, 0.0, 1.0))) > 0.999999, normal

# Mover o corte recentraliza o pino sem carregar a antiga translação própria.
blade.matrix_basis = Matrix.Translation((3.0, 4.0, 5.0)) @ Matrix.Rotation(0.35, 4, 'Y')
draft_engine._sync_cut_objects(cut)
expected_world = blade.matrix_basis @ Vector((-0.5, 1.0, 0.0))
assert (pin.matrix_basis.translation - expected_world).length < 1e-6

# Mesmo oculto e deliberadamente deslocado, o Build lê a matriz autoritativa
# já recentralizada, nunca a matrix_world potencialmente desatualizada.
pin.hide_viewport = True
pin.matrix_basis.translation += Vector((20.0, 20.0, 20.0))
build_matrix = draft_engine.pin_matrix_for_cut(cut)
assert (build_matrix.translation - expected_world).length < 1e-6
assert all(pin.lock_location) and all(pin.lock_rotation)
assert not any(pin.lock_scale)

# Em arquivos reabertos, um Empty fora da cena pode manter matrix_basis correta
# enquanto matrix_world fica desatualizada. O Build lê a matriz persistente.
assert cutter_engine._blade_matrix(blade) == blade.matrix_basis

# Numa superfície não plana, a média 3D pode ficar dentro da concavidade. A
# origem final precisa estar realmente sobre a superfície do corte.
warped_front = [
    Vector((-2.0, -1.0, 0.0)), Vector((-0.5, -1.0, -0.8)), Vector((1.0, -1.0, 0.4)),
]
warped_back = [
    Vector((-2.0, 3.0, 0.6)), Vector((-0.5, 3.0, 0.2)), Vector((1.0, 3.0, 1.1)),
]
draft_engine.store_surface_rails(cut, warped_front, warped_back)
surface_center, _orientation = draft_engine.cut_surface_frame(cut)
assert abs(draft_engine.surface_height_for_cut(cut, surface_center) - surface_center.z) < 1e-8

Cut3D.unregister()
print("CUT3D_PIN_ANCHOR_OK", tuple(round(value, 5) for value in expected_world), tuple(round(value, 3) for value in scale))
