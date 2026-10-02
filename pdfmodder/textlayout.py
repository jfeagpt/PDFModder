"""Anchura de edición derivada del contenido, sin escalar letras ni mover vecinos."""
from dataclasses import replace
import math
import statistics
import pymupdf as fitz
from .model import EditError,LineWidthOverflow,union


def _check_visibility(selected):
    if any(g.mode!=3 and g.opacity<=0 for g in selected):
        raise EditError('Texto invisible mediante opacidad 0: sólo se admite corregir capas OCR con Tr=3.')


def edit_with_layout(data,request,resolver=None):
    from .engine import edit_pdf,extract_page
    from .fonts import FontResolver,FontError
    resolver=resolver or FontResolver()
    requested=request
    partial=False
    if request.line_spacing is not None and (not math.isfinite(request.line_spacing) or request.line_spacing<=0):
        raise EditError('El interlineado debe ser positivo.')
    if not math.isfinite(request.paragraph_spacing) or request.paragraph_spacing<0:
        raise EditError('La separación entre párrafos no puede ser negativa.')
    automatic=request.auto_width and request.text is not None and not request.reflow and '\n' not in request.text and request.ocr_mode=='visible'
    if not automatic:
        with fitz.open(stream=data,filetype='pdf') as doc:
            _check_visibility(extract_page(doc,request.page,data).selected(request.ids))
    if automatic:
        with fitz.open(stream=data,filetype='pdf') as doc:
            model=extract_page(doc,request.page,data)
            selected=model.selected(request.ids)
            if not selected:raise EditError('Selecciona el texto que deseas editar.')
            _check_visibility(selected)
            from .clipping import CLIP_ISSUE
            if CLIP_ISSUE in model.issues:
                # Native fields can carry Tz/Tc/TJ spacing unavailable from a
                # Unicode font measurement. Let their operator planner size
                # the area from its exact advances and original clipping.
                output,report=edit_pdf(data,replace(request,width=None),resolver)
                result_bounds=report.get('new_bounds',union(g.bbox for g in selected))
                report.update(auto_width=True,area_width=max(.1,result_bounds[2]-result_bounds[0]))
                return output,report
            g=selected[0]
            area=selected
            # Partial justified selections use their original whole-line area.
            if request.line_reflow:
                area=[x for x in model.glyphs if x.line==g.line and x.mode==g.mode and (x.opacity>0)==(g.opacity>0)]
            bounds=union(x.bbox for x in area)
            measured={}
            for glyph in model.glyphs:
                if (glyph.font,glyph.font_resource,glyph.mode,glyph.opacity>0)==(g.font,g.font_resource,g.mode,g.opacity>0) and abs(glyph.size-g.size)<.002:
                    measured.setdefault(glyph.text,[]).append(glyph.trace_bbox[2]-glyph.trace_bbox[0])
            sizes={ch:statistics.median(values) for ch,values in measured.items()}
            size=request.size or g.size
            choice=None
            if request.font_file or request.font_name:
                choice=resolver.resolve_explicit(request.font_name or g.font,request.text,request.font_file)
            elif any(ch not in sizes for ch in request.text) or request.size:
                try:choice=resolver.resolve(doc,request.page,g.font,request.text)
                except FontError:pass  # The core produces the precise missing-code explanation.
            def width(ch):
                if choice:return choice.width(ch,size)
                return sizes.get(ch,g.size)*size/g.size
            gaps=[b.origin[0]-a.origin[0]-(a.trace_bbox[2]-a.trace_bbox[0])
                  for a,b in zip(selected,selected[1:]) if a.line==b.line]
            gap=statistics.median(gaps) if gaps else 0.
            wanted=sum(width(ch) for ch in request.text)+max(0,len(request.text)-1)*gap
            partial=request.line_reflow and {x.id for x in selected}!={x.id for x in area}
            if partial:
                # First ask the actual line planner to redistribute its spaces.
                # A longer word need not change the line's original endpoints.
                wanted=bounds[2]-bounds[0]
            # Preserve a sensible minimum for the geometry of an empty replacement.
            wanted=max(.1,wanted+.025)
            anchor=request.anchor
            maximum=(doc[request.page].cropbox.width-bounds[0] if anchor=='left' else
                     bounds[2] if anchor=='right' else
                     2*min((bounds[0]+bounds[2])/2,doc[request.page].cropbox.width-(bounds[0]+bounds[2])/2))
            if wanted>maximum+.035:raise EditError('El texto supera el espacio disponible hasta el borde de página.')
            if partial:
                request=replace(request,width=None,height=None)
            else:
                request=replace(request,width=wanted)
    try:
        output,report=edit_pdf(data,request,resolver)
    except LineWidthOverflow as overflow:
        if not partial:raise
        width=overflow.required_width+.025
        if width>maximum+.035:raise EditError('El texto supera el espacio disponible hasta el borde de página.') from overflow
        request=replace(request,width=width)
        output,report=edit_pdf(data,request,resolver)
    if requested.auto_width and requested.text is not None and not requested.reflow and requested.ocr_mode=='visible':
        regions=report.get('destination_regions',[])
        bounds=report.get('new_bounds',union(regions))
        report['auto_width']=True
        report['area_width']=max(.1,bounds[2]-bounds[0])
    if request.reflow:
        report['paragraph_layout']={'line_spacing':request.line_spacing,'paragraph_spacing':request.paragraph_spacing,
                                    'width':request.width,'height':request.height}
    return output,report
