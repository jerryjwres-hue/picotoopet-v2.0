# Blender 5.x: build real-scale B1 layout from Polycam scan, render cutaway + top plan.
# glTF (x, y_up, z_south) -> Blender (x, y=-z, z=up). Units: meters.
import bpy, os, math
from mathutils import Vector
HERE = os.path.dirname(os.path.abspath(__file__))
SCAN = os.path.join(HERE, "..", "scan", "scan_B1_1F_2026-11-17.glb")
OUT = HERE
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SCAN)

def wbb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts),
            max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))

# --- keep only basement geometry ---
remove = []
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    n = o.name
    x0,y0,z0,x1,y1,z1 = wbb(o)
    if n.startswith("Ceiling"): remove.append(o); continue
    if n.startswith("Wall_") and not (z0 < 0.0 and z1 <= 3.3): remove.append(o); continue
    if n.startswith("Floor_") and z0 > 0.3: remove.append(o); continue
    if n.startswith("Floor_Transition") or n.startswith("Joint"): remove.append(o); continue
    if n.startswith("Door") and z0 > 0.3: remove.append(o); continue
    if n.startswith("Window") and y1 < -3.9: remove.append(o); continue
    if not n.startswith(("Wall_", "Floor_", "Door", "Window")) and z0 > 0.3: remove.append(o); continue
# cut away walls facing the camera (south wall y~-4.3/-4.0 and west outer wall x~-6.3)
for o in bpy.data.objects:
    if o.type == 'MESH' and o.name.startswith("Wall_") and o not in remove:
        x0,y0,z0,x1,y1,z1 = wbb(o)
        if (y1 < -3.9 and (x1 - x0) > 3) or (x1 < -6.2):
            remove.append(o)
for o in remove:
    bpy.data.objects.remove(o, do_unlink=True)

def mat(name, rgb, rough=0.6, metal=0.0):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    return m
M = {k: mat(k, v) for k, v in {
    "floor": (0.80, 0.70, 0.55), "wall": (0.93, 0.92, 0.90), "furn": (0.72, 0.70, 0.67),
    "door": (0.55, 0.65, 0.85), "win": (0.55, 0.85, 0.90), "fence": (0.03, 0.03, 0.03),
    "dog": (0.18, 0.13, 0.10), "dogw": (0.92, 0.88, 0.80), "person": (0.35, 0.45, 0.60),
    "bowl": (0.75, 0.75, 0.78), "water": (0.55, 0.62, 0.70)}.items()}
M["bowl"].node_tree.nodes["Principled BSDF"].inputs["Metallic"].default_value = 1.0
M["bowl"].node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.25
for o in bpy.data.objects:
    if o.type != 'MESH': continue
    n = o.name; o.data.materials.clear()
    o.data.materials.append(M["floor"] if n.startswith("Floor") else M["wall"] if n.startswith("Wall") else
                            M["door"] if n.startswith("Door") else M["win"] if n.startswith("Window") else M["furn"])

def box(name, cx, cy, z0, sx, sy, sz, m):
    bpy.ops.mesh.primitive_cube_add(size=1, location=(cx, cy, z0 + sz / 2))
    o = bpy.context.object; o.name = name; o.scale = (sx, sy, sz); o.data.materials.append(M[m]); return o
def cyl(name, cx, cy, z0, r1, r2, h, m):
    bpy.ops.mesh.primitive_cone_add(vertices=48, radius1=r1, radius2=r2, depth=h, location=(cx, cy, z0 + h / 2))
    o = bpy.context.object; o.name = name; o.data.materials.append(M[m]); return o

# --- fence (owner markup): x~2.4, from scan z -0.3 .. 3.9  -> Blender y +0.3 .. -3.9, gate gap scan z 1.5..2.6 drawn as gate (closed)
FX, H = 2.4, 1.0
y_a, y_b = 0.3, -3.9
box("Fence_rail_top", FX, (y_a + y_b) / 2, H - 0.04, 0.04, abs(y_a - y_b), 0.04, "fence")
box("Fence_rail_mid", FX, (y_a + y_b) / 2, H - 0.16, 0.04, abs(y_a - y_b), 0.03, "fence")
box("Fence_rail_bot", FX, (y_a + y_b) / 2, 0.08, 0.04, abs(y_a - y_b), 0.03, "fence")
y = y_a
while y > y_b:
    box("Fence_bar", FX, y, 0.0, 0.02, 0.02, H, "fence"); y -= 0.11
for yp in (y_a, -1.5, -2.6, y_b):
    box("Fence_post", FX, yp, 0.0, 0.06, 0.06, H + 0.06, "fence")
# --- water bowls (owner markup) + food bowl (16cm top / 12cm base, ~7cm tall)
box("WaterBowl_rect", 2.9, -1.1, 0.0, 0.30, 0.42, 0.09, "water")
cyl("WaterBowl_round", 2.9, -3.2, 0.0, 0.08, 0.10, 0.07, "water")
cyl("FoodBowl_16cm", 3.05, -2.6, 0.0, 0.06, 0.08, 0.07, "bowl")
# --- Maotai proxy: shoulder 0.70 m, body length ~0.95 m, standing west of bowl, facing east
def dog(x, y):
    # standing in the 1.1 m strip between fence and wall, facing south (toward the bowl)
    pass
