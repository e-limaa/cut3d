"""Valida que uma marca no braço não corta o tronco do mesmo objeto."""
import math
import sys

import bpy
from mathutils import Euler, Vector

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine

Cut3D.register()

bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0), scale=(1.0, 1.0, 1.0))
torso = bpy.context.object
bpy.ops.mesh.primitive_cube_add(location=(1.7, 0, 0), scale=(1.0, 0.3, 0.3))
arm = bpy.context.object
modifier = torso.modifiers.new("JoinArm", 'BOOLEAN')
modifier.operation = 'UNION'
modifier.solver = 'EXACT'
modifier.object = arm
bpy.context.view_layer.objects.active = torso
with bpy.context.temp_override(active_object=torso, selected_editable_objects=[torso], selected_objects=[torso]):
    bpy.ops.object.modifier_apply(modifier=modifier.name)
bpy.data.objects.remove(arm, do_unlink=True)
torso.name = "BodyWithArm"

props = bpy.context.scene.cut3d_props
props.target_object = torso
cut = draft_engine._new_cut_record(bpy.context, 'STRAIGHT')
blade = draft_engine.create_cut_objects(
    bpy.context, cut, location=Vector((2.0, 0, 0)), rotation=Euler((0, math.pi / 2, 0), 'XYZ'),
)
cut.add_pin = False
cut.blade_radius = 0.5
cut.profile_data = '[[ -0.38, 0.0 ], [ 0.38, 0.0 ]]'
cut.stroke_data = '[[ -0.38, 0.0, 0.0 ], [ 0.38, 0.0, 0.0 ]]'
draft_engine.restore_local_preview(cut)
cut.status = 'READY'
visual = bpy.data.objects[cut.visual_object]
assert blade.hide_viewport and blade.hide_select, "O plano técnico deve permanecer invisível"
assert visual.hide_viewport, "A curva física deve ficar oculta; a marca é desenhada como overlay"
overlay_points = draft_engine._stroke_coordinates(cut)
assert len(overlay_points) == 2, "O overlay deve reconstruir o gesto local"

result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 2, f"O corte local deveria gerar 2 peças, gerou {len(parts)}"
assert any(min((obj.matrix_world @ Vector(corner)).x for corner in obj.bound_box) < -0.9 for obj in parts)
print("CUT3D_LOCAL_ARM_OK", len(parts))

Cut3D.unregister()
