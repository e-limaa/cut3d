"""Regression: two local cuts may be required before a loop becomes two parts."""
import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D
from Cut3D import draft_engine


Cut3D.register()

# A closed rectangular tube models an arm that also touches the torso at the
# hand: one local cut opens a slit but does not disconnect it; two cuts do.
curve_data = bpy.data.curves.new("ValidationLoopCurve", type='CURVE')
curve_data.dimensions = '3D'
curve_data.resolution_u = 1
curve_data.bevel_depth = 0.20
curve_data.bevel_resolution = 1
spline = curve_data.splines.new(type='POLY')
spline.points.add(3)
for point, coordinate in zip(
    spline.points,
    ((-1.5, 0.0, -1.0, 1.0), (1.5, 0.0, -1.0, 1.0),
     (1.5, 0.0, 1.0, 1.0), (-1.5, 0.0, 1.0, 1.0)),
):
    point.co = coordinate
spline.use_cyclic_u = True
target = bpy.data.objects.new("ValidationLoop", curve_data)
bpy.context.scene.collection.objects.link(target)
bpy.context.view_layer.objects.active = target
target.select_set(True)
bpy.ops.object.convert(target='MESH')

props = bpy.context.scene.cut3d_props
props.target_object = target
for height in (0.60, -0.60):
    bpy.context.view_layer.objects.active = target
    target.select_set(True)
    bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
    cut = props.cuts[-1]
    cut.add_pin = False
    cut.cut_gap = 0.08
    cut.unit_per_mm = 0.001
    cut.profile_data = '[[ -0.40, 0.0 ], [ 0.40, 0.0 ]]'
    cut.stroke_data = '[[ -0.40, 0.0, 0.0 ], [ 0.40, 0.0, 0.0 ]]'
    cut.depth_data = '[-0.40, 0.40]'
    blade = bpy.data.objects[cut.blade_object]
    blade.location = (-1.5, 0.0, height)
    draft_engine._sync_cut_objects(cut)
    draft_engine.restore_local_preview(cut)

result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 2, f"Dois cortes acumulados deveriam soltar o segmento; obtidas {len(parts)} peças"
assert all(len(obj.data.polygons) > 0 for obj in parts)
print("CUT3D_MULTICUT_LOOP_OK", len(parts), *(len(obj.data.polygons) for obj in parts))

