"""Shared MangaDex-style cover-grid list widget: cover thumbnail with a
caption underneath, selection shown as a border around the cover rather
than a color wash over it (so clicking a book never visibly changes its
artwork), plus an optional reading-progress bar. Used by both the
translated-books library tab and the tracked-webnovels list so they
look and behave the same way instead of each rolling their own grid.
"""
from PyQt6.QtCore import QMimeData, QRect, QRectF, QSize, Qt, QUrl
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QLabel, QListView, QListWidget, QSizePolicy, QStyle, QStyledItemDelegate)

from ..core.cover_extract import extract_cover_bytes
from ..formats.cover_generator import generate_cover_bytes

COVER_SIZE = QSize(132, 180)
GRID_SIZE = QSize(158, 234)
ACCENT_COLOR = '#5B9BD1'


class CoverItemDelegate(QStyledItemDelegate):
    TEXT_HEIGHT = 48
    PROGRESS_BAR_HEIGHT = 5
    PROGRESS_BAR_MARGIN = 6

    def __init__(self, parent=None, progress_lookup=None):
        super().__init__(parent)
        # Optional callable(path) -> float|None for a thin "how far
        # read" bar over the cover's bottom edge -- only meaningful for
        # the translated-books library, so the tracked-novels grid just
        # leaves this unset.
        self.progress_lookup = progress_lookup

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Slightly smaller than the default UI font so two-line titles
        # still fit inside TEXT_HEIGHT without wrapping onto a third
        # line and getting clipped.
        font = painter.font()
        font.setPointSize(max(8, font.pointSize() - 1))
        painter.setFont(font)

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        title = index.data(Qt.ItemDataRole.DisplayRole) or ''
        path = index.data(Qt.ItemDataRole.UserRole)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)

        cell_rect = option.rect
        icon_rect = QRect(
            cell_rect.x(), cell_rect.y(), cell_rect.width(),
            cell_rect.height() - self.TEXT_HEIGHT)
        text_rect = QRect(
            cell_rect.x(), icon_rect.bottom(), cell_rect.width(),
            self.TEXT_HEIGHT)

        cover_rect = None
        if icon is not None and not icon.isNull():
            pixmap = icon.pixmap(icon_rect.size())
            cover_rect = QRect(0, 0, pixmap.width(), pixmap.height())
            cover_rect.moveCenter(icon_rect.center())
            painter.drawPixmap(cover_rect, pixmap)

        if cover_rect is not None and path and self.progress_lookup:
            fraction = self.progress_lookup(path)
            if fraction is not None:
                self._draw_progress_bar(painter, cover_rect, fraction)

        if is_selected:
            pen = QPen(QColor(ACCENT_COLOR))
            pen.setWidth(3)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(icon_rect.adjusted(1, 1, -1, -1), 8, 8)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT_COLOR))
            painter.drawRoundedRect(text_rect.adjusted(4, 2, -4, -2), 6, 6)
            painter.setPen(QColor('white'))
        else:
            painter.setPen(
                option.palette.color(option.palette.ColorRole.Text))

        painter.drawText(
            text_rect.adjusted(4, 2, -4, -2),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            title)

        painter.restore()

    def _draw_progress_bar(self, painter, cover_rect, fraction):
        margin = self.PROGRESS_BAR_MARGIN
        height = self.PROGRESS_BAR_HEIGHT
        track_rect = QRectF(
            cover_rect.x() + margin, cover_rect.bottom() - margin - height,
            cover_rect.width() - 2 * margin, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 20, 30, 170))
        painter.drawRoundedRect(track_rect, height / 2, height / 2)

        fill_rect = QRectF(
            track_rect.x(), track_rect.y(), track_rect.width() * fraction,
            height)
        painter.setBrush(QColor(ACCENT_COLOR))
        painter.drawRoundedRect(fill_rect, height / 2, height / 2)

    def sizeHint(self, option, index):
        return GRID_SIZE


class DraggableListWidget(QListWidget):
    """Standard Qt drag-export pattern: the dragged item's file path goes
    out as a file URL, and Explorer/the desktop handles the actual copy.
    """

    def mimeData(self, items):
        mime = QMimeData()
        mime.setUrls([
            QUrl.fromLocalFile(item.data(Qt.ItemDataRole.UserRole))
            for item in items])
        return mime


