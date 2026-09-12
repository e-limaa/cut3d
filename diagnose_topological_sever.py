"""Non-destructive live diagnostic for the Cut3D bridge-sever fallback.

Run inside Blender.  It duplicates only the already-built output nearest the
active cut, removes the tiny set of faces that still crosses the cut surface,
caps the two new borders, reports connectivity, and deletes the duplicate.
"""

import json
import time

import bmesh
import bpy
import numpy as np
from mathutils import Vector

from Cut3D import cutter_engine


STATUS_KEY = "cut3d_sever_test_status"
PAYLOAD_KEY = "cut3d_sever_test_payload"


def _surface_distances(mesh, transform, cut):
    count = len(mesh.vertices)
    coordinates = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coordinates)
    coordinates = coordinates.reshape((-1, 3))

    matrix = np.asarray(transform, dtype=np.float64)
    local = coordinates @ matrix[:3, :3].T + matrix[:3, 3]

    if cut.cut_type == "CURVED":
        front, back = cutter_engine._surface_rails(cut)
        front = np.asarray(sorted(front, key=lambda point: point[0]), dtype=np.float64)
        back = np.asarray(sorted(back, key=lambda point: point[0]), dtype=np.float64)
        x = local[:, 0]
        y = local[:, 1]
        front_y = np.interp(x, front[:, 0], front[:, 1])
        front_z = np.interp(x, front[:, 0], front[:, 2])
        back_y = np.interp(x, back[:, 0], back[:, 1])
        back_z = np.interp(x, back[:, 0], back[:, 2])
        span = back_y - front_y
        factor = np.full_like(span, 0.5)
        valid = np.abs(span) > 1e-20
        factor[valid] = (y[valid] - front_y[valid]) / span[valid]
        factor = np.clip(factor, 0.0, 1.0)
        distance = local[:, 2] - (front_z + (back_z - front_z) * factor)
        x_min = min(front[:, 0].min(), back[:, 0].min())
        x_max = max(front[:, 0].max(), back[:, 0].max())
        y_min = min(front[:, 1].min(), back[:, 1].min())
        y_max = max(front[:, 1].max(), back[:, 1].max())
    else:
        evaluator = cutter_engine._cut_distance_evaluator(cut)
        distance = np.fromiter(
            (evaluator(Vector(point)) for point in local),
            dtype=np.float64,
            count=count,
        )
        profile = cutter_engine._cut_profile(cut)
        x_min, x_max = profile[0][0], profile[-1][0]
        y_min, y_max = cutter_engine._cut_depth(cut)
    return local, distance, (x_min, x_max, y_min, y_max)


