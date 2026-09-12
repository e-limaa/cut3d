"""Valida atualização sobre um submódulo antigo mantido no cache do Blender."""
import importlib
import sys

import bpy

sys.path.insert(0, r"C:\Users\dulim\Downloads\Addon-cut3D\Cut3D_addon.zip")
import Cut3D

# Simula uma ativação que deixou todas as classes registradas antes de falhar.
Cut3D.register()
delattr(Cut3D.draft_engine, "depsgraph_preview_update")
Cut3D = importlib.reload(Cut3D)
assert hasattr(Cut3D.draft_engine, "depsgraph_preview_update")
assert Cut3D.bl_info["version"] == (4, 3, 15)
Cut3D.register()
assert Cut3D.draft_engine.depsgraph_preview_update in bpy.app.handlers.depsgraph_update_post
Cut3D.unregister()
print("CUT3D_HOT_RELOAD_OK")
