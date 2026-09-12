import os
import subprocess
import bpy
from mathutils import Matrix, Vector


def _has_operator(submodule, op_name):
    """Safely check if an operator is actually registered and callable in Blender."""
    try:
        rna_name = f"{submodule.upper()}_OT_{op_name}"
        return hasattr(bpy.types, rna_name)
    except Exception:
        return False


def _center_object_on_bed(obj):
    """
    Translates the object so its bounding box center is at (0, 0)
    and its lowest vertex/boundary sits exactly on the bed at Z = 0.0.
    Returns the original world matrix to restore after export.
    """
    orig_matrix = obj.matrix_world.copy()
    world_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_x = min(c.x for c in world_corners)
    max_x = max(c.x for c in world_corners)
    min_y = min(c.y for c in world_corners)
    max_y = max(c.y for c in world_corners)
    min_z = min(c.z for c in world_corners)

    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5

    offset = Vector((-center_x, -center_y, -min_z))
    obj.matrix_world.translation += offset
    return orig_matrix


class CUT3D_OT_export_parts(bpy.types.Operator):
    """Exporta todas as peças cortadas em lote para a pasta selecionada"""
    bl_idname = "cut3d.export_parts"
    bl_label = "Exportar Todas as Peças"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.cut3d_props
        export_dir = bpy.path.abspath(props.export_path)

        if not export_dir or not os.path.exists(export_dir):
            if bpy.data.filepath:
                export_dir = os.path.dirname(bpy.path.abspath(bpy.data.filepath))
            else:
                export_dir = os.path.expanduser("~\\Downloads")

        os.makedirs(export_dir, exist_ok=True)

        # Encontra objetos para exportar (selecionados ou da coleção de corte)
        target_objs = [
            obj for obj in context.selected_objects
            if obj.type == 'MESH' and obj.get("cut3d_output")
        ]

        if not target_objs:
            for col in bpy.data.collections:
                if "_Cut3D_Parts" in col.name:
                    target_objs.extend([
                        obj for obj in col.objects
                        if obj.type == 'MESH' and obj.get("cut3d_output")
                    ])

        if not target_objs:
            self.report({'WARNING'}, "Nenhuma peça selecionada para exportação.")
            return {'CANCELLED'}

        exported_files = []
        warnings = []
        fmt = props.export_format

        for obj in target_objs:
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            context.view_layer.objects.active = obj

            orig_matrix = None
            if props.auto_center_for_printing:
                orig_matrix = _center_object_on_bed(obj)
                context.view_layer.update()

            file_name = f"{obj.name}.{fmt.lower()}"
            file_path = os.path.join(export_dir, file_name)

            try:
                if fmt == 'STL':
                    if _has_operator("wm", "stl_export"):
                        bpy.ops.wm.stl_export(filepath=file_path, export_selected_objects=True)
                    elif _has_operator("export_mesh", "stl"):
                        bpy.ops.export_mesh.stl(filepath=file_path, use_selection=True)
                    elif hasattr(bpy.ops.wm, "stl_export"):
                        bpy.ops.wm.stl_export(filepath=file_path, export_selected_objects=True)
                    exported_files.append(file_name)

                elif fmt == 'OBJ':
                    if _has_operator("wm", "obj_export"):
                        bpy.ops.wm.obj_export(filepath=file_path, export_selected_objects=True)
                    elif _has_operator("export_scene", "obj"):
                        bpy.ops.export_scene.obj(filepath=file_path, use_selection=True)
                    elif hasattr(bpy.ops.wm, "obj_export"):
                        bpy.ops.wm.obj_export(filepath=file_path, export_selected_objects=True)
                    exported_files.append(file_name)

                elif fmt == '3MF':
                    has_3mf = (
                        _has_operator("wm", "threemf_export")
                        or _has_operator("export_mesh", "threemf")
                    )
                    exported = False
                    if has_3mf:
                        try:
                            if _has_operator("wm", "threemf_export"):
                                bpy.ops.wm.threemf_export(filepath=file_path, export_selected_objects=True)
                            else:
                                bpy.ops.export_mesh.threemf(filepath=file_path, use_selection=True)
                            exported = True
                            exported_files.append(file_name)
                        except Exception:
                            exported = False

                    if not exported:
                        fallback_name = f"{obj.name}.stl"
                        fallback_path = os.path.join(export_dir, fallback_name)
                        if _has_operator("wm", "stl_export"):
                            bpy.ops.wm.stl_export(filepath=fallback_path, export_selected_objects=True)
                        elif _has_operator("export_mesh", "stl"):
                            bpy.ops.export_mesh.stl(filepath=fallback_path, use_selection=True)
                        elif hasattr(bpy.ops.wm, "stl_export"):
                            bpy.ops.wm.stl_export(filepath=fallback_path, export_selected_objects=True)
                        exported_files.append(fallback_name)
                        warnings.append(
                            f"{obj.name}: 3MF nativo indisponível no Blender; exportado como STL para compatibilidade."
                        )

            except Exception as e:
                self.report({'ERROR'}, f"Erro ao exportar {obj.name}: {str(e)}")
            finally:
                if orig_matrix is not None:
                    obj.matrix_world = orig_matrix
                    context.view_layer.update()

        for obj in target_objs:
            obj.select_set(True)

        msg = f"{len(exported_files)} peça(s) exportada(s) para: {export_dir}"
        if warnings:
            self.report({'WARNING'}, f"{msg} (Nota: {warnings[0]})")
        else:
            self.report({'INFO'}, msg)
        return {'FINISHED'}


class CUT3D_OT_lay_flat_on_bed(bpy.types.Operator):
    """Assenta a peça selecionada diretamente na mesa (Z=0) centrada"""
    bl_idname = "cut3d.lay_flat_on_bed"
    bl_label = "Assentar na Mesa"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return bool(context.active_object and context.active_object.type == 'MESH')

    def execute(self, context):
        obj = context.active_object
        _center_object_on_bed(obj)
        context.view_layer.update()
        self.report({'INFO'}, f"Peça '{obj.name}' assentada em Z = 0 e centrada.")
        return {'FINISHED'}


class CUT3D_OT_open_export_folder(bpy.types.Operator):
    """Abre a pasta de exportação no Explorador de Arquivos do Windows"""
    bl_idname = "cut3d.open_export_folder"
    bl_label = "Abrir Pasta"
    bl_options = {'REGISTER'}

    def execute(self, context):
        props = context.scene.cut3d_props
        export_dir = bpy.path.abspath(props.export_path)
        if not export_dir or not os.path.exists(export_dir):
            if bpy.data.filepath:
                export_dir = os.path.dirname(bpy.path.abspath(bpy.data.filepath))
            else:
                export_dir = os.path.expanduser("~\\Downloads")

        if os.path.exists(export_dir):
            os.startfile(export_dir)
        return {'FINISHED'}
