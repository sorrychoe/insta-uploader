"""Korean desktop UI; only worker threads perform network operations."""
import json
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QDate, QSize, Qt, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import ai
import instagram
import storage
from images import EXTENSIONS, prepare_image


class Worker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.progress.emit))
        except ValueError as error:
            self.error.emit(str(error))
        except Exception:
            # External exceptions can contain URLs, tokens, or response bodies.
            self.error.emit("작업을 완료하지 못했습니다. 연결 상태와 저장 공간을 확인해 주세요. 입력 내용은 유지됩니다.")


class PhotoList(QListWidget):
    changed = Signal()
    problem = Signal(str)

    def __init__(self):
        super().__init__()
        self.setIconSize(QSize(96, 96))
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setMinimumWidth(250)
        self.setAccessibleName("사진 목록: 드래그로 순서 변경")
        self.model().rowsMoved.connect(lambda *_: self.changed.emit())

    def paths(self):
        return [self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count())]

    def add_paths(self, paths):
        errors = []
        for path in paths:
            path = Path(path).resolve()
            if str(path) in self.paths():
                continue
            if self.count() >= 10:
                errors.append("사진은 최대 10장까지 선택할 수 있습니다.")
                break
            if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                errors.append("JPG 또는 PNG 파일만 선택해 주세요.")
                continue
            try:
                thumbnail = QPixmap()
                thumbnail.loadFromData(prepare_image(path), "JPEG")
                item = QListWidgetItem(QIcon(thumbnail), path.name)
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(str(path))
                self.addItem(item)
            except ValueError as error:
                errors.append(str(error))
        self.changed.emit()
        if errors:
            self.problem.emit("\n".join(dict.fromkeys(errors)))

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            self.add_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def remove_selected(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))
        self.changed.emit()

    def move_selected(self, offset):
        row = self.currentRow()
        if 0 <= row + offset < self.count() and row >= 0:
            item = self.takeItem(row)
            self.insertItem(row + offset, item)
            self.setCurrentRow(row + offset)
            self.changed.emit()


