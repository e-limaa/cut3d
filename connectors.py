import bpy
import bmesh
import math
from mathutils import Vector, Matrix


def build_cylinder_bmesh(bm, radius, height, chamfer, base_extension=0.001, top_extension=0.0):
    """
    Gera um cilindro com chanfro na ponta superior e extensão na base para união booleana perfeita.
    """
    segments = 32
    # Garante que o chanfro não exceda as dimensões
    safe_chamfer = max(0.0, min(chamfer, height * 0.45, radius * 0.45))
    
    z_base = -base_extension
    z_chamfer_start = height - safe_chamfer
    z_top = height + top_extension
    r_top = radius - safe_chamfer if safe_chamfer > 0 else radius

    # 1. Base (z_base)
    base_verts = [
        bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                      radius * math.sin(i * 2 * math.pi / segments),
                      z_base))
        for i in range(segments)
    ]
    
    # 2. Corpo antes do chanfro (z_chamfer_start)
    if safe_chamfer > 0:
        mid_verts = [
            bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                          radius * math.sin(i * 2 * math.pi / segments),
                          z_chamfer_start))
            for i in range(segments)
        ]
        # 3. Topo chanfrado (z_top)
        top_verts = [
            bm.verts.new((r_top * math.cos(i * 2 * math.pi / segments),
                          r_top * math.sin(i * 2 * math.pi / segments),
                          z_top))
            for i in range(segments)
        ]
    else:
        mid_verts = None
        top_verts = [
            bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                          radius * math.sin(i * 2 * math.pi / segments),
                          z_top))
            for i in range(segments)
        ]

    # Preenche a face da base (apontando para baixo)
    bm.faces.new(reversed(base_verts))

    # Cria faces laterais do corpo
    if mid_verts:
        for i in range(segments):
            next_i = (i + 1) % segments
            bm.faces.new([base_verts[i], base_verts[next_i], mid_verts[next_i], mid_verts[i]])
        # Cria faces do chanfro
        for i in range(segments):
            next_i = (i + 1) % segments
            bm.faces.new([mid_verts[i], mid_verts[next_i], top_verts[next_i], top_verts[i]])
    else:
        for i in range(segments):
            next_i = (i + 1) % segments
            bm.faces.new([base_verts[i], base_verts[next_i], top_verts[next_i], top_verts[i]])

    # Preenche a face do topo
    bm.faces.new(top_verts)


def build_cube_bmesh(bm, radius, height, chamfer, base_extension=0.001, top_extension=0.0):
    """
    Gera um prisma quadrado com chanfro superior.
    """
    safe_chamfer = max(0.0, min(chamfer, height * 0.45, radius * 0.45))
    z_base = -base_extension
    z_top = height + top_extension
    r = radius
    r_top = r - safe_chamfer if safe_chamfer > 0 else r
    z_chamfer = height - safe_chamfer if safe_chamfer > 0 else height

    # Base
    b0 = bm.verts.new((-r, -r, z_base))
    b1 = bm.verts.new(( r, -r, z_base))
    b2 = bm.verts.new(( r,  r, z_base))
    b3 = bm.verts.new((-r,  r, z_base))

    # Mid (início do chanfro)
    if safe_chamfer > 0:
        m0 = bm.verts.new((-r, -r, z_chamfer))
        m1 = bm.verts.new(( r, -r, z_chamfer))
        m2 = bm.verts.new(( r,  r, z_chamfer))
        m3 = bm.verts.new((-r,  r, z_chamfer))

        # Top
        t0 = bm.verts.new((-r_top, -r_top, z_top))
        t1 = bm.verts.new(( r_top, -r_top, z_top))
        t2 = bm.verts.new(( r_top,  r_top, z_top))
        t3 = bm.verts.new((-r_top,  r_top, z_top))

        bm.faces.new([b3, b2, b1, b0])
        # Laterais base-mid
        bm.faces.new([b0, b1, m1, m0])
        bm.faces.new([b1, b2, m2, m1])
        bm.faces.new([b2, b3, m3, m2])
        bm.faces.new([b3, b0, m0, m3])
        # Chanfro
        bm.faces.new([m0, m1, t1, t0])
        bm.faces.new([m1, m2, t2, t1])
        bm.faces.new([m2, m3, t3, t2])
        bm.faces.new([m3, m0, t0, t3])
        # Topo
        bm.faces.new([t0, t1, t2, t3])
    else:
        t0 = bm.verts.new((-r, -r, z_top))
        t1 = bm.verts.new(( r, -r, z_top))
        t2 = bm.verts.new(( r,  r, z_top))
        t3 = bm.verts.new((-r,  r, z_top))

        bm.faces.new([b3, b2, b1, b0])
        bm.faces.new([b0, b1, t1, t0])
        bm.faces.new([b1, b2, t2, t1])
        bm.faces.new([b2, b3, t3, t2])
        bm.faces.new([b3, b0, t0, t3])
        bm.faces.new([t0, t1, t2, t3])


