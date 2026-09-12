import math
import uuid
import json

import bmesh
import bpy
import gpu
from bpy.app.handlers import persistent
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Euler, Matrix, Vector, geometry

from . import connectors, cut_math
from .properties import get_active_cut


DRAFT_COLLECTION_NAME = "Cut3D_Planning"
LEGACY_COLLECTION_NAME = "Cut3D_Draft_Helpers"
PLANE_NAME = "Cut3D_Cut"
PIN_PREVIEW_NAME = "Cut3D_Pin"
CURVE_NAME = "Cut3D_Curve"


_preview_refreshing = False
_dirty_preview_ids = set()
_draw_handle = None
_gesture_draw_handle = None
_active_stroke_2d = []
_surface_editor = None


def surface_rails_for_cut(cut, sample_count=10):
    """Return editable front/back rails in the cut's local coordinates."""
    try:
        data = json.loads(cut.surface_data)
        front = [Vector(point[:3]) for point in data.get("front", [])]
        back = [Vector(point[:3]) for point in data.get("back", [])]
    except (AttributeError, TypeError, ValueError):
        front, back = [], []
    if len(front) >= 2 and len(back) >= 2:
        return front, back

    profile = _profile_for_cut(cut)
    samples = cut_math.resample_polyline(
        [[point[0], 0.0, point[1]] for point in profile], sample_count,
    )
    try:
        depth = json.loads(cut.depth_data)
        y_front, y_back = sorted((float(depth[0]), float(depth[1])))
    except (TypeError, ValueError, IndexError):
        y_front, y_back = -cut.blade_radius, cut.blade_radius
    front = [Vector((point[0], y_front, point[2])) for point in samples]
    back = [Vector((point[0], y_back, point[2])) for point in samples]
    return front, back


def store_surface_rails(cut, front, back):
    cut.surface_data = json.dumps({
        "front": [[point.x, point.y, point.z] for point in front],
        "back": [[point.x, point.y, point.z] for point in back],
    })
    depths = [point.y for point in front] + [point.y for point in back]
    if depths:
        cut.depth_data = json.dumps([min(depths), max(depths)])
    count = max(len(front), len(back), 2)
    sampled_front = [Vector(point) for point in cut_math.resample_polyline(front, count)]
    sampled_back = [Vector(point) for point in cut_math.resample_polyline(back, count)]
    center = [(first + second) * 0.5 for first, second in zip(sampled_front, sampled_back)]
    profile = cut_math.monotonic_profile([(point.x, point.z) for point in center])
    if len(profile) >= 2:
        cut.profile_data = json.dumps(profile)
        cut.stroke_data = json.dumps([
            [point.x, point.y, point.z] for point in center
        ])


def surface_height_for_cut(cut, point):
    if cut.cut_type != 'CURVED':
        return cut_math.profile_value(_profile_for_cut(cut), point.x)
    front, back = surface_rails_for_cut(cut)
    front = cut_math.catmull_rom_polyline(front)
    back = cut_math.catmull_rom_polyline(back)
    return cut_math.surface_height(front, back, point)


def _stroke_coordinates(cut):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return []
    try:
        points = json.loads(cut.stroke_data)
    except (TypeError, ValueError):
        return []
    matrix = _control_matrix(blade)
    return [matrix @ Vector(point) for point in points]


def _surface_world_rails(cut, front=None, back=None):
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return [], []
    if front is None or back is None:
        front, back = surface_rails_for_cut(cut)
    return (
        [_control_matrix(blade) @ Vector(point) for point in front],
        [_control_matrix(blade) @ Vector(point) for point in back],
    )


def draw_draft_overlays():
    """Desenha o Draft em pixels, sem depender da escala ou densidade da malha."""
    context = bpy.context
    scene = getattr(context, "scene", None)
    region = getattr(context, "region", None)
    props = getattr(scene, "cut3d_props", None) if scene else None
    if not props or not region or props.result_visible:
        return
    try:
        line_shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        solid_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        for index, cut in enumerate(props.cuts):
            if not cut.enabled:
                continue
            active = index == props.active_cut_index
            color = (0.08, 1.0, 0.18, 1.0) if active else (0.10, 0.48, 1.0, 0.88)
            pin = bpy.data.objects.get(cut.pin_object) if cut.add_pin else None
            editing_this_cut = (
                _surface_editor is not None
                and getattr(_surface_editor, "_cut_id", None) == cut.cut_id
            )
            if pin and pin.type == 'MESH' and not pin.hide_get() and not editing_this_cut:
                pin.data.calc_loop_triangles()
                triangles = [
                    pin.matrix_world @ pin.data.vertices[vertex_index].co
                    for triangle in pin.data.loop_triangles
                    for vertex_index in triangle.vertices
                ]
                if triangles:
                    pin_batch = batch_for_shader(solid_shader, 'TRIS', {"pos": triangles})
                    solid_shader.bind()
                    solid_shader.uniform_float("color", (*color[:3], 0.82 if active else 0.45))
                    pin_batch.draw(solid_shader)
            if cut.cut_type == 'CURVED':
                raw_front, raw_back = surface_rails_for_cut(cut)
                smooth_front = [Vector(point) for point in cut_math.catmull_rom_polyline(raw_front)]
                smooth_back = [Vector(point) for point in cut_math.catmull_rom_polyline(raw_back)]
                front, back = _surface_world_rails(cut, smooth_front, smooth_back)
                paths = [front, back]
                if front and back:
                    paths.extend(([front[0], back[0]], [front[-1], back[-1]]))
            else:
                paths = [_stroke_coordinates(cut)]
            for coords in paths:
                if len(coords) < 2:
                    continue
                batch = batch_for_shader(line_shader, 'LINE_STRIP', {"pos": coords})
                line_shader.bind()
                line_shader.uniform_float("viewportSize", (region.width, region.height))
                line_shader.uniform_float("lineWidth", 4.0 if active else 2.5)
                line_shader.uniform_float("color", color)
                batch.draw(line_shader)

        editor = _surface_editor
        if editor is not None and getattr(editor, "_cut_id", None):
            cut = next((item for item in props.cuts if item.cut_id == editor._cut_id), None)
            if cut:
                point_front, point_back = _surface_world_rails(cut, editor._front, editor._back)
                smooth_front = cut_math.catmull_rom_polyline(editor._front)
                smooth_back = cut_math.catmull_rom_polyline(editor._back)
                count = max(len(smooth_front), len(smooth_back), 2)
                display_front = [Vector(point) for point in cut_math.resample_polyline(smooth_front, count)]
                display_back = [Vector(point) for point in cut_math.resample_polyline(smooth_back, count)]
                front, back = _surface_world_rails(cut, display_front, display_back)
                triangles = []
                for index in range(count - 1):
                    triangles.extend((
                        front[index], front[index + 1], back[index + 1],
                        front[index], back[index + 1], back[index],
                    ))
                if triangles:
                    surface_batch = batch_for_shader(solid_shader, 'TRIS', {"pos": triangles})
                    solid_shader.bind()
                    solid_shader.uniform_float("color", (0.04, 0.85, 0.16, 0.24))
                    surface_batch.draw(solid_shader)
                point_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
                all_points = point_front + point_back
                if all_points:
                    gpu.state.point_size_set(7.0)
                    point_batch = batch_for_shader(point_shader, 'POINTS', {"pos": all_points})
                    point_shader.bind()
                    point_shader.uniform_float("color", (1.0, 0.30, 0.04, 1.0))
                    point_batch.draw(point_shader)
                selected = getattr(editor, "_selected", None)
                if selected:
                    rail_name, point_index = selected
                    rail = point_front if rail_name == 'front' else point_back
                    if 0 <= point_index < len(rail):
                        gpu.state.point_size_set(12.0)
                        selected_batch = batch_for_shader(point_shader, 'POINTS', {"pos": [rail[point_index]]})
                        point_shader.bind()
                        point_shader.uniform_float("color", (1.0, 0.95, 0.05, 1.0))
                        selected_batch.draw(point_shader)
    except (ReferenceError, RuntimeError, ValueError):
        # A troca/fechamento de uma janela 3D pode invalidar o contexto por um frame.
        return
    finally:
        gpu.state.point_size_set(1.0)
        gpu.state.depth_test_set('LESS_EQUAL')
        gpu.state.blend_set('NONE')


def draw_active_gesture():
    """Draw the complete mouse gesture, including the portions off the mesh."""
    if len(_active_stroke_2d) < 2:
        return
    context = bpy.context
    region = getattr(context, "region", None)
    if not region:
        return
    try:
        shader = gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
        points = [(point[0], point[1], 0.0) for point in _active_stroke_2d]
        batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": points})
        gpu.state.blend_set('ALPHA')
        shader.bind()
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 3.0)
        shader.uniform_float("color", (0.08, 1.0, 0.18, 0.96))
        batch.draw(shader)
    except (ReferenceError, RuntimeError, ValueError):
        return
    finally:
        gpu.state.blend_set('NONE')


def register_draw_handler():
    global _draw_handle, _gesture_draw_handle
    if _draw_handle is None:
        _draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_draft_overlays, (), 'WINDOW', 'POST_VIEW')
    if _gesture_draw_handle is None:
        _gesture_draw_handle = bpy.types.SpaceView3D.draw_handler_add(draw_active_gesture, (), 'WINDOW', 'POST_PIXEL')


def unregister_draw_handler():
    global _draw_handle, _gesture_draw_handle, _surface_editor
    if _draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handle, 'WINDOW')
        _draw_handle = None
    if _gesture_draw_handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_gesture_draw_handle, 'WINDOW')
        _gesture_draw_handle = None
    _surface_editor = None


