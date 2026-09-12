"""Validação headless de corte curvo e conectores. Não faz parte do ZIP."""
import sys
import bpy
import bmesh

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D

Cut3D.register()
bpy.ops.mesh.primitive_cube_add(scale=(0.05, 0.04, 0.06))
target = bpy.context.active_object
target.name = "CurvedPinModel"
props = bpy.context.scene.cut3d_props
props.target_object = target
bpy.ops.cut3d.add_cut(cut_type='CURVED')
cut = props.cuts[0]
cut.pin_radius = 0.006
cut.pin_depth = 0.012
cut.clearance = 0.00025
result = bpy.ops.cut3d.execute_cut()
parts = [obj for obj in bpy.data.objects if obj.get("cut3d_output")]
assert result == {'FINISHED'}, result
assert len(parts) == 2, f"Esperadas 2 peças, obtidas {len(parts)}"
assert all(len(obj.data.polygons) > 0 for obj in parts)
assert cut.get("cut3d_last_connector_applied"), "O encaixe válido não foi aplicado"
for obj in parts:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    assert not [edge for edge in bm.edges if len(edge.link_faces) != 2]
    bm.free()
print("CUT3D_CURVED_PIN_OK", len(parts), sum(len(obj.data.polygons) for obj in parts))
Cut3D.unregister()