def build_hexagon_bmesh(bm, radius, height, chamfer, base_extension=0.001, top_extension=0.0):
    """
    Gera um prisma hexagonal de 6 faces.
    """
    segments = 6
    safe_chamfer = max(0.0, min(chamfer, height * 0.45, radius * 0.45))
    z_base = -base_extension
    z_top = height + top_extension
    z_chamfer = height - safe_chamfer if safe_chamfer > 0 else height
    r_top = radius - safe_chamfer if safe_chamfer > 0 else radius

    base_verts = [
        bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                      radius * math.sin(i * 2 * math.pi / segments),
                      z_base))
        for i in range(segments)
    ]

    if safe_chamfer > 0:
        mid_verts = [
            bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                          radius * math.sin(i * 2 * math.pi / segments),
                          z_chamfer))
            for i in range(segments)
        ]
        top_verts = [
            bm.verts.new((r_top * math.cos(i * 2 * math.pi / segments),
                          r_top * math.sin(i * 2 * math.pi / segments),
                          z_top))
            for i in range(segments)
        ]
    else:
        mid_verts = None
        top_verts = [
            bm.verts.new((radius * math.cos(i * 2 * math.pi / segments),
                          radius * math.sin(i * 2 * math.pi / segments),
                          z_top))
            for i in range(segments)
        ]

    bm.faces.new(reversed(base_verts))

    if mid_verts:
        for i in range(segments):
            next_i = (i + 1) % segments
            bm.faces.new([base_verts[i], base_verts[next_i], mid_verts[next_i], mid_verts[i]])
            bm.faces.new([mid_verts[i], mid_verts[next_i], top_verts[next_i], top_verts[i]])
    else:
        for i in range(segments):
            next_i = (i + 1) % segments
            bm.faces.new([base_verts[i], base_verts[next_i], top_verts[next_i], top_verts[i]])

    bm.faces.new(top_verts)


def build_dovetail_bmesh(bm, radius, height, chamfer, base_extension=0.001, top_extension=0.0, clearance=0.0):
    """
    Gera um conector trapezoidal estilo rabo de andorinha (dovetail) com chanfro guia superior
    e folga uniforme preservando o paralelismo de inclinação.
    """
    safe_chamfer = max(0.0, min(chamfer, height * 0.45, radius * 0.35))
    z_base = -base_extension
    z_top = height + top_extension
    z_chamfer = height - safe_chamfer if safe_chamfer > 0 else height

    # Aplica folga de forma uniforme nas faces sem alterar a inclinação do trapézio
    w_base = radius * 1.5 + clearance
    w_neck = radius * 0.8 + clearance
    half_depth = (radius * 1.5 + clearance * 2.0) * 0.5

    b0 = bm.verts.new((-w_base, -half_depth, z_base))
    b1 = bm.verts.new(( w_base, -half_depth, z_base))
    b2 = bm.verts.new(( w_neck,  half_depth, z_base))
    b3 = bm.verts.new((-w_neck,  half_depth, z_base))

    if safe_chamfer > 0:
        m0 = bm.verts.new((-w_base, -half_depth, z_chamfer))
        m1 = bm.verts.new(( w_base, -half_depth, z_chamfer))
        m2 = bm.verts.new(( w_neck,  half_depth, z_chamfer))
        m3 = bm.verts.new((-w_neck,  half_depth, z_chamfer))

        c = safe_chamfer
        t0 = bm.verts.new((-w_base + c, -half_depth + c, z_top))
        t1 = bm.verts.new(( w_base - c, -half_depth + c, z_top))
        t2 = bm.verts.new(( w_neck - c,  half_depth - c, z_top))
        t3 = bm.verts.new((-w_neck + c,  half_depth - c, z_top))

        bm.faces.new([b3, b2, b1, b0])
        bm.faces.new([b0, b1, m1, m0])
        bm.faces.new([b1, b2, m2, m1])
        bm.faces.new([b2, b3, m3, m2])
        bm.faces.new([b3, b0, m0, m3])

        bm.faces.new([m0, m1, t1, t0])
        bm.faces.new([m1, m2, t2, t1])
        bm.faces.new([m2, m3, t3, t2])
        bm.faces.new([m3, m0, t0, t3])

        bm.faces.new([t0, t1, t2, t3])
    else:
        t0 = bm.verts.new((-w_base, -half_depth, z_top))
        t1 = bm.verts.new(( w_base, -half_depth, z_top))
        t2 = bm.verts.new(( w_neck,  half_depth, z_top))
        t3 = bm.verts.new((-w_neck,  half_depth, z_top))

        bm.faces.new([b3, b2, b1, b0])
        bm.faces.new([b0, b1, t1, t0])
        bm.faces.new([b1, b2, t2, t1])
        bm.faces.new([b2, b3, t3, t2])
        bm.faces.new([b3, b0, t0, t3])
        bm.faces.new([t0, t1, t2, t3])


