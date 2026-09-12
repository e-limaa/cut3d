"""Valida modelos STL em milímetros e modelos Blender em metros."""
import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D

Cut3D.register()
props = bpy.context.scene.cut3d_props

# Escala típica do arquivo real: cerca de 178 x 178 x 417 unidades.
bpy.ops.mesh.primitive_cube_add(scale=(89.0, 89.0, 208.5))
raw_stl = bpy.context.object
props.target_object = raw_stl
bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
cut = props.cuts[-1]
assert cut.unit_per_mm == 1.0
assert 2.5 <= cut.pin_radius <= 10.0, cut.pin_radius
assert bpy.data.objects[cut.visual_object].hide_viewport

# Um objeto modelado em metros continua usando 0,001 unidade por milímetro.
bpy.ops.mesh.primitive_cube_add(scale=(0.05, 0.04, 0.08))
metric = bpy.context.object
props.target_object = raw_stl  # simula o campo antigo ainda apontando para outro modelo
bpy.ops.cut3d.add_cut(cut_type='STRAIGHT')
metric_cut = props.cuts[-1]
assert props.target_object == metric, "O objeto ativo deve vencer o alvo antigo do painel"
assert abs(metric_cut.unit_per_mm - 0.001) < 1e-9

print("CUT3D_SCALE_TARGET_OK", cut.pin_radius, metric_cut.pin_radius)
Cut3D.unregister()
