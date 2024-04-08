import sys

from PyQt6.QtWidgets import QApplication

from main_window import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(
        """
        QLineEdit:read-only, QSpinBox::read-only, QDoubleSpinBox::read-only {
            background: palette(window);
        }"""
    )

    window = MainWindow()
    window.show()

    app.exec()
