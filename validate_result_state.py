"""Regression: Build result mode must not trap the UI or pair distant islands."""
import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import cutter_engine


Cut3D.register()

bpy.ops.mesh.primitive_cube_add()
target = bpy.context.object
target.name = "StateTarget"
props = bpy.context.scene.cut3d_props
props.target_object = target

collection = bpy.data.collections.new(f"{target.name}_Cut3D_Parts")
bpy.context.scene.collection.children.link(collection)
bpy.ops.mesh.primitive_cube_add(location=(3.0, 0.0, 0.0))
output = bpy.context.object
for owner in list(output.users_collection):
    owner.objects.unlink(output)
collection.objects.link(output)
output["cut3d_output"] = True
target.hide_set(True)
props.result_visible = True

result = bpy.ops.cut3d.restore_draft()
assert result == {'FINISHED'}
assert not props.result_visible
assert not target.hide_get()
assert target.select_get() and bpy.context.view_layer.objects.active == target
assert output.hide_get() and collection.hide_viewport

# A hidden generated result must never silently become the new target.
props.result_visible = True
assert not Cut3D.draft_engine.CUT3D_OT_add_cut.poll(bpy.context)
props.result_visible = False
bpy.context.view_layer.objects.active = output
output.select_set(True)
bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
assert props.target_object == target
cut = props.cuts[0]

# Two islands on opposite sides of a cut are not a connector pair when one is
# far outside the finite cut region.
cut.profile_data = '[[ -1.0, 0.0 ], [ 1.0, 0.0 ]]'
cut.depth_data = '[-1.0, 1.0]'
cut.seed_data = '[0.0, 0.0, 0.0]'
blade = bpy.data.objects[cut.blade_object]
blade.matrix_world.identity()

bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, 0.5), scale=(0.25, 0.25, 0.25))
near = bpy.context.object
bpy.ops.mesh.primitive_cube_add(location=(0.0, 0.0, -10.0), scale=(0.25, 0.25, 0.25))
far = bpy.context.object
positive, negative = cutter_engine._connector_parts_for_cut([near, far], cut)
assert positive is None and negative is None

print("CUT3D_RESULT_STATE_OK", target.name, output.name)

