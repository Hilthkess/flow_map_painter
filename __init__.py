# Copyright (C) 2021 Clemens Beute

# ##### BEGIN GPL LICENSE BLOCK #####
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Flow Map Painter",
    "author": "Clemens Beute <feedback.clemensbeute@gmail.com>",
    "version": (1, 4),
    "blender": (3, 0, 1),
    "category": "Paint",
    "location": "Paint Brush Tool Panel",
    "description": "A brush tool for flow map painting. The brush gets the color of the painting direction",
    "warning": "",
    "doc_url": "",
}

import bpy
import numpy
import mathutils
from bpy_extras import view3d_utils
from gpu_extras.presets import draw_circle_2d

# oooooooooooo                                       .    o8o
# `888'     `8                                     .o8    `''
#  888         oooo  oooo  ooo. .oo.    .ooooo.  .o888oo oooo   .ooooo.  ooo. .oo.
#  888oooo8    `888  `888  `888P'Y88b  d88' `'Y8   888   `888  d88' `88b `888P'Y88b
#  888    '     888   888   888   888  888         888    888  888   888  888   888
#  888          888   888   888   888  888   .o8   888 .  888  888   888  888   888
# o888o         `V88V'V8P' o888o o888o `Y8bod8P'   '888' o888o `Y8bod8P' o888o o888o



def lerp(mix, a, b):
    """linear interpolation"""

    return (b - a) * mix + a



def remove_temp_obj():
    """removes the temp object and data if it exists"""

    if bpy.data.meshes.get("FLOWMAP_temp_mesh"):
        bpy.data.meshes.remove(bpy.data.meshes["FLOWMAP_temp_mesh"])
    if bpy.data.objects.get("FLOWMAP_temp_obj"):
        bpy.data.objects.remove(bpy.data.objects["FLOWMAP_temp_obj"])
    return None



def triangulate_object(template_ob):
    """triangulate incoming object and return it as a temporary copy"""
    global tri_obj

    # first remove temp stuff, if it exists already
    remove_temp_obj()

    ob = template_ob.copy()
    ob.data = ob.data.copy()
    ob.modifiers.new("triangulate", 'TRIANGULATE')

    # need to be in scnene, for depsgraph to work apparently
    bpy.context.collection.objects.link(ob)

    depsgraph = bpy.context.evaluated_depsgraph_get()
    object_eval = ob.evaluated_get(depsgraph)
    mesh_from_eval = bpy.data.meshes.new_from_object(object_eval)
    ob.data = mesh_from_eval

    tri_obj = bpy.data.objects.new(name="FLOWMAP_temp_obj", object_data=mesh_from_eval)
    bpy.context.collection.objects.link(tri_obj)
    tri_obj.matrix_world = template_ob.matrix_world

    # remove the depsgraph object
    bpy.data.objects.remove(ob, do_unlink=True)

    # hide temp obj
    # tri_obj.hide_viewport = True
    tri_obj.hide_set(True)

    return tri_obj



def obj_ray_cast(context, area_pos, obj, matrix):
    """Wrapper for ray casting that moves the ray into object space"""

    # get the context arguments
    scene = context.scene
    region = context.region
    rv3d = context.region_data
    coord = area_pos[0], area_pos[1]

    # get the ray from the viewport and mouse
    view_vector = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)
    ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)

    ray_target = ray_origin + view_vector

    # get the ray relative to the object
    matrix_inv = matrix.inverted()
    ray_origin_obj = matrix_inv @ ray_origin
    ray_target_obj = matrix_inv @ ray_target
    ray_direction_obj = ray_target_obj - ray_origin_obj

    # cast the ray
    success, location, normal, face_index = obj.ray_cast(
        origin=ray_origin_obj, direction=ray_direction_obj, distance=bpy.context.scene.flowmap_trace_distance
    )

    if success:
        return location, normal, face_index
    else:
        return None, None, None



def line_trace_for_pos(context, area_pos, tri_obj):
    """Trace at given position. Return hit in obje and world space."""
    obj = bpy.context.active_object
    matrix = obj.matrix_world.copy()
    if obj.type == 'MESH':
        hit, normal, face_index = obj_ray_cast(context=context, area_pos=area_pos, obj=tri_obj, matrix=matrix)
        if hit is not None:
            return hit, matrix @ hit
        else:
            return None, None



