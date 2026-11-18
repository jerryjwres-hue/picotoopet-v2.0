# Clean, approximate B1 set (not a 1:1 copy). Built from Polycam scan proportions + owner photos/markup.
# Blender coords: x = east, y = north, z = up, meters. Footprint ~ 12.9 x 8.9 m (~1,200 sqft).
import bpy, os, math
from mathutils import Vector
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "v2")
bpy.ops.wm.read_factory_settings(use_empty=True)
H = 2.52; T = 0.12
def mat(name, rgb, rough=0.55, metal=0.0, emit=None):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if emit:
        b.inputs["Emission Color"].default_value = (*emit, 1); b.inputs["Emission Strength"].default_value = 8.0
    return m
M = dict(
    floor=mat("floor", (0.66, 0.52, 0.36), 0.4), tile=mat("tile", (0.85, 0.85, 0.85), 0.3),
    wall=mat("wall", (0.80, 0.78, 0.74), 0.8), ceil=mat("ceil", (0.85, 0.84, 0.82), 0.9),
    base=mat("base", (0.96, 0.96, 0.95), 0.5), white=mat("white", (0.93, 0.93, 0.92), 0.4),
    quartz=mat("quartz", (0.95, 0.95, 0.94), 0.15), black=mat("black", (0.03, 0.03, 0.03), 0.4),
    metal=mat("metal", (0.75, 0.75, 0.77), 0.25, 1.0), glass=mat("glass", (0.05, 0.06, 0.07), 0.05),
    fence=mat("fence", (0.02, 0.02, 0.02), 0.5, 0.3), dkwood=mat("dkwood", (0.10, 0.07, 0.06), 0.5),
    wood=mat("wood", (0.62, 0.42, 0.25), 0.5), sofa=mat("sofa", (0.20, 0.28, 0.26), 0.8),
    cover=mat("cover", (0.58, 0.54, 0.52), 0.7), mjgreen=mat("mjgreen", (0.06, 0.28, 0.25), 0.7),
    mjpink=mat("mjpink", (0.85, 0.68, 0.70), 0.7), mjframe=mat("mjframe", (0.20, 0.19, 0.20), 0.4),
    leather=mat("leather", (0.04, 0.035, 0.035), 0.35), marble=mat("marble", (0.92, 0.92, 0.92), 0.2),
    ppblue=mat("ppblue", (0.08, 0.17, 0.42), 0.4), paper=mat("paper", (0.90, 0.86, 0.78), 0.9),
    door=mat("door", (0.94, 0.94, 0.93), 0.5), win=mat("win", (0.10, 0.13, 0.16), 0.05),
    dog=mat("dog", (0.12, 0.09, 0.07), 0.8), dogw=mat("dogw", (0.90, 0.86, 0.78), 0.8),
    person=mat("person", (0.35, 0.45, 0.60), 0.6), water=mat("water", (0.55, 0.62, 0.70), 0.2, 0.8),
    lamp=mat("lamp", (1, 1, 1), 0.5, emit=(1.0, 0.97, 0.92)), green=mat("green", (0.55, 0.85, 0.20), 0.7),
)
GROUP = {"ceiling": [], "label": [], "proxy": [], "cutwall": []}
def box(name, x0, y0, z0, x1, y1, z1, m, grp=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    o = bpy.context.object; o.name = name; o.scale = (abs(x1 - x0), abs(y1 - y0), abs(z1 - z0))
    o.data.materials.append(M[m])
    if grp: GROUP[grp].append(o)
    return o
def cyl(name, x, y, z0, r1, r2, h, m, grp=None, v=40):
    bpy.ops.mesh.primitive_cone_add(vertices=v, radius1=r1, radius2=r2, depth=h, location=(x, y, z0 + h / 2))
    o = bpy.context.object; o.name = name; o.data.materials.append(M[m])
    if grp: GROUP[grp].append(o)
    return o
def wall(x0, y0, x1, y1, gaps=(), grp=None, door_h=2.05):
    """axis-aligned wall; gaps = [(a,b)] along the wall's long axis, with header above"""
    horiz = abs(x1 - x0) >= abs(y1 - y0)
    a0, a1 = (min(x0, x1), max(x0, x1)) if horiz else (min(y0, y1), max(y0, y1))
    c = y0 if horiz else x0
    cuts = [a0] + [v for g in sorted(gaps) for v in g] + [a1]
    for i in range(0, len(cuts), 2):
        s, e = cuts[i], cuts[i + 1]
        if e - s > 0.01:
            (box("Wall", s, c - T/2, 0, e, c + T/2, H, "wall", grp) if horiz else box("Wall", c - T/2, s, 0, c + T/2, e, H, "wall", grp))
    for g in gaps:
        (box("Header", g[0], c - T/2, door_h, g[1], c + T/2, H, "wall", grp) if horiz else box("Header", c - T/2, g[0], door_h, c + T/2, g[1], H, "wall", grp))
    # baseboard
    for i in range(0, len(cuts), 2):
        s, e = cuts[i], cuts[i + 1]
        if e - s > 0.01:
            for side in (-1, 1):
                (box("Base", s, c + side * (T/2 + 0.006) - 0.006, 0, e, c + side * (T/2 + 0.006) + 0.006, 0.12, "base", grp) if horiz
                 else box("Base", c + side * (T/2 + 0.006) - 0.006, s, 0, c + side * (T/2 + 0.006) + 0.006, e, 0.12, "base", grp))

# ---------------- floor plan ----------------
ROOMS = [(-6.4, -4.0, 3.5, 0.3, "floor"), (-6.4, 0.3, 0.3, 4.9, "floor"), (0.3, 0.3, 3.5, 2.1, "tile"), (3.5, -4.0, 6.5, -2.3, "floor")]
for x0, y0, x1, y1, m in ROOMS:
    box("Floor", x0, y0, -0.05, x1, y1, 0, m)
    box("Ceiling", x0, y0, H, x1, y1, H + 0.05, "ceil", "ceiling")
# outer walls
wall(-6.4, -4.0, 6.5, -4.0, grp="cutwall")                               # south (sofa / office windows) – cut for cutaway
wall(-6.4, -4.0, -6.4, 4.9, grp="cutwall")                               # west (office desk)
wall(-6.4, 4.9, 0.3, 4.9)                                                # north (ping-pong window)
wall(0.3, 2.1, 0.3, 4.9)                                                 # east side of stair area
wall(0.3, 2.1, 3.5, 2.1)                                                 # bathroom north
wall(3.5, -2.3, 3.5, 2.1)                                                # east of dog strip / bathroom
wall(3.5, -2.3, 6.5, -2.3)                                               # corridor north
wall(6.5, -4.0, 6.5, -2.3, gaps=[(-3.85, -2.95)])                        # back door (east)
# wet-bar wall + bathroom door
wall(-2.9, 0.3, 0.3, 0.3)
wall(0.3, 0.3, 3.5, 0.3, gaps=[(0.45, 1.25)])
wall(-2.9, 0.3, -2.9, 1.6, gaps=[(0.5, 1.3)])                            # closet door faces ping-pong area
wall(-2.9, 1.6, -1.2, 1.6)
# doors
box("BathDoor", 0.45, 0.26, 0, 1.25, 0.30, 2.04, "door"); box("BathKnob", 1.12, 0.21, 0.95, 1.18, 0.26, 1.0, "black")
box("ClosetDoor", -2.94, 0.5, 0, -2.90, 1.3, 2.04, "door")
box("BackDoor", 6.46, -3.85, 0, 6.50, -2.95, 2.04, "door")
box("BackDoorWin", 6.44, -3.75, 1.55, 6.46, -3.05, 1.95, "win")
box("DogFlap", 6.44, -3.65, 0.10, 6.46, -3.15, 0.75, "metal"); box("DogFlapIn", 6.43, -3.58, 0.16, 6.45, -3.22, 0.70, "glass")
# high basement windows
for x0, x1 in ((-4.2, -3.25), (-3.1, -2.15)):
    box("Win", x0, -4.07, 1.75, x1, -3.93, 2.35, "win", "cutwall")
box("Win", -4.9, 4.83, 1.85, -4.1, 4.97, 2.35, "win")
box("Win", 4.6, -4.07, 1.75, 5.3, -3.93, 2.3, "win", "cutwall")
# ---------------- wet bar (north wall, faces south) ----------------
box("WB_lower", -2.5, -0.30, 0.10, 0.6, 0.24, 0.88, "white"); box("WB_kick", -2.45, -0.25, 0, 0.55, 0.24, 0.10, "black")
box("WB_counter", -2.55, -0.35, 0.88, 0.65, 0.26, 0.93, "quartz")
box("WB_fridge", -1.75, -0.31, 0.10, -1.15, -0.28, 0.85, "glass"); box("WB_fridgeTrim", -1.78, -0.30, 0.08, -1.12, -0.29, 0.87, "metal")
box("WB_sink", -0.75, -0.15, 0.86, -0.30, 0.10, 0.935, "metal")
cyl("WB_faucet", -0.52, 0.17, 0.93, 0.015, 0.015, 0.35, "metal")
box("WB_upperL", -2.5, -0.05, 1.45, -1.30, 0.24, 2.20, "white")
box("WB_upperR", -0.20, -0.05, 1.45, 0.60, 0.24, 2.20, "white")
box("WB_rackBox", -1.28, -0.05, 1.45, -0.22, 0.24, 1.80, "white")
for ang in (45, -45):
    o = box("WB_X", -1.25, 0.0, 1.62 - 0.01, -0.25, 0.22, 1.62 + 0.01, "white"); o.rotation_euler = (0, math.radians(ang * 0.33), 0)
box("WB_shelf", -1.28, -0.05, 1.82, -0.22, 0.24, 2.20, "white")
for x in (-2.2, -1.6, -0.0, 0.35):
    cyl("Knob", x, -0.31, 0.75, 0.015, 0.015, 0.02, "black", v=12)
# ---------------- mahjong + chairs + stools ----------------
mx, my = -1.6, -1.55
box("MJ_base", mx - 0.30, my - 0.30, 0, mx + 0.30, my + 0.30, 0.62, "mjframe")
box("MJ_frame", mx - 0.50, my - 0.50, 0.62, mx + 0.50, my + 0.50, 0.78, "mjframe")
box("MJ_pink", mx - 0.46, my - 0.46, 0.78, mx + 0.46, my + 0.46, 0.785, "mjpink")
box("MJ_green", mx - 0.34, my - 0.34, 0.785, mx + 0.34, my + 0.34, 0.79, "mjgreen")
def chair(cx, cy, face, m="leather"):
    dx, dy = face
    box("Ch_seat", cx - 0.22, cy - 0.22, 0.44, cx + 0.22, cy + 0.22, 0.48, m)
    bx, by = cx - dx * 0.21, cy - dy * 0.21
    if dx: box("Ch_back", bx - 0.02, cy - 0.21, 0.48, bx + 0.02, cy + 0.21, 1.00, m)
    else: box("Ch_back", cx - 0.21, by - 0.02, 0.48, cx + 0.21, by + 0.02, 1.00, m)
    for sx in (-1, 1):
        for sy in (-1, 1):
            box("Ch_leg", cx + sx * 0.19 - 0.015, cy + sy * 0.19 - 0.015, 0, cx + sx * 0.19 + 0.015, cy + sy * 0.19 + 0.015, 0.44, m)
for (ox, oy) in ((0, 0.78), (0, -0.78), (0.78, 0), (-0.78, 0)):
    chair(mx + ox, my + oy, (-ox / 0.78 if ox else 0, -oy / 0.78 if oy else 0))
for sx, sy in ((mx - 0.75, my - 0.75), (mx + 0.75, my + 0.75)):
    cyl("Stool", sx, sy, 0, 0.17, 0.15, 0.48, "black", v=24); cyl("StoolTop", sx, sy, 0.48, 0.18, 0.18, 0.03, "marble")
# ---------------- sofa wall (south) ----------------
box("Sofa_base", -2.4, -3.92, 0, -0.2, -3.05, 0.42, "sofa")
box("Sofa_seat", -2.25, -3.85, 0.42, -0.35, -3.05, 0.55, "cover")
box("Sofa_back", -2.4, -3.92, 0.42, -0.2, -3.70, 0.90, "cover")
box("Sofa_armL", -2.4, -3.92, 0.42, -2.25, -3.05, 0.65, "sofa"); box("Sofa_armR", -0.35, -3.92, 0.42, -0.2, -3.05, 0.65, "sofa")
for px in (-1.95, -0.95):
    box("PaintFrame", px - 0.30, -3.94, 1.35, px + 0.30, -3.92, 2.20, "dkwood", "cutwall"); box("Paint", px - 0.25, -3.925, 1.40, px + 0.25, -3.915, 2.15, "paper", "cutwall")
box("Cart", 0.0, -3.92, 0, 0.45, -3.55, 1.05, "white"); box("RobotDock", 0.55, -3.92, 0, 0.90, -3.55, 0.55, "white")
box("PrinterDesk", 1.05, -3.95, 0.72, 2.25, -3.30, 0.76, "dkwood")
for lx, ly in ((1.1, -3.9), (2.2, -3.9), (1.1, -3.35), (2.2, -3.35)):
    box("PD_leg", lx - 0.03, ly - 0.03, 0, lx + 0.03, ly + 0.03, 0.72, "dkwood")
box("Printer", 1.55, -3.90, 0.76, 2.05, -3.45, 0.98, "white")
chair(1.65, -3.0, (0, -1), "dkwood")
# ---------------- office (west) ----------------
box("Desk", -6.32, -3.6, 0.72, -5.62, -0.8, 0.75, "white")
for ly in (-3.5, -0.9):
    box("DeskLeg", -6.0, ly - 0.03, 0, -5.9, ly + 0.03, 0.72, "white")
for my2 in (-2.9, -2.1, -1.4):
    box("Monitor", -6.25, my2 - 0.30, 0.95, -6.22, my2 + 0.30, 1.30, "black"); box("MonStand", -6.25, my2 - 0.03, 0.75, -6.20, my2 + 0.03, 0.95, "black")
box("PCcase", -6.30, -0.95, 0.75, -5.85, -0.75, 1.20, "black")
for cx, cy in ((-5.1, -2.6), (-5.0, -1.4)):
    cyl("OChairBase", cx, cy, 0, 0.30, 0.05, 0.10, "metal"); box("OChairSeat", cx - 0.26, cy - 0.26, 0.45, cx + 0.26, cy + 0.26, 0.55, "white")
    box("OChairBack", cx + 0.20, cy - 0.25, 0.55, cx + 0.28, cy + 0.25, 1.15, "white")
box("Shelf", -6.38, -3.2, 1.55, -6.20, -2.4, 1.58, "black", "cutwall")
# ---------------- ping-pong area (north-west) + stairs ----------------
px, py = -4.4, 2.8
box("PP_edge", px - 0.77, py - 1.38, 0.73, px + 0.77, py + 1.38, 0.76, "white")
box("PP_top", px - 0.76, py - 1.37, 0.76, px + 0.76, py + 1.37, 0.765, "ppblue")
box("PP_line", px - 0.004, py - 1.37, 0.765, px + 0.004, py + 1.37, 0.767, "white")
box("PP_net", px - 0.83, py - 0.01, 0.765, px + 0.83, py + 0.01, 0.92, "black")
for lx in (-0.6, 0.6):
    for ly in (-1.1, 1.1):
        box("PP_leg", px + lx - 0.025, py + ly - 0.025, 0, px + lx + 0.025, py + ly + 0.025, 0.73, "black")
box("Freezer", -2.45, 2.0, 0, -1.6, 2.65, 0.88, "white"); box("MiniFridge", -2.45, 2.7, 0, -1.95, 3.2, 0.85, "metal")
steps = 12; rise = H / steps; run = 0.25
for i in range(steps):
    y0 = 1.85 + i * run
    box("Riser", -1.15, y0, 0, -0.15, y0 + 0.02, (i + 1) * rise, "white")
    box("Tread", -1.17, y0, (i + 1) * rise - 0.035, -0.13, y0 + run + 0.02, (i + 1) * rise, "wood")
    box("Stringer", -1.20, y0, 0, -1.15, y0 + run, (i + 1) * rise, "white")
    box("Baluster", -1.19, y0 + 0.10, (i + 1) * rise, -1.17, y0 + 0.12, (i + 1) * rise + 0.90, "black")
rail = box("Rail", -1.21, 1.85, 0.0, -1.15, 1.85 + steps * run, 0.07, "wood")
rail.rotation_euler = (math.atan2(H, steps * run), 0, 0); rail.location = (-1.18, 1.85 + steps * run / 2, H / 2 + 0.95)
box("Newel", -1.25, 1.75, 0, -1.10, 1.90, 1.15, "white")
# bathroom fixtures (inside, behind door)
box("Vanity", 0.6, 1.5, 0, 1.4, 2.0, 0.85, "white"); box("Toilet", 2.4, 1.6, 0, 2.8, 2.05, 0.42, "white")
# ---------------- Maotai's fenced area (owner markup: fence wall-to-wall at x≈2.4) ----------------
FX, FH = 2.4, 1.15
y_top, y_bot = 0.3 - T/2, -4.0 + T/2
box("F_railTop", FX - 0.02, y_bot, FH - 0.05, FX + 0.02, y_top, FH, "fence")
box("F_railTop2", FX - 0.02, y_bot, FH - 0.20, FX + 0.02, y_top, FH - 0.16, "fence")
box("F_railBot", FX - 0.02, y_bot, 0.08, FX + 0.02, y_top, 0.12, "fence")
y = y_top - 0.06
while y > y_bot + 0.03:
    box("F_bar", FX - 0.011, y - 0.011, 0.08, FX + 0.011, y + 0.011, FH, "fence"); y -= 0.11
for yp in (y_top - 0.04, -1.45, -2.55, y_bot + 0.04):
    box("F_post", FX - 0.035, yp - 0.035, 0, FX + 0.035, yp + 0.035, FH + 0.06, "fence")
    box("F_foot", FX - 0.09, yp - 0.09, 0, FX + 0.09, yp + 0.09, 0.03, "fence")
box("WaterRect", 2.75, -1.30, 0, 3.15, -0.90, 0.09, "metal"); box("WaterRectIn", 2.78, -1.27, 0.02, 3.12, -0.93, 0.085, "water")
cyl("WaterRound", 3.4, -3.55, 0, 0.09, 0.11, 0.07, "metal")
cyl("FoodBowl_16cm", 3.0, -2.85, 0, 0.06, 0.08, 0.07, "metal")
cyl("FoodBowlBase", 3.0, -2.85, 0, 0.065, 0.065, 0.012, "black")
# ---------------- scale proxies ----------------
def dog(x, y, heading_deg):
    parts = []
    parts.append(box("Dog_body", -0.47, -0.19, 0.40, 0.47, 0.19, 0.72, "dog"))
    for lx in (-0.32, 0.30):
        for ly in (-0.11, 0.11):
            parts.append(box("Dog_leg", lx - 0.06, ly - 0.06, 0, lx + 0.06, ly + 0.06, 0.44, "dogw"))
    parts.append(box("Dog_chest", 0.30, -0.15, 0.35, 0.52, 0.15, 0.70, "dogw"))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.15, location=(0.62, 0, 0.86)); h = bpy.context.object; h.data.materials.append(M["dog"]); parts.append(h)
    parts.append(box("Dog_muzzle", 0.72, -0.07, 0.74, 0.86, 0.07, 0.84, "dogw"))
    for ey in (-0.08, 0.08):
        parts.append(box("Dog_ear", 0.58, ey - 0.03, 0.96, 0.64, ey + 0.03, 1.06, "dog"))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.13, location=(-0.50, 0, 0.82)); t = bpy.context.object; t.data.materials.append(M["dogw"]); parts.append(t)
    parts.append(box("Bandana", 0.42, -0.16, 0.66, 0.52, 0.16, 0.74, "green"))
    bpy.ops.object.empty_add(location=(0, 0, 0)); root = bpy.context.object; root.name = "Maotai_proxy"
    for p in parts: p.parent = root; GROUP["proxy"].append(p)
    root.location = (x, y, 0); root.rotation_euler = (0, 0, math.radians(heading_deg)); return root
