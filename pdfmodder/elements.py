"""Inventario seleccionable de una zona, sin agrupar columnas por proximidad."""
from .model import union,intersects
from collections import defaultdict


def zone_elements(model,images,zone=None,level='line'):
    lines=defaultdict(list)
    for glyph in model.glyphs:
        if zone is None or intersects(glyph.bbox,zone):lines[(glyph.line,glyph.mode,glyph.opacity>0)].append(glyph)
    groups=[]
    for glyphs in lines.values():
        if level=='line':groups.append(glyphs)
        elif level=='character':groups.extend([g] for g in glyphs)
        else:
            current=[]
            for g in glyphs:
                if current and (g.id!=current[-1].id+1 or g.origin[0]-current[-1].bbox[2]>g.size*.65 or g.text.isspace()):
                    groups.append(current);current=[]
                if not g.text.isspace():current.append(g)
            if current:groups.append(current)
    result=[]
    for glyphs in groups:
        text=''.join(g.text for g in glyphs)
        if not text.strip() and level!='character':continue
        bounds=union(g.bbox for g in glyphs)
        g=glyphs[0]
        kind='OCR' if g.mode==3 else 'Invisible (opacidad 0; no editable)' if g.opacity<=0 else 'Texto'
        result.append({'kind':'text','ids':[g.id for g in glyphs],'rect':bounds,'text':text,
                       'label':f"{kind} · {text!r} · {g.font} {g.size:.3f} pt",
                       'ocr':g.mode==3})
    for index,item in enumerate(images):
        if zone is not None and not intersects(item['rect'],zone):continue
        result.append({'kind':'image','id':item['id'],'rect':item['rect'],
                       'label':f"Imagen {index+1} · {item.get('width_px', '?')} × {item.get('height_px', '?')} px",
                       'reason':item.get('reason','')})
    return sorted(result,key=lambda item:(round(item['rect'][1],1),item['rect'][0],item['kind']))
