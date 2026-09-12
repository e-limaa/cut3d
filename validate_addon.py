"""Validação headless do fluxo principal. Não faz parte do ZIP do addon."""
import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine

Cut3D.register()
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0), scale=(0.05, 0.04, 0.06))
target = bpy.context.active_object
target.name = "ValidationModel"
props = bpy.context.scene.cut3d_props
props.target_object = target

bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
cut_one = props.cuts[0]
cut_one.add_pin = False
assert bpy.data.objects[cut_one.blade_object].type == 'EMPTY'
assert bpy.data.objects[cut_one.visual_object].type == 'CURVE'
visual = bpy.data.objects[cut_one.visual_object]
blade_one = bpy.data.objects[cut_one.blade_object]
blade_one.location.z = -0.02
cut_one.profile_data = '[[ -0.05, 0.0 ], [ 0.05, 0.0 ]]'
cut_one.stroke_data = '[[ -0.05, 0.0, 0.0 ], [ 0.05, 0.0, 0.0 ]]'
draft_engine._sync_cut_objects(cut_one)
draft_engine.restore_local_preview(cut_one)
assert blade_one.hide_viewport and visual.hide_viewport
overlay_points = draft_engine._stroke_coordinates(cut_one)
assert len(overlay_points) == 2
assert abs((overlay_points[1] - overlay_points[0]).length - 0.1) < 1e-6
draw_matrix = draft_engine._draw_matrix(
    draft_engine.Vector((-0.03, 0, 0)),
    draft_engine.Vector((0.03, 0, 0)),
    draft_engine.Vector((0, 1, 0)),
    draft_engine.Vector((0, 0, 1)),
)
assert draw_matrix is not None
assert abs(draw_matrix.translation.length) < 1e-8

bpy.context.view_layer.objects.active = target
target.select_set(True)
bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
cut_two = props.cuts[1]
cut_two.add_pin = False
blade_two = bpy.data.objects[cut_two.blade_object]
blade_two.location.z = 0.02
cut_two.profile_data = '[[ -0.05, 0.0 ], [ 0.05, 0.0 ]]'
cut_two.stroke_data = '[[ -0.05, 0.0, 0.0 ], [ 0.05, 0.0, 0.0 ]]'
draft_engine._sync_cut_objects(cut_two)
draft_engine.restore_local_preview(cut_two)

result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 3, f"Esperadas 3 peças em dois cortes locais, obtidas {len(parts)}"
assert target.hide_get(), "No resultado, o original preservado não deve ficar sobreposto às peças"
assert props.result_visible
bpy.ops.cut3d.restore_draft()
assert not target.hide_get() and not props.result_visible
output_collection = bpy.data.collections.get(f"{target.name}_Cut3D_Parts")
assert output_collection and output_collection.hide_viewport
assert all(obj.hide_get() for obj in output_collection.objects)
print("CUT3D_FLOW_OK", len(props.cuts), len(parts))

Cut3D.unregister()