def get_uv_space_direction_color(context, area_pos, area_prev_pos, tri_obj):
    """combine area_pos and previouse linetrace into direction color"""

    def line_trace_for_uv(context, area_pos, tri_obj):
        """line trace into the scene, to find uv coordinates at the brush location at the object """

        def pos_to_uv_co(obj, matrix_world, world_pos, face_index):
            """translate 3D postion on a mesh into uv coordinates"""

            face_verts = []
            uv_verts = []

            # uv"s are stored in loops
            face = obj.data.polygons[face_index]
            for vert_idx, loop_idx in zip(face.vertices, face.loop_indices):
                uv_coords = obj.data.uv_layers.active.data[loop_idx].uv

                face_verts.append(matrix_world @ obj.data.vertices[vert_idx].co)
                uv_verts.append(uv_coords.to_3d())

                # print(f'face idx {face.index}, vert idx {vert_idx}, vert coords {ob.data.vertices[vert_idx].co},uv coords {uv_coords.x} {uv_coords.y}')

            # print("world_pos: ", world_pos)
            # print("face_verts: ", face_verts[0], face_verts[1], face_verts[2])
            # print("uv_verts: ", uv_verts[0], uv_verts[1], uv_verts[2])

            # point, tri_a1, tri_a2, tri_a3, tri_b1, tri_b2, tri_b3
            uv_co = mathutils.geometry.barycentric_transform(
                world_pos, face_verts[0], face_verts[1], face_verts[2], uv_verts[0], uv_verts[1], uv_verts[2]
            )

            return uv_co

        obj = bpy.context.active_object
        matrix = obj.matrix_world.copy()
        uv_co = None
        hit = None
        hit_world = None
        if obj.type == 'MESH':
            hit, normal, face_index = obj_ray_cast(context=context, area_pos=area_pos, obj=tri_obj, matrix=matrix)
            if hit is not None:
                hit_world = matrix @ hit
                # scene.cursor.location = hit_world
                uv_co = pos_to_uv_co(
                    obj=tri_obj, matrix_world=obj.matrix_world, world_pos=hit_world, face_index=face_index
                )

        return uv_co, hit

    # finally get the uv coordinates
    uv_pos, hit_world = line_trace_for_uv(context, area_pos, tri_obj)
    uv_prev_pos, _ = line_trace_for_uv(context, area_prev_pos, tri_obj)

    if uv_pos is None or uv_prev_pos is None:
        return None, None

    # convert to numpy array for further math
    uv_pos = numpy.array([uv_pos[0], uv_pos[1]])
    uv_prev_pos = numpy.array([uv_prev_pos[0], uv_prev_pos[1]])

    # calculate direction vector and normalize it
    uv_direction_vector = uv_pos - uv_prev_pos
    norm_factor = numpy.linalg.norm(uv_direction_vector)
    if norm_factor == 0:
        return None, None

    norm_uv_direction_vector = uv_direction_vector / norm_factor

    # map the range to the color range, so 0.5 ist the middle
    color_range_vector = (norm_uv_direction_vector + 1) * 0.5
    direction_color = [color_range_vector[0], color_range_vector[1], 0]

    # return [uv_pos[0], uv_pos[1], 0]
    return direction_color, hit_world



def get_obj_space_direction_color(context, area_pos, area_prev_pos, tri_obj):
    """get the normalized vector color from brush and previous location in object space"""

    # get world hit and previus
    location, hit_world = line_trace_for_pos(context=context, area_pos=area_pos, tri_obj=tri_obj)
    _, prev_hit_world = line_trace_for_pos(context=context, area_pos=area_prev_pos, tri_obj=tri_obj)

    if hit_world is None or prev_hit_world is None:
        return None, None

    obj = bpy.context.scene.flowmap_object
    if obj is None:
        obj = bpy.context.active_object

    matrix = obj.matrix_world.inverted().copy()
    hit_obj = matrix @ hit_world
    prev_hit_obj = matrix @ prev_hit_world

    # convert to numpy array for further math
    obj_pos = numpy.array([hit_obj[0], hit_obj[1], hit_obj[2]])
    obj_prev_pos = numpy.array([prev_hit_obj[0], prev_hit_obj[1], prev_hit_obj[2]])

    # calculate direction vector and normalize it
    world_direction_vector = obj_pos - obj_prev_pos
    norm_factor = numpy.linalg.norm(world_direction_vector)
    if norm_factor == 0:
        return None, None

    norm_world_direction_vector = world_direction_vector / norm_factor

    # map the range to the color range, so 0.5 ist the middle
    color_range_vector = (norm_world_direction_vector + 1) * 0.5
    # color_range_vector = norm_world_direction_vector #debug original color
    direction_color = [color_range_vector[0], color_range_vector[1], color_range_vector[2]]

    return direction_color, location