def build_cover_list_widget(parent=None, draggable=False, progress_lookup=None):
    """Returns a QListWidget pre-configured for the cover-grid look --
    callers just addItem() QListWidgetItems with an icon, a title, and
    Qt.ItemDataRole.UserRole set to the item's file path.
    """
    list_widget = (DraggableListWidget if draggable else QListWidget)(parent)
    list_widget.setViewMode(QListView.ViewMode.IconMode)
    list_widget.setMovement(QListView.Movement.Static)
    list_widget.setResizeMode(QListView.ResizeMode.Adjust)
    list_widget.setIconSize(COVER_SIZE)
    list_widget.setGridSize(GRID_SIZE)
    list_widget.setSpacing(10)
    list_widget.setUniformItemSizes(True)
    list_widget.setItemDelegate(
        CoverItemDelegate(list_widget, progress_lookup=progress_lookup))
    if draggable:
        list_widget.setDragEnabled(True)
    return list_widget


def build_cover_icon(cache_key, title, cover_source_path, cache, widget=None):
    """Returns a cached QIcon: the EPUB's own embedded cover if
    cover_source_path points at one, otherwise a generated placeholder.

    cache_key and cover_source_path are separate on purpose -- the
    translated-books library keys its cache by the book's own path (so
    they're the same value there), but the tracked-webnovels list keys
    entries by source URL while the actual cover lives in a different
    output_path, so it needs to cache under one value while extracting
    from another.

    cache is a plain dict the caller owns (cache_key -> QIcon) -- covers
    don't change once a file is recorded, so callers keep this across
    refresh() calls instead of re-extracting/re-decoding every time.
    widget (optional) just supplies the platform's generic file icon as
    a last resort if even the placeholder generator fails.
    """
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    cover_bytes = None
    if cover_source_path and cover_source_path.lower().endswith('.epub'):
        cover_bytes = extract_cover_bytes(cover_source_path)
    if not cover_bytes:
        try:
            cover_bytes = generate_cover_bytes(title)
        except Exception:
            cover_bytes = None

    icon = icon_from_cover_bytes(cover_bytes, widget=widget)
    cache[cache_key] = icon
    return icon


def icon_from_cover_bytes(cover_bytes, widget=None):
    """Scales raw cover image bytes (real or generated-placeholder) down
    to COVER_SIZE and wraps them as a QIcon. widget (optional) supplies
    the platform's generic file icon as a last resort when there are no
    usable bytes at all.
    """
    pixmap = QPixmap()
    if cover_bytes:
        pixmap.loadFromData(cover_bytes)
    if pixmap.isNull():
        return (
            widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            if widget is not None else QIcon())
    scaled = pixmap.scaled(
        COVER_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    return QIcon(scaled)


def build_placeholder_icon(title, widget=None):
    """A generated cover for things that aren't backed by a local file
    at all yet -- e.g. a search result whose real cover hasn't finished
    downloading (or never had one).
    """
    try:
        cover_bytes = generate_cover_bytes(title)
    except Exception:
        cover_bytes = None
    return icon_from_cover_bytes(cover_bytes, widget=widget)


class ResponsiveCoverLabel(QLabel):
    """A single, larger cover preview (novel-info panes, not the grid)
    that grows with whatever space its layout gives it -- a fixed pixel
    size either looked tiny on a maximized window or cramped on a small
    one. Keeps the cover's own aspect ratio instead of QLabel's
    setScaledContents(), which would stretch it to fill the box exactly
    and distort the artwork whenever the box isn't the same proportions
    as the cover.
    """

    def __init__(self, parent=None, max_size=QSize(280, 400)):
        super().__init__(parent)
        self._original = QPixmap()
        self._max_size = max_size
        self.setMinimumSize(90, 128)
        # Capped at max_size so Qt's layout stops handing this label
        # extra room once it's already as big as it'll ever render --
        # past that point a sibling with its own stretch (e.g. the
        # title/author text next to it) gets the leftover space instead
        # of it sitting unused as blank margin around the image.
        self.setMaximumSize(max_size)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

    def setCoverPixmap(self, pixmap):
        self._original = pixmap
        # The #coverPlaceholder QSS rule paints a flat fill so an empty
        # cover slot doesn't look broken -- but once a real, aspect-fit
        # cover is showing, that same fill shows through as an ugly
        # solid block wherever the image is narrower or shorter than the
        # box the layout gave this label. Clearing it per-instance (the
        # shared theme files stay untouched) only kicks in once there's
        # an actual cover to show.
        self.setStyleSheet(
            '' if pixmap.isNull() else 'background: transparent;')
        self._rescale()

    def clear(self):
        self._original = QPixmap()
        self.setStyleSheet('')
        super().clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._original.isNull():
            self.setPixmap(QPixmap())
            return
        target = self.size().boundedTo(self._max_size)
        scaled = self._original.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
