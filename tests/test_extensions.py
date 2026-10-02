"""Session integration across typography, images, page maps and safe exports."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
import pymupdf as fitz
from pypdf import PdfReader
import pytest

from pdfmodder.model import EditError
from pdfmodder.worker import Session


ROOT = Path(__file__).resolve().parents[1]


def image_bytes():
    image = Image.new("RGB", (80, 60), "#c52f3d")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 71, 51), outline="#f9e268", width=5)
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.fixture
def session(tmp_path):
    source = tmp_path / "original.pdf"
    source.write_bytes((ROOT / "examples/digital.pdf").read_bytes())
    history = tmp_path / "history"
    history.mkdir()
    value = Session(source, config_path=tmp_path / "fonts.json", history_dir=history)
    yield value
    value.close()


def chosen_image(session, rect):
    matches = [item for item in session.page(0)["images"] if all(abs(a-b) < .04 for a, b in zip(item["rect"], rect))]
    assert len(matches) == 1
    assert matches[0]["editable"], matches[0]["reason"]
    return matches[0]


def test_session_font_text_image_move_resize_save_and_reopen(session, tmp_path):
    original = session.original
    initial_hash = sha256(original).hexdigest()
    session.insert_text({"page": 0, "x": 48, "y": 690, "width": 310, "height": 32,
                         "text": "Añadido: café, piñón y 25,50 €", "font_name": "LiberationSans",
                         "font_file": str(ROOT / "assets/fonts/LiberationSans-Regular.ttf"),
                         "size": 11.25, "color": (.55, .05, .12),
                         "revision": session.page(0)["model"].revision})
    assert session.state()["preview"] and session.state()["history_index"] == 0
    assert session.history.current == original
    session.commit()
    assert session.state()["history_index"] == 1

    inserted = (440, 700, 500, 745)
    session.image_operation("add", 0, rect=inserted, image_bytes=image_bytes(), revision=session.page(0)["model"].revision)
    assert session.state()["preview"]
    session.commit()
    item = chosen_image(session, inserted)
    moved = (360, 685, 420, 730)
    session.image_operation("transform", 0, image_id=item["id"], rect=moved, revision=session.page(0)["model"].revision)
    session.commit()
    item = chosen_image(session, moved)
    resized = (360, 685, 444, 748)
    session.image_operation("transform", 0, image_id=item["id"], rect=resized, revision=session.page(0)["model"].revision)
    session.commit()
    assert session.state()["history_index"] == 4
    assert len(session.page(0)["images"]) == 2

    destination = tmp_path / "text-and-image.pdf"
    session.save(destination)
    assert not session.state()["dirty"]
    reader = PdfReader(destination, strict=True)
    assert "Añadido: café, piñón y 25,50 €" in reader.pages[0].extract_text()
    assert reader.pages[1].extract_text() == PdfReader(BytesIO(original)).pages[1].extract_text()
    assert sha256(Path(session.path).read_bytes()).hexdigest() == initial_hash
    with fitz.open(destination) as pdf:
        assert len(pdf[0].get_image_info()) == 2
        matches = [item for item in pdf[0].get_image_info() if tuple(item["bbox"]) == pytest.approx(resized, abs=.04)]
        assert len(matches) == 1
        assert matches[0]["width"] == 80 and matches[0]["height"] == 60

    reopened_history = tmp_path / "reopened-history"
    reopened_history.mkdir()
    reopened = Session(destination, config_path=tmp_path / "reopened-fonts.json", history_dir=reopened_history)
    try:
        chosen_image(reopened, resized)
        reopened.insert_text({"page": 0, "x": 48, "y": 737, "width": 240, "height": 25,
                              "text": "Nueva edición tras reabrir", "font_name": "Helvetica", "size": 10.5})
        reopened.commit()
        assert "Nueva edición tras reabrir" in PdfReader(BytesIO(reopened.history.current)).pages[0].extract_text()
        assert reopened.state()["history_index"] == 1
    finally:
        reopened.close()


def test_session_delete_undo_redo_extract_no_change_and_original_mapping(session, tmp_path):
    original = session.original
    source_second_page = PdfReader(BytesIO(original)).pages[1].extract_text()
    session.delete_pages("1")
    deleted_bytes = session.history.current
    assert session.state()["page_count"] == 1
    assert session.state()["original_pages"] == [1]
    assert source_second_page == PdfReader(BytesIO(deleted_bytes)).pages[0].extract_text()
    original_view = session.page(0, original=True)
    assert original_view["model"].number == 1
    assert "PÁGINA" in "".join(g.text for g in original_view["model"].glyphs)
    session.navigate_history()
    assert session.history.current == original
    assert session.state()["original_pages"] == [0, 1]
    session.navigate_history(redo=True)
    assert session.history.current == deleted_bytes
    assert session.state()["original_pages"] == [1]

    unchanged_state = dict(session.state())
    extracted = tmp_path / "extracted.pdf"
    session.extract_pages("1", extracted)
    assert session.history.current == deleted_bytes
    assert session.state() == unchanged_state
    assert PdfReader(extracted).pages[0].extract_text() == source_second_page

    added = tmp_path / "rotated-source.pdf"
    added.write_bytes((ROOT / "examples/rotated_crop.pdf").read_bytes())
    session.merge([added])
    assert session.state()["page_count"] == 2
    assert session.state()["original_pages"] == [1, None]
    assert session.page(1)["model"].rotation == 90
    with pytest.raises(EditError, match="no existe en el original"):
        session.page(1, original=True)
    assert session.page(0, original=True)["model"].number == 1
    session.navigate_history()
    assert session.history.current == deleted_bytes
    assert session.state()["original_pages"] == [1]
    session.navigate_history(redo=True)
    assert session.state()["original_pages"] == [1, None]


def test_session_save_and_extract_protect_every_merged_source_after_undo(session, tmp_path):
    additions = [tmp_path / "first-added.pdf", tmp_path / "second-added.pdf"]
    additions[0].write_bytes((ROOT / "examples/rotated_crop.pdf").read_bytes())
    additions[1].write_bytes((ROOT / "examples/digital.pdf").read_bytes())
    originals = {Path(session.path): session.original, **{path: path.read_bytes() for path in additions}}
    session.merge(additions)
    assert session.state()["page_count"] == 5
    assert session.state()["original_pages"] == [0, 1, None, None, None]
    session.navigate_history()
    current = session.history.current
    for source in originals:
        with pytest.raises(EditError, match="original"):
            session.save(source)
        with pytest.raises(EditError, match="original"):
            session.extract_pages("1", source)
    assert session.history.current == current
    assert all(path.read_bytes() == content for path, content in originals.items())
    session.navigate_history(redo=True)
    output = tmp_path / "joined-copy.pdf"
    session.save(output)
    assert len(PdfReader(output).pages) == 5
    assert all(path.read_bytes() == content for path, content in originals.items())