def get_world_space_direction_color(context, area_pos, area_prev_pos, tri_obj):
    """get the normalized vector color from brush and previous location in world space"""

    # get world hit and previus
    location, hit_world = line_trace_for_pos(context=context, area_pos=area_pos, tri_obj=tri_obj)
    _, prev_hit_world = line_trace_for_pos(context=context, area_pos=area_prev_pos, tri_obj=tri_obj)

    if hit_world is None or prev_hit_world is None:
        return None, None

    # convert to numpy array for further math
    world_pos = numpy.array([hit_world[0], hit_world[1], hit_world[2]])
    world_prev_pos = numpy.array([prev_hit_world[0], prev_hit_world[1], prev_hit_world[2]])

    # calculate direction vector and normalize it
    world_direction_vector = world_pos - world_prev_pos
    norm_factor = numpy.linalg.norm(world_direction_vector)
    if norm_factor == 0:
        return None, None

    norm_world_direction_vector = world_direction_vector / norm_factor

    # map the range to the color range, so 0.5 ist the middle
    color_range_vector = (norm_world_direction_vector + 1) * 0.5
    # color_range_vector = norm_world_direction_vector #debug original color
    direction_color = [color_range_vector[0], color_range_vector[1], color_range_vector[2]]

    return direction_color, location



def paint_a_dot(mouse_position, event, location=None):
    """paint one dot | works 2D, as well as 3D and also for vertex paint"""

    # get the active brush
    if bpy.context.object.mode == 'VERTEX_PAINT':
        brush = bpy.context.tool_settings.vertex_paint.brush
    elif bpy.context.object.mode == 'TEXTURE_PAINT':
        brush = bpy.context.tool_settings.image_paint.brush
    else:
        return None

    # pressure and dynamic pen pressure
    pressure = bpy.context.scene.tool_settings.unified_paint_settings.use_unified_strength
    if brush.use_pressure_strength is True:
        pressure = pressure * event.pressure

    # size and dynamic pen pressure size
    size = bpy.context.scene.tool_settings.unified_paint_settings.size
    if brush.use_pressure_size is True:
        size = size * event.pressure

    stroke = [
        {
            "name": "flowmap stroke",
            "is_start": True,
            "location": location or (0, 0, 0),
            "mouse": (mouse_position[0] - bpy.context.area.x, mouse_position[1] - bpy.context.area.y),
            "mouse_event": (mouse_position[0] - bpy.context.area.x, mouse_position[1] - bpy.context.area.y),
            "pen_flip": False,
            "pressure": pressure,
            "size": size,
            "time": 1,
            "x_tilt": 0,
            "y_tilt": 0,
        }
    ]

    if bpy.context.object.mode == 'TEXTURE_PAINT':
        bpy.ops.paint.image_paint(stroke=stroke, mode='NORMAL')

    elif bpy.context.object.mode == 'VERTEX_PAINT' and location:
        bpy.ops.paint.vertex_paint(stroke=stroke, mode='NORMAL')



def get_cursor_target():
    if bpy.context.area.type == 'IMAGE_EDITOR':
        return bpy.types.SpaceImageEditor
    if bpy.context.area.type == 'VIEW_3D':
        return bpy.types.SpaceView3D



#   .oooooo.                                               .
#  d8P'  `Y8b                                            .o8
# 888      888 oo.ooooo.   .ooooo.  oooo d8b  .oooo.   .o888oo  .ooooo.  oooo d8b
# 888      888  888' `88b d88' `88b `888''8P `P  )88b    888   d88' `88b `888''8P
# 888      888  888   888 888ooo888  888      .oP'888    888   888   888  888
# `88b    d88'  888   888 888    .o  888     d8(  888    888 . 888   888  888
#  `Y8bood8P'   888bod8P' `Y8bod8P' d888b    `Y888''8o   '888' `Y8bod8P' d888b
#               888
#              o888o



