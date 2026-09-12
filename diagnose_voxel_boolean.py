"""Non-destructive Cut3D voxel-remesh + Boolean diagnostic."""

import json
import time

import bpy
from mathutils import Vector

from Cut3D import cutter_engine


STATUS_KEY = "cut3d_voxel_test_status"
PAYLOAD_KEY = "cut3d_voxel_test_payload"


def _bbox_center(obj):
    return sum((obj.matrix_world @ Vector(corner) for corner in obj.bound_box), Vector()) / 8.0


def _run():
    scene = bpy.context.scene
    start = time.perf_counter()
    work = None
    cutter = None
    try:
        props = scene.cut3d_props
        cut = props.cuts[props.active_cut_index]
        seed = cutter_engine._cut_seed_world(cut)
        outputs = [obj for obj in bpy.data.objects if obj.type == "MESH" and obj.get("cut3d_output")]
        source = min(outputs, key=lambda obj: (_bbox_center(obj) - seed).length)

        work = source.copy()
        work.data = source.data.copy()
        work.name = "Cut3D_Voxel_Test"
        scene.collection.objects.link(work)
        work.hide_set(False)
        work.hide_viewport = False

        bpy.ops.object.select_all(action="DESELECT")
        work.select_set(True)
        bpy.context.view_layer.objects.active = work
        work.data.remesh_voxel_size = max(float(cut.unit_per_mm), 0.0005)
        work.data.remesh_voxel_adaptivity = 0.0
        before_faces = len(work.data.polygons)
        remesh_start = time.perf_counter()
        with bpy.context.temp_override(
            active_object=work,
            selected_editable_objects=[work],
            selected_objects=[work],
        ):
            result = bpy.ops.object.voxel_remesh()
        remesh_seconds = time.perf_counter() - remesh_start
        if "FINISHED" not in result:
            raise RuntimeError(f"Voxel Remesh falhou: {result}")
        remeshed_faces = len(work.data.polygons)

        cutter = cutter_engine._make_local_kerf_cutter(bpy.context, cut)
        boolean_start = time.perf_counter()
        if not cutter_engine.apply_boolean_safe(bpy.context, work, cutter, "DIFFERENCE"):
            raise RuntimeError("Boolean após Voxel Remesh falhou")
        boolean_seconds = time.perf_counter() - boolean_start
        components = cutter_engine._connected_component_count(work)

        payload = {
            "source": source.name,
            "voxel_size": work.data.remesh_voxel_size,
            "faces_before": before_faces,
            "faces_after_remesh": remeshed_faces,
            "faces_after_boolean": len(work.data.polygons),
            "components": components,
            "remesh_seconds": round(remesh_seconds, 3),
            "boolean_seconds": round(boolean_seconds, 3),
            "seconds": round(time.perf_counter() - start, 3),
        }
        scene[PAYLOAD_KEY] = json.dumps(payload, ensure_ascii=False)
        scene[STATUS_KEY] = "DONE"
        print("CUT3D_VOXEL_TEST", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        scene[PAYLOAD_KEY] = json.dumps({"error": repr(exc)}, ensure_ascii=False)
        scene[STATUS_KEY] = "ERROR"
        print("CUT3D_VOXEL_TEST_ERROR", repr(exc))
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
print("CUT3D_VOXEL_TEST_SCHEDULED")
