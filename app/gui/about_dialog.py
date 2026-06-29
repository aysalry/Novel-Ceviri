from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from ..core.i18n import _
from ..core.version import APP_VERSION


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_('Hakkında'))
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        title = QLabel('Novel Çeviri')
        title.setObjectName('aboutTitle')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        version = QLabel(_('Sürüm {}').format(APP_VERSION))
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(version)

        description = QLabel(_(
            'Webnovel ve lightnovel çevirisi için bağımsız bir araç. '
            'Google, Microsoft Edge, DeepL, Gemini, OpenAI, Claude, '
            'OpenRouter ve özel API\'lerle EPUB, TXT ve SRT dosyalarını '
            'çevirir; novelfire.net, novelight.net ve novelbuddy.com gibi '
            'sitelerden de doğrudan roman indirebilir.'))
        description.setWordWrap(True)
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(description)

        credit = QLabel(_(
            'Çeviri motoru ve içerik çıkarma mantığı, bookfere.com '
            'tarafından geliştirilen açık kaynaklı "Ebook Translator" '
            'Calibre eklentisinden (GPLv3) uyarlanmıştır. Roman indirme '
            'özelliği, dteviot\'un "WebToEpub" (GPLv3) ve kodjodevf\'in '
            '"Mangayomi" (Apache 2.0) projelerinden esinlenerek '
            'sıfırdan yazılmıştır.'))
        credit.setWordWrap(True)
        credit.setObjectName('hintLabel')
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(credit)

        license_label = QLabel(_(
            'Bu program GPLv3 lisansı ile dağıtılmaktadır.'))
        license_label.setWordWrap(True)
        license_label.setObjectName('hintLabel')
        license_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(license_label)

        close_btn = QPushButton(_('Kapat'))
        close_btn.setObjectName('primaryButton')
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignCenter)
