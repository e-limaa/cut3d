"""Regression: a front limb cut must not continue into geometry behind it."""
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine


Cut3D.register()

# Two overlapping screen silhouettes in one object: the front shell represents
# an arm and the rear shell a torso.  Only the front depth interval is marked.
bpy.ops.mesh.primitive_cube_add(location=(0.0, -1.0, 0.0), scale=(1.0, 0.4, 1.0))
front = bpy.context.object
bpy.ops.mesh.primitive_cube_add(location=(0.0, 1.0, 0.0), scale=(1.0, 0.4, 1.0))
rear = bpy.context.object
front.select_set(True)
rear.select_set(True)
bpy.context.view_layer.objects.active = front
bpy.ops.object.join()
target = bpy.context.object
target.name = "OccludedArmAndTorso"

props = bpy.context.scene.cut3d_props
props.target_object = target
cut = draft_engine._new_cut_record(bpy.context, 'STRAIGHT')
draft_engine.create_cut_objects(bpy.context, cut, location=Vector((0.0, 0.0, 0.0)))
cut.add_pin = False
cut.cut_gap = 0.08
cut.unit_per_mm = 0.001
cut.profile_data = '[[ -1.20, 0.0 ], [ 1.20, 0.0 ]]'
cut.stroke_data = '[[ -1.20, 0.0, 0.0 ], [ 1.20, 0.0, 0.0 ]]'
cut.depth_data = '[-1.60, -0.40]'
cut.seed_data = '[0.0, -1.40, 0.0]'
cut.status = 'READY'
draft_engine.restore_local_preview(cut)

result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 3, f"Esperadas 2 metades frontais + torso intacto; obtidas {len(parts)} peças"
full_height = [obj for obj in parts if obj.dimensions.z > 1.9]
half_height = [obj for obj in parts if obj.dimensions.z < 1.1]
assert len(full_height) == 1, "A geometria traseira foi cortada indevidamente"
assert len(half_height) == 2, "A geometria frontal não foi separada em duas"
print("CUT3D_OCCLUDED_SCOPE_OK", len(parts))

