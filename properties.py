import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import PropertyGroup


CONNECTOR_ITEMS = [
    ('CYLINDER', "Cilindro", "Encaixe redondo de montagem simples", 'MESH_CYLINDER', 0),
    ('SQUARE', "Quadrado", "Encaixe antirrotação", 'MESH_CUBE', 1),
    ('HEXAGON', "Sextavado", "Encaixe rígido de seis faces", 'MESH_ICOSPHERE', 2),
    ('DOVETAIL', "Rabo de andorinha", "Encaixe deslizante", 'MOD_LATTICE', 3),
]


def _refresh_cut(self, context):
    if not context or not getattr(context.scene, "cut3d_props", None):
        return
    try:
        from . import draft_engine
        draft_engine.refresh_cut_preview(self, context)
    except (AttributeError, ReferenceError):
        pass


def update_connector_size(self, context):
    unit = max(self.unit_per_mm, 0.000001)
    presets = {
        'SMALL': (2.5 * unit, 6.0 * unit, 0.7 * unit),
        'MEDIUM': (3.5 * unit, 8.0 * unit, 1.0 * unit),
        'LARGE': (5.0 * unit, 12.0 * unit, 1.3 * unit),
    }
    values = presets.get(self.connector_size)
    if values:
        self.pin_radius, self.pin_depth, self.chamfer_size = values
    _refresh_cut(self, context)


def update_material_preset(self, context):
    values = {
        'PLA': 0.00025,
        'PETG': 0.00022,
        'ABS': 0.00020,
        'RESIN': 0.00010,
        'LOOSE': 0.00035,
    }
    if self.material_preset in values:
        self.default_clearance = values[self.material_preset]
        clearance_mm = values[self.material_preset] * 1000.0
        props = getattr(context.scene, "cut3d_props", None) if context else None
        if props:
            for cut in props.cuts:
                cut.clearance = clearance_mm * max(cut.unit_per_mm, 0.000001)


class Cut3D_CutItem(PropertyGroup):
    cut_id: StringProperty(name="ID")
    name: StringProperty(name="Nome", default="Corte")
    cut_type: EnumProperty(
        name="Tipo",
        items=[
            ('STRAIGHT', "Reto", "Plano de corte reto", 'IPO_LINEAR', 0),
            ('CURVED', "Curvo", "Superfície criada a partir de uma linha desenhada", 'CURVE_BEZCURVE', 1),
        ],
        default='STRAIGHT',
    )
    enabled: BoolProperty(name="Ativo", default=True, update=_refresh_cut)
    status: EnumProperty(
        name="Estado",
        items=[
            ('EDITING', "Editando", "O corte ainda está sendo posicionado", 'GREASEPENCIL', 0),
            ('READY', "Pronto", "Corte pronto para construir", 'CHECKMARK', 1),
            ('WARNING', "Verificar", "O corte precisa de atenção", 'ERROR', 2),
        ],
        default='EDITING',
    )
    blade_object: StringProperty(name="Objeto do corte")
    visual_object: StringProperty(name="Indicador visual")
    pin_object: StringProperty(name="Objeto do pino")
    curve_object: StringProperty(name="Objeto da curva")
    profile_data: StringProperty(name="Perfil interno", default="")
    stroke_data: StringProperty(name="Traço local", default="")
    surface_data: StringProperty(
        name="Superfície curva editável",
        description="Bordas locais frontal e traseira usadas pelo editor ponto a ponto",
        default="",
    )
    depth_data: StringProperty(
        name="Profundidade local",
        description="Limites locais frente/fundo da peça atingida pelo gesto",
        default="",
    )
    seed_data: StringProperty(
        name="Ponto alvo",
        description="Ponto local que identifica a peça/ramo escolhido pelo gesto",
        default="",
    )
    gesture_version: IntProperty(name="Versão do gesto", default=4, min=1)
    unit_per_mm: FloatProperty(name="Escala interna por mm", default=0.001, min=0.000001)
    blade_radius: FloatProperty(name="Área do corte", default=0.08, min=0.005, unit='LENGTH')

    add_pin: BoolProperty(name="Adicionar pino", default=True, update=_refresh_cut)
    connector_type: EnumProperty(
        name="Formato",
        items=CONNECTOR_ITEMS,
        default='CYLINDER',
        update=_refresh_cut,
    )
    connector_size: EnumProperty(
        name="Tamanho",
        items=[
            ('SMALL', "P", "Pino pequeno", 0),
            ('MEDIUM', "M", "Pino médio", 1),
            ('LARGE', "G", "Pino grande", 2),
            ('CUSTOM', "Personalizado", "Dimensões manuais", 3),
        ],
        default='MEDIUM',
        update=update_connector_size,
    )
    pin_radius: FloatProperty(
        name="Raio / largura",
        default=0.0035,
        min=0.0005,
        max=1000.0,
        precision=4,
        unit='LENGTH',
        update=_refresh_cut,
    )
    pin_depth: FloatProperty(
        name="Comprimento",
        default=0.008,
        min=0.001,
        max=2000.0,
        precision=4,
        unit='LENGTH',
        update=_refresh_cut,
    )
    chamfer_size: FloatProperty(
        name="Chanfro guia",
        default=0.001,
        min=0.0,
        max=500.0,
        precision=4,
        unit='LENGTH',
        update=_refresh_cut,
    )
    pin_side: EnumProperty(
        name="Pino no lado",
        items=[
            ('SIDE_A', "A", "Pino macho no lado positivo do corte", 'TRIA_UP', 0),
            ('SIDE_B', "B", "Pino macho no lado negativo do corte", 'TRIA_DOWN', 1),
        ],
        default='SIDE_A',
        update=_refresh_cut,
    )
    clearance: FloatProperty(
        name="Folga",
        default=0.00025,
        min=0.0,
        max=100.0,
        precision=5,
        unit='LENGTH',
    )
    glue_gap: FloatProperty(
        name="Folga para cola",
        default=0.0005,
        min=0.0,
        max=100.0,
        precision=4,
        unit='LENGTH',
    )
    cut_gap: FloatProperty(
        name="Abertura do corte",
        description="Material removido entre as duas partes",
        default=0.0,
        min=0.0,
        max=100.0,
        precision=5,
        unit='LENGTH',
    )


