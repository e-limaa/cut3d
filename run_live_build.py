"""Run the actual open-scene Cut3D Build asynchronously and record evidence."""

import json
import time

import bpy


STATUS_KEY = "cut3d_final_build_status"
PAYLOAD_KEY = "cut3d_final_build_payload"


def _run():
    scene = bpy.context.scene
    start = time.perf_counter()
    try:
        result = bpy.ops.cut3d.execute_cut()
        props = scene.cut3d_props
        pieces = [
            {
                "name": obj.name,
                "faces": len(obj.data.polygons),
                "dimensions": [round(float(value), 6) for value in obj.dimensions],
            }
            for obj in bpy.data.objects
            if obj.type == "MESH" and obj.get("cut3d_output") and not obj.hide_get()
        ]
        payload = {
            "result": list(result),
            "seconds": round(time.perf_counter() - start, 3),
            "piece_count": props.last_build_piece_count,
            "source_components": props.last_build_source_components,
            "new_separations": props.last_build_new_separations,
            "cut_count": props.last_build_cut_count,
            "pieces": pieces,
        }
        scene[PAYLOAD_KEY] = json.dumps(payload, ensure_ascii=False)
        scene[STATUS_KEY] = "DONE"
        print("CUT3D_FINAL_BUILD", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        scene[PAYLOAD_KEY] = json.dumps({"error": repr(exc)}, ensure_ascii=False)
        scene[STATUS_KEY] = "ERROR"
        print("CUT3D_FINAL_BUILD_ERROR", repr(exc))
    return None


scene = bpy.context.scene
scene[STATUS_KEY] = "RUNNING"
scene[PAYLOAD_KEY] = ""
bpy.app.timers.register(_run, first_interval=0.1)
print("CUT3D_FINAL_BUILD_SCHEDULED")