def dog_s(x, y):
    import mathutils
    parts = []
    parts.append(box("Dog_legs_front", x, y - 0.32, 0.0, 0.26, 0.14, 0.42, "dogw"))
    parts.append(box("Dog_legs_back", x, y + 0.32, 0.0, 0.28, 0.16, 0.42, "dogw"))
    parts.append(box("Dog_body", x, y, 0.40, 0.38, 0.95, 0.30, "dog"))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, location=(x, y - 0.55, 0.80)); h = bpy.context.object
    h.name = "Dog_head"; h.data.materials.append(M["dog"])
    box("Dog_muzzle", x, y - 0.72, 0.70, 0.12, 0.14, 0.10, "dogw")
def _unused(x, y):
    box("Dog_legs_front", x + 0.32, y, 0.0, 0.14, 0.26, 0.42, "dogw")
    box("Dog_legs_back", x - 0.32, y, 0.0, 0.16, 0.28, 0.42, "dogw")
    box("Dog_body", x, y, 0.40, 0.95, 0.38, 0.30, "dog")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, location=(x + 0.55, y, 0.80)); h = bpy.context.object
    h.name = "Dog_head"; h.data.materials.append(M["dog"])
    box("Dog_muzzle", x + 0.72, y, 0.70, 0.14, 0.12, 0.10, "dogw")
dog_s(2.95, -1.75)
# --- person proxy 1.70 m (scale reference) next to wet bar
bpy.ops.mesh.primitive_cylinder_add(radius=0.18, depth=1.45, location=(0.9, -0.9, 0.725)); p = bpy.context.object
p.name = "Person_1p70"; p.data.materials.append(M["person"])
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.12, location=(0.9, -0.9, 1.58)); bpy.context.object.data.materials.append(M["person"])

# --- labels (CJK font if available)
font = None
for fp in (r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"):
    if os.path.exists(fp):
        try: font = bpy.data.fonts.load(fp); break
        except Exception: pass
txtm = mat("txt", (0.8, 0.1, 0.05), 0.5)
def label(t, x, y, z=2.0, s=0.32):
    bpy.ops.object.text_add(location=(x, y, z)); o = bpy.context.object
    o.data.body = t; o.data.size = s; o.data.align_x = 'CENTER'
    if font: o.data.font = font
    o.data.materials.append(txtm); o.visible_shadow = False; o.rotation_euler = (math.radians(55), 0, math.radians(-30)); return o
LB = [("乒乓球区", -3.5, 2.0), ("水吧 0.95m", -1.0, 0.1), ("麻将桌", -1.6, -1.55), ("沙发", -1.3, -3.75),
      ("电脑桌", -5.9, -2.6), ("楼梯", -0.45, 2.25), ("栏杆", 2.4, 0.6), ("茅台 肩高0.7m", 2.95, -1.4),
      ("碗 16cm", 3.05, -2.95), ("人 1.70m", 0.9, -0.9), ("后门走廊", 5.0, -3.3)]
labels = [label(t, x, y, 2.3 if t.startswith(("人", "茅台")) else 1.6) for t, x, y in LB]

# --- light, world, render
scn = bpy.context.scene
scn.world = bpy.data.worlds.new("W"); scn.world.use_nodes = True
scn.world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
bpy.ops.object.light_add(type='SUN', location=(0, 0, 10)); sun = bpy.context.object
sun.data.energy = 3.0; sun.rotation_euler = (math.radians(35), math.radians(15), math.radians(30))
scn.render.engine = 'CYCLES'; scn.cycles.samples = 48; scn.cycles.use_denoising = True
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for t in ('OPTIX', 'CUDA'):
        try:
            prefs.compute_device_type = t; prefs.get_devices()
            for d in prefs.devices: d.use = True
            scn.cycles.device = 'GPU'; break
        except Exception: continue
except Exception: pass
scn.render.resolution_x, scn.render.resolution_y = 1800, 1200
scn.view_settings.view_transform = 'Standard'

def look_at(cam, target):
    d = Vector(target) - cam.location; cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
# 3/4 cutaway from south-west, high
bpy.ops.object.camera_add(location=(-9.5, -15.0, 12.5)); cam = bpy.context.object
cam.data.lens = 30; look_at(cam, (0.2, -0.3, 0.0)); scn.camera = cam
scn.render.filepath = os.path.join(OUT, "B1_cutaway_realscale.png"); bpy.ops.render.render(write_still=True)
# top-down orthographic plan
for o in labels: o.rotation_euler = (0, 0, 0); o.location.z = 2.6
bpy.ops.object.camera_add(location=(0.1, -0.3, 20)); top = bpy.context.object
top.data.type = 'ORTHO'; top.data.ortho_scale = 14.0; top.rotation_euler = (0, 0, 0); scn.camera = top
scn.render.resolution_x, scn.render.resolution_y = 1800, 1300
scn.render.filepath = os.path.join(OUT, "B1_topdown_realscale.png"); bpy.ops.render.render(write_still=True)
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT, "B1_layout_v1.blend"))
print("BUILD_DONE")