class Cut3D_Properties(PropertyGroup):
    target_object: PointerProperty(
        name="Modelo alvo",
        type=bpy.types.Object,
        description="Modelo que será dividido",
    )
    workflow_mode: EnumProperty(
        name="Modo",
        items=[
            ('EASY', "Modo Fácil", "Um corte com o menor número de etapas", 'LIGHT', 0),
            ('DRAFT', "Modo Rascunho", "Planeje e edite vários cortes antes de construir", 'GREASEPENCIL', 1),
        ],
        default='DRAFT',
    )
    cuts: CollectionProperty(type=Cut3D_CutItem)
    active_cut_index: IntProperty(name="Corte ativo", default=-1)
    cut_counter: IntProperty(default=0)
    result_visible: BoolProperty(
        name="Resultado construído",
        description="Separa visualmente o resultado pesado do modo de planejamento",
        default=False,
    )
    last_build_piece_count: IntProperty(name="Peças no último Build", default=0, min=0)
    last_build_source_components: IntProperty(name="Ilhas antes do Build", default=0, min=0)
    last_build_new_separations: IntProperty(name="Novas separações", default=0, min=0)
    last_build_cut_count: IntProperty(name="Cortes aplicados", default=0, min=0)

    material_preset: EnumProperty(
        name="Material",
        items=[
            ('PLA', "PLA · 0,25 mm", "Folga recomendada para PLA", 0),
            ('PETG', "PETG · 0,22 mm", "Folga recomendada para PETG", 1),
            ('ABS', "ABS/ASA · 0,20 mm", "Folga recomendada para ABS e ASA", 2),
            ('RESIN', "Resina · 0,10 mm", "Folga recomendada para resina", 3),
            ('LOOSE', "Encaixe solto · 0,35 mm", "Montagem com pouca resistência", 4),
            ('CUSTOM', "Personalizado", "Defina a folga em cada corte", 5),
        ],
        default='PLA',
        update=update_material_preset,
    )
    default_clearance: FloatProperty(
        name="Folga padrão",
        default=0.00025,
        min=0.0,
        max=0.003,
        precision=5,
        unit='LENGTH',
    )
    keep_original: BoolProperty(
        name="Preservar original",
        description="Mantém a malha original intacta e cria novas peças",
        default=True,
    )
    apply_transforms_before_cut: BoolProperty(
        name="Normalizar transformações nas cópias",
        default=True,
    )
    show_advanced: BoolProperty(name="Ajustes avançados", default=False)
    show_export: BoolProperty(name="Exportação", default=False)

    export_format: EnumProperty(
        name="Formato",
        items=[
            ('STL', "STL", "Formato padrão para fatiadores", 'FILE', 0),
            ('3MF', "3MF", "Formato moderno com unidades", 'FILE', 1),
            ('OBJ', "OBJ", "Formato Wavefront", 'FILE', 2),
        ],
        default='STL',
    )
    export_path: StringProperty(name="Pasta", default="", subtype='DIR_PATH')
    auto_center_for_printing: BoolProperty(name="Centralizar na mesa", default=True)


def get_active_cut(props):
    if 0 <= props.active_cut_index < len(props.cuts):
        return props.cuts[props.active_cut_index]
    return None
