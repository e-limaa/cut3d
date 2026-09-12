"""Validate body-conforming curved rails and persistent viewport pin scale."""
import math
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine


Cut3D.register()
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, radius=1.0)
target = bpy.context.object
target.name = "BodyFitSphere"
props = bpy.context.scene.cut3d_props
props.target_object = target

cut = draft_engine._new_cut_record(bpy.context, 'CURVED')
blade = draft_engine.create_cut_objects(bpy.context, cut, location=Vector())
blade.matrix_world.translation = Vector()
cut.unit_per_mm = 0.001
# Intentionally stop well inside the silhouette. Build must extend this Draft
# seam until the cutter exits the shell on both sides, as a CatPin-style swipe
# does not require the user to estimate invisible boolean margins.
front = [Vector((x, -1.5, 0.0)) for x in (-0.70, -0.35, 0.0, 0.35, 0.70)]
back = [Vector((x, 1.5, 0.0)) for x in (-0.70, -0.35, 0.0, 0.35, 0.70)]
front, back, mapped = draft_engine.fit_surface_rails_to_target(
    bpy.context, cut, front, back,
)
assert mapped == 10, mapped
assert all(point.y <= 1e-5 for point in front)
assert all(point.y >= -1e-5 for point in back)
assert any(point.y < -0.5 for point in front)
assert any(point.y > 0.5 for point in back)
for point in front + back:
    assert abs(point.length - 1.0) < 0.035, (point[:], point.length)

draft_engine.store_surface_rails(cut, front, back)
pin = bpy.data.objects[cut.pin_object]
pin.scale = (1.4, 1.6, 2.0)
bpy.context.view_layer.update()
draft_engine.center_pin_on_cut(cut)
relative_scale = (blade.matrix_world.inverted_safe() @ pin.matrix_world).to_scale()
assert math.isclose(relative_scale.x, 1.4, rel_tol=1e-5)
assert math.isclose(relative_scale.y, 1.6, rel_tol=1e-5)
assert math.isclose(relative_scale.z, 2.0, rel_tol=1e-5)

cut.add_pin = False
cut.cut_gap = 0.025
cut.status = 'READY'
result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 2, f"A superfície apoiada na casca deveria separar a esfera; obtidas {len(parts)} peças"

print("CUT3D_BODY_FIT_PIN_SCALE_OK", mapped, *(round(value, 3) for value in relative_scale), len(parts))
Cut3D.unregister()
