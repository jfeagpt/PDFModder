"""Final-order plans: intact PDF pages, explicit destinations and real Qt controls."""
from io import BytesIO
import json
from pathlib import Path

import pymupdf as fitz
from pypdf import PdfReader
import pytest
from PySide6.QtCore import QBuffer, QIODevice, QModelIndex, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QAbstractItemView, QDialog, QDialogButtonBox

from pdfmodder.engine import full_write
from pdfmodder.model import EditError, pt
from pdfmodder.page_organizer import PageOrganizerDialog
from pdfmodder.pageops import organize_pages_pdf
from test_pageops import fixture_pdf, texts


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def current(page, rotation=0):
    return dict(source="current", page=page, rotation=rotation)


def link_destinations(reader, page):
    result = []
    page_ids = {p.indirect_reference.idnum: n for n, p in enumerate(reader.pages)}
    for reference in reader.pages[page].get("/Annots", []):
        annotation = reference.get_object()
        action = annotation.get("/A", {})
        if hasattr(action, "get_object"):
            action = action.get_object()
        destination = annotation.get("/Dest", action.get("/D"))
        if destination is not None:
            result.append((page_ids[destination[0].idnum], list(destination[1:])))
    return result


def test_organizer_combines_reorder_rotate_duplicate_blank_and_pdf_without_pixel_changes():
    source, extra = fixture_pdf(), fixture_pdf("ANEXO", count=1, links=False)
    originals = bytes(source), bytes(extra)
    plan = [current(2, 90), current(0), dict(source="blank", width=210, height=300, rotation=0),
            dict(source="annex", page=0, rotation=270), current(1), current(0, 90)]
    output, report = organize_pages_pdf(source, plan, {"annex": extra})
    assert (source, extra) == originals
    assert report["verified"] and report["page_map"] == [2, 0, None, None, 1, 0]
    assert report["assignments"] == plan
    assert texts(output) == [texts(source)[2], texts(source)[0], "", texts(extra)[0], texts(source)[1], texts(source)[0]]
    assert all(page["max_channel_delta"] == 0 for page in report["pages"])
    with fitz.open(stream=source, filetype="pdf") as original, fitz.open(stream=output, filetype="pdf") as result:
        assert [page.rotation for page in result] == [180, 0, 0, 270, 0, 90]
        assert result[0].cropbox == original[2].cropbox
        assert result[2].mediabox == fitz.Rect(0, 0, 210, 300)
        assert result[1].get_links()[0]["page"] == result[5].get_links()[0]["page"] == 0
        assert result[0].get_links()[0]["page"] == 1
        assert result.get_toc() == [[1, "BASE inicio", 2], [2, "BASE detalle 2", 5],
                                    [2, "BASE detalle 3", 1], [1, "ANEXO inicio", 4]]
        assert result.metadata["title"] == original.metadata["title"]
        assert result.get_xml_metadata() == original.get_xml_metadata()
    before, after = PdfReader(BytesIO(source)), PdfReader(BytesIO(output))
    assert link_destinations(after, 1) == [(0, link_destinations(before, 0)[0][1])]
    assert link_destinations(after, 5) == [(0, link_destinations(before, 0)[0][1])]


def test_organizer_duplicate_self_links_and_popup_owners_belong_to_each_copy():
    with fitz.open(stream=fixture_pdf(links=False, count=1), filetype="pdf") as doc:
        doc[0].insert_link({"kind": fitz.LINK_GOTO, "page": 0, "from": fitz.Rect(50, 175, 120, 190),
                            "to": fitz.Point(50, 80), "zoom": 1.25})
        source = full_write(doc)
    result, _ = organize_pages_pdf(source, [current(0), current(0, 90), current(0, 180)])
    reader = PdfReader(BytesIO(result))
    for number, page in enumerate(reader.pages):
        assert link_destinations(reader, number)[0][0] == number
        annotations = [ref.get_object() for ref in page["/Annots"]]
        note = next(item for item in annotations if item["/Subtype"] == "/Text")
        popup = next(item for item in annotations if item["/Subtype"] == "/Popup")
        assert note.raw_get("/Popup") == popup.indirect_reference
        assert popup.raw_get("/Parent") == note.indirect_reference
        for item in annotations:
            if "/P" in item:
                assert item.raw_get("/P") == page.indirect_reference
    with fitz.open(stream=result, filetype="pdf") as doc:
        first_page = doc[0]
        first = next(first_page.annots())
        first.set_info(content="Sólo esta copia")
        first.update()
        changed = full_write(doc)
    with fitz.open(stream=changed, filetype="pdf") as reopened:
        pages = [reopened[index] for index in range(3)]
        assert next(pages[0].annots()).info["content"] == "Sólo esta copia"
        assert next(pages[1].annots()).info["content"] == "NOTA BASE 1"
        assert next(pages[2].annots()).info["content"] == "NOTA BASE 1"


