"""Regression: an enabled cut that misses must cancel the whole Build."""

import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine


Cut3D.register()

bpy.ops.mesh.primitive_cube_add(size=2.0)
target = bpy.context.object
target.name = "AtomicBuildTarget"
props = bpy.context.scene.cut3d_props
props.target_object = target

for index, height in enumerate((0.0, 10.0), 1):
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
    cut = props.cuts[-1]
    cut.name = f"Atomic Cut {index:02d}"
    cut.add_pin = False
    cut.cut_gap = 0.05
    cut.unit_per_mm = 0.001
    cut.profile_data = '[[-2.0, 0.0], [2.0, 0.0]]'
    cut.stroke_data = '[[-2.0, 0.0, 0.0], [2.0, 0.0, 0.0]]'
    cut.depth_data = '[-2.0, 2.0]'
    blade = bpy.data.objects[cut.blade_object]
    blade.location = (0.0, 0.0, height)
    draft_engine._sync_cut_objects(cut)
    draft_engine.restore_local_preview(cut)

source_faces = len(target.data.polygons)
try:
    result = bpy.ops.cut3d.execute_cut()
except RuntimeError as exc:
    # Background Blender promotes an ERROR report from a cancelled operator
    # to RuntimeError; the interactive UI simply shows the same message.
    assert "Build cancelado sem alterar o modelo" in str(exc), str(exc)
    result = {'CANCELLED'}
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]

assert result == {'CANCELLED'}, result
assert not parts, [obj.name for obj in parts]
assert not target.hide_get()
assert not target.hide_render
assert not props.result_visible
assert len(props.cuts) == 2
assert len(target.data.polygons) == source_faces

cut_count = len(props.cuts)
Cut3D.unregister()
print("CUT3D_ATOMIC_BUILD_OK", source_faces, cut_count)