def button(text, handler, layout):
    widget = QPushButton(text)
    widget.clicked.connect(handler)
    layout.addWidget(widget)
    return widget


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("인스타 업로더")
        self.resize(1120, 840)
        self.config = storage.load_config()
        self.worker = None
        self.callback = None
        self.setCentralWidget(QWidget())
        layout = QVBoxLayout(self.centralWidget())
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.build_editor()
        self.build_history()
        self.build_settings()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.statusBar().showMessage("사진을 선택하고 제품 정보를 입력해 주세요.")
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(500)
        self.draft_timer.timeout.connect(self.save_draft)
        for field in [*self.fields.values(), self.caption, self.hashtags]:
            field.textChanged.connect(self.editor_changed)
        self.tone.currentTextChanged.connect(self.editor_changed)
        self.use_image.toggled.connect(self.editor_changed)
        self.photos.changed.connect(self.editor_changed)
        self.photos.changed.connect(self.update_preview)
        self.photos.currentItemChanged.connect(self.update_preview)
        self.restore_draft()
        self.refresh_history()
        self.editor_changed()
        self.token_timer = QTimer(self)
        self.token_timer.setInterval(60 * 60 * 1000)
        self.token_timer.timeout.connect(self.check_token)
        self.token_timer.start()
        QTimer.singleShot(100, self.check_token)

    def build_editor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        split = QSplitter()
        layout.addWidget(split)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("사진 1~10장 · 파일을 끌어 놓으세요"))
        self.photos = PhotoList()
        self.photos.problem.connect(self.show_error)
        left_layout.addWidget(self.photos)
        actions = QHBoxLayout()
        button("사진 선택", self.choose_photos, actions)
        button("선택 삭제", self.photos.remove_selected, actions)
        button("위로", lambda: self.photos.move_selected(-1), actions)
        button("아래로", lambda: self.photos.move_selected(1), actions)
        left_layout.addLayout(actions)
        left_layout.addWidget(QLabel("게시 사진 미리보기 · 여러 장은 정사각 여백 적용"))
        self.preview = QLabel("사진을 선택해 주세요")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(230)
        left_layout.addWidget(self.preview)
        split.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        form = QFormLayout()
        self.fields = {}
        for key, label in [("name", "제품명 *"), ("features", "핵심 특징 *"), ("price", "가격"),
                           ("target", "타깃 고객"), ("store_link", "스토어 링크"), ("requests", "추가 요청")]:
            field = QPlainTextEdit() if key in {"features", "requests"} else QLineEdit()
            if isinstance(field, QPlainTextEdit):
                field.setMaximumHeight(75)
            self.fields[key] = field
            form.addRow(label, field)
        self.tone = QComboBox()
        self.tone.addItems(ai.TONES)
        self.tone.setCurrentText(self.config["tone"])
        form.addRow("말투 *", self.tone)
        self.use_image = QCheckBox("대표 사진을 AI에 전송해 참고 (추가 비용)")
        form.addRow(self.use_image)
        right_layout.addLayout(form)
        self.generate_button = button("소개글·해시태그 생성", self.generate, right_layout)
        right_layout.addWidget(QLabel("소개글 · 직접 수정할 수 있습니다"))
        self.caption = QPlainTextEdit()
        self.caption.setAccessibleName("소개글")
        right_layout.addWidget(self.caption)
        right_layout.addWidget(QLabel("해시태그 · 공백으로 구분"))
        self.hashtags = QPlainTextEdit()
        self.hashtags.setAccessibleName("해시태그")
        self.hashtags.setMaximumHeight(85)
        right_layout.addWidget(self.hashtags)
        self.counter = QLabel()
        self.counter.setWordWrap(True)
        right_layout.addWidget(self.counter)
        actions = QHBoxLayout()
        button("다시 생성", self.generate, actions)
        self.upload_button = button("업로드", self.upload, actions)
        right_layout.addLayout(actions)
        self.result_link = QLabel()
        self.result_link.setTextFormat(Qt.TextFormat.PlainText)
        self.result_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_layout.addWidget(self.result_link)
        button("게시물 열기", self.open_result, right_layout)
        self.last_link = ""
        split.addWidget(right)
        split.setStretchFactor(1, 2)
        self.tabs.addTab(page, "새 게시물")

    def build_history(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(["일시", "제품명", "상태", "게시물 링크"])
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.itemSelectionChanged.connect(self.history_selected)
        layout.addWidget(self.history_table)
        self.history_detail = QPlainTextEdit()
        self.history_detail.setReadOnly(True)
        self.history_detail.setAccessibleName("게시 기록 상세")
        layout.addWidget(self.history_detail)
        actions = QHBoxLayout()
        button("새로고침", self.refresh_history, actions)
        button("제품 정보 불러오기 / 재시도", self.reuse_history, actions)
        button("게시물 열기", self.open_history, actions)
        layout.addLayout(actions)
        self.tabs.addTab(page, "기록")

    def build_settings(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel("Instagram Login용 장기 토큰을 사용하세요.\n"
                      "비밀값은 Windows 자격 증명 관리자에 저장됩니다. 빈칸은 기존 값을 유지합니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.settings = {}
        for key, label in [
            ("openai_key", "OpenAI API 키"), ("model", "OpenAI 모델"),
            ("ig_user_id", "인스타 계정 ID"), ("ig_token", "인스타 장기 액세스 토큰"),
            ("graph_version", "인스타 API 버전"), ("cloud_name", "Cloudinary 클라우드 이름"),
            ("cloud_api_key", "Cloudinary API 키"), ("cloud_api_secret", "Cloudinary API 비밀키"),
            ("fixed_hashtags", "고정 해시태그"),
        ]:
            field = QLineEdit()
            if key in storage.SECRET_NAMES:
                field.setEchoMode(QLineEdit.EchoMode.Password)
                field.setPlaceholderText("새 값 입력 / 빈칸이면 기존 값 유지")
            else:
                field.setText(self.config[key])
            self.settings[key] = field
            form.addRow(label, field)
        self.expiry = QDateEdit()
        self.expiry.setCalendarPopup(True)
        self.expiry.setDisplayFormat("yyyy-MM-dd")
        self.expiry.setDate(QDate.currentDate().addDays(60))
        if self.config["token_expires_at"]:
            self.expiry.setDate(QDate.fromString(self.config["token_expires_at"][:10], "yyyy-MM-dd"))
        form.addRow("토큰 실제 만료일 (발급 화면에서 확인)", self.expiry)
        self.default_tone = QComboBox()
        self.default_tone.addItems(ai.TONES)
        self.default_tone.setCurrentText(self.config["tone"])
        form.addRow("기본 말투", self.default_tone)
        layout.addLayout(form)
        button("설정 저장", self.save_settings, layout)
        button("저장 후 연결 테스트", self.test_connections, layout)
        guide = QLabel(
            "최초 설정\n"
            "1. 인스타 계정을 비즈니스 또는 크리에이터로 전환합니다.\n"
            "2. Meta 개발자 앱에 Instagram 제품을 추가하고 본인 계정을 연결합니다.\n"
            "3. instagram_business_basic, instagram_business_content_publish 권한의 장기 토큰을 발급합니다.\n"
            "4. OpenAI API 키와 결제 설정, Cloudinary 클라우드 이름·키·비밀키를 준비합니다.\n"
            "5. 위 값을 저장하고 연결 테스트를 실행합니다.\n\n"
            "연결 테스트는 Cloudinary에 작은 테스트 사진을 업로드한 뒤 삭제합니다.\n"
            "토큰은 앱 실행 중과 게시 전에 만료 7일 이내이면 자동 갱신합니다.\n"
            "앱이 꺼져 있는 동안에는 갱신되지 않습니다."
        )
        guide.setWordWrap(True)
        layout.addWidget(guide)
        layout.addStretch()
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "설정")

    def product(self):
        return {**{key: (field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()).strip()
                    for key, field in self.fields.items()}, "tone": self.tone.currentText()}

    def draft(self):
        return {"product": self.product(), "images": self.photos.paths(), "caption": self.caption.toPlainText(),
                "hashtags": self.hashtags.toPlainText(), "use_image": self.use_image.isChecked()}

    def restore_draft(self):
        draft = storage.read_json("draft.json", {})
        self.load_editor(draft)

    def load_editor(self, draft):
        for key, field in self.fields.items():
            text = draft.get("product", {}).get(key, "")
            field.setPlainText(text) if isinstance(field, QPlainTextEdit) else field.setText(text)
        self.tone.setCurrentText(draft.get("product", {}).get("tone", self.config["tone"]))
        self.caption.setPlainText(draft.get("caption", ""))
        self.hashtags.setPlainText(draft.get("hashtags", ""))
        self.use_image.setChecked(draft.get("use_image", False))
        self.photos.clear()
        paths = draft.get("images", [])
        self.photos.add_paths([p for p in paths if Path(p).is_file()])
        if any(not Path(p).is_file() for p in paths):
            self.statusBar().showMessage("이전 사진 중 찾을 수 없는 파일이 있습니다. 다시 선택해 주세요.")

    @Slot()
    def editor_changed(self):
        try:
            text = ai.assemble_caption(self.caption.toPlainText(), self.hashtags.toPlainText())
            count = len(ai.TAG_PATTERN.findall(text))
            message = f"글자수 {len(text):,}/2,200 · 해시태그 {count}/30"
            ai.validate_caption(text)
            valid = True
        except ValueError as error:
            message, valid = str(error), False
        self.counter.setText(message)
        self.upload_button.setEnabled(valid and bool(self.photos.count()))
        self.draft_timer.start()

    @Slot()
    def save_draft(self):
        try:
            storage.write_json("draft.json", self.draft())
        except OSError:
            self.statusBar().showMessage("작성 내용을 저장하지 못했습니다. 저장 공간을 확인해 주세요.")

    def choose_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "제품 사진 선택", "", "사진 (*.jpg *.jpeg *.png)")
        self.photos.add_paths(paths)

    def update_preview(self, *_):
        paths = self.photos.paths()
        if not paths:
            self.preview.clear()
            self.preview.setText("사진을 선택해 주세요")
            return
        row = max(0, self.photos.currentRow())
        try:
            pixmap = QPixmap()
            pixmap.loadFromData(prepare_image(paths[row], ratio=1 if len(paths) > 1 else None), "JPEG")
            self.preview.setPixmap(pixmap.scaled(300, 230, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
        except ValueError:
            self.preview.setText("사진을 다시 선택해 주세요")

    def run_job(self, operation, callback):
        if self.worker is not None:
            return
        self.save_draft()
        self.callback = callback
        self.tabs.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage("작업 중입니다…")
        self.worker = Worker(operation, self)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.result.connect(self.job_result)
        self.worker.error.connect(self.show_error)
        self.worker.finished.connect(self.job_finished)
        self.worker.start()

    @Slot(object)
    def job_result(self, result):
        self.callback(result)

    @Slot()
    def job_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.tabs.setEnabled(True)
        self.progress.hide()
        self.sync_expiry()
        self.editor_changed()

    @Slot(str)
    def show_error(self, message):
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "확인이 필요합니다", message)
        if any(word in message for word in ("OpenAI", "설정", "토큰", "자격 증명")):
            self.tabs.setCurrentIndex(2)

    def generate(self):
        product, paths = self.product(), self.photos.paths()
        try:
            ai.validate_product(product)
            if self.use_image.isChecked() and not paths:
                raise ValueError("AI가 참고할 대표 사진을 먼저 선택해 주세요.")
        except ValueError as error:
            self.show_error(str(error))
            return
        use_image = self.use_image.isChecked()
        def operation(progress):
            progress("AI가 소개글과 해시태그를 작성하고 있습니다")
            return ai.generate(product, storage.load_config(), storage.get_secret("openai_key"),
                               prepare_image(paths[0]) if use_image else None)
        self.run_job(operation, self.generated)

    def generated(self, result):
        self.caption.setPlainText(result["caption"])
        self.hashtags.setPlainText(" ".join(result["hashtags"]))
        self.statusBar().showMessage("소개글을 생성했습니다. 내용과 사실 여부를 확인해 주세요.")

    def upload(self):
        try:
            product, paths = self.product(), self.photos.paths()
            ai.validate_product(product)
            caption = ai.assemble_caption(self.caption.toPlainText(), self.hashtags.toPlainText())
            ai.validate_caption(caption)
            if not paths:
                raise ValueError("사진을 선택해 주세요.")
        except ValueError as error:
            self.show_error(str(error))
            return
        preview = QMessageBox(self)
        preview.setWindowTitle("인스타그램 게시 확인")
        preview.setTextFormat(Qt.TextFormat.PlainText)
        preview.setText(f"사진 {len(paths)}장과 아래 내용으로 게시합니다.\n\n{caption}")
        publish = preview.addButton("게시하기", QMessageBox.ButtonRole.AcceptRole)
        cancel = preview.addButton("돌아가기", QMessageBox.ButtonRole.RejectRole)
        preview.setDefaultButton(cancel)
        preview.exec()
        if preview.clickedButton() is publish:
            self.run_job(lambda progress: instagram.upload_post(product, paths, caption, progress), self.uploaded)

    def uploaded(self, result):
        self.last_link = result["permalink"]
        self.result_link.setText(self.last_link or (f"게시물 ID: {result['media_id']}" if result["media_id"] else ""))
        self.refresh_history()
        self.statusBar().showMessage(f"게시 결과: {result['status']}")
        self.upload_button.setText("재시도" if result["status"] == "실패" else "업로드")
        message = f"게시 결과: {result['status']}\n{result['permalink']}\n{result['detail']}"
        if result["status"] == "성공":
            QMessageBox.information(self, "게시 완료", message)
        else:
            self.show_error(message)

    def open_result(self):
        if self.last_link:
            QDesktopServices.openUrl(QUrl(self.last_link))

    def refresh_history(self):
        self.records = storage.history()
        self.history_table.setRowCount(0)
        for row, record in enumerate(self.records):
            self.history_table.insertRow(row)
            product = json.loads(record["product"])
            date = datetime.fromisoformat(record["created_at"]).astimezone().strftime("%Y-%m-%d %H:%M")
            for column, value in enumerate((date, product.get("name", ""), record["status"], record["permalink"])):
                self.history_table.setItem(row, column, QTableWidgetItem(value))
        self.history_table.resizeColumnsToContents()

    def selected_record(self):
        row = self.history_table.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def history_selected(self):
        record = self.selected_record()
        self.history_detail.setPlainText(
            f"{record['caption']}\n\n{record['detail']}\n게시물 ID: {record['media_id']}" if record else "")

    def reuse_history(self):
        record = self.selected_record()
        if not record:
            return
        message = "현재 작성 내용을 이 기록으로 바꿀까요?"
        if record["status"] in {"결과 확인 필요", "준비 중"}:
            message = "이전 게시 여부가 확정되지 않았습니다. 인스타 계정을 먼저 확인해 주세요.\n\n" + message
        answer = QMessageBox.question(self, "기록 불러오기", message,
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.load_editor({"product": json.loads(record["product"]), "images": json.loads(record["images"]),
                          "caption": record["caption"], "hashtags": ""})
        self.tabs.setCurrentIndex(0)

    def open_history(self):
        record = self.selected_record()
        if record and record["permalink"].startswith(("https://www.instagram.com/", "https://instagram.com/")):
            QDesktopServices.openUrl(QUrl(record["permalink"]))

    def save_settings(self, checked=False, notify=True):
        try:
            config = storage.load_config()
            for key, field in self.settings.items():
                if key not in storage.SECRET_NAMES:
                    config[key] = field.text().strip()
            if not config["model"]:
                raise ValueError("OpenAI 모델명을 입력해 주세요.")
            if len(ai.parse_hashtags(config["fixed_hashtags"])) > 30:
                raise ValueError("고정 해시태그는 최대 30개까지 입력해 주세요.")
            config["tone"] = self.default_tone.currentText()
            if (self.settings["ig_token"].text().strip()
                    or config["token_expires_at"][:10] != self.expiry.date().toString("yyyy-MM-dd")):
                config["token_expires_at"] = datetime.combine(
                    self.expiry.date().toPython(), datetime.min.time(), tzinfo=timezone.utc).isoformat()
            for key in storage.SECRET_NAMES:
                value = self.settings[key].text().strip()
                if value:
                    storage.save_secret(key, value)
                    self.settings[key].clear()
            storage.save_config(config)
            self.config = config
            if notify:
                self.statusBar().showMessage("설정을 저장했습니다.")
            return True
        except (ValueError, OSError) as error:
            self.show_error(str(error) if isinstance(error, ValueError) else "설정을 저장하지 못했습니다. 저장 공간을 확인해 주세요.")
            return False

    def test_connections(self):
        if not self.save_settings(notify=False):
            return
        def operation(progress):
            config = storage.load_config()
            results = []
            checks = [
                ("OpenAI", lambda: ai.test_connection(storage.get_secret("openai_key"), config["model"])),
                ("인스타", lambda: instagram.configured_client(config).test_connection()),
                ("Cloudinary", lambda: instagram.configured_host(config).test_connection()),
            ]
            for name, check in checks:
                progress(f"{name} 연결 확인 중")
                try:
                    results.append(check())
                except ValueError as error:
                    results.append(f"{name}: {error}")
            return "\n\n".join(results)
        self.run_job(operation, self.connections_tested)

    def connections_tested(self, result):
        self.sync_expiry()
        self.statusBar().showMessage("연결 테스트를 마쳤습니다.")
        QMessageBox.information(self, "연결 테스트 결과", result)

    def sync_expiry(self):
        self.config = storage.load_config()
        if self.config["token_expires_at"]:
            self.expiry.setDate(QDate.fromString(self.config["token_expires_at"][:10], "yyyy-MM-dd"))

    def check_token(self):
        if self.worker is not None:
            return
        config = storage.load_config()
        expiry = config.get("token_expires_at")
        if not config["ig_user_id"] or not expiry:
            return
        if QDate.fromString(expiry[:10], "yyyy-MM-dd") > QDate.currentDate().addDays(7):
            return
        self.run_job(lambda progress: instagram.configured_client(config), self.token_checked)

    def token_checked(self, _):
        self.sync_expiry()
        self.statusBar().showMessage("인스타 토큰을 갱신했습니다.")

    def closeEvent(self, event):
        if self.worker is not None:
            QMessageBox.information(self, "작업 중", "작업이 끝난 뒤 닫아 주세요. 입력 내용은 유지됩니다.")
            event.ignore()
            return
        try:
            storage.write_json("draft.json", self.draft())
        except OSError:
            self.show_error("작성 내용을 저장하지 못했습니다. 저장 공간을 확인한 뒤 닫아 주세요.")
            event.ignore()
            return
        event.accept()