def test_organizer_external_internal_links_map_to_their_source_and_exact_coordinates():
    base, addition = fixture_pdf("BASE", count=1, links=False), fixture_pdf("ANEXO")
    result, report = organize_pages_pdf(base, [dict(source="annex", page=2, rotation=90), current(0),
                                              dict(source="annex", page=0, rotation=270),
                                              dict(source="annex", page=1, rotation=0)], {"annex": addition})
    reader, original = PdfReader(BytesIO(result)), PdfReader(BytesIO(addition))
    assert link_destinations(reader, 0) == [(2, link_destinations(original, 2)[0][1])]
    assert link_destinations(reader, 2) == [(0, link_destinations(original, 0)[0][1])]
    assert report["page_map"] == [None, 0, None, None]
    assert all(page["max_channel_delta"] == 0 for page in report["pages"])


def test_organizer_full_page_image_vectors_font_programs_and_notes_are_unchanged():
    data = (EXAMPLES / "digital.pdf").read_bytes()
    output, report = organize_pages_pdf(data, [current(1), current(0, 90), current(0)])
    assert report["verified"]
    assert all(page["font_programs_equal"] for page in report["pages"])
    assert all(page["max_channel_delta"] == 0 for page in report["pages"])
    with fitz.open(stream=output, filetype="pdf") as doc:
        for index in (1, 2):
            assert len(doc[index].get_images()) == 1
            assert len(list(doc[index].annots())) == 1
            assert doc[index].get_links()[0]["uri"] == "https://example.org/pdf-modder"


def test_organizer_refuses_omitted_link_target_and_reports_omitted_bookmarks():
    with pytest.raises(EditError, match="enlace.*excluida"):
        organize_pages_pdf(fixture_pdf(), [current(0)])
    source = fixture_pdf(links=False)
    output, report = organize_pages_pdf(source, [current(2)])
    assert report["removed_bookmarks"] == ["BASE inicio", "BASE detalle 2"]
    with fitz.open(stream=output, filetype="pdf") as doc:
        assert doc.get_toc() == [[1, "BASE detalle 3", 1]]


@pytest.mark.parametrize("filename", ["form.pdf", "signature_marker_invalid.pdf", "encrypted.pdf", "restricted.pdf"])
def test_organizer_keeps_existing_protected_document_guards(filename):
    protected = (EXAMPLES / filename).read_bytes()
    with pytest.raises(EditError):
        organize_pages_pdf(protected, [current(0, 90)])
    with pytest.raises(EditError):
        organize_pages_pdf(fixture_pdf(links=False, count=1), [current(0), dict(source="extra", page=0, rotation=0)], {"extra": protected})


@pytest.mark.parametrize("plan", [[], [current(10)], [current(-1)], [current(True)], [current(0, 45)],
    [dict(source="missing", page=0, rotation=0)], [dict(source="blank", width=float("nan"), height=100, rotation=0)],
    [dict(source="blank", width=0, height=100, rotation=0)], [dict(source="blank", width=100, height=100, rotation=1)],
    [dict(source="current", page=0, rotation=0, unknown="never ignored")]])
def test_organizer_rejects_invalid_plans_before_producing_output(plan):
    with pytest.raises(EditError):
        organize_pages_pdf(fixture_pdf(links=False, count=1), plan)


def png():
    image = QImage(60, 80, QImage.Format_RGB32)
    image.fill(QColor("white"))
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def dialog_pages(with_png=True):
    return [dict(page=index, width=400, height=500, rotation=90 if index == 2 else 0,
                 **({"png": png()} if with_png else {})) for index in range(3)]