class FlowmapOperator(bpy.types.Operator):
    """The base class for all flowmap operators.  Has an event loop and understands
    mouse movements.  Knows it needs to compute flowmap colors but that is implmented
    in its child classes.  Knows how to startup, shutdown, and draw its own cursor."""

    furthest_position = numpy.array([0, 0])
    mouse_prev_position = (0, 0)
    pressing = False

    cursor = None           #cursor is the handler that was added as a draw_handler, if it is active.


    def modal(self, context: bpy.types.Context, event: bpy.types.Event):

        # this is necessary, to find out if left mouse is pressed down (so no other keypress ist taken into account to trigger painting)
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # set first position of stroke
            self.furthest_position = numpy.array([event.mouse_x, event.mouse_y])
            self.pressing = True
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            self.pressing = False
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE' or event.type == 'LEFTMOUSE':

            # get mouse positions
            mouse_position = numpy.array([event.mouse_x, event.mouse_y])

            # if mouse has traveled enough distance and mouse is pressed, draw a dot
            distance = numpy.linalg.norm(self.furthest_position - mouse_position)
            if distance >= bpy.context.scene.flowmap_brush_spacing:

                self.furthest_position = mouse_position

                direction_color, location = self.get_direction_color(context, mouse_position, self.mouse_prev_position)

                # set paint brush color, but check for nan first (fucked value, when direction didnt work)
                if not direction_color is None:
                    if not any(numpy.isnan(val) for val in direction_color):
                        bpy.context.scene.tool_settings.unified_paint_settings.color = direction_color

                if self.pressing:
                    # paint the actual dots with the selected brush spacing
                    # if mouse moved more than double of the brush_spacing -> draw substeps
                    substeps_float = distance / bpy.context.scene.flowmap_brush_spacing
                    substeps_int = int(substeps_float)
                    if distance > 2 * bpy.context.scene.flowmap_brush_spacing:
                        # substep_count = substeps_int
                        substep_count = substeps_int
                        while substep_count > 0:
                            # lerp_mix = 1 / (substeps_int + 1) * substep_count
                            lerp_mix = 1 / (substeps_int) * substep_count
                            lerp_paint_position = numpy.array(
                                [
                                    lerp(lerp_mix, self.mouse_prev_position[0], mouse_position[0]),
                                    lerp(lerp_mix, self.mouse_prev_position[1], mouse_position[1])
                                ]
                            )
                            paint_a_dot(mouse_position=lerp_paint_position, event=event, location=location)
                            substep_count = substep_count - 1
                    else:
                        paint_a_dot(mouse_position=mouse_position, event=event, location=location)

                self.mouse_prev_position = mouse_position

            self.redraw_cursor((event.mouse_region_x, event.mouse_region_y))

            return {'RUNNING_MODAL'}

        if event.type == 'ESC':
            # clean brush color from nan shit
            bpy.context.scene.tool_settings.unified_paint_settings.color = (0.5, 0.5, 0.5)
            self.clear_cursor()
            self.cleanup()
            return {'FINISHED'}

        return {'PASS_THROUGH'}


    def invoke(self, context, event):
        self.pressing = False
        context.window_manager.modal_handler_add(self)
        bpy.context.scene.tool_settings.unified_paint_settings.use_unified_color = True
        bpy.context.scene.tool_settings.unified_paint_settings.use_unified_strength = True
        bpy.context.scene.tool_settings.unified_paint_settings.use_unified_size = True
        bpy.context.window.cursor_set('PAINT_CROSS')
        self.startup()
        return {'RUNNING_MODAL'}


    def startup(self):
        pass


    def cleanup(self):
        pass


    def redraw_cursor(self, pos):

        def draw(x, y):
            brush_col = bpy.context.scene.tool_settings.unified_paint_settings.color
            col = (brush_col[0], brush_col[1], 0, 1)

            size = bpy.context.scene.tool_settings.unified_paint_settings.size

            draw_circle_2d((x,y), col, size)

        self.clear_cursor()
        self.cursor = get_cursor_target().draw_handler_add(draw, pos, 'WINDOW', 'POST_PIXEL')
        bpy.context.area.tag_redraw()


    def clear_cursor(self):
        if self.cursor:
            get_cursor_target().draw_handler_remove(self.cursor, 'WINDOW')
            self.cursor = None
        bpy.context.area.tag_redraw()



