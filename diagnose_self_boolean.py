"""Non-destructive Exact Boolean diagnostic with self-intersection enabled."""

import json
import time

import bpy

from Cut3D import cutter_engine


STATUS_KEY = "cut3d_self_test_status"
PAYLOAD_KEY = "cut3d_self_test_payload"


def _run():
    scene = bpy.context.scene
    start = time.perf_counter()
    work = None
    cutter = None
    try:
        props = scene.cut3d_props
        cut = props.cuts[props.active_cut_index]
        source = props.target_object
        work = source.copy()
        work.data = source.data.copy()
        work.name = "Cut3D_SelfBoolean_Test"
        scene.collection.objects.link(work)
        work.hide_set(False)
        work.hide_viewport = False

        cutter = cutter_engine._make_local_kerf_cutter(bpy.context, cut)
        modifier = work.modifiers.new(name="Cut3D_SelfBoolean", type="BOOLEAN")
        modifier.operation = "DIFFERENCE"
        modifier.object = cutter
        modifier.solver = "EXACT"
        modifier.use_self = True
        modifier.use_hole_tolerant = False
        bpy.context.view_layer.update()
        bpy.ops.object.select_all(action="DESELECT")
        work.select_set(True)
        bpy.context.view_layer.objects.active = work
        with bpy.context.temp_override(
            active_object=work,
            selected_editable_objects=[work],
            selected_objects=[work],
        ):
            bpy.ops.object.modifier_apply(modifier=modifier.name)

        components = cutter_engine._connected_component_count(work)
        payload = {
            "faces": len(work.data.polygons),
            "components": components,
            "seconds": round(time.perf_counter() - start, 3),
        }
        scene[PAYLOAD_KEY] = json.dumps(payload, ensure_ascii=False)
        scene[STATUS_KEY] = "DONE"
        print("CUT3D_SELF_TEST", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        scene[PAYLOAD_KEY] = json.dumps({"error": repr(exc)}, ensure_ascii=False)
        scene[STATUS_KEY] = "ERROR"
        print("CUT3D_SELF_TEST_ERROR", repr(exc))
    finally:
        for obj in (cutter, work):
            if obj and obj.name in bpy.data.objects:
                mesh = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if mesh and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
    return None


scene = bpy.context.scene
scene[STATUS_KEY] = "RUNNING"
scene[PAYLOAD_KEY] = ""
bpy.app.timers.register(_run, first_interval=0.1)
print("CUT3D_SELF_TEST_SCHEDULED")