def test_dialog_real_controls_expose_final_order_and_serializable_plan(qtbot, monkeypatch):
    def cannot_open_pdf(*args, **kwargs):
        raise AssertionError("El diálogo no puede abrir el motor PDF")
    monkeypatch.setattr(fitz, "open", cannot_open_pdf)
    dialog = PageOrganizerDialog(dialog_pages())
    qtbot.addWidget(dialog)
    dialog.show()
    assert dialog.page_list.dragDropMode() == QAbstractItemView.InternalMove
    assert not dialog.apply_button.isEnabled()
    dialog.page_list.item(2).setSelected(True)
    qtbot.mouseClick(dialog.rotate_button, Qt.LeftButton)
    qtbot.mouseClick(dialog.up_button, Qt.LeftButton)
    assert dialog.plan() == [current(0), current(2, 90), current(1)]
    assert "giro final 180°" in dialog.page_list.item(1).text()
    qtbot.mouseClick(dialog.duplicate_button, Qt.LeftButton)
    assert dialog.plan() == [current(0), current(2, 90), current(2, 90), current(1)]
    assert "copia" in dialog.page_list.item(2).text()
    dialog.position_box.setValue(2)
    dialog.width_box.setValue(100)
    dialog.height_box.setValue(150)
    qtbot.mouseClick(dialog.blank_button, Qt.LeftButton)
    assert dialog.plan()[1] == dict(source="blank", width=pt(100), height=pt(150), rotation=0)
    assert [item["source"] for item in json.loads(json.dumps(dialog.plan()))] == ["current", "blank", "current", "current", "current"]
    assert all(dialog.page_list.item(index).text().startswith(f"{index+1} ·") for index in range(5))
    assert dialog.apply_button.isEnabled()
    qtbot.mouseClick(dialog.reset_button, Qt.LeftButton)
    assert dialog.plan() == [current(0), current(1), current(2)]
    assert not dialog.apply_button.isEnabled()


def test_dialog_internal_move_model_renumbers_without_losing_rotation_or_source(qtbot):
    dialog = PageOrganizerDialog(dialog_pages())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.page_list.item(0).setSelected(True)
    qtbot.mouseClick(dialog.rotate_button, Qt.LeftButton)
    assert dialog.page_list.model().moveRows(QModelIndex(), 0, 1, QModelIndex(), 3)
    assert dialog.plan() == [current(1), current(2), current(0, 90)]
    assert [dialog.page_list.item(index).text().split(" ·", 1)[0] for index in range(3)] == ["1", "2", "3"]


def test_dialog_import_is_async_and_can_recover_errors_without_losing_plan(qtbot, monkeypatch):
    import pdfmodder.page_organizer as ui
    dialog = PageOrganizerDialog(dialog_pages())
    qtbot.addWidget(dialog)
    received = []
    dialog.import_requested.connect(lambda paths, position: received.append((paths, position)))
    monkeypatch.setattr(ui.QFileDialog, "getOpenFileNames", lambda *args: (["C:/manual/anexo.pdf"], ""))
    dialog.position_box.setValue(2)
    dialog.import_button.click()
    assert received == [(["C:/manual/anexo.pdf"], 1)]
    assert not dialog.page_list.isEnabled() and not dialog.apply_button.isEnabled()
    original_plan = dialog.plan()
    dialog.set_error("El PDF añadido contiene campos de formulario")
    assert dialog.page_list.isEnabled() and dialog.plan() == original_plan
    assert "campos de formulario" in dialog.status_label.text()
    dialog.add_source("extra-1", [dict(page=0, width=200, height=300, rotation=270, png=png())], "Anexo", 1)
    assert dialog.plan()[1] == dict(source="extra-1", page=0, rotation=0)
    assert "Anexo" in dialog.page_list.item(1).text()
    assert "giro final 270°" in dialog.page_list.item(1).text()
    assert dialog.apply_button.isEnabled()


def test_dialog_thumbnails_are_requested_serially_for_visible_pages(qtbot):
    dialog = PageOrganizerDialog(dialog_pages(False))
    qtbot.addWidget(dialog)
    received = []
    dialog.thumbnail_requested.connect(lambda source, page: received.append((source, page)))
    dialog.show()
    qtbot.waitUntil(lambda: len(received) == 1)
    first = received[0]
    assert first == ("current", 0)
    assert dialog.page_list.item(0).icon().isNull()
    dialog.set_thumbnail(*first, png())
    qtbot.waitUntil(lambda: len(received) == 2)
    assert received[1] == ("current", 1)
    assert not dialog.page_list.item(0).icon().isNull()


def test_dialog_cancel_and_remove_all_do_not_accept_an_invalid_plan(qtbot):
    dialog = PageOrganizerDialog(dialog_pages())
    qtbot.addWidget(dialog)
    dialog.page_list.selectAll()
    dialog.remove_button.click()
    assert len(dialog.plan()) == 3 and "al menos una" in dialog.status_label.text()
    dialog.rotate_button.click()
    assert dialog.apply_button.isEnabled()
    dialog.buttons.button(QDialogButtonBox.Cancel).click()
    assert dialog.result() == QDialog.Rejected