class FLOWMAP_OT_image_editor(FlowmapOperator):
    """The 2D flowmap operator.  Used by image paint only.  Computes flowmap
    based on screen space coordinates since images are always axis aligned
    in the image editor."""

    bl_idname = "flowmap.image_editor"
    bl_label = "Flowmap Image Editor Operator"


    def get_direction_color(self, context, mouse_position, mouse_prev_position):
        # calculate direction vector and normalize it
        mouse_direction_vector = mouse_position - mouse_prev_position
        norm_factor = numpy.linalg.norm(mouse_direction_vector)
        if norm_factor == 0:
            norm_mouse_direction_vector = numpy.array([0, 0])
        else:
            norm_mouse_direction_vector = mouse_direction_vector / norm_factor

        # map the range to the color range, so 0.5 ist the middle
        color_range_vector = (norm_mouse_direction_vector + 1) * 0.5
        direction_color = [color_range_vector[0], color_range_vector[1], 0]
        return direction_color, None



class FLOWMAP_OT_3d_viewport(FlowmapOperator):
    """The 3d flowmap operator.  Used buy both Texture Paint and Vertex Paint.
    computes flowmap based on UV, object, or world coordinates. Needs a triangulated
    mesh to do that.  Sets the triangulated mesuh up and tears it down during
    startup and cleanup."""

    bl_idname = "flowmap.3d_viewport"
    bl_label = "Flowmap 3D Viewport Operator"
    tri_obj = None


    def startup(self):
        FlowmapOperator.startup(self)
        self.tri_obj = triangulate_object(bpy.context.active_object)


    def cleanup(self):
        FlowmapOperator.cleanup(self)
        remove_temp_obj()


    def get_direction_color(self, context, mouse_position, mouse_prev_position):

        # get area mouse positions
        area_pos = (mouse_position[0] - bpy.context.area.x, mouse_position[1] - bpy.context.area.y)
        area_prev_pos = (self.mouse_prev_position[0] - bpy.context.area.x, self.mouse_prev_position[1] - bpy.context.area.y)

        # finding the direction vector, from UV Coordinates, from 3D location | object space | world space
        direction_color = None
        location = None
        if bpy.context.scene.flowmap_space_type == "uv_space":
            direction_color, location = get_uv_space_direction_color(context, area_pos, area_prev_pos, self.tri_obj)
        elif bpy.context.scene.flowmap_space_type == "object_space":
            direction_color, location = get_obj_space_direction_color(context, area_pos, area_prev_pos, self.tri_obj)
        elif bpy.context.scene.flowmap_space_type == "world_space":
            direction_color, location = get_world_space_direction_color(context, area_pos, area_prev_pos, self.tri_obj)
        return direction_color, location



# ooooo                 .                       .o88o.
# `888'               .o8                       888 `'
#  888  ooo. .oo.   .o888oo  .ooooo.  oooo d8b o888oo   .oooo.    .ooooo.   .ooooo.
#  888  `888P'Y88b    888   d88' `88b `888''8P  888    `P  )88b  d88' `'Y8 d88' `88b
#  888   888   888    888   888ooo888  888      888     .oP'888  888       888ooo888
#  888   888   888    888 . 888    .o  888      888    d8(  888  888   .o8 888    .o
# o888o o888o o888o   '888' `Y8bod8P' d888b    o888o   `Y888''8o `Y8bod8P' `Y8bod8P'