def _face_mask(mesh, local, distance, bounds, cut):
    loop_count = len(mesh.loops)
    loop_vertices = np.empty(loop_count, dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    starts = np.empty(len(mesh.polygons), dtype=np.int32)
    totals = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
    mesh.polygons.foreach_get("loop_total", totals)

    loop_distance = distance[loop_vertices]
    minimum = np.minimum.reduceat(loop_distance, starts)
    maximum = np.maximum.reduceat(loop_distance, starts)
    loop_x = local[loop_vertices, 0]
    loop_y = local[loop_vertices, 1]
    face_x_min = np.minimum.reduceat(loop_x, starts)
    face_x_max = np.maximum.reduceat(loop_x, starts)
    face_y_min = np.minimum.reduceat(loop_y, starts)
    face_y_max = np.maximum.reduceat(loop_y, starts)

    x_min, x_max, y_min, y_max = bounds
    unit = max(float(cut.unit_per_mm), 1e-6)
    width = max(x_max - x_min, unit)
    depth = max(y_max - y_min, unit)
    x_margin = max(width * 0.50, float(cut.blade_radius) * 2.0, unit * 1.5)
    y_margin = max(depth * 0.20, unit * 1.5)
    half_band = max(float(cut.cut_gap) * 0.5, unit * 0.08)
    in_x = (face_x_max >= x_min - x_margin) & (face_x_min <= x_max + x_margin)
    in_y = (face_y_max >= y_min - y_margin) & (face_y_min <= y_max + y_margin)
    in_scope = (
        in_x & in_y
    )
    crosses = (minimum <= half_band) & (maximum >= -half_band)
    stats = {
        "bounds": [float(value) for value in bounds],
        "half_band": float(half_band),
        "crosses_global": int(np.count_nonzero(crosses)),
        "crosses_in_x": int(np.count_nonzero(crosses & in_x)),
        "crosses_in_y": int(np.count_nonzero(crosses & in_y)),
        "in_scope": int(np.count_nonzero(in_scope)),
        "minimum_abs_vertex_distance": float(np.min(np.abs(distance))),
        "local_bounds": [
            float(local[:, 0].min()), float(local[:, 0].max()),
            float(local[:, 1].min()), float(local[:, 1].max()),
            float(local[:, 2].min()), float(local[:, 2].max()),
        ],
    }
    return in_scope & crosses, stats


def _run():
    scene = bpy.context.scene
    start = time.perf_counter()
    temp = None
    temp_mesh = None
    generated = []
    try:
        props = scene.cut3d_props
        cut = props.cuts[props.active_cut_index]
        blade = bpy.data.objects.get(cut.blade_object)
        outputs = [obj for obj in bpy.data.objects if obj.type == "MESH" and obj.get("cut3d_output")]
        seed = cutter_engine._cut_seed_world(cut)
        source = min(
            outputs,
            key=lambda obj: (
                sum((obj.matrix_world @ Vector(corner) for corner in obj.bound_box), Vector()) / 8.0
                - seed
            ).length,
        )

        temp = source.copy()
        temp.data = source.data.copy()
        temp.name = "Cut3D_Sever_Test"
        scene.collection.objects.link(temp)
        temp.hide_set(False)
        temp.hide_viewport = False
        temp_mesh = temp.data

        transform = blade.matrix_world.inverted_safe() @ temp.matrix_world
        local, distance, bounds = _surface_distances(temp_mesh, transform, cut)
        mask, mask_stats = _face_mask(temp_mesh, local, distance, bounds, cut)
        face_indices = np.flatnonzero(mask).tolist()

        bm = bmesh.new()
        bm.from_mesh(temp_mesh)
        bm.faces.ensure_lookup_table()
        removed = {bm.faces[index] for index in face_indices}
        border_edges = {
            edge
            for face in removed
            for edge in face.edges
            if any(linked not in removed for linked in edge.link_faces)
        }
        bmesh.ops.delete(bm, geom=list(removed), context="FACES")
        border_edges = [
            edge for edge in border_edges
            if edge.is_valid and len(edge.link_faces) == 1
        ]
        fill_result = bmesh.ops.holes_fill(bm, edges=border_edges, sides=0)
        filled_faces = len(fill_result.get("faces", []))
        component_groups = cutter_engine._face_components(bm)
        component_sizes = sorted((len(group) for group in component_groups), reverse=True)
        components = len(component_groups)
        boundary_edges = sum(1 for edge in bm.edges if edge.is_boundary)
        bm.to_mesh(temp_mesh)
        temp_mesh.update()
        bm.free()

        split = cutter_engine._group_boolean_result_by_draft(
            temp, [cut], "Cut3D_SeverRemesh_Test", scene.collection,
        )
        split.sort(key=lambda obj: len(obj.data.polygons), reverse=True)
        generated = split[:2]
        for debris in split[2:]:
            cutter_engine._delete_mesh_object(debris)
        cutter_engine._delete_mesh_object(temp)
        temp = None

        remesh_parts = []
        for part in generated:
            before = len(part.data.polygons)
            repaired = cutter_engine._voxel_repair_object(
                bpy.context, part, max(float(cut.unit_per_mm), 0.0005),
            )
            check = bmesh.new()
            check.from_mesh(part.data)
            repaired_groups = cutter_engine._face_components(check)
            repaired_sizes = sorted((len(group) for group in repaired_groups), reverse=True)
            remesh_parts.append({
                "name": part.name,
                "repaired": repaired,
                "faces_before": before,
                "faces_after": len(part.data.polygons),
                "boundary_edges": sum(1 for edge in check.edges if edge.is_boundary),
                "components": len(repaired_groups),
                "largest_components": repaired_sizes[:12],
            })
            check.free()

        payload = {
            "source": source.name,
            "removed_faces": len(face_indices),
            "candidate_border_edges": len(border_edges),
            "filled_faces": filled_faces,
            "components_after": components,
            "largest_components": component_sizes[:12],
            "boundary_edges_after": boundary_edges,
            "remesh_parts": remesh_parts,
            "seconds": round(time.perf_counter() - start, 3),
            "mask_stats": mask_stats,
        }
        scene[PAYLOAD_KEY] = json.dumps(payload, ensure_ascii=False)
        scene[STATUS_KEY] = "DONE"
        print("CUT3D_SEVER_TEST", json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        scene[PAYLOAD_KEY] = json.dumps({"error": repr(exc)}, ensure_ascii=False)
        scene[STATUS_KEY] = "ERROR"
        print("CUT3D_SEVER_TEST_ERROR", repr(exc))
    finally:
        for part in generated:
            cutter_engine._delete_mesh_object(part)
        if temp and temp.name in bpy.data.objects:
            mesh = temp.data
            bpy.data.objects.remove(temp, do_unlink=True)
            if mesh and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        elif temp_mesh and temp_mesh.users == 0:
            bpy.data.meshes.remove(temp_mesh)
    return None


scene = bpy.context.scene
scene[STATUS_KEY] = "RUNNING"
scene[PAYLOAD_KEY] = ""
bpy.app.timers.register(_run, first_interval=0.1)
print("CUT3D_SEVER_TEST_SCHEDULED")