def _matrix_values(matrix):
    return [value for row in matrix for value in row]


def _stored_matrix(blade):
    values = blade.get("cut3d_last_matrix")
    if not values or len(values) != 16:
        return None
    return Matrix((values[0:4], values[4:8], values[8:12], values[12:16]))


def _control_matrix(obj):
    """Read a persisted Draft control even while its collection is hidden."""
    return obj.matrix_basis.copy() if obj.parent is None else obj.matrix_world.copy()


def _sync_cut_objects(cut):
    """Mantém contorno e pino com o corte sem usar parentesco visual no viewport."""
    blade = bpy.data.objects.get(cut.blade_object)
    if not blade:
        return
    previous = _stored_matrix(blade)
    # O Empty não tem pai; matrix_basis reflete location/rotation imediatamente,
    # mesmo antes da próxima atualização do depsgraph do Blender.
    current = blade.matrix_basis.copy()
    blade.matrix_world = current
    visual = bpy.data.objects.get(cut.visual_object)
    if visual:
        visual.matrix_world = current
        visual["cut3d_last_matrix"] = _matrix_values(current)
    blade["cut3d_last_matrix"] = _matrix_values(current)
    center_pin_on_cut(cut)


def _sync_from_visual(cut):
    """A marca é o controle visível; o plano técnico acompanha-a oculto."""
    blade = bpy.data.objects.get(cut.blade_object)
    visual = bpy.data.objects.get(cut.visual_object)
    if not blade or not visual:
        return
    current = _control_matrix(visual)
    blade.matrix_basis = current
    blade.matrix_world = current
    blade["cut3d_last_matrix"] = _matrix_values(current)
    visual["cut3d_last_matrix"] = _matrix_values(current)
    center_pin_on_cut(cut)


def get_or_create_draft_collection(context):
    collection = bpy.data.collections.get(DRAFT_COLLECTION_NAME)
    if collection is None:
        collection = bpy.data.collections.new(DRAFT_COLLECTION_NAME)
        context.scene.collection.children.link(collection)
    collection.hide_render = True
    return collection


def _delete_object(name):
    obj = bpy.data.objects.get(name)
    if not obj:
        return
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data and getattr(data, "users", 1) == 0:
        if isinstance(data, bpy.types.Mesh):
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve):
            bpy.data.curves.remove(data)


def create_or_get_material(name, color, emission=True):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs['Base Color'].default_value = color
        if 'Emission Color' in bsdf.inputs:
            bsdf.inputs['Emission Color'].default_value = color if emission else (0, 0, 0, 1)
        if 'Emission Strength' in bsdf.inputs:
            bsdf.inputs['Emission Strength'].default_value = 1.5 if emission else 0.0
        if 'Roughness' in bsdf.inputs:
            bsdf.inputs['Roughness'].default_value = 0.25
    return mat


def _make_straight_preview(cut, collection, radius):
    """Linha curta que representa o corte sem exibir o plano matemático infinito."""
    curve_data = bpy.data.curves.new(f"Cut3D_Line_{cut.cut_id}", 'CURVE')
    curve_data.dimensions = '3D'
    curve_data.resolution_u = 1
    curve_data.bevel_depth = max(radius * 0.009, 0.0003)
    curve_data.bevel_resolution = 2
    spline = curve_data.splines.new('POLY')
    spline.points.add(1)
    spline.points[0].co = (-radius, 0, 0.0002, 1)
    spline.points[1].co = (radius, 0, 0.0002, 1)
    visual = bpy.data.objects.new(f"Cut3D_Line_{cut.cut_id}", curve_data)
    visual.show_in_front = True
    visual.hide_select = False
    visual.data.materials.append(create_or_get_material("Cut3D_Line_Ready", (0.04, 1.0, 0.20, 1.0)))
    collection.objects.link(visual)
    cut.visual_object = visual.name
    cut.profile_data = json.dumps([[-radius, 0.0], [radius, 0.0]])
    return visual


def _make_curve_preview(cut, collection, radius):
    curve_data = bpy.data.curves.new(f"{CURVE_NAME}_{cut.cut_id}", 'CURVE')
    curve_data.dimensions = '3D'
    curve_data.bevel_depth = max(radius * 0.008, 0.00035)
    curve_data.bevel_resolution = 2
    spline = curve_data.splines.new('BEZIER')
    spline.bezier_points.add(4)
    points = [(-1, 0), (-.55, .12), (0, -.08), (.55, .12), (1, 0)]
    for point, (x, y) in zip(spline.bezier_points, points):
        point.co = (x * radius, y * radius, 0.0002)
        point.handle_left_type = 'AUTO'
        point.handle_right_type = 'AUTO'
    obj = bpy.data.objects.new(f"{CURVE_NAME}_{cut.cut_id}", curve_data)
    obj.show_in_front = True
    obj.hide_select = False
    obj.data.materials.append(create_or_get_material("Cut3D_Curve_Ready", (0.08, 1.0, 0.28, 1.0)))
    collection.objects.link(obj)
    cut.curve_object = obj.name
    cut.visual_object = obj.name
    cut.profile_data = json.dumps([[point[0] * radius, point[1] * radius] for point in points])
    return obj


def _calibrated_dimensions(context, target):
    size = max(target.dimensions.x, target.dimensions.y, target.dimensions.z, 0.01)
    cross_size = max(target.dimensions.x, target.dimensions.y, size * 0.18)
    radius = max(cross_size * 0.65, 0.015)
    scale_length = max(context.scene.unit_settings.scale_length, 1e-9)
    unit_per_mm = 1.0 if size > 10.0 else 0.001 / scale_length
    pin_radius = max(cross_size * 0.018, 2.5 * unit_per_mm)
    pin_depth = max(pin_radius * 2.4, 6.0 * unit_per_mm)
    return radius, pin_radius, pin_depth, unit_per_mm


def create_cut_objects(context, cut, location=None, rotation=None):
    props = context.scene.cut3d_props
    target = props.target_object
    collection = get_or_create_draft_collection(context)
    radius, pin_radius, pin_depth, unit_per_mm = _calibrated_dimensions(context, target)
    cut.unit_per_mm = unit_per_mm
    cut.blade_radius = radius
    cut.pin_radius = pin_radius
    cut.pin_depth = pin_depth
    cut.chamfer_size = min(pin_depth * .15, pin_radius * .35)
    cut.clearance = props.default_clearance * 1000.0 * unit_per_mm
    cut.cut_gap = 0.30 * unit_per_mm
    cut.glue_gap = 0.50 * unit_per_mm

    corners = [target.matrix_world @ Vector(corner) for corner in target.bound_box]
    center = sum(corners, Vector()) / 8
    # O plano de cálculo é um Empty pequeno; o contorno verde é a interseção real com a malha.
    blade = bpy.data.objects.new(f"{PLANE_NAME}_{cut.cut_id}", None)
    blade.location = location or center
    blade.rotation_euler = rotation or Euler((0, 0, 0), 'XYZ')
    blade.show_in_front = True
    blade.empty_display_type = 'PLAIN_AXES'
    blade.empty_display_size = 0.000001
    blade.hide_viewport = True
    blade.hide_render = True
    blade.hide_select = True
    blade["cut3d_cut_id"] = cut.cut_id
    blade["cut3d_role"] = "BLADE"
    collection.objects.link(blade)
    cut.blade_object = blade.name

    if cut.cut_type == 'CURVED':
        curve_obj = _make_curve_preview(cut, collection, radius)
        curve_obj.matrix_world = blade.matrix_world.copy()
        curve_obj.hide_viewport = True
    else:
        line_obj = _make_straight_preview(cut, collection, radius)
        line_obj.matrix_world = blade.matrix_world.copy()
        line_obj.hide_viewport = True

    pin_mesh = bpy.data.meshes.new(f"{PIN_PREVIEW_NAME}_{cut.cut_id}_Mesh")
    pin = bpy.data.objects.new(f"{PIN_PREVIEW_NAME}_{cut.cut_id}", pin_mesh)
    pin.matrix_world = blade.matrix_world.copy()
    pin.show_in_front = True
    pin["cut3d_cut_id"] = cut.cut_id
    pin["cut3d_role"] = "PIN"
    pin.data.materials.append(create_or_get_material("Cut3D_Pin_Ready", (0.04, 1.0, 0.20, 1.0)))
    collection.objects.link(pin)
    cut.pin_object = pin.name
    _sync_cut_objects(cut)
    blade["cut3d_last_matrix"] = _matrix_values(_control_matrix(blade))
    refresh_cut_preview(cut, context)
    return blade


def refresh_cut_preview(cut, context):
    pin = bpy.data.objects.get(getattr(cut, "pin_object", ""))
    blade = bpy.data.objects.get(getattr(cut, "blade_object", ""))
    if blade:
        blade.hide_viewport = True
        blade.hide_select = True
    curve = bpy.data.objects.get(getattr(cut, "curve_object", ""))
    if curve:
        curve.hide_viewport = True
    visual = bpy.data.objects.get(getattr(cut, "visual_object", ""))
    if visual:
        visual.hide_viewport = True
    if not pin:
        return
    pin.hide_viewport = not cut.enabled or not cut.add_pin
    if not cut.add_pin:
        return
    bm = connectors.generate_connector_mesh(
        cut.connector_type,
        cut.pin_radius,
        cut.pin_depth,
        cut.chamfer_size,
        base_ext=0.0,
        top_ext=0.0,
    )
    if cut.pin_side == 'SIDE_B':
        bmesh.ops.transform(bm, matrix=Matrix.Scale(-1, 4, Vector((0, 0, 1))), verts=bm.verts)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    new_mesh = bpy.data.meshes.new(f"{PIN_PREVIEW_NAME}_{cut.cut_id}_Mesh")
    bm.to_mesh(new_mesh)
    bm.free()
    old_mesh = pin.data
    pin.data = new_mesh
    if old_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    center_pin_on_cut(cut)


