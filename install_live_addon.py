"""Install the workspace Cut3D ZIP while preserving the open Draft exactly."""

import importlib
import sys

import bpy


ZIP_PATH = r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip"


def _plain_values(group, excluded=()):
    values = {}
    for prop in group.bl_rna.properties:
        if prop.identifier in excluded or prop.identifier == "rna_type" or prop.is_readonly:
            continue
        value = getattr(group, prop.identifier)
        if isinstance(value, (str, bool, int, float)):
            values[prop.identifier] = value
    return values


scene = bpy.context.scene
old_props = scene.cut3d_props
snapshot = {
    "props": _plain_values(old_props, {"cuts", "target_object"}),
    "target": old_props.target_object.name if old_props.target_object else "",
    "cuts": [_plain_values(cut) for cut in old_props.cuts],
    "objects": {},
}
for cut in old_props.cuts:
    for name in dict.fromkeys((cut.blade_object, cut.visual_object, cut.curve_object, cut.pin_object)):
        obj = bpy.data.objects.get(name)
        if obj:
            snapshot["objects"][name] = {
                "basis": obj.matrix_basis.copy(),
                "world": obj.matrix_world.copy(),
                "hidden": obj.hide_get(),
            }

import Cut3D

try:
    Cut3D.unregister()
except Exception:
    pass
bpy.ops.preferences.addon_install(filepath=ZIP_PATH, overwrite=True)
importlib.invalidate_caches()
for module_name in [name for name in sys.modules if name == "Cut3D" or name.startswith("Cut3D.")]:
    del sys.modules[module_name]
Cut3D = importlib.import_module("Cut3D")
Cut3D.register()

props = scene.cut3d_props
if len(props.cuts) != len(snapshot["cuts"]):
    props.cuts.clear()
    for cut_values in snapshot["cuts"]:
        cut = props.cuts.add()
        for key, value in cut_values.items():
            setattr(cut, key, value)
for key, value in snapshot["props"].items():
    setattr(props, key, value)
props.target_object = bpy.data.objects.get(snapshot["target"])

for name, state in snapshot["objects"].items():
    obj = bpy.data.objects.get(name)
    if not obj:
        continue
    # All Cut3D controls are unparented. Basis is the persisted authority and
    # remains valid even when hidden controls have an unevaluated world matrix.
    obj.matrix_basis = state["basis"]
    obj.matrix_world = state["basis"]
    obj.hide_set(state["hidden"])

bpy.context.view_layer.update()
bpy.ops.wm.save_userpref()
active = props.cuts[props.active_cut_index] if props.cuts else None
print(
    "CUT3D_LIVE_INSTALLED",
    Cut3D.bl_info["version"],
    len(props.cuts),
    active.name if active else None,
    active.cut_id if active else None,
    props.target_object.name if props.target_object else None,
)
