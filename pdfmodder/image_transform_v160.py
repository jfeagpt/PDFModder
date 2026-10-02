"""Move, resize and rotate one isolated placement without resampling its asset.

The affine map surrounds the original placement, including its own crop. This
keeps rotation independent of the separate fit/fill operations in the editor.
"""
import math

import pymupdf as fitz
from pypdf.generic import FloatObject

from .engine import full_write
from .media import _safe, _rect, _ops, _validate, _image_selection
from .model import EditError


def transform_image_instance_pdf(data, page, image_id, rect=None, revision=None, *, rotation=0.):
    """Apply a clockwise delta around the visible frame centre, or map its box.

    Original q/clip/cm/Do/Q operators and the shared image remain untouched.
    The containing stream reference alone is cloned for the selected page.
    """
    _safe(data, page, revision, transform_tagged=True)
    if isinstance(rotation, bool) or not isinstance(rotation, (int, float)) or not math.isfinite(rotation):
        raise EditError('El giro debe ser un número finito de grados.')
    if rect is not None and rotation:
        raise EditError('Mueve o redimensiona y gira la imagen en operaciones separadas.')
    with fitz.open(stream=data, filetype='pdf') as doc:
        target = doc[page]
        item = _image_selection(doc, page, image_id)
        from .tagged_image_v160 import TaggedImageTransform
        semantic_guard = TaggedImageTransform(data, page, item)
        if not item['editable']:
            raise EditError(item['reason'])
        stream = _ops(doc.xref_stream(item['stream_xref']))
        offset, count = item['operator_index'], item['operator_count']
        parent = fitz.Matrix(item['parent_matrix'])
        original_rect = fitz.Rect(item['rect'])
        page_rotation = target.rotation
        try:
            target.set_rotation(0)
            page_matrix = target.transformation_matrix
        finally:
            target.set_rotation(page_rotation)
        old_pdf_rect = original_rect * ~page_matrix
        if rect is None:
            cx, cy = (old_pdf_rect.x0 + old_pdf_rect.x1)/2, (old_pdf_rect.y0 + old_pdf_rect.y1)/2
            mapping = fitz.Matrix(1, 0, 0, 1, -cx, -cy) * fitz.Matrix(-rotation) * fitz.Matrix(1, 0, 0, 1, cx, cy)
            if item.get('framed'):
                x, y, width, height = map(float, stream.operations[offset+1][0])
                destination = fitz.Rect(x, y, x+width, y+height) * (parent * mapping * page_matrix)
            else:
                destination = fitz.Rect(0, 0, 1, 1) * (fitz.Matrix(item['matrix_pdf']) * mapping * page_matrix)
            destination = _rect(target, tuple(destination))
        else:
            destination = _rect(target, rect)
            pdf_rect = destination * ~page_matrix
            sx, sy = pdf_rect.width/old_pdf_rect.width, pdf_rect.height/old_pdf_rect.height
            mapping = fitz.Matrix(sx, 0, 0, sy, pdf_rect.x0-old_pdf_rect.x0*sx, pdf_rect.y0-old_pdf_rect.y0*sy)
        clip = item.get('clip_rect_pdf')
        if clip is not None and not (fitz.Rect(clip)+(-.01, -.01, .01, .01)).contains(destination * ~page_matrix):
            raise EditError('El destino de la imagen supera su recorte heredado. Elige una posición y tamaño dentro del área visible original.')
        inverse = fitz.Matrix(parent)
        if inverse.invert():
            raise EditError('La imagen hereda una matriz no invertible.')
        local_map = parent * mapping * inverse
        selected = stream.operations[offset:offset+count]
        stream.operations[offset:offset+count] = [([], b'q'), ([FloatObject(v) for v in local_map], b'cm'), *selected, ([], b'Q')]
        clone = doc.get_new_xref()
        doc.update_object(clone, '<<>>')
        doc.update_stream(clone, stream.get_data())
        contents = target.get_contents()[:]
        contents[item['stream_position']] = clone
        doc.xref_set_key(target.xref, 'Contents', '['+' '.join(f'{xref} 0 R' for xref in contents)+']')
        expected_bbox = tuple(fitz.Rect(0, 0, 1, 1) * (fitz.Matrix(item['matrix_pdf']) * mapping * page_matrix))
        output = full_write(doc)
    report = _validate(data, output, page, int(image_id), destination,
                       expected_bbox=expected_bbox, old_rect=original_rect)
    accessibility = semantic_guard.validate(output)
    if accessibility is not None:
        report['accessibility'] = accessibility
    report.update(instance_only=True, pixels_preserved=True, rotation_clockwise=rotation,
                  operation_geometry='rotate' if rect is None else 'move_resize',
                  centre_preserved=rect is None, physical_size_preserved=rect is None)
    return output, report
