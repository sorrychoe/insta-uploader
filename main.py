"""Run with Python 3.12; build Linux locally or Windows through GitHub Actions."""
import sys

from PySide6.QtCore import QLibraryInfo, QLockFile, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

import storage
from ui import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("InstaUploader")
    translator = QTranslator(app)
    if translator.load("qtbase_ko", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)
    try:
        lock = QLockFile(str(storage.app_dir() / "app.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(None, "인스타 업로더", "프로그램이 이미 실행 중입니다.")
            return 0
        window = MainWindow()
    except Exception:
        QMessageBox.critical(None, "실행 오류", "설정 또는 게시 기록을 읽지 못했습니다. 앱 데이터 폴더와 저장 공간을 확인해 주세요.")
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