dog(2.95, -1.9, -90)                        # standing in the strip, facing south toward the bowl
cyl("Person_1p70", 0.9, -1.0, 0, 0.19, 0.17, 1.45, "person", "proxy"); bpy.ops.mesh.primitive_uv_sphere_add(radius=0.11, location=(0.9, -1.0, 1.58))
bpy.context.object.data.materials.append(M["person"]); GROUP["proxy"].append(bpy.context.object)
# ---------------- lights ----------------
scn = bpy.context.scene
scn.world = bpy.data.worlds.new("W"); scn.world.use_nodes = True
bg = scn.world.node_tree.nodes["Background"]; bg.inputs[0].default_value = (0.9, 0.92, 0.95, 1); bg.inputs[1].default_value = 0.25
LIGHTS = []
for x0, y0, x1, y1, _ in ROOMS:
    nx = max(1, round((x1 - x0) / 2.2)); ny = max(1, round((y1 - y0) / 2.2))
    for i in range(nx):
        for j in range(ny):
            lx = x0 + (i + 0.5) * (x1 - x0) / nx; ly = y0 + (j + 0.5) * (y1 - y0) / ny
            bpy.ops.object.light_add(type='POINT', location=(lx, ly, H - 0.12)); L = bpy.context.object
            L.data.energy = 45; L.data.shadow_soft_size = 0.12; L.data.color = (1.0, 0.97, 0.92); LIGHTS.append(L)
            cyl("Downlight", lx, ly, H - 0.012, 0.07, 0.07, 0.01, "lamp", "ceiling", v=20)
