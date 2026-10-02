"""Validated clipboard transactions. PDF objects stay in the worker process.

The bundle contains selected text/styles and isolated image/font bytes only.
It never contains a document snapshot or executable PDF content operators.
"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import math

import pymupdf as fitz
from pypdf import PdfReader

from .engine import extract_page, full_write, _insert, _redact, edit_pdf
from .fonts import (FontError, ResolvedFont, _font_metadata, _check_embedding,
                    _check_characters, normalized_name)
from .model import EditError, EditRequest
from .richmodels import RichTextRequest
from .richtext import selection_payload, edit_rich_pdf, has_rich_metadata

BUNDLE_VERSION = 1


def _revision(data, revision):
    if revision and revision != sha256(data).hexdigest():
        raise EditError('El documento cambió. Selecciona el objeto de nuevo antes de usar el portapapeles.')


def _font_identity(value, depth=0):
    """A resource identity independent of renumbered indirect references."""
    if depth > 12:
        raise EditError('El recurso de fuente tiene una estructura demasiado compleja.')
    value = value.get_object() if hasattr(value, 'get_object') else value
    if hasattr(value, 'get_data'):
        return ('stream', sha256(value.get_data()).hexdigest(),
                _font_identity({k:v for k,v in value.items() if k not in ('/Length','/Filter','/DecodeParms')}, depth+1))
    if isinstance(value, dict):
        return tuple((str(k),_font_identity(v,depth+1)) for k,v in sorted(value.items(),key=lambda item:str(item[0])))
    if isinstance(value,(list,tuple)):
        return tuple(_font_identity(v,depth+1) for v in value)
    if isinstance(value, bytes):
        return ('bytes', value.hex())
    return str(value)


def _resource_identity(reader, page, resource):
    try:
        font = reader.pages[page]['/Resources']['/Font'][resource]
        return sha256(repr(_font_identity(font)).encode('utf-8')).hexdigest()
    except (KeyError,TypeError,AttributeError):
        raise EditError('No se puede identificar el recurso de fuente seleccionado.')


def _copy_fonts(data, page, model, runs, resolver):
    """Resolve selected faces and prove that their portable programs reproduce them."""
    reader=PdfReader(BytesIO(data),strict=True)
    fonts={}; resolved={}; errors=[]
    with fitz.open(stream=data,filetype='pdf') as doc:
        for run in runs:
            key=(run.get('font_resource'),run.get('font_name'))
            token=sha256(repr(key).encode()).hexdigest()[:20]
            run['clipboard_font']=token
            if token in fonts:continue
            text=''.join(r['text'] for r in runs if (r.get('font_resource'),r.get('font_name'))==key)
            text=''.join(c for c in text if c not in '\n\u2028\t')
            entry={'name':key[1],'resource':key[0],
                   'identity':_resource_identity(reader,page,key[0]) if key[0] else None}
            try:
                face=resolver.resolve(doc,page,key[1],text)
                entry.update(name=face.name,buffer=bytes(face.buffer) if face.buffer else None,
                             base14=face.base14,source=face.source,metadata=deepcopy(face.metadata),portable=True)
                resolved[key[1]]=face
            except (FontError,RuntimeError,ValueError) as exc:
                entry.update(portable=False,error=str(exc));errors.append(str(exc))
            fonts[token]=entry
        if not errors:
            try:
                # Reproduce at the original glyph origins before exporting a
                # program. Matching a font name or a cmap alone is insufficient.
                _redact(doc[page],model,model.glyphs)
                erased=full_write(doc)
                with fitz.open(stream=erased,filetype='pdf') as probe:
                    _insert(probe[page],model.glyphs,resolved)
                    reproduced=full_write(probe)
                from .validation import assert_pixels
                with fitz.open(stream=data,filetype='pdf') as before, fitz.open(stream=reproduced,filetype='pdf') as after:
                    assert_pixels(before[page],after[page],reproduction=True)
            except (EditError,FontError,RuntimeError,ValueError) as exc:
                errors.append(str(exc))
                for entry in fonts.values():entry.update(portable=False,error=str(exc))
    return fonts,errors


def copy_selection_v170(session, page, ids=None, image_id=None, revision=None):
    data=session.history.current;_revision(data,revision)
    with session._open(data) as doc:
        if not doc.permissions & fitz.PDF_PERM_COPY:
            raise EditError('Los permisos del PDF no permiten copiar contenido.')
        if not 0 <= page < doc.page_count:raise EditError('La página seleccionada ya no existe.')
        model=extract_page(doc,page,data)
    if image_id is not None:
        from .media import export_image_pdf, image_items
        asset=export_image_pdf(data,page,image_id,revision=revision)
        with fitz.open(stream=data,filetype='pdf') as doc:
            item=next((i for i in image_items(doc,page) if i['id']==str(image_id)),None)
        if item is None:raise EditError('La imagen seleccionada ya no existe.')
        bundle={'version':BUNDLE_VERSION,'kind':'image','source_revision':model.revision,'source_page':page,
                'rect':tuple(asset['rect']),'image_bytes':bytes(asset['image_bytes']),
                'image_operation':deepcopy(asset.get('image_operation')),
                'width_px':asset['width_px'],'height_px':asset['height_px'],
                'portable':True,'notice':asset.get('notice','')}
        return {'bundle':bundle,'image_bytes':bytes(asset.get('preview_png') or asset['image_bytes']),
                'notice':asset.get('notice','')}
    ids=list(ids or [])
    selected=model.selected(ids)
    if not selected or len(selected)!=len(set(ids)):
        raise EditError('Selecciona texto del PDF actual para copiar.')
    if any(g.mode != 0 or g.opacity <= 0 for g in selected):
        raise EditError('Selecciona texto visible para copiar como objeto editable.')
    payload=selection_payload(data,page,ids,session.resolver)
    runs=deepcopy(payload['runs'])
    # A model restricted to the selection still lets redaction check all
    # neighbours: _redact receives the complete model and selected separately.
    from dataclasses import replace
    subset=replace(model,glyphs=selected)
    fonts,errors=_copy_fonts(data,page,subset,runs,session.resolver)
    bundle={'version':BUNDLE_VERSION,'kind':'text','source_revision':model.revision,'source_page':page,
            'rect':tuple(payload['rect']),'runs':runs,'paragraphs':deepcopy(payload.get('paragraphs',[])),
            'fonts':fonts,'text':payload['text'],'portable':not errors,
            'font_error':' '.join(dict.fromkeys(errors))}
    return {'bundle':bundle,'text':payload['text'],'notice':
            ('La fuente sólo puede reutilizarse en una página con el recurso original verificado. '+bundle['font_error']) if errors else ''}


class _BundleResolver:
    """Reuse verified in-memory programs without paths into another installation."""
    def __init__(self, resolver, fonts):self.resolver=resolver;self.fonts=fonts
    def resolve(self,*args,**kwargs):return self.resolver.resolve(*args,**kwargs)
    def resolve_explicit(self,name,text,font_file=None):
        if not str(font_file or '').startswith('clipboard-font:'):
            return self.resolver.resolve_explicit(name,text,font_file)
        entry=self.fonts.get(str(font_file).split(':',1)[1])
        if not entry or not entry.get('portable'):
            raise FontError('La fuente copiada no está disponible con fidelidad. Importa y asocia la fuente exacta y copia de nuevo.')
        buffer=entry.get('buffer')
        base14=entry.get('base14')
        if buffer:
            metadata=_font_metadata(buffer,entry['name'])
            _check_embedding(metadata,entry['name'],bool(metadata.get('subset')))
            font=fitz.Font(fontbuffer=buffer)
        elif base14:
            from .fonts import BASE14
            if BASE14.get(entry['name']) != base14:
                raise FontError('La identidad de la fuente estándar copiada no es válida.')
            metadata={};font=fitz.Font(base14)
        else:
            raise FontError('El portapapeles no contiene el programa de la fuente exacta.')
        _check_characters(font,text,entry['name'])
        return ResolvedFont(entry['name'],font,buffer,base14,'portapapeles verificado',metadata)


def _paste_rect(bundle, point=None, rect=None):
    source=bundle.get('rect') or (0,0,200,40)
    if rect is None:
        x,y=point if point is not None else (source[0]+12,source[1]+12)
        rect=(x,y,x+source[2]-source[0],y+source[3]-source[1])
    if (len(rect)!=4 or any(not isinstance(v,(float,int)) or not math.isfinite(v) for v in rect)
            or rect[2]<=rect[0] or rect[3]<=rect[1]):
        raise EditError('El área donde se pega debe tener coordenadas finitas y dimensiones positivas.')
    return tuple(rect)


def _paste_text(data,page,bundle,rect,resolver,allow_overlap):
    runs=deepcopy(bundle.get('runs',[]));fonts=bundle.get('fonts',{})
    if not runs or not any(r.get('text','').strip() for r in runs):
        raise EditError('El portapapeles no contiene texto para pegar.')
    reader=PdfReader(BytesIO(data),strict=True)
    page_fonts=reader.pages[page].get('/Resources',{}).get('/Font',{})
    identities={_resource_identity(reader,page,str(resource)):str(resource) for resource in page_fonts}
    from .clipping import operator_glyph_map
    with fitz.open(stream=data,filetype='pdf') as doc:model=extract_page(doc,page,data)
    _,_,shows,_=operator_glyph_map(data,page,model)
    used_resources={s['resource'] for s in shows}
    for run in runs:
        token=run.pop('clipboard_font',None);entry=fonts.get(token,{})
        resource=identities.get(entry.get('identity'))
        if resource in used_resources:
            run.update(font_resource=resource,font_xref=None,font_file=None)
        elif entry.get('portable'):
            run.update(font_resource=None,font_xref=None,font_file='clipboard-font:'+str(token),font_name=entry['name'])
        else:
            raise EditError('No está disponible la fuente exacta «'+str(entry.get('name',run.get('font_name','')))+'». '
                            'Importa y asocia esa fuente y copia de nuevo. '+str(entry.get('error','')))
    request=RichTextRequest(page,[],runs,rect=rect,paragraphs=deepcopy(bundle.get('paragraphs',[])),
                           allow_overlap=allow_overlap,auto_width=False,auto_height=True)
    return edit_rich_pdf(data,request,_BundleResolver(resolver,fonts))


def apply_clipboard_v170(session, operation, page, revision=None, bundle=None, point=None, rect=None,
                         ids=None, image_id=None, allow_overlap=False, accessibility_order=None,
                         alt_text=None, decorative=False):
    """Validate first; install one history state only after every step succeeds."""
    session._writable();data=session.history.current;_revision(data,revision)
    if operation=='delete':
        if image_id is not None:
            from .media import delete_image_pdf
            candidate,report=delete_image_pdf(data,page,image_id,revision=revision)
            report['operation']='image_delete'
        elif ids:
            if has_rich_metadata(data,page):
                payload=selection_payload(data,page,ids,session.resolver)
                empty=[dict(r,text='') for r in payload['runs']]
                candidate,report=edit_rich_pdf(data,RichTextRequest(page,list(ids),empty,rect=payload['rect'],revision=revision),session.resolver)
            else:
                candidate,report=edit_pdf(data,EditRequest(page,list(ids),text='',revision=revision),session.resolver)
            report['operation']='clipboard_delete_text'
        else:raise EditError('Selecciona texto o una imagen para eliminar.')
    elif operation=='paste':
        if not isinstance(bundle,dict) or bundle.get('version')!=BUNDLE_VERSION:
            raise EditError('El contenido del portapapeles no es compatible con esta versión.')
        area=_paste_rect(bundle,point,rect)
        if bundle.get('kind')=='image':
            from .media import add_image_pdf, edit_image_pdf, image_items
            image_bytes=bundle.get('image_bytes')
            if not isinstance(image_bytes,bytes) or not image_bytes:raise EditError('El portapapeles no contiene una imagen válida.')
            candidate,report=add_image_pdf(data,page,image_bytes,area,revision=revision,
                                           accessibility_order=accessibility_order,alt_text=alt_text,decorative=decorative)
            if bundle.get('image_operation'):
                with fitz.open(stream=candidate,filetype='pdf') as doc:
                    inserted=next(i for i in reversed(image_items(doc,page)) if all(abs(a-b)<.04 for a,b in zip(i['rect'],area)))
                candidate,second=edit_image_pdf(candidate,page,inserted['id'],**bundle['image_operation'])
                report.update(destination_regions=[area],image_operation=second.get('image_operation'))
            report.update(operation='image_clipboard_paste',destination_regions=[area])
        elif bundle.get('kind')=='text':
            candidate,report=_paste_text(data,page,bundle,area,session.resolver,allow_overlap)
            report['operation']='clipboard_paste_text'
        elif bundle.get('kind')=='plain_text':
            from .composition import AddTextRequest, insert_text_pdf
            candidate,report=insert_text_pdf(data,AddTextRequest(page,area[0],area[1],area[2]-area[0],area[3]-area[1],
                bundle.get('text',''),font_name=bundle['font_name'],font_file=bundle.get('font_file'),
                allow_overlap=allow_overlap,accessibility_order=accessibility_order),session.resolver)
            report['operation']='clipboard_paste_text'
        else:raise EditError('El objeto del portapapeles no se puede pegar en el PDF.')
    else:raise EditError('Operación de portapapeles desconocida.')
    report.update(page=page,clipboard_operation=operation)
    session._mark_page_edit(report,page)
    # History.push writes a snapshot before touching redo. No pending preview is
    # published if either composition/validation or disk materialization fails.
    session.history.push(candidate,report);session._clear_cache()
    return {'state':session.state(),'report':report,'page':page}