def update_draft_pin_visual(context):
    cut = get_active_cut(context.scene.cut3d_props)
    if cut:
        refresh_cut_preview(cut, context)


def select_cut(context, cut):
    # A marca é um overlay; selecionar um objeto técnico só criaria gizmos e cruzes.
    bpy.ops.object.select_all(action='DESELECT')
    context.area.tag_redraw()


def restore_planning_state(context):
    """Return to a single coherent Draft view, regardless of old target state."""
    props = context.scene.cut3d_props
    props.result_visible = False
    bpy.ops.object.select_all(action='DESELECT')
    # A target may have changed while a generated piece was active. Hide every
    # generated result, otherwise it can overlap the preserved original and
    # look like a failed/z-fighting Build.
    for obj in bpy.data.objects:
        if obj.get("cut3d_output"):
            obj.hide_set(True)
    for collection in bpy.data.collections:
        if collection.name.endswith("_Cut3D_Parts"):
            collection.hide_viewport = True
    target = props.target_object
    if target and target.name in context.view_layer.objects:
        target.hide_viewport = False
        target.hide_set(False)
        target.hide_render = False
        target.select_set(True)
        context.view_layer.objects.active = target
    for cut in props.cuts:
        for name in dict.fromkeys((cut.blade_object, cut.pin_object, cut.curve_object, cut.visual_object)):
            obj = bpy.data.objects.get(name)
            if obj:
                obj.hide_set(not cut.enabled)
                if obj.type == 'CURVE' or obj.get("cut3d_role") == "BLADE":
                    obj.hide_viewport = True
    for area in context.screen.areas if context.screen else []:
        area.tag_redraw()


def remove_cut_item(context, index):
    props = context.scene.cut3d_props
    if not (0 <= index < len(props.cuts)):
        return
    cut = props.cuts[index]
    for name in dict.fromkeys((cut.pin_object, cut.curve_object, cut.visual_object, cut.blade_object)):
        _delete_object(name)
    props.cuts.remove(index)
    props.active_cut_index = min(index, len(props.cuts) - 1)


def cleanup_draft_objects(context):
    props = context.scene.cut3d_props
    for index in reversed(range(len(props.cuts))):
        remove_cut_item(context, index)
    collection = bpy.data.collections.get(DRAFT_COLLECTION_NAME)
    if collection:
        for obj in list(collection.objects):
            _delete_object(obj.name)
        bpy.data.collections.remove(collection)
    props.active_cut_index = -1


def cleanup_legacy_previews(context):
    """Remove o aro das versões anteriores, inclusive quando salvo no .blend."""
    props = context.scene.cut3d_props
    has_mesh_blade = any(
        bpy.data.objects.get(cut.blade_object)
        and bpy.data.objects[cut.blade_object].type == 'MESH'
        for cut in props.cuts
    )
    planning = bpy.data.collections.get(DRAFT_COLLECTION_NAME)
    collection_has_ring = bool(planning and any(
        obj.type == 'MESH' and obj.get("cut3d_role") == "BLADE"
        for obj in planning.objects
    ))
    if has_mesh_blade or collection_has_ring:
        if len(props.cuts):
            cleanup_draft_objects(context)
        elif planning:
            for obj in list(planning.objects):
                _delete_object(obj.name)
            bpy.data.collections.remove(planning)
    legacy = bpy.data.collections.get(LEGACY_COLLECTION_NAME)
    if legacy:
        for obj in list(legacy.objects):
            _delete_object(obj.name)
        bpy.data.collections.remove(legacy)


def migrate_surface_previews(context):
    """Converte cortes da 2.1 sem manter linhas de parentesco no viewport."""
    props = getattr(context.scene, "cut3d_props", None)
    if not props:
        return
    for cut in props.cuts:
        blade = bpy.data.objects.get(cut.blade_object)
        if not blade:
            continue
        blade.empty_display_size = 0.000001
        blade.hide_viewport = True
        blade.hide_render = True
        blade.hide_select = True
        for name in dict.fromkeys((cut.visual_object, cut.curve_object, cut.pin_object)):
            obj = bpy.data.objects.get(name)
            if obj and obj.parent:
                world_matrix = obj.matrix_world.copy()
                obj.parent = None
                obj.matrix_world = world_matrix
        visual = bpy.data.objects.get(cut.visual_object)
        if visual:
            visual.hide_viewport = True
        if not cut.stroke_data:
            try:
                old_profile = json.loads(cut.profile_data)
            except (TypeError, ValueError):
                old_profile = []
            if len(old_profile) >= 2:
                cut.stroke_data = json.dumps([[x, 0.0, z] for x, z in old_profile])
        if cut.cut_type == 'CURVED' and not cut.surface_data:
            front, back = surface_rails_for_cut(cut, sample_count=10)
            store_surface_rails(cut, front, back)
        if cut.cut_type == 'CURVED' and cut.gesture_version < 4:
            front, back = surface_rails_for_cut(cut, sample_count=10)
            front, back, mapped = fit_surface_rails_to_target(
                context, cut, front, back,
            )
            if mapped:
                store_surface_rails(cut, front, back)
                cut.gesture_version = 4
        blade["cut3d_last_matrix"] = _matrix_values(_control_matrix(blade))
        restore_local_preview(cut)


def deferred_migrate_surface_previews():
    """Run after Blender has restored collection properties from the .blend."""
    try:
        migrate_surface_previews(bpy.context)
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return None


def _new_cut_record(context, cut_type):
    props = context.scene.cut3d_props
    props.cut_counter += 1
    cut = props.cuts.add()
    cut.cut_id = uuid.uuid4().hex[:8]
    cut.name = f"Corte {props.cut_counter:02d}"
    cut.cut_type = cut_type
    cut.status = 'EDITING'
    props.active_cut_index = len(props.cuts) - 1
    return cut


def _raycast_target_coord(context, coord, target):
    region, rv3d = context.region, context.region_data
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    depsgraph = context.view_layer.depsgraph
    evaluated = target.evaluated_get(depsgraph)
    inverse = target.matrix_world.inverted()
    local_origin = inverse @ origin
    local_direction = (inverse.to_3x3() @ direction).normalized()
    hit, local_location, local_normal, _ = evaluated.ray_cast(local_origin, local_direction)
    if not hit:
        return None
    world_location = target.matrix_world @ local_location
    world_normal = (target.matrix_world.to_3x3() @ local_normal).normalized()
    return world_location, world_normal, direction.normalized()


def _raycast_target_layers(context, coord, target, limit=12):
    """Return consecutive intersections along one screen ray.

    The first pair describes the visible shell hit by the gesture.  A torso or
    another limb farther behind produces later pairs and is deliberately not
    included in the local cutter depth.
    """
    region, rv3d = context.region, context.region_data
    world_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    world_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    depsgraph = context.view_layer.depsgraph
    evaluated = target.evaluated_get(depsgraph)
    world_matrix = evaluated.matrix_world.copy()
    inverse = world_matrix.inverted_safe()
    local_direction = (inverse.to_3x3() @ world_direction).normalized()
    local_origin = inverse @ world_origin
    local_scale = max((inverse.to_3x3() @ world_direction).length, 1e-9)
    epsilon_world = max(target.dimensions.length * 1e-6, 1e-6)
    epsilon_local = epsilon_world * local_scale
    hits = []
    cursor = local_origin
    travelled = 0.0
    for _index in range(limit):
        hit, location, normal, face_index = evaluated.ray_cast(cursor, local_direction)
        if not hit:
            break
        world_location = world_matrix @ location
        world_normal = (world_matrix.to_3x3() @ normal).normalized()
        distance = (world_location - world_origin).dot(world_direction)
        if distance >= travelled - epsilon_world:
            hits.append((world_location, world_normal, world_direction.copy(), face_index))
            travelled = distance + epsilon_world
        cursor = location + local_direction * epsilon_local
    return hits


def _raycast_target_world_layers(target, depsgraph, origin, direction, distance, limit=32):
    """Intersect ``target`` repeatedly along an arbitrary world-space ray."""
    if not target or distance <= 0.0:
        return []
    evaluated = target.evaluated_get(depsgraph)
    world_matrix = evaluated.matrix_world.copy()
    inverse = world_matrix.inverted_safe()
    direction = Vector(direction).normalized()
    local_vector = inverse.to_3x3() @ direction
    local_scale = max(local_vector.length, 1e-12)
    local_direction = local_vector.normalized()
    cursor = inverse @ Vector(origin)
    maximum_local = float(distance) * local_scale
    epsilon_world = max(target.dimensions.length * 1e-6, 1e-7)
    epsilon_local = epsilon_world * local_scale
    travelled = 0.0
    hits = []
    for _index in range(limit):
        hit, location, normal, face_index = evaluated.ray_cast(
            cursor, local_direction, distance=max(maximum_local - travelled, 0.0),
        )
        if not hit:
            break
        step = max((location - cursor).dot(local_direction), 0.0)
        travelled += step
        if travelled > maximum_local + epsilon_local:
            break
        world_location = world_matrix @ location
        world_normal = (world_matrix.to_3x3() @ normal).normalized()
        hits.append((world_location, world_normal, face_index))
        cursor = location + local_direction * epsilon_local
        travelled += epsilon_local
    return hits