class FlowmapPanel(bpy.types.Panel):


    def draw(self, context):
        """Base class for the UI panel.  knows how to draw itself, tailors itself based on mode
        that was set by the child class"""

        split1 = self.layout.split(factor=0.55)
        split2 = split1.split(factor=0.15)
        # split.use_property_split = True
        column1 = split2.column()
        column2 = split2.column()
        column3 = split1.column()

        # space
        if bpy.context.area.type == 'VIEW_3D':
            column1.label(icon='ORIENTATION_GLOBAL')
            column2.label(text="Space Type")
            column3.prop(context.scene, "flowmap_space_type", text="")

            if context.scene.flowmap_space_type == "object_space":
                column1.label(text="")
                column2.label(text="Object")
                column3.prop_search(context.scene, "flowmap_object", context.scene, "objects", text="")

        # spacing
        column1.label(icon='ONIONSKIN_ON')
        column2.label(text="Brush Spacing")
        column3.prop(context.scene, "flowmap_brush_spacing", slider=True, text="")

        # trace distance
        if bpy.context.area.type == 'VIEW_3D':
            column1.label(icon='CON_TRACKTO')
            column2.label(text="Trace Distance")
            column3.prop(context.scene, "flowmap_trace_distance", slider=True, text="")

        # exit
        self.layout.separator()

        splitexit = self.layout.split(factor=0.078)
        splitcol1 = splitexit.column()
        splitcol2 = splitexit.column()
        splitcol1.label(icon='EVENT_ESC')
        txt1 = splitcol2.row()
        txt1.active = False
        txt1.label(text="press ESC to Exit")

        splitcol1.label(text="")
        txt2 = splitcol2.row()
        txt2.active = False
        txt2.label(text="Flowmap painting mode")

        self.layout.separator()

        # paint
        if bpy.context.area.type == 'IMAGE_EDITOR':
            self.layout.operator("flowmap.image_editor", text="Start Flowmap Mode", icon='ANIM_DATA')
        if bpy.context.area.type == 'VIEW_3D':
            self.layout.operator("flowmap.3d_viewport", text="Start Flowmap Mode", icon='ANIM_DATA')

        self.layout.separator()



class FLOWMAP_PT_image_paint(FlowmapPanel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Flowmap Image Paint"
    bl_context = ".imagepaint_2d"



class FLOWMAP_PT_texture_paint(FlowmapPanel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Flowmap Texture Paint"
    bl_context = "imagepaint"



class FLOWMAP_PT_vertex_paint(FlowmapPanel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tool"
    bl_label = "Flowmap Vertex Paint"
    bl_context = "vertexpaint"



# ooooooooo.                         o8o               .
# `888   `Y88.                       `''             .o8
#  888   .d88'  .ooooo.   .oooooooo oooo   .oooo.o .o888oo  .ooooo.  oooo d8b
#  888ooo88P'  d88' `88b 888' `88b  `888  d88(  '8   888   d88' `88b `888''8P
#  888`88b.    888ooo888 888   888   888  `'Y88b.    888   888ooo888  888
#  888  `88b.  888    .o `88bod8P'   888  o.  )88b   888 . 888    .o  888
# o888o  o888o `Y8bod8P' `8oooooo.  o888o 8''888P'   '888' `Y8bod8P' d888b
#                        d'     YD
#                        'Y88888P'

PROPERTIES = [

    ("flowmap_brush_spacing", bpy.props.FloatProperty(
        name="Brush Spacing",
        description="How much has the mouse to travel, bevor a new stroke is painted?",
        default=20,
        soft_min=0.1,
        soft_max=100,
        min=0,
        subtype='PIXEL')),

    ("flowmap_trace_distance", bpy.props.FloatProperty(
        name="Trace Distance",
        description="How deep reaches your object into the scene?",
        min=0,
        soft_max=10000,
        default=1000,
        unit='LENGTH')),

    ("flowmap_space_type", bpy.props.EnumProperty(
        name="Space Type",
        description="Which space type is used for the direction color?",
        items=[
            (
                "uv_space", "UV Space",
                "Use it, if you want to transform your material UV Coordinates. Your object needs a UV Map",
                'UV', 0
            ),
            (
                "object_space", "Object Space",
                "Use it, if you want to transform your material Object Coordinates. If empty, current object is used. No UV Map needed in Vertex Paint",
                'OBJECT_DATAMODE', 1
            ),
            (
                "world_space", "World Space",
                "Similar to object Space, but it uses world coordinates",
                'WORLD_DATA', 2
            ),
        ],
        default=0)),

    ("flowmap_object", bpy.props.PointerProperty(
        name="Object",
        description="Which object is used for the object space? Default is the active object itself.",
        type=bpy.types.Object))

    ]



CLASSES = [
    FLOWMAP_OT_image_editor,
    FLOWMAP_OT_3d_viewport,
    FLOWMAP_PT_image_paint,
    FLOWMAP_PT_texture_paint,
    FLOWMAP_PT_vertex_paint
    ]



def register():
    for (prop_name, prop_value) in PROPERTIES:
        setattr(bpy.types.Scene, prop_name, prop_value)
    for type in CLASSES:
        bpy.utils.register_class(type)



def unregister():
    for (prop_name, prop_value) in PROPERTIES:
        delattr(bpy.types.Scene, prop_name)
    for type in CLASSES:
        bpy.utils.unregister_class(type)
