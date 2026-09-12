import math
import json

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import connectors, cut_math, draft_engine


def _blade_matrix(blade):
    """Return the persisted Draft transform, even for an unlinked hidden Empty."""
    return draft_engine._control_matrix(blade)


def apply_boolean_safe(context, target_obj, cutter_obj, operation='UNION'):
    modifier = target_obj.modifiers.new(name="Cut3D_Connector", type='BOOLEAN')
    modifier.operation = operation
    modifier.object = cutter_obj
    modifier.solver = 'EXACT'
    context.view_layer.update()
    try:
        if target_obj.name in context.view_layer.objects:
            bpy.ops.object.select_all(action='DESELECT')
            target_obj.select_set(True)
            context.view_layer.objects.active = target_obj
        with context.temp_override(active_object=target_obj, selected_editable_objects=[target_obj], selected_objects=[target_obj]):
            bpy.ops.object.modifier_apply(modifier=modifier.name)
        return True
    except Exception:
        if modifier.name in target_obj.modifiers:
            target_obj.modifiers.remove(modifier)
        return False


def _delete_mesh_object(obj):
    if not obj or obj.name not in bpy.data.objects:
        return
    mesh = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if isinstance(mesh, bpy.types.Mesh) and mesh.users == 0:
        bpy.data.meshes.remove(mesh)


def _duplicate_mesh_object(source, name, collection):
    duplicate = source.copy()
    duplicate.data = source.data.copy()
    duplicate.name = name
    collection.objects.link(duplicate)
    duplicate.hide_set(False)
    duplicate.hide_viewport = False
    duplicate.hide_render = False
    return duplicate


