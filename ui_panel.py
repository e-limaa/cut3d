import bpy

from . import draft_engine
from .properties import get_active_cut


class CUT3D_OT_apply_transforms_quick(bpy.types.Operator):
    bl_idname = "cut3d.apply_transforms_quick"
    bl_label = "Aplicar Escala e Rotação"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        target = context.scene.cut3d_props.target_object or context.active_object
        if not target:
            return {'CANCELLED'}
        bpy.ops.object.select_all(action='DESELECT')
        target.select_set(True)
        context.view_layer.objects.active = target
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        return {'FINISHED'}


class CUT3D_OT_select_active_as_target(bpy.types.Operator):
    bl_idname = "cut3d.select_active_as_target"
    bl_label = "Usar Objeto Selecionado"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'MESH' and not obj.get("cut3d_role") and not obj.get("cut3d_output"):
            context.scene.cut3d_props.target_object = obj
            self.report({'INFO'}, f"Modelo alvo: {obj.name}")
            return {'FINISHED'}
        self.report({'WARNING'}, "Selecione a malha ou peça que deseja cortar.")
        return {'CANCELLED'}


class CUT3D_UL_cuts(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        cut = item
        row = layout.row(align=True)
        row.prop(cut, "enabled", text="", icon='HIDE_OFF' if cut.enabled else 'HIDE_ON', emboss=False)
        select = row.operator(
            "cut3d.select_cut",
            text=cut.name,
            icon='CURVE_BEZCURVE' if cut.cut_type == 'CURVED' else 'IPO_LINEAR',
            emboss=False,
        )
        select.index = index
        row.label(text="", icon='CHECKMARK' if cut.status == 'READY' else 'ERROR')
        if cut.add_pin:
            row.label(text=cut.pin_side[-1], icon='PINNED')


def _draw_target(layout, props):
    box = layout.box()
    row = box.row(align=True)
    row.label(text="MODELO", icon='OBJECT_DATA')
    if props.target_object:
        row.label(text=props.target_object.name, icon='CHECKMARK')
    select = box.row(align=True)
    select.prop(props, "target_object", text="")
    select.operator("cut3d.select_active_as_target", text="", icon='EYEDROPPER')
    target = props.target_object
    if target and any(abs(value - 1.0) > 0.001 for value in target.scale):
        warning = box.row()
        warning.alert = True
        warning.operator("cut3d.apply_transforms_quick", text="Corrigir escala do original", icon='ERROR')


def _draw_cut_tools(layout, props):
    box = layout.box()
    box.label(text="NOVO CORTE", icon='ADD')
    box.label(text="Marque agora; a geometria será criada só no Build", icon='MOUSE_LMB')
    row = box.row(align=True)
    row.scale_y = 1.25
    straight = row.operator("cut3d.add_cut", text="Reto", icon='IPO_LINEAR')
    straight.cut_type = 'STRAIGHT'
    curved = row.operator("cut3d.add_cut", text="Curvo", icon='CURVE_BEZCURVE')
    curved.cut_type = 'CURVED'


def _draw_cut_list(layout, props):
    box = layout.box()
    header = box.row()
    header.label(text=f"PLANO DE CORTES  ·  {len(props.cuts)}", icon='OUTLINER_COLLECTION')
    box.template_list("CUT3D_UL_cuts", "", props, "cuts", props, "active_cut_index", rows=max(2, min(5, len(props.cuts))))
    row = box.row(align=True)
    row.operator("cut3d.duplicate_cut", text="Duplicar", icon='DUPLICATE')
    row.operator("cut3d.remove_draft_cut", text="Remover", icon='TRASH')


def _draw_active_cut(layout, props):
    if props.result_visible:
        result = layout.box()
        result.label(text="RESULTADO CONSTRUÍDO", icon='CHECKMARK')
        if props.last_build_piece_count:
            result.label(text=f"{props.last_build_piece_count} peças · {props.last_build_cut_count} cortes aplicados")
        if props.last_build_new_separations > 0:
            result.label(text=f"{props.last_build_new_separations} nova(s) separação(ões)", icon='MOD_EXPLODE')
        elif props.last_build_piece_count:
            warning = result.column(align=True)
            warning.alert = True
            warning.label(text="Nenhuma peça nova foi solta", icon='ERROR')
            warning.label(text="Existe outra ligação física na malha")
        if props.cuts:
            result.label(text="O planejamento está guardado e editável.")
        else:
            result.label(text="As marcas foram removidas; volte para recomeçar.", icon='INFO')
        result.operator("cut3d.restore_draft", text="Voltar e editar marcas", icon='LOOP_BACK')
        return
    cut = get_active_cut(props)
    if not cut:
        hint = layout.box()
        hint.label(text="Adicione um corte para começar", icon='INFO')
        return
    box = layout.box()
    header = box.row(align=True)
    header.prop(cut, "name", text="", icon='CURVE_BEZCURVE' if cut.cut_type == 'CURVED' else 'IPO_LINEAR')
    header.label(text="PRONTO", icon='CHECKMARK')

    place = box.column(align=True)
    place.scale_y = 1.2
    place.operator("cut3d.place_cut_interactive", text="Reposicionar marca", icon='RESTRICT_SELECT_OFF')
    if cut.cut_type == 'CURVED':
        place.operator(
            "cut3d.edit_curved_surface",
            text="Editar superfície ponto a ponto",
            icon='EDITMODE_HLT',
        )
        place.operator(
            "cut3d.fit_curved_surface",
            text="Ajustar todos os pontos à malha",
            icon='SNAP_ON',
        )
        hint = box.column(align=True)
        hint.label(text="Frente e verso independentes · gire a câmera", icon='INFO')
        hint.label(text="Pontos aderem à pele · A reajusta todos")
        hint.label(text="Ctrl+clique adiciona ponto · X remove")
    row = place.row(align=True)
    row.operator("cut3d.select_pin", text="Dimensionar pino", icon='PINNED')
    pin_hint = box.row()
    pin_hint.label(text="Arraste as alças · S escala uniforme", icon='FULLSCREEN_ENTER')

    orient = box.row(align=True)
    for label, axis in (("Topo", 'XY'), ("Frente", 'XZ'), ("Lado", 'YZ')):
        operator = orient.operator("cut3d.set_preset_orientation", text=label)
        operator.axis = axis
    nudge = box.row(align=True)
    down = nudge.operator("cut3d.nudge_height", text="− 1 mm")
    down.delta = -1.0
    up = nudge.operator("cut3d.nudge_height", text="+ 1 mm")
    up.delta = 1.0

    box.separator()
    box.prop(cut, "add_pin", text="Adicionar encaixe")
    if cut.add_pin:
        row = box.row(align=True)
        row.prop(cut, "connector_type", text="")
        row.prop(cut, "connector_size", text="")
        side = box.row(align=True)
        side.prop(cut, "pin_side", expand=True)
        side.operator("cut3d.flip_pin_direction", text="Trocar", icon='ARROW_LEFTRIGHT')
        box.prop(cut, "clearance", text="Folga do encaixe")

    advanced = box.row()
    advanced.prop(props, "show_advanced", icon='TRIA_DOWN' if props.show_advanced else 'TRIA_RIGHT', emboss=False)
    if props.show_advanced:
        column = box.column(align=True)
        if cut.add_pin:
            column.prop(cut, "pin_radius")
            column.prop(cut, "pin_depth")
            column.prop(cut, "chamfer_size")
            column.prop(cut, "glue_gap")
        column.prop(cut, "cut_gap")
        column.operator("cut3d.center_pin", text="Centralizar pino", icon='PIVOT_CURSOR')


def _draw_build(layout, props):
    if props.result_visible:
        return
    options = layout.box()
    options.prop(props, "keep_original", text="Preservar modelo original", icon='DUPLICATE')
    options.prop(props, "material_preset", text="Material")

    build = layout.column(align=True)
    build.scale_y = 1.7
    build.enabled = bool(props.target_object and any(c.enabled for c in props.cuts))
    build.operator("cut3d.execute_cut", text="BUILD DRAFT · CONSTRUIR PEÇAS", icon='MOD_BOOLEAN')
    restore = layout.row()
    restore.operator("cut3d.restore_draft", text="Voltar ao planejamento", icon='LOOP_BACK')


def _draw_easy_mode(layout, props):
    _draw_target(layout, props)
    if props.result_visible:
        _draw_active_cut(layout, props)
        return
    if not props.cuts:
        hero = layout.box()
        hero.label(text="1. Escolha e desenhe sobre o modelo", icon='MOUSE_LMB')
        row = hero.row(align=True)
        row.scale_y = 1.5
        straight = row.operator("cut3d.add_cut", text="Corte reto", icon='IPO_LINEAR')
        straight.cut_type = 'STRAIGHT'
        curved = row.operator("cut3d.add_cut", text="Corte curvo", icon='CURVE_BEZCURVE')
        curved.cut_type = 'CURVED'
        return
    _draw_active_cut(layout, props)
    _draw_build(layout, props)


class VIEW3D_PT_cut3d_main(bpy.types.Panel):
    bl_label = "Cut3D"
    bl_idname = "VIEW3D_PT_cut3d_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Cut3D'

    def draw_header(self, context):
        self.layout.label(text="", icon='MOD_BOOLEAN')

    def draw(self, context):
        layout = self.layout
        props = context.scene.cut3d_props

        mode = layout.row(align=True)
        mode.scale_y = 1.35
        mode.prop(props, "workflow_mode", expand=True)
        layout.separator()

        if props.result_visible:
            _draw_target(layout, props)
            _draw_active_cut(layout, props)
            return

        if props.workflow_mode == 'EASY':
            _draw_easy_mode(layout, props)
        else:
            _draw_target(layout, props)
            _draw_cut_tools(layout, props)
            if props.cuts:
                _draw_cut_list(layout, props)
            _draw_active_cut(layout, props)
            _draw_build(layout, props)


class VIEW3D_PT_cut3d_export(bpy.types.Panel):
    bl_label = "Exportar para impressão"
    bl_idname = "VIEW3D_PT_cut3d_export"
    bl_parent_id = "VIEW3D_PT_cut3d_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Cut3D'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props = context.scene.cut3d_props
        layout.prop(props, "export_format")
        layout.prop(props, "export_path")
        layout.prop(props, "auto_center_for_printing")
        row = layout.row(align=True)
        row.scale_y = 1.25
        row.operator("cut3d.export_parts", text="Exportar peças", icon='EXPORT')
        row.operator("cut3d.open_export_folder", text="", icon='FILE_FOLDER')