# ---------------- labels (overview renders only) ----------------
font = None
for fp in (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyh.ttc"):
    if os.path.exists(fp):
        try: font = bpy.data.fonts.load(fp); break
        except Exception: pass
txtm = mat("txt", (0.85, 0.12, 0.05), 0.5, emit=(0.85, 0.12, 0.05))
for t, x, y in [("水吧", -1.0, -0.05), ("麻将桌", -1.6, -1.0), ("沙发", -1.3, -2.7), ("打印机桌", 1.65, -2.55),
                ("电脑桌", -5.4, -0.5), ("乒乓球区", -4.4, 1.2), ("楼梯↑", -0.65, 4.4), ("卫生间", 1.9, 1.2),
                ("栏杆", 2.1, -0.4), ("茅台区", 2.95, -0.6), ("后门", 5.6, -2.8), ("碗16cm", 3.45, -2.85), ("人1.70m", 0.9, -1.45)]:
    bpy.ops.object.text_add(location=(x, y, 2.7)); o = bpy.context.object
    o.data.body = t; o.data.size = 0.30; o.data.align_x = 'CENTER'; o.data.align_y = 'CENTER'
    if font: o.data.font = font
    o.data.materials.append(txtm); o.visible_shadow = False; GROUP["label"].append(o)
# ---------------- render setup ----------------
scn.render.engine = 'CYCLES'; scn.cycles.samples = 96; scn.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for t in ('OPTIX', 'CUDA'):
        try:
            prefs.compute_device_type = t; prefs.get_devices()
            for d in prefs.devices: d.use = True
            scn.cycles.device = 'GPU'; break
        except Exception: continue
except Exception: pass
scn.view_settings.view_transform = 'AgX'; scn.view_settings.look = 'AgX - Medium High Contrast'
def show(grp, on):
    for o in GROUP[grp]: o.hide_render = not on
def cam(name, loc, target, lens, w, h, ortho=None, clean=True):
    bpy.ops.object.camera_add(location=loc); c = bpy.context.object; c.name = name
    if ortho: c.data.type = 'ORTHO'; c.data.ortho_scale = ortho; c.rotation_euler = (0, 0, 0)
    else:
        d = Vector(target) - Vector(loc); c.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    c.data.lens = lens; c.data.clip_end = 100
    scn.camera = c; scn.render.resolution_x, scn.render.resolution_y = w, h
    scn.render.filepath = os.path.join(OUT, name + ".png"); bpy.ops.render.render(write_still=True)
    if clean:  # same shot without the dog/person proxies -> background plate guide
        show("proxy", False); scn.render.filepath = os.path.join(OUT, "clean", name + ".png"); bpy.ops.render.render(write_still=True); show("proxy", True)
# A/B overview: no ceiling, labels on, south+west walls cut for the 3/4 view
show("ceiling", False); show("label", True); show("proxy", True)
for L in LIGHTS: L.data.energy = 30
bpy.context.scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
cam("A_topdown", (0.05, 0.45, 25), None, 50, 1800, 1300, ortho=13.8, clean=False)
show("label", False)
show("cutwall", False)
cam("B_cutaway_34", (-7.5, -12.5, 10.5), (0.0, 0.3, 0.3), 30, 1800, 1200)
cam("B2_cutaway_from_SE", (8.5, -11.5, 9.5), (-0.8, 0.3, 0.3), 30, 1800, 1200)
# C-F eye-level / dog-level views: full room, ceiling on, labels off, vertical 9:16
show("cutwall", True); show("ceiling", True); show("label", False)
for L in LIGHTS: L.data.energy = 45
bpy.context.scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.05
cam("C_front_from_office", (-4.9, -3.3, 1.55), (2.0, -1.2, 0.9), 18, 1080, 1920)
cam("D_side_from_sofa", (0.2, -3.6, 1.45), (-1.8, 0.2, 0.9), 18, 1080, 1920)
cam("E_dogeye_in_strip", (3.3, -3.75, 0.55), (2.95, 0.3, 0.45), 20, 1080, 1920)
cam("F_low_at_fence", (0.4, -1.6, 0.65), (3.0, -2.2, 0.5), 22, 1080, 1920)
cam("G_high_over_fence", (1.3, -1.0, 2.30), (3.0, -2.6, 0.2), 20, 1080, 1920)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "B1_set_v2.blend"))
print("BUILD_DONE")