def fit_surface_rails_to_target(context, cut, front=None, back=None):
    """Snap every editable rail point to the target shell along cut depth.

    Each control keeps its X/Z design coordinates.  Only its depth is solved
    again against the evaluated mesh, so the front and rear perimeters sit on
    the real body instead of two flat planes.
    """
    props = getattr(context.scene, "cut3d_props", None)
    target = props.target_object if props else None
    blade = bpy.data.objects.get(cut.blade_object) if cut else None
    if not target or not blade:
        return list(front or []), list(back or []), 0
    if front is None or back is None:
        front, back = surface_rails_for_cut(cut)
    front = [Vector(point) for point in front]
    back = [Vector(point) for point in back]
    blade_matrix = _control_matrix(blade)
    blade_inverse = blade_matrix.inverted_safe()
    local_corners = [
        blade_inverse @ (target.matrix_world @ Vector(corner))
        for corner in target.bound_box
    ]
    y_values = [point.y for point in local_corners]
    if not y_values:
        return front, back, 0
    y_min, y_max = min(y_values), max(y_values)
    span = max(y_max - y_min, target.dimensions.length * 0.05, cut.unit_per_mm)
    margin = max(span * 0.08, cut.unit_per_mm * 0.5)
    ray_start = y_min - margin
    ray_end = y_max + margin
    ray_distance = ray_end - ray_start
    direction = (blade_matrix.to_3x3() @ Vector((0.0, 1.0, 0.0))).normalized()
    depsgraph = context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(depsgraph)
    world_matrix = evaluated.matrix_world.copy()
    try:
        depth_values = json.loads(cut.depth_data)
        fallback_depth = (float(depth_values[0]) + float(depth_values[1])) * 0.5
    except (TypeError, ValueError, IndexError):
        rail_depths = [point.y for point in front + back]
        fallback_depth = sum(rail_depths) / max(len(rail_depths), 1)

    def fit_point(point):
        origin = blade_matrix @ Vector((point.x, ray_start, point.z))
        hits = _raycast_target_world_layers(
            target, depsgraph, origin, direction, ray_distance,
        )
        if not hits:
            # No extremo da silhueta o raio pode ser tangente e não formar um
            # par de entradas. O ponto mais próximo da malha fecha esse último
            # intervalo sem deixar um controle flutuando fora do corpo.
            # Search from the middle of the selected shell. Starting from the
            # old front/back margin would pull a silhouette control diagonally
            # inward and shorten the cutter instead of preserving its outline.
            expected_world = blade_matrix @ Vector((
                point.x, fallback_depth, point.z,
            ))
            expected_local = world_matrix.inverted_safe() @ expected_world
            hit, location, _normal, _face_index = evaluated.closest_point_on_mesh(
                expected_local,
            )
            if not hit:
                return point.copy(), False
            return blade_inverse @ (world_matrix @ location), True
        local_hits = [blade_inverse @ item[0] for item in hits]
        chosen = min(local_hits, key=lambda item: abs(item.y - point.y))
        return chosen, True

    fitted_front = []
    fitted_back = []
    mapped = 0
    for point in front:
        fitted, success = fit_point(point)
        fitted_front.append(fitted)
        mapped += int(success)
    for point in back:
        fitted, success = fit_point(point)
        fitted_back.append(fitted)
        mapped += int(success)
    return fitted_front, fitted_back, mapped


def _project_to_view_plane(context, coord, plane_point, plane_normal):
    region, rv3d = context.region, context.region_data
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord).normalized()
    point = geometry.intersect_line_plane(
        origin,
        origin + direction * max(context.space_data.clip_end, 1000.0),
        plane_point,
        plane_normal,
        False,
    )
    return point


def _refine_silhouette_edge(context, target, outside, inside, iterations=9):
    """Return a screen point just inside the target silhouette."""
    outside = Vector(outside)
    inside = Vector(inside)
    for _index in range(iterations):
        middle = outside.lerp(inside, 0.5)
        if _raycast_target_coord(context, (middle.x, middle.y), target):
            inside = middle
        else:
            outside = middle
    return inside


def _visible_gesture_run(context, target, screen_points):
    """Choose and precisely bound the visible mesh interval crossed by a swipe."""
    samples = []
    runs = []
    current = []
    for index, point in enumerate(screen_points):
        hit = _raycast_target_coord(context, (point.x, point.y), target)
        sample = (index, point, hit)
        samples.append(sample)
        if hit:
            current.append(sample)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    if not runs:
        return None
    gesture_middle = (len(screen_points) - 1) * 0.5
    run = max(
        runs,
        key=lambda values: (
            len(values),
            -abs((values[0][0] + values[-1][0]) * 0.5 - gesture_middle),
        ),
    )
    first_index, first_point, _first_hit = run[0]
    last_index, last_point, _last_hit = run[-1]
    start = first_point.copy()
    end = last_point.copy()
    if first_index > 0 and samples[first_index - 1][2] is None:
        start = _refine_silhouette_edge(
            context, target, samples[first_index - 1][1], first_point,
        )
    if last_index + 1 < len(samples) and samples[last_index + 1][2] is None:
        end = _refine_silhouette_edge(
            context, target, samples[last_index + 1][1], last_point,
        )
    clipped = [start]
    clipped.extend(
        screen_points[index].copy()
        for index in range(first_index + 1, last_index)
    )
    if not clipped or (end - clipped[-1]).length > 0.25:
        clipped.append(end)
    return {
        "samples": run,
        "screen_points": clipped,
        "first_index": first_index,
        "last_index": last_index,
    }


def _gesture_matrix(projected_points, view_direction):
    """Create the stable cutter frame: X=swipe, Y=view depth, Z=cut side."""
    if len(projected_points) < 2:
        return None
    start, end = projected_points[0], projected_points[-1]
    chord = end - start
    if chord.length <= 1e-8:
        return None
    x_axis = chord.normalized()
    y_axis = view_direction - x_axis * view_direction.dot(x_axis)
    if y_axis.length <= 1e-8:
        return None
    y_axis.normalize()
    z_axis = x_axis.cross(y_axis)
    if z_axis.length <= 1e-8:
        return None
    z_axis.normalize()
    y_axis = z_axis.cross(x_axis).normalized()
    matrix = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    matrix.translation = (start + end) * 0.5
    return matrix


def _json_vector(value, fallback=(0.0, 0.0, 0.0)):
    try:
        data = json.loads(value)
        if len(data) >= 3:
            return Vector((float(data[0]), float(data[1]), float(data[2])))
    except (TypeError, ValueError):
        pass
    return Vector(fallback)


def _profile_for_cut(cut):
    try:
        profile = json.loads(cut.profile_data)
    except (TypeError, ValueError):
        profile = []
    return profile if len(profile) >= 2 else [[-cut.blade_radius, 0.0], [cut.blade_radius, 0.0]]