def generate_connector_mesh(conn_type, radius, height, chamfer, base_ext=0.002, top_ext=0.0, clearance=0.0):
    """
    Cria uma nova malha do Blender com a geometria especificada.
    """
    bm = bmesh.new()
    if conn_type == 'CYLINDER':
        build_cylinder_bmesh(bm, radius, height, chamfer, base_ext, top_ext)
    elif conn_type == 'SQUARE':
        build_cube_bmesh(bm, radius, height, chamfer, base_ext, top_ext)
    elif conn_type == 'HEXAGON':
        build_hexagon_bmesh(bm, radius, height, chamfer, base_ext, top_ext)
    elif conn_type == 'DOVETAIL':
        build_dovetail_bmesh(bm, radius, height, chamfer, base_ext, top_ext, clearance=clearance)
    else:
        build_cylinder_bmesh(bm, radius, height, chamfer, base_ext, top_ext)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def create_male_pin_object(props, name="Cut3D_MalePin"):
    """
    Cria o objeto 3D do Pino Macho com chanfro e âncora de união na base.
    """
    mesh = bpy.data.meshes.new(name + "_Mesh")
    base_extension = max(
        0.002,
        float(props.pin_radius) * 0.18,
        float(getattr(props, "cut_gap", 0.0)) * 4.0,
    )
    bm = generate_connector_mesh(
        props.connector_type,
        radius=props.pin_radius,
        height=props.pin_depth,
        chamfer=props.chamfer_size,
        base_ext=base_extension,
        top_ext=0.0,
        clearance=0.0,
    )
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    return obj


def create_female_socket_cutter_object(props, name="Cut3D_FemaleCutter"):
    """
    Cria o objeto 3D cortador do Soquete Fêmea com folga (clearance) e folga de cola na profundidade.
    """
    mesh = bpy.data.meshes.new(name + "_Mesh")
    conn_type = props.connector_type
    if conn_type == 'DOVETAIL':
        # Dovetail usa a folga uniforme interna preservando proporções
        effective_radius = props.pin_radius
        dovetail_clearance = props.clearance
    else:
        effective_radius = props.pin_radius + props.clearance
        dovetail_clearance = 0.0

    expanded_depth = props.pin_depth + props.glue_gap
    socket_chamfer = props.chamfer_size + props.clearance

    base_extension = max(
        0.003,
        (props.pin_radius + props.clearance) * 0.18,
        float(getattr(props, "cut_gap", 0.0)) * 4.0,
    )
    bm = generate_connector_mesh(
        conn_type,
        radius=effective_radius,
        height=expanded_depth,
        chamfer=socket_chamfer,
        base_ext=base_extension,
        top_ext=0.0,
        clearance=dovetail_clearance,
    )
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(name, mesh)
    return obj
