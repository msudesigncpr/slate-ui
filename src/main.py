import sys

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QGroupBox,
    QPushButton,
    QSpinBox,
    QWidget,
    QGridLayout,
    QLabel,
    QHBoxLayout,
    QVBoxLayout,
    QDoubleSpinBox,
    QProgressBar,
    QLineEdit,
)

def generate_spinbox_layout(label_text, min_bound, max_bound, default_val):
    layout = QHBoxLayout()

    label = QLabel(label_text)

    spinbox = QSpinBox() if isinstance(default_val, int) else QDoubleSpinBox()
    spinbox.setRange(min_bound, max_bound)
    spinbox.setValue(default_val)

    layout.addWidget(label)
    layout.addWidget(spinbox)
    return layout

def generate_pdish_layout(name):
    layout = QHBoxLayout()
    label = QLabel(f"Petri Dish {name}: ")

    selection = QLineEdit()
    selection.setMaxLength(16)
    selection.setText(f"P{name}")

    layout.addWidget(label)
    layout.addWidget(selection)
    return layout


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("CPR Slate Interface")
        #  self.setMinimumSize(1000, 1000)
        widget = QWidget()
        layout = QGridLayout(widget)

        # BEGIN BASIC SETUP LAYOUT

        basic_setup = QGroupBox("Basic Setup")
        basic_setup_lay = QVBoxLayout()
        basic_setup.setLayout(basic_setup_lay)

        pdish_count_lay = generate_spinbox_layout("Number of Petri Dishes:", 1, 6, 6)
        dwellt_ster_lay = generate_spinbox_layout("Sterilizer Dwell Time (s):", 0, 1000, 20.0)
        dwellt_cool_lay = generate_spinbox_layout("Cooling Time (s):", 0, 1000, 5.0)

        basic_setup_lay.addLayout(pdish_count_lay)
        basic_setup_lay.addLayout(dwellt_ster_lay)
        basic_setup_lay.addLayout(dwellt_cool_lay)

        basic_setup_lay.addStretch(1)
        layout.addWidget(basic_setup, 0, 0)

        # END BASIC SETUP LAYOUT

        # BEGIN METADATA CONFIGURATION LAYOUT

        metadata_config = QGroupBox("Metadata Configuration")
        metadata_config_lay = QVBoxLayout()
        metadata_config.setLayout(metadata_config_lay)

        for i in range(1, 7):
            pdish_lay = generate_pdish_layout(i)
            metadata_config_lay.addLayout(pdish_lay)

        layout.addWidget(metadata_config, 0, 1)

        # END METADATA CONFIGURATION LAYOUT

        # BEGIN SAMPLING STATUS LAYOUT

        sampling_status = QGroupBox("Sampling Status")
        sampling_status_lay = QGridLayout()
        sampling_status.setLayout(sampling_status_lay)

        progress_bar = QProgressBar()

        sampling_act_label = QLabel("Current State: ")
        sampling_act_status_msg = QLabel("N/A")

        start_button = QPushButton()
        start_button.setText("START")

        stop_button = QPushButton()
        stop_button.setText("STOP")

        sampling_status_lay.addWidget(progress_bar, 0, 0, 1, 4)
        sampling_status_lay.addWidget(sampling_act_label, 1, 0)
        sampling_status_lay.addWidget(sampling_act_status_msg, 1, 1)
        sampling_status_lay.setColumnStretch(1, 1)
        sampling_status_lay.addWidget(start_button, 1, 2)
        sampling_status_lay.addWidget(stop_button, 1, 3)

        layout.addWidget(sampling_status, 1, 0, 1, 2)

        # END SAMPLING STATUS LAYOUT

        layout.setRowStretch(layout.rowCount(), 1)

        self.setCentralWidget(widget)


app = QApplication(sys.argv)

window = MainWindow()
window.show()

sys.exit(app.exec())