def cut_surface_frame(cut, sample_count=64):
    """Return the area centroid and local frame of the complete cut surface."""
    front, back = surface_rails_for_cut(cut, sample_count=max(sample_count // 4, 10))
    if cut.cut_type == 'CURVED':
        front = [Vector(point) for point in cut_math.catmull_rom_polyline(front)]
        back = [Vector(point) for point in cut_math.catmull_rom_polyline(back)]
    # Preserve the authoritative smoothed rails for the final projection. The
    # resampled copies below exist only to integrate the surface area.
    surface_front = [point.copy() for point in front]
    surface_back = [point.copy() for point in back]
    count = max(sample_count, len(front), len(back), 2)
    front = [Vector(point) for point in cut_math.resample_polyline(front, count)]
    back = [Vector(point) for point in cut_math.resample_polyline(back, count)]

    weighted_center = Vector()
    accumulated_normal = Vector()
    accumulated_tangent = Vector()
    total_area = 0.0
    for index in range(count - 1):
        first_front = front[index]
        next_front = front[index + 1]
        first_back = back[index]
        next_back = back[index + 1]
        accumulated_tangent += (next_front - first_front) + (next_back - first_back)
        for first, second, third in (
            (first_front, next_front, next_back),
            (first_front, next_back, first_back),
        ):
            area_vector = (second - first).cross(third - first)
            double_area = area_vector.length
            if double_area <= 1e-18:
                continue
            area = double_area * 0.5
            weighted_center += ((first + second + third) / 3.0) * area
            accumulated_normal += area_vector
            total_area += area

    if total_area > 1e-18:
        center = weighted_center / total_area
    else:
        points = front + back
        center = sum(points, Vector()) / max(len(points), 1)

    # O centro de área de uma faixa não plana pode ficar dentro da concavidade,
    # alguns milímetros longe da própria costura. X/Y continuam representando o
    # centro da área completa, mas Z é projetado de volta na superfície regrada.
    # Assim a origem do conector fica exatamente sobre o corte, não apenas perto.
    center.z = cut_math.surface_height(surface_front, surface_back, center)

    x_values = [point.x for point in surface_front + surface_back]
    y_values = [point.y for point in surface_front + surface_back]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    x_step = max((x_max - x_min) * 0.001, 1e-7)
    y_step = max((y_max - y_min) * 0.001, 1e-7)
    x_low, x_high = max(x_min, center.x - x_step), min(x_max, center.x + x_step)
    y_low, y_high = max(y_min, center.y - y_step), min(y_max, center.y + y_step)
    x_tangent = Vector((
        max(x_high - x_low, 1e-7),
        0.0,
        cut_math.surface_height(surface_front, surface_back, (x_high, center.y, 0.0))
        - cut_math.surface_height(surface_front, surface_back, (x_low, center.y, 0.0)),
    ))
    y_tangent = Vector((
        0.0,
        max(y_high - y_low, 1e-7),
        cut_math.surface_height(surface_front, surface_back, (center.x, y_high, 0.0))
        - cut_math.surface_height(surface_front, surface_back, (center.x, y_low, 0.0)),
    ))
    local_normal = x_tangent.cross(y_tangent)
    normal = (
        local_normal.normalized()
        if local_normal.length > 1e-12
        else accumulated_normal.normalized()
        if accumulated_normal.length > 1e-12
        else Vector((0, 0, 1))
    )
    if normal.z < 0.0:
        normal.negate()
    tangent = x_tangent - normal * x_tangent.dot(normal)
    if tangent.length <= 1e-12:
        tangent = Vector((1, 0, 0)) - normal * normal.x
    if tangent.length <= 1e-12:
        tangent = Vector((0, 1, 0)) - normal * normal.y
    tangent.normalize()
    depth_axis = normal.cross(tangent).normalized()
    orientation = Matrix((tangent, depth_axis, normal)).transposed().to_4x4()
    return center, orientation


def center_pin_on_cut(cut):
    blade = bpy.data.objects.get(cut.blade_object)
    pin = bpy.data.objects.get(cut.pin_object)
    if not blade or not pin:
        return None
    blade_matrix = _control_matrix(blade)
    pin_matrix = _control_matrix(pin)
    center, orientation = cut_surface_frame(cut)
    # Recentrar ou editar a superfície não pode apagar uma escala feita pelo
    # usuário no gizmo. Descartamos translação/rotação acidentais e preservamos
    # exclusivamente a escala relativa do conector.
    relative = blade_matrix.inverted_safe() @ pin_matrix
    scale = relative.to_scale()
    scale_matrix = Matrix.Diagonal((
        max(abs(scale.x), 1e-6),
        max(abs(scale.y), 1e-6),
        max(abs(scale.z), 1e-6),
        1.0,
    ))
    desired = (
        blade_matrix
        @ Matrix.Translation(center)
        @ orientation
        @ scale_matrix
    )
    current_values = _matrix_values(pin_matrix)
    desired_values = _matrix_values(desired)
    if any(abs(first - second) > 1e-9 for first, second in zip(current_values, desired_values)):
        pin.matrix_basis = desired
        pin.matrix_world = desired
    pin.lock_location = (True, True, True)
    pin.lock_rotation = (True, True, True)
    pin.lock_scale = (False, False, False)
    pin["cut3d_last_matrix"] = desired_values
    return desired.copy()


def pin_matrix_for_cut(cut):
    """Authoritative centered pin matrix used by Draft and final Build."""
    centered = center_pin_on_cut(cut)
    if centered is not None:
        return centered
    blade = bpy.data.objects.get(cut.blade_object)
    return _control_matrix(blade) if blade else Matrix.Identity(4)


def _raycast_target(context, event, target):
    return _raycast_target_coord(context, (event.mouse_region_x, event.mouse_region_y), target)


def _draw_matrix(start, end, view_direction, fallback_normal):
    stroke = end - start
    if stroke.length < 1e-6:
        return None
    x_axis = stroke.normalized()
    z_axis = x_axis.cross(view_direction).normalized()
    if z_axis.length < 1e-5:
        z_axis = fallback_normal.normalized()
    y_axis = z_axis.cross(x_axis).normalized()
    z_axis = x_axis.cross(y_axis).normalized()
    matrix = Matrix((x_axis, y_axis, z_axis)).transposed().to_4x4()
    matrix.translation = (start + end) * 0.5
    return matrix


def _update_drawn_preview(cut, world_points):
    blade = bpy.data.objects.get(cut.blade_object)
    visual = bpy.data.objects.get(cut.visual_object)
    if not blade or not visual or len(world_points) < 2:
        return
    # Corte reto é a lâmina definida pelo gesto, não uma curva que acompanha
    # os relevos da superfície (isso produzia o "U" visto no pescoço).
    if cut.cut_type == 'STRAIGHT':
        world_points = [world_points[0], world_points[-1]]
    blade_matrix = _control_matrix(blade)
    inverse = blade_matrix.inverted()
    visual.matrix_world = blade_matrix
    local_points = [inverse @ point for point in world_points]
    profile = [[point.x, point.z] for point in local_points]
    cut.profile_data = json.dumps(profile)
    cut.stroke_data = json.dumps([[point.x, point.y, point.z] for point in local_points])
    curve_data = visual.data
    curve_data.splines.clear()
    spline = curve_data.splines.new('POLY')
    spline.points.add(len(local_points) - 1)
    for point, local in zip(spline.points, local_points):
        point.co = (local.x, local.y, local.z, 1.0)
    stroke_length = sum((second - first).length for first, second in zip(local_points, local_points[1:]))
    curve_data.bevel_depth = max(min(stroke_length * 0.015, 0.0025), 0.00035)
    visual.show_in_front = True


def restore_local_preview(cut):
    blade = bpy.data.objects.get(cut.blade_object)
    visual = bpy.data.objects.get(cut.visual_object)
    if not blade or not visual or visual.type != 'CURVE':
        return False
    try:
        coords = json.loads(cut.stroke_data)
    except (TypeError, ValueError):
        coords = []
    if len(coords) < 2:
        return False
    visual.matrix_world = _control_matrix(blade)
    visual.data.splines.clear()
    spline = visual.data.splines.new('POLY')
    spline.points.add(len(coords) - 1)
    for point, coordinate in zip(spline.points, coords):
        point.co = (*coordinate, 1.0)
    stroke_length = sum((Vector(b) - Vector(a)).length for a, b in zip(coords, coords[1:]))
    visual.data.bevel_depth = max(min(stroke_length * 0.015, 0.0025), 0.00035)
    visual.show_in_front = True
    return True


def _profile_value(profile, x):
    return cut_math.profile_value(profile, x)


def rebuild_surface_preview(context, cut, depsgraph=None, target=None):
    """Mostra a interseção real entre a superfície de corte e a malha avaliada."""
    target = target or context.scene.cut3d_props.target_object
    blade = bpy.data.objects.get(cut.blade_object)
    visual = bpy.data.objects.get(cut.visual_object)
    if not target or not blade or not visual or visual.type != 'CURVE':
        return 0
    try:
        profile = json.loads(cut.profile_data) if cut.cut_type == 'CURVED' else []
    except (TypeError, ValueError):
        profile = []
    _sync_cut_objects(cut)
    depsgraph = depsgraph or context.evaluated_depsgraph_get()
    evaluated = target.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    mesh.calc_loop_triangles()
    target_world = evaluated.matrix_world
    blade_matrix = _control_matrix(blade)
    blade_inverse = blade_matrix.inverted()
    local_vertices = [blade_inverse @ (target_world @ vertex.co) for vertex in mesh.vertices]
    segments = []
    epsilon = max(target.dimensions.length * 1e-7, 1e-7)
    for triangle in mesh.loop_triangles:
        points = [local_vertices[index] for index in triangle.vertices]
        values = [
            point.z - surface_height_for_cut(cut, point)
            if cut.cut_type == 'CURVED'
            else point.z - _profile_value(profile, point.x)
            for point in points
        ]
        crossings = []
        for edge_index in range(3):
            first = points[edge_index]
            second = points[(edge_index + 1) % 3]
            first_value = values[edge_index]
            second_value = values[(edge_index + 1) % 3]
            if abs(first_value) <= epsilon:
                crossings.append(first.copy())
            if first_value * second_value < -(epsilon * epsilon):
                factor = first_value / (first_value - second_value)
                crossings.append(first.lerp(second, factor))
        unique = []
        for point in crossings:
            if not any((point - other).length <= epsilon * 4 for other in unique):
                unique.append(point)
        if len(unique) >= 2:
            segments.append((unique[0], unique[1]))
    evaluated.to_mesh_clear()

    visual.data.splines.clear()
    visual.matrix_world = blade_matrix
    for first, second in segments:
        spline = visual.data.splines.new('POLY')
        spline.points.add(1)
        spline.points[0].co = (first.x, first.y, first.z, 1.0)
        spline.points[1].co = (second.x, second.y, second.z, 1.0)
    visual.show_in_front = False
    visual.data.bevel_depth = max(min(target.dimensions) * 0.004, 0.00025)
    return len(segments)


def _flush_dirty_previews():
    global _preview_refreshing
    if _preview_refreshing:
        return 0.1
    pending = set(_dirty_preview_ids)
    _dirty_preview_ids.clear()
    if not pending:
        return None
    _preview_refreshing = True
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for scene in bpy.data.scenes:
            props = getattr(scene, "cut3d_props", None)
            if not props or not props.target_object:
                continue
            for cut in props.cuts:
                if cut.cut_id in pending and cut.enabled and cut.status == 'READY':
                    rebuild_surface_preview(bpy.context, cut, depsgraph=depsgraph, target=props.target_object)
    finally:
        _preview_refreshing = False
    return None


@persistent
def depsgraph_preview_update(scene, depsgraph):
    """Move apenas a marca e o pino; nenhuma geometria pesada é calculada no rascunho."""
    if _preview_refreshing:
        return
    props = getattr(scene, "cut3d_props", None)
    if not props:
        return
    for cut in props.cuts:
        blade = bpy.data.objects.get(cut.blade_object)
        visual = bpy.data.objects.get(cut.visual_object)
        if not blade:
            continue
        if visual:
            stored_visual = visual.get("cut3d_last_matrix")
            visual_values = _matrix_values(_control_matrix(visual))
            if stored_visual is None or any(abs(a - b) > 1e-8 for a, b in zip(stored_visual, visual_values)):
                _sync_from_visual(cut)
                continue
        previous = _stored_matrix(blade)
        current_values = _matrix_values(_control_matrix(blade))
        changed = previous is None
        # A comparação plana evita depender do modo de rotação do objeto.
        if previous is not None:
            previous_values = _matrix_values(previous)
            changed = any(abs(a - b) > 1e-8 for a, b in zip(previous_values, current_values))
        if changed:
            _sync_cut_objects(cut)
        elif not props.result_visible and cut.enabled and cut.add_pin:
            # Scaling remains interactive, but translation/rotation can never
            # leave the connector floating away from the current cut surface.
            center_pin_on_cut(cut)


class CUT3D_OT_add_cut(bpy.types.Operator):
    """Adiciona um corte editável ao plano"""
    bl_idname = "cut3d.add_cut"
    bl_label = "Adicionar Corte"
    bl_options = {'REGISTER', 'UNDO'}

    cut_type: bpy.props.EnumProperty(items=[('STRAIGHT', "Reto", ""), ('CURVED', "Curvo", "")], default='STRAIGHT')

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        active = context.active_object
        active_is_source = bool(
            active and active.type == 'MESH'
            and not active.get("cut3d_role")
            and not active.get("cut3d_output")
        )
        return bool(props and not props.result_visible and (props.target_object is not None or active_is_source))

    def execute(self, context):
        """Caminho programático; a interface usa invoke/modal para desenhar."""
        props = context.scene.cut3d_props
        active = context.active_object
        target = active if (
            active and active.type == 'MESH'
            and not active.get("cut3d_role")
            and not active.get("cut3d_output")
        ) else props.target_object
        if not target or target.type != 'MESH':
            self.report({'ERROR'}, "Selecione uma malha para começar.")
            return {'CANCELLED'}
        props.target_object = target
        cut = _new_cut_record(context, self.cut_type)
        create_cut_objects(context, cut)
        cut.status = 'READY'
        self.report({'INFO'}, "Corte criado. Use G e R no viewport; selecione o pino para movê-lo.")
        return {'FINISHED'}

    def invoke(self, context, event):
        props = context.scene.cut3d_props
        # O objeto selecionado no viewport sempre vence o campo antigo do painel.
        # Isso permite cortar só um braço/peça, inclusive uma peça criada pelo Cut3D.
        active = context.active_object
        target = active if (
            active and active.type == 'MESH'
            and not active.get("cut3d_role")
            and not active.get("cut3d_output")
        ) else props.target_object
        if context.area.type != 'VIEW_3D' or not target or target.type != 'MESH':
            self.report({'ERROR'}, "Selecione uma malha no Viewport 3D.")
            return {'CANCELLED'}
        props.target_object = target
        props.result_visible = False
        output = bpy.data.collections.get(f"{target.name}_Cut3D_Parts")
        if output:
            output.hide_viewport = True
            for obj in output.objects:
                obj.hide_set(True)
        cleanup_legacy_previews(context)
        self._drawing = False
        self._screen_points = []
        context.window.cursor_modal_set('CROSSHAIR')
        context.workspace.status_text_set(
            "Arraste como no Fruit Ninja: comece fora, atravesse o modelo e solte  •  Esc para cancelar"
        )
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _append_stroke_to(self, end_mouse):
        """Store the complete 2D gesture at stable pixel spacing."""
        start_mouse = self._screen_points[-1] if self._screen_points else end_mouse
        distance = (end_mouse - start_mouse).length
        steps = max(1, int(math.ceil(distance / 4.0)))
        for step in range(1, steps + 1):
            factor = step / steps
            sample = start_mouse.lerp(end_mouse, factor)
            if not self._screen_points or (sample - self._screen_points[-1]).length > 0.5:
                self._screen_points.append(sample.copy())
        _active_stroke_2d.clear()
        _active_stroke_2d.extend((point.x, point.y) for point in self._screen_points)

    def _analyze_gesture(self, context, target):
        """Convert one 2D swipe into a finite, local 3D cut definition."""
        if len(self._screen_points) < 2:
            return None, "O gesto ficou curto demais."
        pixel_length = sum(
            (second - first).length
            for first, second in zip(self._screen_points, self._screen_points[1:])
        )
        if pixel_length < 12.0:
            return None, "O gesto ficou curto demais. Atravesse a região do corte."

        visible_run = _visible_gesture_run(context, target, self._screen_points)
        if not visible_run:
            return None, "O gesto não atravessou o modelo. Passe o traço por cima da peça."
        hit_samples = visible_run["samples"]

        middle_index = (hit_samples[0][0] + hit_samples[-1][0]) * 0.5
        _index, seed_screen, seed_hit = min(
            hit_samples, key=lambda item: abs(item[0] - middle_index)
        )
        layers = _raycast_target_layers(context, (seed_screen.x, seed_screen.y), target)
        if layers:
            seed_hit = layers[0][:3]
        seed_world, _seed_normal, view_direction = seed_hit

        screen_tuples = [
            (point.x, point.y) for point in visible_run["screen_points"]
        ]
        simplified_screen = cut_math.simplify_polyline(screen_tuples, 1.25)
        projected = []
        for point in simplified_screen:
            world = _project_to_view_plane(
                context, point, seed_world, view_direction,
            )
            if world is not None:
                projected.append(world)
        if len(projected) < 2:
            return None, "Não foi possível construir a superfície do gesto nesta vista."
        matrix = _gesture_matrix(projected, view_direction)
        if matrix is None:
            return None, "A direção do gesto ficou indefinida. Desenhe um traço mais longo."

        inverse = matrix.inverted_safe()
        local_projected = [inverse @ point for point in projected]
        width = abs(local_projected[-1].x - local_projected[0].x)
        unit = _calibrated_dimensions(context, target)[3]
        if self.cut_type == 'STRAIGHT':
            x_start = local_projected[0].x
            x_end = local_projected[-1].x
            profile = [[min(x_start, x_end), 0.0], [max(x_start, x_end), 0.0]]
        else:
            raw_profile = [(point.x, point.z) for point in local_projected]
            tolerance = max(width * 0.0025, unit * 0.03)
            raw_profile = cut_math.simplify_polyline(raw_profile, tolerance)
            profile = cut_math.monotonic_profile(
                raw_profile, min_step=max(width * 1e-5, unit * 0.001),
            )
            if len(profile) < 2 or profile[-1][0] - profile[0][0] <= unit * 0.1:
                return None, "A curva dobrou sobre si mesma. Faça um único movimento contínuo."

        local_stroke = [[point[0], 0.0, point[1]] for point in profile]
        seed_local = inverse @ seed_world
        layer_points = [item[0] for item in layers[:2]] if layers else [seed_world]
        local_layers = [inverse @ point for point in layer_points]
        if len(local_layers) >= 2 and abs(local_layers[1].y - local_layers[0].y) > unit * 0.02:
            low = min(local_layers[0].y, local_layers[1].y)
            high = max(local_layers[0].y, local_layers[1].y)
            thickness = high - low
            margin = max(thickness * 0.12, unit * 0.35, target.dimensions.length * 1e-5)
            depth = [low - margin, high + margin]
        else:
            fallback = max(width * 0.45, unit * 3.0, target.dimensions.length * 0.025)
            margin = max(unit * 0.35, fallback * 0.08)
            depth = [seed_local.y - margin, seed_local.y + fallback]

        return {
            "matrix": matrix,
            "profile": profile,
            "stroke": local_stroke,
            "seed": [seed_local.x, seed_local.y, seed_local.z],
            "depth": depth,
            "radius": max(width * 0.5, unit * 2.0),
        }, None

    def _create_from_gesture(self, context, target):
        data, error = self._analyze_gesture(context, target)
        if error:
            return None, error
        cut = _new_cut_record(context, self.cut_type)
        blade = create_cut_objects(context, cut, location=data["matrix"].translation)
        blade.matrix_world = data["matrix"]
        cut.profile_data = json.dumps(data["profile"])
        cut.stroke_data = json.dumps(data["stroke"])
        cut.seed_data = json.dumps(data["seed"])
        cut.depth_data = json.dumps(data["depth"])
        cut.gesture_version = 4 if cut.cut_type == 'CURVED' else 3
        cut.blade_radius = data["radius"]
        if cut.cut_type == 'CURVED':
            front, back = surface_rails_for_cut(cut, sample_count=10)
            front, back, _mapped = fit_surface_rails_to_target(
                context, cut, front, back,
            )
            store_surface_rails(cut, front, back)
        cut.status = 'READY'
        blade["cut3d_last_matrix"] = _matrix_values(_control_matrix(blade))
        restore_local_preview(cut)
        center_pin_on_cut(cut)
        return cut, None

    def _finish(self, context, cancelled=False):
        _active_stroke_2d.clear()
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        context.area.tag_redraw()

    def modal(self, context, event):
        props = context.scene.cut3d_props
        target = props.target_object
        if event.type == 'ESC':
            self._finish(context, cancelled=True)
            return {'CANCELLED'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not self._drawing:
            return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            self._drawing = True
            point = Vector((event.mouse_region_x, event.mouse_region_y))
            self._screen_points = [point]
            _active_stroke_2d.clear()
            _active_stroke_2d.append((point.x, point.y))
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE' and self._drawing:
            self._append_stroke_to(Vector((event.mouse_region_x, event.mouse_region_y)))
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self._drawing:
            self._append_stroke_to(Vector((event.mouse_region_x, event.mouse_region_y)))
            cut, error = self._create_from_gesture(context, target)
            if error:
                self.report({'WARNING'}, error)
                self._finish(context, cancelled=True)
                return {'CANCELLED'}
            bpy.ops.object.select_all(action='DESELECT')
            self._finish(context)
            self.report({'INFO'}, "Marcação local criada. A malha só será processada em Construir Peças.")
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class CUT3D_OT_edit_curved_surface(bpy.types.Operator):
    """Edit the front/back perimeter rails of a curved cutting surface."""
    bl_idname = "cut3d.edit_curved_surface"
    bl_label = "Editar Superfície Curva"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        cut = get_active_cut(props) if props else None
        return bool(
            context.area and context.area.type == 'VIEW_3D'
            and cut and cut.cut_type == 'CURVED' and not props.result_visible
        )

    def _serialize(self):
        return json.dumps({
            "front": [[point.x, point.y, point.z] for point in self._front],
            "back": [[point.x, point.y, point.z] for point in self._back],
        })

    def _load_snapshot(self, value):
        data = json.loads(value)
        self._front = [Vector(point) for point in data["front"]]
        self._back = [Vector(point) for point in data["back"]]
        self._selected = None

    def _push_undo(self):
        value = self._serialize()
        if not self._undo or self._undo[-1] != value:
            self._undo.append(value)
        self._redo.clear()

    def _redraw(self, context):
        for area in context.screen.areas if context.screen else []:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    def _update_status(self, context):
        snap = "ligado" if self._surface_snap else "desligado"
        context.workspace.status_text_set(
            "Editar perímetro  •  Arrastar: LMB  •  Girar vista: MMB  •  "
            f"Snap na malha: {snap} (S)  •  Adicionar: Ctrl+LMB  •  "
            f"Excluir: X  •  Desfazer: Ctrl+Z  •  Reset: R  •  Enter/Esc  •  "
            f"Ajustar tudo: A  •  Pontos: {len(self._front) + len(self._back)}"
        )

    def _fit_all_to_model(self, context):
        props = context.scene.cut3d_props
        cut = next((item for item in props.cuts if item.cut_id == self._cut_id), None)
        if not cut:
            return 0
        front, back, mapped = fit_surface_rails_to_target(
            context, cut, self._front, self._back,
        )
        if mapped:
            self._front, self._back = front, back
            cut.gesture_version = 4
            self._sync_preview(context)
        return mapped

    def _sync_preview(self, context):
        props = context.scene.cut3d_props
        cut = next((item for item in props.cuts if item.cut_id == self._cut_id), None)
        if cut:
            store_surface_rails(cut, self._front, self._back)
            center_pin_on_cut(cut)
        self._redraw(context)

    def _projected_controls(self, context):
        props = context.scene.cut3d_props
        cut = next((item for item in props.cuts if item.cut_id == self._cut_id), None)
        blade = bpy.data.objects.get(cut.blade_object) if cut else None
        if not blade:
            return []
        controls = []
        for rail_name, rail in (("front", self._front), ("back", self._back)):
            for index, point in enumerate(rail):
                world = _control_matrix(blade) @ point
                screen = view3d_utils.location_3d_to_region_2d(
                    context.region, context.region_data, world,
                )
                if screen is not None:
                    controls.append((rail_name, index, screen, world))
        return controls

    def _pick_control(self, context, mouse, radius=15.0):
        candidates = []
        for rail_name, index, screen, _world in self._projected_controls(context):
            distance = (screen - mouse).length
            if distance <= radius:
                candidates.append((distance, rail_name, index))
        if not candidates:
            return None
        _distance, rail_name, index = min(candidates, key=lambda item: item[0])
        return rail_name, index

    def _closest_segment(self, context, mouse):
        controls = self._projected_controls(context)
        lookup = {(rail_name, index): screen for rail_name, index, screen, _world in controls}
        candidates = []
        for rail_name, rail in (("front", self._front), ("back", self._back)):
            for index in range(len(rail) - 1):
                first = lookup.get((rail_name, index))
                second = lookup.get((rail_name, index + 1))
                if first is None or second is None:
                    continue
                delta = second - first
                length_sq = delta.length_squared
                factor = 0.0 if length_sq <= 1e-12 else (mouse - first).dot(delta) / length_sq
                factor = max(0.0, min(1.0, factor))
                nearest = first.lerp(second, factor)
                candidates.append(((nearest - mouse).length, rail_name, index, factor))
        return min(candidates, key=lambda item: item[0]) if candidates else None

    def _point_from_mouse(self, context, mouse, rail_name, index, old_local):
        props = context.scene.cut3d_props
        target = props.target_object
        cut = next((item for item in props.cuts if item.cut_id == self._cut_id), None)
        blade = bpy.data.objects.get(cut.blade_object) if cut else None
        if not target or not blade:
            return old_local.copy()
        blade_matrix = _control_matrix(blade)
        old_world = blade_matrix @ old_local
        world = None
        if self._surface_snap:
            layers = _raycast_target_layers(context, (mouse.x, mouse.y), target, limit=16)
            if layers:
                world = min((item[0] for item in layers), key=lambda point: (point - old_world).length)
            else:
                # Snap ligado significa que o ponto nunca deve escapar da pele
                # quando o cursor passa momentaneamente fora da silhueta.
                return old_local.copy()
        else:
            view_direction = view3d_utils.region_2d_to_vector_3d(
                context.region, context.region_data, (mouse.x, mouse.y),
            ).normalized()
            world = _project_to_view_plane(
                context, (mouse.x, mouse.y), old_world, view_direction,
            )
        if world is None:
            return old_local.copy()
        local = blade_matrix.inverted_safe() @ world
        rail = self._front if rail_name == 'front' else self._back
        epsilon = max(cut.unit_per_mm * 0.01, cut.blade_radius * 1e-6)
        if index > 0:
            local.x = max(local.x, rail[index - 1].x + epsilon)
        if index + 1 < len(rail):
            local.x = min(local.x, rail[index + 1].x - epsilon)
        return local

    def _add_control(self, context, mouse):
        nearest = self._closest_segment(context, mouse)
        if not nearest:
            return False
        distance, rail_name, index, factor = nearest
        if distance > 24.0:
            return False
        rail = self._front if rail_name == 'front' else self._back
        self._push_undo()
        local = rail[index].lerp(rail[index + 1], factor)
        rail.insert(index + 1, local)
        self._selected = (rail_name, index + 1)
        rail[index + 1] = self._point_from_mouse(
            context, mouse, rail_name, index + 1, rail[index + 1],
        )
        self._sync_preview(context)
        self._update_status(context)
        return True

    def invoke(self, context, event):
        global _surface_editor
        props = context.scene.cut3d_props
        cut = get_active_cut(props)
        if not cut or cut.cut_type != 'CURVED':
            return {'CANCELLED'}
        self._cut_id = cut.cut_id
        self._front, self._back = surface_rails_for_cut(cut, sample_count=10)
        if cut.gesture_version < 4:
            front, back, mapped = fit_surface_rails_to_target(
                context, cut, self._front, self._back,
            )
            if mapped:
                self._front, self._back = front, back
                cut.gesture_version = 4
        self._initial = self._serialize()
        self._undo = []
        self._redo = []
        self._selected = None
        self._dragging = False
        self._surface_snap = True
        pin = bpy.data.objects.get(cut.pin_object)
        self._pin_name = pin.name if pin else ""
        self._pin_was_hidden = bool(pin.hide_viewport) if pin else False
        if pin:
            pin.hide_viewport = True
        store_surface_rails(cut, self._front, self._back)
        _surface_editor = self
        bpy.ops.object.select_all(action='DESELECT')
        context.window.cursor_modal_set('CROSSHAIR')
        self._update_status(context)
        context.window_manager.modal_handler_add(self)
        self._redraw(context)
        return {'RUNNING_MODAL'}

    def _finish(self, context, cancelled=False):
        global _surface_editor
        props = context.scene.cut3d_props
        cut = next((item for item in props.cuts if item.cut_id == self._cut_id), None)
        if cut:
            if cancelled:
                self._load_snapshot(self._initial)
            store_surface_rails(cut, self._front, self._back)
            cut.status = 'READY'
            center_pin_on_cut(cut)
        pin = bpy.data.objects.get(getattr(self, "_pin_name", ""))
        if pin:
            pin.hide_viewport = getattr(self, "_pin_was_hidden", False)
        _surface_editor = None
        context.window.cursor_modal_restore()
        context.workspace.status_text_set(None)
        self._redraw(context)

    def modal(self, context, event):
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._finish(context)
            self.report({'INFO'}, "Superfície curva atualizada. A geometria será criada somente no Build.")
            return {'FINISHED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context, cancelled=True)
            return {'CANCELLED'}
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and not self._dragging:
            return {'PASS_THROUGH'}
        if event.type == 'S' and event.value == 'PRESS':
            self._surface_snap = not self._surface_snap
            self._update_status(context)
            return {'RUNNING_MODAL'}
        if event.type == 'Z' and event.ctrl and event.value == 'PRESS':
            if event.shift:
                if self._redo:
                    current = self._serialize()
                    if not self._undo or self._undo[-1] != current:
                        self._undo.append(current)
                    self._load_snapshot(self._redo.pop())
                    self._sync_preview(context)
            elif self._undo:
                self._redo.append(self._serialize())
                self._load_snapshot(self._undo.pop())
                self._sync_preview(context)
            return {'RUNNING_MODAL'}
        if event.type == 'R' and event.value == 'PRESS':
            self._push_undo()
            self._load_snapshot(self._initial)
            self._sync_preview(context)
            return {'RUNNING_MODAL'}
        if event.type == 'A' and event.value == 'PRESS':
            self._push_undo()
            mapped = self._fit_all_to_model(context)
            if not mapped and self._undo:
                self._undo.pop()
            self._update_status(context)
            return {'RUNNING_MODAL'}
        if event.type in {'X', 'DEL'} and event.value == 'PRESS' and self._selected:
            rail_name, index = self._selected
            rail = self._front if rail_name == 'front' else self._back
            if len(rail) > 2:
                self._push_undo()
                rail.pop(index)
                self._selected = None
                self._sync_preview(context)
                self._update_status(context)
            return {'RUNNING_MODAL'}

        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            if event.ctrl:
                self._add_control(context, mouse)
                return {'RUNNING_MODAL'}
            selected = self._pick_control(context, mouse)
            if selected:
                self._push_undo()
                self._selected = selected
                self._dragging = True
                return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE' and self._dragging and self._selected:
            rail_name, index = self._selected
            rail = self._front if rail_name == 'front' else self._back
            rail[index] = self._point_from_mouse(context, mouse, rail_name, index, rail[index])
            self._sync_preview(context)
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE' and self._dragging:
            self._dragging = False
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}


class CUT3D_OT_fit_curved_surface(bpy.types.Operator):
    """Project every curved-surface control back onto the target shell."""
    bl_idname = "cut3d.fit_curved_surface"
    bl_label = "Ajustar Superfície à Malha"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        cut = get_active_cut(props) if props else None
        return bool(cut and cut.cut_type == 'CURVED' and not props.result_visible)

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        front, back = surface_rails_for_cut(cut, sample_count=10)
        front, back, mapped = fit_surface_rails_to_target(
            context, cut, front, back,
        )
        if mapped < 2:
            self.report({'WARNING'}, "Não encontrei a casca do modelo sob essa superfície.")
            return {'CANCELLED'}
        store_surface_rails(cut, front, back)
        cut.gesture_version = 4
        center_pin_on_cut(cut)
        context.area.tag_redraw()
        self.report({'INFO'}, f"{mapped} pontos ajustados à malha.")
        return {'FINISHED'}


class CUT3D_OT_select_cut(bpy.types.Operator):
    bl_idname = "cut3d.select_cut"
    bl_label = "Selecionar Corte"
    index: bpy.props.IntProperty()

    def execute(self, context):
        props = context.scene.cut3d_props
        if 0 <= self.index < len(props.cuts):
            props.active_cut_index = self.index
            select_cut(context, props.cuts[self.index])
        return {'FINISHED'}


class CUT3D_OT_remove_draft_cut(bpy.types.Operator):
    bl_idname = "cut3d.remove_draft_cut"
    bl_label = "Remover Corte"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        return bool(props and not props.result_visible and len(props.cuts))

    def execute(self, context):
        remove_cut_item(context, context.scene.cut3d_props.active_cut_index)
        return {'FINISHED'}


class CUT3D_OT_duplicate_cut(bpy.types.Operator):
    bl_idname = "cut3d.duplicate_cut"
    bl_label = "Duplicar Corte"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = getattr(context.scene, "cut3d_props", None)
        return bool(props and not props.result_visible and get_active_cut(props))

    def execute(self, context):
        props = context.scene.cut3d_props
        source = get_active_cut(props)
        if not source:
            return {'CANCELLED'}
        blade = bpy.data.objects.get(source.blade_object)
        props.cut_counter += 1
        cut = props.cuts.add()
        cut.cut_id = uuid.uuid4().hex[:8]
        cut.name = f"Corte {props.cut_counter:02d}"
        cut.cut_type = source.cut_type
        cut.add_pin = source.add_pin
        cut.connector_type = source.connector_type
        cut.pin_radius = source.pin_radius
        cut.pin_depth = source.pin_depth
        cut.chamfer_size = source.chamfer_size
        cut.clearance = source.clearance
        cut.glue_gap = source.glue_gap
        cut.cut_gap = source.cut_gap
        cut.unit_per_mm = source.unit_per_mm
        cut.blade_radius = source.blade_radius
        props.active_cut_index = len(props.cuts) - 1
        new_blade = create_cut_objects(context, cut, blade.location + Vector((0, 0, .005)), blade.rotation_euler.copy())
        new_blade.scale = blade.scale.copy()
        cut.profile_data = source.profile_data
        cut.stroke_data = source.stroke_data
        cut.depth_data = source.depth_data
        cut.surface_data = source.surface_data
        cut.seed_data = source.seed_data
        cut.gesture_version = source.gesture_version
        restore_local_preview(cut)
        center_pin_on_cut(cut)
        cut.status = 'READY'
        return {'FINISHED'}


class CUT3D_OT_flip_pin_direction(bpy.types.Operator):
    bl_idname = "cut3d.flip_pin_direction"
    bl_label = "Trocar Lado A/B"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        if not cut:
            return {'CANCELLED'}
        cut.pin_side = 'SIDE_B' if cut.pin_side == 'SIDE_A' else 'SIDE_A'
        return {'FINISHED'}


class CUT3D_OT_select_pin(bpy.types.Operator):
    bl_idname = "cut3d.select_pin"
    bl_label = "Dimensionar Pino no Viewport"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        pin = bpy.data.objects.get(cut.pin_object) if cut else None
        if not pin:
            return {'CANCELLED'}
        center_pin_on_cut(cut)
        bpy.ops.object.select_all(action='DESELECT')
        pin.hide_select = False
        pin.hide_viewport = False
        pin.lock_location = (True, True, True)
        pin.lock_rotation = (True, True, True)
        pin.lock_scale = (False, False, False)
        pin.select_set(True)
        context.view_layer.objects.active = pin
        if context.area and context.area.type == 'VIEW_3D':
            try:
                bpy.ops.wm.tool_set_by_id(name="builtin.scale")
            except RuntimeError:
                pass
        self.report({'INFO'}, "Arraste as alças para dimensionar; S faz escala uniforme.")
        return {'FINISHED'}


class CUT3D_OT_center_pin(bpy.types.Operator):
    bl_idname = "cut3d.center_pin"
    bl_label = "Centralizar Pino"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        if cut:
            center_pin_on_cut(cut)
        return {'FINISHED'}


class CUT3D_OT_nudge_height(bpy.types.Operator):
    bl_idname = "cut3d.nudge_height"
    bl_label = "Deslocar Corte"
    bl_options = {'REGISTER', 'UNDO'}
    delta: bpy.props.FloatProperty(default=0.005)

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        blade = bpy.data.objects.get(cut.blade_object) if cut else None
        if blade:
            normal = (_control_matrix(blade).to_3x3() @ Vector((0, 0, 1))).normalized()
            # A interface informa milímetros; convertemos para a escala real do STL.
            blade.location += normal * self.delta * cut.unit_per_mm
            _sync_cut_objects(cut)
        return {'FINISHED'}


class CUT3D_OT_set_preset_orientation(bpy.types.Operator):
    bl_idname = "cut3d.set_preset_orientation"
    bl_label = "Alinhar Corte"
    bl_options = {'REGISTER', 'UNDO'}
    axis: bpy.props.StringProperty(default="XY")

    def execute(self, context):
        cut = get_active_cut(context.scene.cut3d_props)
        blade = bpy.data.objects.get(cut.blade_object) if cut else None
        if blade:
            rotations = {'XY': (0, 0, 0), 'XZ': (math.pi / 2, 0, 0), 'YZ': (0, math.pi / 2, 0)}
            blade.rotation_euler = Euler(rotations.get(self.axis, (0, 0, 0)), 'XYZ')
            _sync_cut_objects(cut)
        return {'FINISHED'}


class CUT3D_OT_place_cut_interactive(bpy.types.Operator):
    """Posiciona o corte sob o mouse e orienta-o pela superfície do modelo"""
    bl_idname = "cut3d.place_cut_interactive"
    bl_label = "Posicionar no Modelo"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D' or not get_active_cut(context.scene.cut3d_props):
            return {'CANCELLED'}
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set("Clique: posicionar  •  Shift: manter orientação  •  Esc: cancelar")
        self._original_matrix = _control_matrix(
            bpy.data.objects[get_active_cut(context.scene.cut3d_props).blade_object]
        )
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        cut = get_active_cut(context.scene.cut3d_props)
        blade = bpy.data.objects.get(cut.blade_object) if cut else None
        target = context.scene.cut3d_props.target_object
        if not blade or not target:
            return {'CANCELLED'}
        if event.type == 'ESC':
            blade.matrix_world = self._original_matrix
            _sync_cut_objects(cut)
            context.workspace.status_text_set(None)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            _sync_cut_objects(cut)
            context.workspace.status_text_set(None)
            cut.status = 'READY'
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            coord = (event.mouse_region_x, event.mouse_region_y)
            hit = _raycast_target_coord(context, coord, target)
            if hit:
                location, _normal, _direction = hit
                seed_world = _control_matrix(blade) @ _json_vector(cut.seed_data)
                blade.location += location - seed_world
                _sync_cut_objects(cut)
            context.area.tag_redraw()
        return {'RUNNING_MODAL'}
