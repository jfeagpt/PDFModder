"""Coincidencias revisables ligadas a una revisión y a caracteres concretos."""
from collections import defaultdict
from dataclasses import replace
import hashlib
import re
import pymupdf as fitz
from .model import EditError,EditRequest,union


def find_matches(data,query,pages=None,selection=None,case_sensitive=True,whole_word=False,include_ocr=False):
    from .engine import extract_page
    from .pageops import parse_pages
    revision=hashlib.sha256(data).hexdigest()
    if not query:raise EditError('Escribe el texto que deseas buscar.')
    if '\n' in query:raise EditError('Busca un fragmento de una sola línea.')
    pattern=re.escape(query)
    if whole_word:pattern=r'(?<!\w)'+pattern+r'(?!\w)'
    expression=re.compile(pattern,0 if case_sensitive else re.IGNORECASE)
    result=[]
    with fitz.open(stream=data,filetype='pdf') as doc:
        numbers=parse_pages(pages,len(doc)) if pages else list(range(len(doc)))
        if selection:
            if selection.get('revision')!=revision:raise EditError('La selección de búsqueda pertenece a una revisión anterior.')
            numbers=[number for number in numbers if number==selection['page']]
        for number in numbers:
            model=extract_page(doc,number,data)
            groups=defaultdict(list)
            allowed=set(selection['ids']) if selection else None
            for g in model.glyphs:
                if (g.mode==3 or g.opacity<=0) and not include_ocr:continue
                groups[(g.line,g.mode,g.opacity>0)].append(g)
            for glyphs in groups.values():
                text=''.join(g.text for g in glyphs)
                for match in expression.finditer(text):
                    chosen=glyphs[match.start():match.end()]
                    if not chosen:continue
                    if allowed is not None and any(g.id not in allowed for g in chosen):continue
                    key=f'{revision}:{number}:'+','.join(str(g.id) for g in chosen)
                    result.append({'id':hashlib.sha256(key.encode()).hexdigest(), 'page':number,
                        'ids':[g.id for g in chosen],'rect':union(g.bbox for g in chosen),
                        'text':match.group(),'context':text[max(0,match.start()-35):match.end()+35],
                        'revision':revision,'ocr':chosen[0].mode==3,
                        'visible':chosen[0].opacity>0,
                        'unsupported_reason':'Texto invisible mediante opacidad 0: sólo se admite corregir capas OCR con Tr=3.'
                            if chosen[0].mode!=3 and chosen[0].opacity<=0 else '',
                        'origins':[g.origin for g in chosen],'font':chosen[0].font,'size':chosen[0].size})
    return result


def replace_matches(data,matches,replacement,resolver=None,auto_width=True):
    from .engine import extract_page
    from .textlayout import edit_with_layout
    revision=hashlib.sha256(data).hexdigest()
    if not matches:raise EditError('Marca al menos una coincidencia para previsualizar.')
    if any(m['revision']!=revision for m in matches):raise EditError('El PDF cambió; repite la búsqueda antes de reemplazar.')
    if any(m.get('unsupported_reason') for m in matches):
        raise EditError(next(m['unsupported_reason'] for m in matches if m.get('unsupported_reason')))
    seen=set()
    for match in matches:
        selected={(match['page'],i) for i in match['ids']}
        if seen & selected:raise EditError('Las coincidencias marcadas se superponen. Revisa la selección.')
        seen.update(selected)
    candidate=data
    reports=[]
    # Locate each original appearance anew by text + exact origin; prior edits
    # change numeric glyph ids, never retarget another occurrence by its spelling.
    for match in sorted(matches,key=lambda m:(m['page'],m['ids'][0]),reverse=True):
        with fitz.open(stream=candidate,filetype='pdf') as doc:
            model=extract_page(doc,match['page'],candidate)
        chosen=[]
        for char,origin in zip(match['text'],match['origins']):
            found=[g for g in model.glyphs if g.text==char and (g.mode==3)==match['ocr'] and
                   (g.opacity>0)==match.get('visible',True) and
                   abs(g.origin[0]-origin[0])<.035 and abs(g.origin[1]-origin[1])<.035 and g not in chosen]
            if len(found)!=1:raise EditError('Una coincidencia ya no se puede aislar. Repite la búsqueda.')
            chosen.append(found[0])
        request=EditRequest(match['page'],[g.id for g in chosen],text=replacement,revision=model.revision,
                            auto_width=auto_width,line_reflow=False,
                            ocr_mode='searchable' if match['ocr'] else 'visible')
        try:candidate,report=edit_with_layout(candidate,request,resolver)
        except EditError as exc:raise EditError(f"Página {match['page']+1}, «{match['text']}»: {exc}") from exc
        report.update(match_id=match['id'],page=match['page'])
        reports.append(report)
    return candidate,{'operation':'replace_matches','verified':True,'match_count':len(matches),'edits':reports,
                      'warning':'Las coincidencias OCR modifican sólo la capa buscable, sin cambiar la imagen.' if any(m['ocr'] for m in matches) else ''}
