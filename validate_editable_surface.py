"""Validate a curved cut with independently editable front/back rails."""
import json
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine


Cut3D.register()
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0), scale=(1, 1, 1))
target = bpy.context.object
target.name = "EditableSurfaceModel"
props = bpy.context.scene.cut3d_props
props.target_object = target

cut = draft_engine._new_cut_record(bpy.context, 'CURVED')
draft_engine.create_cut_objects(bpy.context, cut, location=Vector())
cut.add_pin = False
cut.cut_gap = 0.08
cut.unit_per_mm = 0.001
front = [
    Vector((-1.20, -1.20, -0.25)),
    Vector((-0.40, -1.20, -0.15)),
    Vector((0.40, -1.20, -0.05)),
    Vector((1.20, -1.20, 0.05)),
]
back = [
    Vector((-1.20, 1.20, 0.10)),
    Vector((-0.40, 1.20, 0.20)),
    Vector((0.40, 1.20, 0.30)),
    Vector((1.20, 1.20, 0.40)),
]
draft_engine.store_surface_rails(cut, front, back)
cut.status = 'READY'

stored = json.loads(cut.surface_data)
assert len(stored["front"]) == 4 and len(stored["back"]) == 4
assert abs(draft_engine.surface_height_for_cut(cut, Vector((-0.4, -1.2, 0.0))) + 0.15) < 1e-6
assert abs(draft_engine.surface_height_for_cut(cut, Vector((0.4, 1.2, 0.0))) - 0.30) < 1e-6

result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 2, f"A superfície curva editável deveria produzir duas peças; obtidas {len(parts)}"
assert all(len(obj.data.polygons) > 0 for obj in parts)
print("CUT3D_EDITABLE_SURFACE_OK", len(parts), *(len(obj.data.polygons) for obj in parts))

