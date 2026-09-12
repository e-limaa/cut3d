bl_info = {
    "name": "Cut3D — Corte & Pinos para Impressão 3D",
    "author": "Antigravity & Dulim",
    "version": (4, 3, 15),
    "blender": (3, 6, 0),
    "location": "View3D > Barra Lateral (N) > Aba Cut3D",
    "description": "Cortes locais por gesto, superfície curva editável, Build Draft, encaixes e exportação para impressão 3D.",
    "warning": "",
    "doc_url": "",
    "category": "3D View",
}

import importlib
import bpy
from . import properties
from . import connectors
from . import cut_math
from . import draft_engine
from . import cutter_engine
from . import ui_panel
from . import exporter

# O Blender preserva submódulos em memória ao instalar um ZIP sobre uma versão
# já carregada. Recarregá-los evita misturar o __init__ novo com engines antigas.
properties = importlib.reload(properties)
connectors = importlib.reload(connectors)
cut_math = importlib.reload(cut_math)
draft_engine = importlib.reload(draft_engine)
cutter_engine = importlib.reload(cutter_engine)
ui_panel = importlib.reload(ui_panel)
exporter = importlib.reload(exporter)


classes = (
    properties.Cut3D_CutItem,
    properties.Cut3D_Properties,
    
    # Operadores Draft
    draft_engine.CUT3D_OT_add_cut,
    draft_engine.CUT3D_OT_remove_draft_cut,
    draft_engine.CUT3D_OT_select_cut,
    draft_engine.CUT3D_OT_duplicate_cut,
    draft_engine.CUT3D_OT_flip_pin_direction,
    draft_engine.CUT3D_OT_select_pin,
    draft_engine.CUT3D_OT_center_pin,
    draft_engine.CUT3D_OT_nudge_height,
    draft_engine.CUT3D_OT_set_preset_orientation,
    draft_engine.CUT3D_OT_place_cut_interactive,
    draft_engine.CUT3D_OT_edit_curved_surface,
    draft_engine.CUT3D_OT_fit_curved_surface,
    
    # Operadores de Corte
    cutter_engine.CUT3D_OT_execute_cut,
    cutter_engine.CUT3D_OT_restore_draft,
    
    # Operadores UI e utilidades
    ui_panel.CUT3D_OT_apply_transforms_quick,
    ui_panel.CUT3D_OT_select_active_as_target,
    ui_panel.CUT3D_UL_cuts,
    ui_panel.VIEW3D_PT_cut3d_main,
    ui_panel.VIEW3D_PT_cut3d_export,
    
    # Exportador
    exporter.CUT3D_OT_export_parts,
    exporter.CUT3D_OT_open_export_folder,
)


def register():
    # Recupera instalações que falharam depois de registrar apenas parte do addon.
    if hasattr(bpy.types.Scene, "cut3d_props"):
        del bpy.types.Scene.cut3d_props
    for cls in reversed(classes):
        stale_class = getattr(bpy.types, cls.__name__, None)
        if stale_class is not None:
            try:
                bpy.utils.unregister_class(stale_class)
            except (RuntimeError, ValueError):
                pass
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.cut3d_props = bpy.props.PointerProperty(type=properties.Cut3D_Properties)
    if draft_engine.depsgraph_preview_update not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(draft_engine.depsgraph_preview_update)
    draft_engine.register_draw_handler()
    # Migração visual: elimina os aros criados pelas versões 2.0/2.0.1.
    try:
        draft_engine.cleanup_legacy_previews(bpy.context)
        draft_engine.migrate_surface_previews(bpy.context)
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    if not bpy.app.timers.is_registered(draft_engine.deferred_migrate_surface_previews):
        bpy.app.timers.register(draft_engine.deferred_migrate_surface_previews, first_interval=0.1)


def unregister():
    draft_engine.unregister_draw_handler()
    if draft_engine.depsgraph_preview_update in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(draft_engine.depsgraph_preview_update)
    if bpy.app.timers.is_registered(draft_engine._flush_dirty_previews):
        bpy.app.timers.unregister(draft_engine._flush_dirty_previews)
    if bpy.app.timers.is_registered(draft_engine.deferred_migrate_surface_previews):
        bpy.app.timers.unregister(draft_engine.deferred_migrate_surface_previews)
    if hasattr(bpy.types.Scene, "cut3d_props"):
        del bpy.types.Scene.cut3d_props
    for cls in reversed(classes):
        registered_class = getattr(bpy.types, cls.__name__, None)
        if registered_class is not None:
            try:
                bpy.utils.unregister_class(registered_class)
            except (RuntimeError, ValueError):
                pass


if __name__ == "__main__":
    register()