def _surface_vertex_distances(mesh, transform, cut):
    """Vectorized local signed distances used only by the robust fallback."""
    import numpy as np

    count = len(mesh.vertices)
    coordinates = np.empty(count * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", coordinates)
    coordinates = coordinates.reshape((-1, 3))
    matrix = np.asarray(transform, dtype=np.float64)
    local = coordinates @ matrix[:3, :3].T + matrix[:3, 3]

    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
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
        bounds = (
            min(front[:, 0].min(), back[:, 0].min()),
            max(front[:, 0].max(), back[:, 0].max()),
            min(front[:, 1].min(), back[:, 1].min()),
            max(front[:, 1].max(), back[:, 1].max()),
        )
    else:
        evaluator = _cut_distance_evaluator(cut)
        distance = np.fromiter(
            (evaluator(Vector(point)) for point in local),
            dtype=np.float64,
            count=count,
        )
        profile = _cut_profile(cut)
        y_min, y_max = _cut_depth(cut)
        bounds = (profile[0][0], profile[-1][0], y_min, y_max)
    return local, distance, bounds


def _sever_surface_bridges(obj, cut):
    """Remove only faces that still bridge both sides of a failed local cut."""
    import numpy as np

    blade = bpy.data.objects.get(cut.blade_object)
    mesh = obj.data
    if not blade or not mesh.polygons:
        return 0
    transform = _blade_matrix(blade).inverted_safe() @ obj.matrix_world
    local, distance, bounds = _surface_vertex_distances(mesh, transform, cut)

    loop_vertices = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", loop_vertices)
    starts = np.empty(len(mesh.polygons), dtype=np.int32)
    mesh.polygons.foreach_get("loop_start", starts)
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
    width = max(float(x_max - x_min), unit)
    depth = max(float(y_max - y_min), unit)
    x_margin = max(width * 0.50, float(cut.blade_radius) * 2.0, unit * 1.5)
    y_margin = max(depth * 0.20, unit * 1.5)
    half_band = max(float(cut.cut_gap) * 0.5, unit * 0.08)
    in_scope = (
        (face_x_max >= x_min - x_margin)
        & (face_x_min <= x_max + x_margin)
        & (face_y_max >= y_min - y_margin)
        & (face_y_min <= y_max + y_margin)
    )
    mask = in_scope & (minimum <= half_band) & (maximum >= -half_band)
    face_indices = np.flatnonzero(mask).tolist()
    if not face_indices:
        return 0

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.faces.ensure_lookup_table()
    removed = {bm.faces[index] for index in face_indices}
    border_edges = {
        edge
        for face in removed
        for edge in face.edges
        if any(linked not in removed for linked in edge.link_faces)
    }
    bmesh.ops.delete(bm, geom=list(removed), context='FACES')
    border_edges = [
        edge for edge in border_edges
        if edge.is_valid and len(edge.link_faces) == 1
    ]
    filled_faces = []
    if border_edges:
        try:
            filled_faces = bmesh.ops.holes_fill(
                bm, edges=border_edges, sides=0,
            ).get('faces', [])
        except (RuntimeError, ValueError):
            pass
    # The open-source cutters use this same inexpensive pattern: cut the
    # original topology, fill only the new non-manifold boundary and leave the
    # rest of the model untouched. Keep the cap as one face. Explicit BMesh
    # triangulation can reuse diagonals already present in dense scans and turn
    # a closed cap into edges shared by three faces.
    filled_faces = [face for face in filled_faces if face.is_valid]
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return len(face_indices)


def _boundary_edge_components(edges):
    """Group boundary edges without assuming every component is a clean loop."""
    remaining = set(edges)
    components = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            edge = stack.pop()
            for vertex in edge.verts:
                for linked in vertex.link_edges:
                    if linked in remaining:
                        remaining.remove(linked)
                        component.add(linked)
                        stack.append(linked)
        components.append(component)
    return components


def _boundary_component_near_cut(obj, edges, cut):
    """Keep pre-existing holes away from the requested seam untouched."""
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return False
    transform = _blade_matrix(blade).inverted_safe() @ obj.matrix_world
    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
        points = front + back
        if not points:
            return False
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
    else:
        profile = _cut_profile(cut)
        x_values = [point[0] for point in profile]
        y_values = list(_cut_depth(cut))
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    unit = max(float(cut.unit_per_mm), 1e-6)
    width = max(x_max - x_min, unit)
    depth = max(y_max - y_min, unit)
    x_margin = max(width * 0.50, float(cut.blade_radius) * 2.0, unit * 1.5)
    y_margin = max(depth * 0.20, unit * 1.5)
    height_margin = max(
        float(cut.cut_gap) * 4.0,
        float(getattr(cut, "pin_depth", 0.0)) * 2.0,
        float(cut.blade_radius),
        unit * 3.0,
    )
    signed_distance = _cut_distance_evaluator(cut)
    for edge in edges:
        midpoint = transform @ ((edge.verts[0].co + edge.verts[1].co) * 0.5)
        if not (x_min - x_margin <= midpoint.x <= x_max + x_margin):
            continue
        if not (y_min - y_margin <= midpoint.y <= y_max + y_margin):
            continue
        if abs(signed_distance(midpoint)) <= height_margin + unit * 0.5:
            return True
    return False


def _ordered_closed_boundary(component):
    """Return an ordered vertex loop, or [] for an open/branched boundary."""
    vertices = {vertex for edge in component for vertex in edge.verts}
    adjacency = {
        vertex: [edge for edge in vertex.link_edges if edge in component]
        for vertex in vertices
    }
    if len(component) < 3 or any(len(linked) != 2 for linked in adjacency.values()):
        return []
    start = next(iter(vertices))
    ordered = []
    current = start
    previous = None
    for _index in range(len(component) + 1):
        ordered.append(current)
        candidates = [edge for edge in adjacency[current] if edge is not previous]
        if not candidates:
            return []
        edge = candidates[0]
        following = edge.other_vert(current)
        if following is start:
            return ordered if len(ordered) == len(vertices) else []
        previous = edge
        current = following
    return []


def _cap_cut_boundaries(obj, cuts):
    """Close only new cut/connector loops, preserving unrelated source holes."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)

    boundary = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    targets = [
        component
        for component in _boundary_edge_components(boundary)
        if any(_boundary_component_near_cut(obj, component, cut) for cut in cuts)
    ]
    target_edges = [edge for component in targets for edge in component]
    filled_faces = []
    if target_edges:
        try:
            filled_faces = bmesh.ops.holes_fill(
                bm, edges=target_edges, sides=0,
            ).get('faces', [])
        except (RuntimeError, ValueError):
            filled_faces = []
    filled_faces = [face for face in filled_faces if face.is_valid]

    # Blender's automatic filler can skip a valid ring when another Boolean
    # face already spans part of the same region. The small open-source cutter
    # pattern is an explicit face fallback. Keep it as an n-gon here: forcing
    # diagonals may reuse internal edges and create new non-manifold geometry.
    manual_faces = []
    boundary = [edge for edge in bm.edges if len(edge.link_faces) == 1]
    for component in _boundary_edge_components(boundary):
        if not any(_boundary_component_near_cut(obj, component, cut) for cut in cuts):
            continue
        ordered = _ordered_closed_boundary(component)
        if not ordered:
            continue
        try:
            manual_faces.append(bm.faces.new(ordered))
        except ValueError:
            pass

    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    remaining = sum(
        len(component)
        for component in _boundary_edge_components(
            [edge for edge in bm.edges if len(edge.link_faces) == 1]
        )
        if any(_boundary_component_near_cut(obj, component, cut) for cut in cuts)
    )
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(filled_faces) + len(manual_faces), remaining


def _extract_major_components(source, name_base, collection, minimum_ratio=0.005):
    """Extract meaningful sides while ignoring Boolean/scan slivers."""
    bm = bmesh.new()
    bm.from_mesh(source.data)
    components = _face_components(bm)
    components.sort(key=len, reverse=True)
    if not components:
        bm.free()
        return []
    minimum_faces = max(64, int(len(components[0]) * minimum_ratio))
    components = [component for component in components if len(component) >= minimum_faces]
    objects = []
    for index, component in enumerate(components, 1):
        vertices, faces, materials = _mesh_data_for_faces(component)
        mesh = bpy.data.meshes.new(f"{name_base}_{index:02d}_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        for polygon, material_index in zip(mesh.polygons, materials):
            polygon.material_index = material_index
        obj = bpy.data.objects.new(f"{name_base}_{index:02d}", mesh)
        obj.matrix_world = source.matrix_world.copy()
        for material in source.data.materials:
            mesh.materials.append(material)
        collection.objects.link(obj)
        objects.append(obj)
    bm.free()
    return objects


def _keep_largest_component(obj):
    """Keep the printable exterior when a Boolean leaves a microscopic sliver."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    components = _face_components(bm)
    if len(components) <= 1:
        bm.free()
        return
    largest = max(components, key=len)
    remove_faces = [face for component in components if component is not largest for face in component]
    bmesh.ops.delete(bm, geom=remove_faces, context='FACES')
    loose_vertices = [vertex for vertex in bm.verts if not vertex.link_faces]
    if loose_vertices:
        bmesh.ops.delete(bm, geom=loose_vertices, context='VERTS')
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def clean_mesh_geometry(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.00001)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def _get_output_collection(context, target):
    name = f"{target.name}_Cut3D_Parts"
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        context.scene.collection.children.link(collection)
    collection.hide_viewport = False
    for obj in collection.objects:
        obj.hide_set(False)
    return collection


def _clear_previous_output(target):
    """Build substitui somente o resultado gerado anteriormente, nunca o original."""
    collection = bpy.data.collections.get(f"{target.name}_Cut3D_Parts")
    if not collection:
        return
    for obj in list(collection.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)


def _world_plane_for_cut(cut):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return None
    matrix = _blade_matrix(blade)
    point = matrix.translation.copy()
    normal = (matrix.to_3x3() @ Vector((0, 0, 1))).normalized()
    return point, normal


def _object_crosses_plane(obj, point, normal, gap=0.0):
    distances = [normal.dot((obj.matrix_world @ Vector(corner)) - point) for corner in obj.bound_box]
    epsilon = max(gap * 0.5, 1e-6)
    return min(distances) < -epsilon and max(distances) > epsilon


def _bisect_to_object(source, point_world, normal_world, keep_positive, name, collection, gap=0.0):
    inverse = source.matrix_world.inverted()
    local_normal = (inverse.to_3x3() @ normal_world).normalized()
    offset = gap * 0.5 * (1.0 if keep_positive else -1.0)
    local_point = inverse @ (point_world + normal_world * offset)

    bm = bmesh.new()
    bm.from_mesh(source.data)
    result = bmesh.ops.bisect_plane(
        bm,
        geom=list(bm.verts) + list(bm.edges) + list(bm.faces),
        plane_co=local_point,
        plane_no=local_normal,
        clear_inner=keep_positive,
        clear_outer=not keep_positive,
        use_snap_center=False,
    )
    cut_edges = [item for item in result['geom_cut'] if isinstance(item, bmesh.types.BMEdge) and item.is_valid]
    if cut_edges:
        try:
            bmesh.ops.edgenet_fill(bm, edges=cut_edges)
        except Exception:
            pass
    if not bm.faces:
        bm.free()
        return None
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(f"{name}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.matrix_world = source.matrix_world.copy()
    collection.objects.link(obj)
    return obj


def _make_curved_cutter(context, cut):
    """Cria um volume cujo limite superior segue a curva desenhada no preview."""
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return None
    try:
        profile = sorted(json.loads(cut.profile_data), key=lambda point: point[0])
    except (TypeError, ValueError):
        return None
    if len(profile) < 2:
        return None
    radius = cut.blade_radius * 3.0
    left_z = profile[0][1]
    right_z = profile[-1][1]
    extended = [[-radius, left_z], *profile, [radius, right_z]]
    bottom = -radius
    polygon = [(x, -radius, z) for x, z in extended]
    polygon.extend(((radius, -radius, bottom), (-radius, -radius, bottom)))
    bm = bmesh.new()
    verts = [bm.verts.new(co) for co in polygon]
    face = bm.faces.new(verts)
    extrusion = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded_verts = [item for item in extrusion['geom'] if isinstance(item, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=Vector((0, radius * 2, 0)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(f"Cut3D_CurvedCutter_{cut.cut_id}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    cutter = bpy.data.objects.new(f"Cut3D_CurvedCutter_{cut.cut_id}", mesh)
    cutter.matrix_world = _blade_matrix(blade)
    context.scene.collection.objects.link(cutter)
    cutter.hide_render = True
    return cutter


def _make_local_kerf_cutter(context, cut):
    """Build the finite ribbon stored by the viewport gesture."""
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return None
    if cut.cut_type == 'CURVED':
        return _make_ruled_surface_cutter(context, cut, blade)
    try:
        profile = json.loads(cut.profile_data)
    except (TypeError, ValueError):
        profile = []
    if len(profile) < 2:
        half_x = max(cut.blade_radius * 0.625, 0.005)
        profile = [[-half_x, 0.0], [half_x, 0.0]]
    profile = cut_math.monotonic_profile(profile)
    min_x, max_x = profile[0][0], profile[-1][0]
    unit = max(cut.unit_per_mm, 0.000001)
    margin = max((max_x - min_x) * 0.025, unit * 0.20)
    profile = cut_math.expanded_profile(profile, margin)
    try:
        depth = json.loads(cut.depth_data)
        y_min, y_max = float(depth[0]), float(depth[1])
    except (TypeError, ValueError, IndexError):
        half_depth = max(cut.blade_radius * 0.75, unit * 3.0)
        y_min, y_max = -half_depth, half_depth
    if y_max < y_min:
        y_min, y_max = y_max, y_min
    if y_max - y_min < unit * 0.05:
        y_max = y_min + unit * 0.05
    kerf = max(cut.cut_gap, unit * 0.02, cut.blade_radius * 1e-5)
    bm = bmesh.new()
    upper = [(x, y_min, z + kerf * 0.5) for x, z in profile]
    lower = [(x, y_min, z - kerf * 0.5) for x, z in reversed(profile)]
    face = bm.faces.new([bm.verts.new(co) for co in upper + lower])
    extrusion = bmesh.ops.extrude_face_region(bm, geom=[face])
    extruded = [item for item in extrusion['geom'] if isinstance(item, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded, vec=Vector((0, y_max - y_min, 0)))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    mesh = bpy.data.meshes.new(f"Cut3D_LocalKerf_{cut.cut_id}_Mesh")
    bm.to_mesh(mesh)
    bm.free()
    cutter = bpy.data.objects.new(f"Cut3D_LocalKerf_{cut.cut_id}", mesh)
    cutter.matrix_world = _blade_matrix(blade)
    context.scene.collection.objects.link(cutter)
    cutter.hide_render = True
    return cutter


def _surface_rails(cut):
    front, back = draft_engine.surface_rails_for_cut(cut)
    return (
        cut_math.catmull_rom_polyline(front),
        cut_math.catmull_rom_polyline(back),
    )


def _extended_rail(rail, margin):
    if len(rail) < 2:
        return list(rail)
    first = list(rail[0])
    last = list(rail[-1])
    first[0] -= margin
    last[0] += margin
    return [first, *[list(point) for point in rail], last]


def _make_ruled_surface_cutter(context, cut, blade):
    """Create a watertight kerf that fully exits the target shell.

    The editable rails intentionally sit on the model skin.  A boolean cutter
    ending exactly on that skin is tangent/coplanar and often leaves a narrow
    bridge, so Build extends the same surface a little beyond both sides.  The
    Draft remains visually exact while the final operation becomes robust.
    """
    front, back = _surface_rails(cut)
    if len(front) < 2 or len(back) < 2:
        return None
    unit = max(cut.unit_per_mm, 0.000001)
    x_values = [point[0] for point in front + back]
    width = max(x_values) - min(x_values)
    # The visible stroke describes the desired seam, but users naturally stop
    # close to the silhouette instead of several centimetres outside it. The
    # boolean surface must auto-complete past both lateral exits; otherwise a
    # beard, collar or rounded silhouette leaves two tiny bridges and the head
    # remains connected despite a correct-looking U-shaped Draft mark.
    margin = max(width * 0.50, cut.blade_radius * 2.0, unit * 0.75)
    front = _extended_rail(front, margin)
    back = _extended_rail(back, margin)
    count = max(len(front), len(back), 2)
    front = [Vector(point) for point in cut_math.resample_polyline(front, count)]
    back = [Vector(point) for point in cut_math.resample_polyline(back, count)]
    kerf = max(cut.cut_gap, unit * 0.02, cut.blade_radius * 1e-5)
    half = kerf * 0.5

    depth_vectors = [second - first for first, second in zip(front, back)]
    usable_depths = sorted(vector.length for vector in depth_vectors if vector.length > 1e-9)
    typical_depth = usable_depths[len(usable_depths) // 2] if usable_depths else unit
    depth_outset = max(typical_depth * 0.20, unit * 0.75, kerf * 3.0)
    minimum_direction_depth = max(typical_depth * 0.05, unit * 0.10)
    reference = sum(
        (
            vector.normalized()
            for vector in depth_vectors
            if vector.length > minimum_direction_depth
        ),
        Vector(),
    )
    if reference.length <= 1e-9:
        reference = Vector((0.0, 1.0, 0.0))
    else:
        reference.normalize()
    extended_front = []
    extended_back = []
    for first, second, vector in zip(front, back, depth_vectors):
        direction = (
            vector.normalized()
            if vector.length > minimum_direction_depth
            else reference
        )
        extended_front.append(first - direction * depth_outset)
        extended_back.append(second + direction * depth_outset)
    front, back = extended_front, extended_back

    upper_front = [(x, y, z + half) for x, y, z in front]
    upper_back = [(x, y, z + half) for x, y, z in back]
    lower_front = [(x, y, z - half) for x, y, z in front]
    lower_back = [(x, y, z - half) for x, y, z in back]
    vertices = upper_front + upper_back + lower_front + lower_back
    uf, ub, lf, lb = 0, count, count * 2, count * 3
    faces = []
    for index in range(count - 1):
        following = index + 1
        faces.extend((
            (uf + index, uf + following, ub + following, ub + index),
            (lf + index, lb + index, lb + following, lf + following),
            (lf + index, lf + following, uf + following, uf + index),
            (lb + index, ub + index, ub + following, lb + following),
        ))
    last = count - 1
    faces.extend((
        (lf, uf, ub, lb),
        (lf + last, lb + last, ub + last, uf + last),
    ))
    mesh = bpy.data.meshes.new(f"Cut3D_RuledKerf_{cut.cut_id}_Mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    cutter = bpy.data.objects.new(f"Cut3D_RuledKerf_{cut.cut_id}", mesh)
    cutter.matrix_world = _blade_matrix(blade)
    context.scene.collection.objects.link(cutter)
    cutter.hide_render = True
    return cutter


def _cut_profile(cut):
    try:
        profile = json.loads(cut.profile_data)
    except (TypeError, ValueError):
        profile = []
    if len(profile) < 2:
        radius = max(cut.blade_radius, 0.005)
        profile = [[-radius, 0.0], [radius, 0.0]]
    return cut_math.monotonic_profile(profile)


def _cut_depth(cut):
    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
        values = [point[1] for point in front + back]
        if values:
            return min(values), max(values)
    try:
        values = json.loads(cut.depth_data)
        low, high = float(values[0]), float(values[1])
        return (low, high) if low <= high else (high, low)
    except (TypeError, ValueError, IndexError):
        radius = max(cut.blade_radius, 0.005)
        return -radius, radius


def _signed_cut_distance(cut, point):
    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
        return cut_math.signed_surface_distance(front, back, point)
    return cut_math.signed_profile_distance(_cut_profile(cut), point)


def _cut_distance_evaluator(cut):
    """Prepare one fast signed-distance function for dense mesh loops."""
    if cut.cut_type != 'CURVED':
        profile = _cut_profile(cut)
        return lambda point: cut_math.signed_profile_distance(profile, point)

    front, back = _surface_rails(cut)
    front = sorted(
        ((float(point[0]), float(point[1]), float(point[2])) for point in front),
        key=lambda point: point[0],
    )
    back = sorted(
        ((float(point[0]), float(point[1]), float(point[2])) for point in back),
        key=lambda point: point[0],
    )

    def rail_value(rail, x):
        if x <= rail[0][0]:
            return rail[0][1], rail[0][2]
        if x >= rail[-1][0]:
            return rail[-1][1], rail[-1][2]
        low, high = 0, len(rail) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if rail[middle][0] <= x:
                low = middle
            else:
                high = middle
        first, second = rail[low], rail[high]
        span = second[0] - first[0]
        factor = 0.0 if abs(span) <= 1e-20 else (x - first[0]) / span
        return (
            first[1] + (second[1] - first[1]) * factor,
            first[2] + (second[2] - first[2]) * factor,
        )

    def evaluate(point):
        x, y = float(point[0]), float(point[1])
        front_y, front_z = rail_value(front, x)
        back_y, back_z = rail_value(back, x)
        span = back_y - front_y
        factor = 0.5 if abs(span) <= 1e-20 else (y - front_y) / span
        factor = max(0.0, min(1.0, factor))
        height = front_z + (back_z - front_z) * factor
        return float(point[2]) - height

    return evaluate


def _mesh_intersects_local_cut(source, cut):
    """Cheap guard against cutting a different part whose bounds merely overlap."""
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return False
    profile = _cut_profile(cut)
    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
        x_values = [point[0] for point in front + back]
        x_min, x_max = min(x_values), max(x_values)
    else:
        x_min, x_max = profile[0][0], profile[-1][0]
    y_min, y_max = _cut_depth(cut)
    transform = _blade_matrix(blade).inverted_safe() @ source.matrix_world
    mesh = source.data
    mesh.calc_loop_triangles()
    local_vertices = [transform @ vertex.co for vertex in mesh.vertices]
    signed_distance = _cut_distance_evaluator(cut)
    epsilon = max(cut.cut_gap, cut.unit_per_mm * 0.03, source.dimensions.length * 1e-7)
    for triangle in mesh.loop_triangles:
        points = [local_vertices[index] for index in triangle.vertices]
        if max(point.x for point in points) < x_min or min(point.x for point in points) > x_max:
            continue
        if max(point.y for point in points) < y_min or min(point.y for point in points) > y_max:
            continue
        values = [signed_distance(point) for point in points]
        if min(values) <= epsilon and max(values) >= -epsilon:
            return True
    return False


def _face_components(bm):
    remaining = set(bm.faces)
    components = []
    while remaining:
        seed = remaining.pop()
        stack = [seed]
        component = [seed]
        while stack:
            face = stack.pop()
            for edge in face.edges:
                for neighbour in edge.link_faces:
                    if neighbour in remaining:
                        remaining.remove(neighbour)
                        stack.append(neighbour)
                        component.append(neighbour)
        components.append(component)
    return components


def _connected_component_count(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        return len(_face_components(bm))
    finally:
        bm.free()


def _component_side(component, result, blade_inverse, profile):
    weighted = Vector()
    total = 0.0
    transform = blade_inverse @ result.matrix_world
    for face in component:
        area = max(face.calc_area(), 1e-12)
        weighted += (transform @ face.calc_center_median()) * area
        total += area
    center = weighted / max(total, 1e-12)
    return 1 if cut_math.signed_profile_distance(profile, center) >= 0.0 else -1


def _mesh_data_for_side(source_bm, side_layer, side):
    """Extract one side without relying on destructive BMesh layer copying."""
    vertex_map = {}
    vertices = []
    faces = []
    materials = []
    for face in source_bm.faces:
        if face[side_layer] != side:
            continue
        polygon = []
        for vertex in face.verts:
            if vertex not in vertex_map:
                vertex_map[vertex] = len(vertices)
                vertices.append(tuple(vertex.co))
            polygon.append(vertex_map[vertex])
        if len(polygon) >= 3:
            faces.append(polygon)
            materials.append(face.material_index)
    return vertices, faces, materials


def _mesh_data_for_faces(faces_to_copy):
    """Copy one logical component group to plain mesh data."""
    vertex_map = {}
    vertices = []
    faces = []
    materials = []
    for face in faces_to_copy:
        polygon = []
        for vertex in face.verts:
            if vertex not in vertex_map:
                vertex_map[vertex] = len(vertices)
                vertices.append(tuple(vertex.co))
            polygon.append(vertex_map[vertex])
        if len(polygon) >= 3:
            faces.append(polygon)
            materials.append(face.material_index)
    return vertices, faces, materials


def _group_boolean_result(result, cut, name_base, collection):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return []
    profile = _cut_profile(cut)
    bm = bmesh.new()
    bm.from_mesh(result.data)
    bm.faces.ensure_lookup_table()
    side_layer = bm.faces.layers.int.new("cut3d_side")
    present = set()
    blade_inverse = _blade_matrix(blade).inverted_safe()
    for component in _face_components(bm):
        side = _component_side(component, result, blade_inverse, profile)
        present.add(side)
        for face in component:
            face[side_layer] = side
    if present != {-1, 1}:
        bm.free()
        return []

    objects = []
    for side, suffix in ((1, 'A'), (-1, 'B')):
        vertices, faces, materials = _mesh_data_for_side(bm, side_layer, side)
        if not faces:
            continue
        mesh = bpy.data.meshes.new(f"{name_base}_{suffix}_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        for polygon, material_index in zip(mesh.polygons, materials):
            polygon.material_index = material_index
        obj = bpy.data.objects.new(f"{name_base}_{suffix}", mesh)
        obj.matrix_world = result.matrix_world.copy()
        for material in result.data.materials:
            obj.data.materials.append(material)
        collection.objects.link(obj)
        objects.append(obj)
    bm.free()
    return objects


def _split_with_local_kerf(context, source, cut, name_base, collection):
    if not _mesh_intersects_local_cut(source, cut):
        return []
    cutter = _make_local_kerf_cutter(context, cut)
    if not cutter:
        return []
    result = source.copy()
    result.data = source.data.copy()
    result.name = name_base
    collection.objects.link(result)
    succeeded = apply_boolean_safe(context, result, cutter, 'DIFFERENCE')
    cutter_mesh = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cutter_mesh.users == 0:
        bpy.data.meshes.remove(cutter_mesh)
    if not succeeded:
        bpy.data.objects.remove(result, do_unlink=True)
        return []

    pieces = _group_boolean_result(result, cut, name_base, collection)
    result_mesh = result.data
    bpy.data.objects.remove(result, do_unlink=True)
    if result_mesh.users == 0:
        bpy.data.meshes.remove(result_mesh)
    return pieces


def _mesh_build_health(mesh):
    """Small topology snapshot used to reject destructive Boolean results."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    components = _face_components(bm)
    health = {
        "faces": len(bm.faces),
        "boundary": sum(1 for edge in bm.edges if len(edge.link_faces) == 1),
        "multi": sum(1 for edge in bm.edges if len(edge.link_faces) >= 3),
        "components": len(components),
    }
    bm.free()
    return health


def _restore_mesh_backup(source, backup):
    failed_mesh = source.data
    source.data = backup
    if failed_mesh is not backup and failed_mesh.users == 0:
        bpy.data.meshes.remove(failed_mesh)


def _apply_local_kerf(context, source, cut):
    """Apply one finite draft cut in-place without requiring an immediate split.

    A limb can reconnect to the body somewhere else (for example a hand resting
    on the hip).  In that case the first kerf is valid even though the object is
    still one connected component.  CatPin-style planning therefore accumulates
    every kerf and separates the logical pieces only after the complete draft.
    """
    if not _mesh_intersects_local_cut(source, cut):
        return False
    cutter = _make_local_kerf_cutter(context, cut)
    if not cutter:
        return False
    before = _mesh_build_health(source.data)
    backup = source.data.copy()
    succeeded = apply_boolean_safe(context, source, cutter, 'DIFFERENCE')
    cutter_mesh = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cutter_mesh.users == 0:
        bpy.data.meshes.remove(cutter_mesh)

    invalid = not succeeded
    if succeeded:
        after = _mesh_build_health(source.data)
        # A kerf removes only a thin ribbon. Losing most of the model or
        # criar novas bordas abertas/não-manifold significa que o Boolean
        # Exato colapsou ao acumular cortes. Não deixe a corrupção alcançar o
        # próximo corte e virar várias "peças" microscópicas.
        invalid = (
            # A Cut3D kerf is only a thin ribbon around the painted mark.  If
            # one Boolean removes a sizeable part of the scan, Blender has
            # interpreted the closed cutter as a half-space instead of a
            # ribbon.  The previous 50% limit was too permissive: a failed
            # symmetric cut could retain 50.1% and publish half a figurine.
            after["faces"] < max(4, int(before["faces"] * 0.85))
            or after["boundary"] > before["boundary"]
            or after["multi"] > before["multi"]
            # One local mark can release at most one additional logical side.
            # More components are Boolean shrapnel, never a valid Cut3D cut.
            or after["components"] > before["components"] + 1
        )

    if not invalid and (
        after["components"] > before["components"]
        or cut.cut_type != 'CURVED'
    ):
        if backup.users == 0:
            bpy.data.meshes.remove(backup)
        return True

    if not invalid:
        # A Boolean can remain manifold yet leave a hairline bridge, so the
        # mark is visible but no part is actually released. Retry this one cut
        # from its pristine pre-Boolean mesh with the local topology severer.
        # If the topology path finds nothing, restore the valid Exact result.
        exact_mesh = source.data
        source.data = backup
        removed = _sever_surface_bridges(source, cut)
        if removed:
            if exact_mesh.users == 0:
                bpy.data.meshes.remove(exact_mesh)
            source["cut3d_transactional_fallbacks"] = int(
                source.get("cut3d_transactional_fallbacks", 0)
            ) + 1
            return True
        fallback_mesh = source.data
        source.data = exact_mesh
        if fallback_mesh is not exact_mesh and fallback_mesh.users == 0:
            bpy.data.meshes.remove(fallback_mesh)
        return True

    _restore_mesh_backup(source, backup)
    removed = _sever_surface_bridges(source, cut)
    if removed:
        source["cut3d_transactional_fallbacks"] = int(
            source.get("cut3d_transactional_fallbacks", 0)
        ) + 1
        return True
    return False


def _group_boolean_result_by_draft(result, cuts, name_base, collection):
    """Split the finished draft into its truly connected printable pieces.

    A side-signature is not sufficient here: after two cuts in a closed loop,
    the detached middle segment and the remaining loop can share the same
    centroid signs even though they are physically separate.  Connectivity is
    the reliable definition of a part after all kerfs have been accumulated.
    """
    bm = bmesh.new()
    bm.from_mesh(result.data)
    bm.faces.ensure_lookup_table()
    components = _face_components(bm)
    objects = []
    components.sort(key=len, reverse=True)
    for index, faces_to_copy in enumerate(components, 1):
        vertices, faces, materials = _mesh_data_for_faces(faces_to_copy)
        if not faces:
            continue
        mesh = bpy.data.meshes.new(f"{name_base}_{index:02d}_Mesh")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        for polygon, material_index in zip(mesh.polygons, materials):
            polygon.material_index = material_index
        obj = bpy.data.objects.new(f"{name_base}_{index:02d}", mesh)
        obj.matrix_world = result.matrix_world.copy()
        for material in result.data.materials:
            obj.data.materials.append(material)
        collection.objects.link(obj)
        objects.append(obj)
    bm.free()
    return objects


def _discard_boolean_debris(parts):
    """Remove only microscopic islands produced by booleans on dense meshes.

    Exact booleans can leave closed slivers with a handful of faces beside a
    valid cut. Besides cluttering the result, such an island may be mistaken
    for one side of a connector. The thresholds are deliberately conservative
    and disabled for ordinary/low-poly models, where a small component can be
    intentional.
    """
    if len(parts) < 3:
        return parts
    largest_face_count = max((len(part.data.polygons) for part in parts), default=0)
    if largest_face_count < 100_000:
        return parts

    volumes = {}
    for part in parts:
        bm = bmesh.new()
        bm.from_mesh(part.data)
        try:
            volumes[part] = abs(float(bm.calc_volume(signed=True)))
        except ValueError:
            volumes[part] = 0.0
        finally:
            bm.free()

    largest_volume = max(volumes.values(), default=0.0)
    minimum_faces = max(32, int(largest_face_count * 0.001))
    minimum_volume = largest_volume * 0.0000005
    kept = []
    discarded = []
    for part in parts:
        face_count = len(part.data.polygons)
        # A closed printable component cannot be represented credibly by only
        # a handful of triangles inside a six-figure scan. Signed volume is
        # unreliable for these degenerate Boolean shells, so never let it keep
        # an absolute microscopic fragment alive.
        if face_count < 32:
            discarded.append(part)
            continue
        meaningful_faces = face_count >= minimum_faces
        meaningful_volume = volumes.get(part, 0.0) >= minimum_volume
        (kept if meaningful_faces or meaningful_volume else discarded).append(part)

    # Never turn a valid result into fewer than two printable sides.
    if len(kept) < 2:
        return parts
    for part in discarded:
        mesh = part.data
        bpy.data.objects.remove(part, do_unlink=True)
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    return kept


def _retry_with_topology_cut(context, parts, cuts, name_base, collection):
    """Sever residual bridges and cap the cut without remeshing the model.

    This follows the deliberately simple approach used by open-source model
    cutters: preserve the Boolean result, delete only faces that still cross
    the requested seam, fill that seam's boundary loops, and extract the
    connected sides. No voxel operation is allowed here.
    """
    original_parts = list(parts)
    trial_parts = list(parts)
    work_by_original = {}
    original_by_work = {}

    for index, cut in enumerate(cuts, 1):
        candidate = _choose_part_for_cut(trial_parts, cut)
        if not candidate:
            continue
        if candidate not in original_by_work:
            duplicate = _duplicate_mesh_object(
                candidate, f"{name_base}_Repair_{index:02d}", collection,
            )
            trial_parts[trial_parts.index(candidate)] = duplicate
            work_by_original[candidate] = duplicate
            original_by_work[duplicate] = candidate
            candidate = duplicate
        _sever_surface_bridges(candidate, cut)

    repaired_by_original = {}
    for branch_index, (original, work) in enumerate(work_by_original.items(), 1):
        major = _extract_major_components(
            work, f"{name_base}_RepairSide_{branch_index:02d}", collection,
        )
        _delete_mesh_object(work)
        if len(major) < 2:
            for obj in major:
                _delete_mesh_object(obj)
            continue
        for obj in major:
            obj["cut3d_topology_repaired"] = True
        repaired_by_original[original] = major

    result = []
    for original in original_parts:
        replacements = repaired_by_original.get(original)
        if replacements:
            _delete_mesh_object(original)
            result.extend(replacements)
        else:
            result.append(original)
    return (result, True) if len(result) > len(original_parts) else (original_parts, False)


def _boolean_copy(context, source, cutter, operation, name, collection):
    obj = source.copy()
    obj.data = source.data.copy()
    obj.name = name
    collection.objects.link(obj)
    if not apply_boolean_safe(context, obj, cutter, operation):
        bpy.data.objects.remove(obj, do_unlink=True)
        return None
    if len(obj.data.polygons) == 0:
        bpy.data.objects.remove(obj, do_unlink=True)
        return None
    return obj


def _split_curved(context, source, cut, name_base, collection):
    cutter = _make_curved_cutter(context, cut)
    if not cutter:
        return None, None
    positive = _boolean_copy(context, source, cutter, 'DIFFERENCE', f"{name_base}_A", collection)
    negative = _boolean_copy(context, source, cutter, 'INTERSECT', f"{name_base}_B", collection)
    cutter_mesh = cutter.data
    bpy.data.objects.remove(cutter, do_unlink=True)
    if cutter_mesh.users == 0:
        bpy.data.meshes.remove(cutter_mesh)
    return positive, negative


def _link_temp(context, obj):
    context.scene.collection.objects.link(obj)
    obj.hide_render = True


def _remove_opposed_boolean_faces(obj):
    """Remove coincident opposite face pairs created at a Boolean union seam."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.verts.index_update()
    suspect_faces = {
        face
        for edge in bm.edges
        if len(edge.link_faces) >= 3
        for face in edge.link_faces
    }
    grouped = {}
    for face in suspect_faces:
        key = tuple(sorted(vertex.index for vertex in face.verts))
        grouped.setdefault(key, []).append(face)
    remove = set()
    for faces in grouped.values():
        for index, first in enumerate(faces):
            for second in faces[index + 1:]:
                if first.normal.dot(second.normal) < -0.999:
                    remove.update((first, second))
                    break
    if remove:
        bmesh.ops.delete(bm, geom=list(remove), context='FACES')
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()
    return len(remove)


def _fan_triangulate_build_caps(obj):
    """Triangulate generated n-gon caps without reusing scan diagonals."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    targets = [face for face in bm.faces if len(face.verts) > 4]
    made = 0
    for face in list(targets):
        if not face.is_valid:
            continue
        vertices = list(face.verts)
        center = bm.verts.new(face.calc_center_median())
        material_index = face.material_index
        smooth = face.smooth
        for index, vertex in enumerate(vertices):
            try:
                triangle = bm.faces.new((
                    vertex,
                    vertices[(index + 1) % len(vertices)],
                    center,
                ))
                triangle.material_index = material_index
                triangle.smooth = smooth
                made += 1
            except ValueError:
                pass
        bmesh.ops.delete(bm, geom=[face], context='FACES_ONLY')
    if targets:
        if bm.faces:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()
    return made


def _apply_connector_pair(context, positive, negative, cut):
    if not cut.add_pin:
        return False
    pin_matrix = draft_engine.pin_matrix_for_cut(cut)
    male = connectors.create_male_pin_object(cut, name="Cut3D_Temp_Male")
    socket = connectors.create_female_socket_cutter_object(cut, name="Cut3D_Temp_Socket")
    _link_temp(context, male)
    _link_temp(context, socket)
    if cut.pin_side == 'SIDE_A':
        # O positivo recebe o macho apontando para o negativo.
        transform = pin_matrix @ Matrix.Rotation(math.pi, 4, 'X')
        male.matrix_world = transform
        socket.matrix_world = transform
        male_target, socket_target = positive, negative
    else:
        male.matrix_world = pin_matrix
        socket.matrix_world = pin_matrix
        male_target, socket_target = negative, positive

    targets = (male_target, socket_target)
    before = {target: _mesh_build_health(target.data) for target in targets}
    backups = {target: target.data.copy() for target in targets}
    prepared = True
    for target in targets:
        if target.get("cut3d_topology_repaired"):
            _fan_triangulate_build_caps(target)
            after_prepare = _mesh_build_health(target.data)
            baseline = before[target]
            if (
                after_prepare["boundary"] > baseline["boundary"]
                or after_prepare["multi"] > baseline["multi"]
                or after_prepare["components"] != baseline["components"]
            ):
                prepared = False
                break
    male_ok = prepared and apply_boolean_safe(context, male_target, male, 'UNION')
    socket_ok = prepared and apply_boolean_safe(context, socket_target, socket, 'DIFFERENCE')
    if male_ok:
        provisional = _mesh_build_health(male_target.data)
        if provisional["multi"] > before[male_target]["multi"]:
            _remove_opposed_boolean_faces(male_target)
    if socket_ok:
        provisional = _mesh_build_health(socket_target.data)
        if provisional["multi"] > before[socket_target]["multi"]:
            _remove_opposed_boolean_faces(socket_target)
    valid = male_ok and socket_ok
    if valid:
        for target in targets:
            after = _mesh_build_health(target.data)
            baseline = before[target]
            if (
                after["faces"] < max(4, int(baseline["faces"] * 0.50))
                or after["boundary"] > baseline["boundary"]
                or after["multi"] > baseline["multi"]
            ):
                valid = False
                break
    if valid:
        for backup in backups.values():
            if backup.users == 0:
                bpy.data.meshes.remove(backup)
    else:
        for target, backup in backups.items():
            _restore_mesh_backup(target, backup)
    bpy.data.objects.remove(male, do_unlink=True)
    bpy.data.objects.remove(socket, do_unlink=True)
    return valid


def _copy_target(context, target, collection):
    """Freeze the evaluated target once; Build never mutates the original."""
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph,
    )
    copy = bpy.data.objects.new(f"{target.name}_Base", mesh)
    copy.matrix_world = evaluated.matrix_world.copy()
    collection.objects.link(copy)
    return copy


def _cut_seed_world(cut):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return None
    try:
        values = json.loads(cut.seed_data)
        seed = Vector((float(values[0]), float(values[1]), float(values[2])))
    except (TypeError, ValueError, IndexError):
        seed = Vector()
    return _blade_matrix(blade) @ seed


def _surface_distance(obj, world_point):
    local_point = obj.matrix_world.inverted_safe() @ world_point
    hit, location, _normal, _index = obj.closest_point_on_mesh(local_point)
    if not hit:
        return float('inf')
    return (obj.matrix_world @ location - world_point).length


def _choose_part_for_cut(parts, cut):
    """Choose one planned branch instead of applying a plane to every part."""
    seed = _cut_seed_world(cut)
    if seed is None:
        return None
    ranked = sorted(parts, key=lambda obj: _surface_distance(obj, seed))
    for part in ranked:
        if _mesh_intersects_local_cut(part, cut):
            return part
    return None


def _part_metric_near_cut(part, cut):
    """Return signed cut distance and surface distance nearest the cut seed."""
    seed = _cut_seed_world(cut)
    blade = bpy.data.objects.get(cut.blade_object)
    if seed is None or not blade:
        return 0.0, float('inf')
    local_seed = part.matrix_world.inverted_safe() @ seed
    hit, location, _normal, _index = part.closest_point_on_mesh(local_seed)
    if not hit:
        return 0.0, float('inf')
    world_location = part.matrix_world @ location
    cut_location = _blade_matrix(blade).inverted_safe() @ world_location
    distance = (world_location - seed).length
    signed = _signed_cut_distance(cut, cut_location)
    return signed, distance


def _part_side_near_cut(part, cut):
    """Return the side of the cut represented by the surface nearest its seed."""
    signed, distance = _part_metric_near_cut(part, cut)
    if not math.isfinite(distance):
        return None, distance
    return (1 if signed >= 0.0 else -1), distance


def _connector_parts_for_cut(parts, cut):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return None, None
    if cut.cut_type == 'CURVED':
        front, back = _surface_rails(cut)
        points = front + back
        x_values = [point[0] for point in points]
        y_values = [point[1] for point in points]
    else:
        profile = _cut_profile(cut)
        x_values = [point[0] for point in profile]
        y_values = list(_cut_depth(cut))
    width = max(x_values) - min(x_values) if x_values else 0.0
    depth = max(y_values) - min(y_values) if y_values else 0.0
    local_reach = max(
        width * 0.75,
        depth * 0.75,
        cut.pin_radius * 4.0,
        cut.pin_depth * 2.0,
        cut.unit_per_mm * 8.0,
    )
    blade_matrix = _blade_matrix(blade)
    world_scale = max((blade_matrix.to_3x3() @ axis).length for axis in (
        Vector((1.0, 0.0, 0.0)),
        Vector((0.0, 1.0, 0.0)),
        Vector((0.0, 0.0, 1.0)),
    ))
    maximum_distance = local_reach * max(world_scale, 1e-9)
    positive = []
    negative = []
    local_candidates = []
    for part in parts:
        signed, distance = _part_metric_near_cut(part, cut)
        # Never pair a failed/local slit with an unrelated disconnected island
        # elsewhere in the same object (for example a second figurine).
        if distance > maximum_distance:
            continue
        local_candidates.append((distance, signed, part))
        side = 1 if signed >= 0.0 else -1
        if side == 1:
            positive.append((distance, part))
        elif side == -1:
            negative.append((distance, part))
    if positive and negative:
        return min(positive, key=lambda item: item[0])[1], min(negative, key=lambda item: item[0])[1]
    # Two cuts can release one shared part (for example both feet from a base).
    # At one seam, numerical closest points may land on the same signed side
    # even though the two nearest pieces are unquestionably the local pair.
    # Use their signed ordering only after the strict locality filter above.
    local_candidates.sort(key=lambda item: item[0])
    if len(local_candidates) < 2:
        return None, None
    first, second = local_candidates[:2]
    if first[2] == second[2]:
        return None, None
    ordered = sorted((first, second), key=lambda item: item[1], reverse=True)
    return ordered[0][2], ordered[1][2]


class CUT3D_OT_execute_cut(bpy.types.Operator):
    """Constrói todas as peças a partir do plano de cortes editável"""
    bl_idname = "cut3d.execute_cut"
    bl_label = "Construir Peças"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        return bool(props and props.target_object and any(c.enabled for c in props.cuts))

    def execute(self, context):
        props = context.scene.cut3d_props
        target = props.target_object
        enabled_cuts = [cut for cut in props.cuts if cut.enabled]
        if not target or target.type != 'MESH' or not enabled_cuts:
            self.report({'ERROR'}, "Escolha um modelo e adicione ao menos um corte ativo.")
            return {'CANCELLED'}

        _clear_previous_output(target)
        collection = _get_output_collection(context, target)
        working = _copy_target(context, target, collection)
        source_face_count = len(working.data.polygons)
        source_component_count = _connected_component_count(working)
        applied_cuts = []

        # Build Draft: accumulate every lightweight mark on one frozen copy.
        # No cut is rejected merely because another planned cut is still needed
        # before a limb becomes a separate component.
        for cut in enabled_cuts:
            if _apply_local_kerf(context, working, cut):
                applied_cuts.append(cut)

        if not applied_cuts:
            working_mesh = working.data
            bpy.data.objects.remove(working, do_unlink=True)
            if working_mesh.users == 0:
                bpy.data.meshes.remove(working_mesh)
            self.report({'ERROR'}, "Nenhum plano atravessa o modelo. Reposicione os cortes sobre a malha.")
            return {'CANCELLED'}

        # Build is all-or-nothing. Publishing only the first marks is
        # misleading (and can make the untouched half appear to vanish after
        # an earlier Boolean failure). Keep every editable mark and restore
        # the original when even one enabled cut cannot be applied.
        if len(applied_cuts) != len(enabled_cuts):
            applied_ids = {cut.cut_id for cut in applied_cuts}
            skipped = [cut.name for cut in enabled_cuts if cut.cut_id not in applied_ids]
            working_mesh = working.data
            bpy.data.objects.remove(working, do_unlink=True)
            if working_mesh.users == 0:
                bpy.data.meshes.remove(working_mesh)
            target.hide_set(False)
            target.hide_render = False
            props.result_visible = False
            self.report(
                {'ERROR'},
                "Build cancelado sem alterar o modelo. Revise: " + ", ".join(skipped),
            )
            return {'CANCELLED'}

        used_transactional_fallback = bool(
            working.get("cut3d_transactional_fallbacks", 0)
        )
        working_parts = _group_boolean_result_by_draft(
            working, applied_cuts, f"{target.name}_Draft", collection,
        )
        working_parts = _discard_boolean_debris(working_parts)
        retained_face_count = sum(len(part.data.polygons) for part in working_parts)
        excessive_separations = (
            len(working_parts) - source_component_count > len(applied_cuts)
        )
        microscopic_shrapnel = (
            source_face_count >= 100_000
            and any(len(part.data.polygons) < 32 for part in working_parts)
        )
        if (
            retained_face_count < max(4, int(source_face_count * 0.85))
            or excessive_separations
            or microscopic_shrapnel
        ):
            for part in working_parts:
                _delete_mesh_object(part)
            working_mesh = working.data
            bpy.data.objects.remove(working, do_unlink=True)
            if working_mesh.users == 0:
                bpy.data.meshes.remove(working_mesh)
            target.hide_set(False)
            target.hide_render = False
            props.result_visible = False
            self.report(
                {'ERROR'},
                "O Boolean tentou fragmentar o modelo. O Build foi cancelado e o original foi preservado.",
            )
            return {'CANCELLED'}
        working_mesh = working.data
        bpy.data.objects.remove(working, do_unlink=True)
        if working_mesh.users == 0:
            bpy.data.meshes.remove(working_mesh)
        if not working_parts:
            self.report({'ERROR'}, "O rascunho foi aplicado, mas a malha não pôde ser separada.")
            return {'CANCELLED'}

        new_separations = max(0, len(working_parts) - source_component_count)
        used_topology_repair = used_transactional_fallback
        if used_topology_repair:
            for part in working_parts:
                part["cut3d_topology_repaired"] = True

        # Success is evaluated per mark, not only by the global piece count.
        # A curved cut may already release the head while two valid straight
        # slits around the feet still need to be completed together. In that
        # case the old global test skipped the straight cuts entirely.
        if new_separations == 0:
            unresolved_cuts = list(applied_cuts)
        else:
            unresolved_cuts = []
            for cut in applied_cuts:
                positive, negative = _connector_parts_for_cut(working_parts, cut)
                if not positive or not negative or positive == negative:
                    unresolved_cuts.append(cut)
        if unresolved_cuts:
            repaired_parts, late_repair = _retry_with_topology_cut(
                context,
                working_parts,
                unresolved_cuts,
                f"{target.name}_Draft",
                collection,
            )
            if late_repair:
                working_parts = _discard_boolean_debris(repaired_parts)
                used_topology_repair = True
                new_separations = max(0, len(working_parts) - source_component_count)

        # Connectors are intentionally deferred until every cut exists.  Only
        # then do both logical sides of cuts in loops (arm/hand/torso) exist.
        requested_connectors = sum(1 for cut in applied_cuts if cut.add_pin)
        applied_connectors = 0
        for cut in applied_cuts:
            cut["cut3d_last_connector_applied"] = False
            if not cut.add_pin or len(working_parts) < 2:
                continue
            positive, negative = _connector_parts_for_cut(working_parts, cut)
            if positive and negative and positive != negative:
                if _apply_connector_pair(context, positive, negative, cut):
                    cut["cut3d_last_connector_applied"] = True
                    applied_connectors += 1

        for piece in working_parts:
            if piece.get("cut3d_topology_repaired"):
                # A connector Boolean can leave a microscopic closed sliver.
                # Cap only loops created around the seam/pin, then remove the
                # sliver without touching the original surface elsewhere.
                _cap_cut_boundaries(piece, applied_cuts)
                _keep_largest_component(piece)
            else:
                clean_mesh_geometry(piece)

        # Connector Booleans may themselves leave a closed microscopic island.
        # Run the same conservative filter again before publishing the result.
        working_parts = _discard_boolean_debris(working_parts)
        final_face_count = sum(len(part.data.polygons) for part in working_parts)
        excessive_separations = (
            len(working_parts) - source_component_count > len(applied_cuts)
        )
        microscopic_shrapnel = (
            source_face_count >= 100_000
            and any(len(part.data.polygons) < 32 for part in working_parts)
        )
        if (
            final_face_count < max(4, int(source_face_count * 0.85))
            or excessive_separations
            or microscopic_shrapnel
        ):
            for part in working_parts:
                _delete_mesh_object(part)
            target.hide_set(False)
            target.hide_render = False
            props.result_visible = False
            self.report(
                {'ERROR'},
                "Os encaixes produziram uma malha inválida. O resultado foi descartado e o original foi preservado.",
            )
            return {'CANCELLED'}
        new_separations = max(0, len(working_parts) - source_component_count)

        for index, part in enumerate(working_parts, 1):
            part.name = f"{target.name}_Peça_{index:02d}"
            part["cut3d_output"] = True
            # A reconstrução reutiliza a coleção de saída. Se o usuário voltou
            # ao planejamento antes do novo Build, tanto a coleção quanto as
            # peças anteriores podem ter ficado ocultas no Viewport. Garanta
            # que o novo resultado sempre apareça por completo.
            part.hide_set(False)
            part.hide_viewport = False
            part.hide_render = False
        collection.hide_viewport = False

        # "Preservar" significa manter o original recuperável, não sobrepô-lo
        # ao resultado. O original volta ao clicar em Voltar ao planejamento.
        target.hide_set(True)
        target.hide_render = not props.keep_original
        for cut in props.cuts:
            for name in dict.fromkeys((cut.blade_object, cut.pin_object, cut.curve_object, cut.visual_object)):
                obj = bpy.data.objects.get(name)
                if obj:
                    obj.hide_set(True)
        props.result_visible = True
        props.last_build_piece_count = len(working_parts)
        props.last_build_source_components = source_component_count
        props.last_build_new_separations = new_separations
        props.last_build_cut_count = len(applied_cuts)
        context.scene["cut3d_last_connector_count"] = applied_connectors
        context.scene["cut3d_last_connector_requested"] = requested_connectors

        bpy.ops.object.select_all(action='DESELECT')
        for part in working_parts:
            part.select_set(True)
        context.view_layer.objects.active = working_parts[0]
        if new_separations == 0:
            message = (
                f"{len(applied_cuts)} corte(s) aplicado(s), mas nenhuma peça nova foi solta. "
                "Há outra ligação física na malha; adicione o corte que falta."
            )
            self.report({'WARNING'}, message)
        else:
            repair_note = " preservando a malha original" if used_topology_repair else ""
            connector_note = (
                f", {applied_connectors}/{requested_connectors} encaixe(s)"
                if requested_connectors else ""
            )
            message = (
                f"Pronto: {len(working_parts)} peças, {new_separations} nova(s) "
                f"separação(ões), com {len(applied_cuts)} corte(s){connector_note}{repair_note}."
            )
            level = {'INFO'} if applied_connectors == requested_connectors else {'WARNING'}
            self.report(level, message)
        return {'FINISHED'}


class CUT3D_OT_restore_draft(bpy.types.Operator):
    bl_idname = "cut3d.restore_draft"
    bl_label = "Voltar ao Planejamento"

    def execute(self, context):
        draft_engine.restore_planning_state(context)
        return {'FINISHED'}
