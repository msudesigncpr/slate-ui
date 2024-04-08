import asyncio
import logging
import sys
from enum import Enum

from PyQt6.QtCore import QSize, Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
)

from generators import generate_spinbox_layout, generate_pdish_layout
from process_control import ProcessControlWorker


class State(Enum):
    IDLE = 0
    RUNNING = 1
    PAUSED = 2


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("CPR Slate Interface")
        self.state = State.IDLE
        #  self.setMinimumSize(1000, 1000)
        widget = QWidget()
        layout = QGridLayout(widget)

        # BEGIN BASIC SETUP LAYOUT

        basic_setup = QGroupBox("Basic Setup")
        self.basic_setup_lay = QVBoxLayout()
        basic_setup.setLayout(self.basic_setup_lay)

        pdish_count_lay, self.pdish_count = generate_spinbox_layout(
            "Number of Petri Dishes:", 1, 6, 6
        )
        self.pdish_count.valueChanged.connect(self.set_status_pdish_entry_fields)
        dwellt_ster_lay, self.dwellt_ster = generate_spinbox_layout(
            "Sterilizer Dwell Time (s):", 0, 1000, 20.0
        )
        dwellt_cool_lay, self.dwellt_cool = generate_spinbox_layout(
            "Cooling Time (s):", 0, 1000, 5.0
        )

        self.basic_setup_lay.addLayout(pdish_count_lay)
        self.basic_setup_lay.addLayout(dwellt_ster_lay)
        self.basic_setup_lay.addLayout(dwellt_cool_lay)

        self.basic_setup_lay.addStretch(1)
        layout.addWidget(basic_setup, 0, 0)

        # END BASIC SETUP LAYOUT

        # BEGIN METADATA CONFIGURATION LAYOUT

        metadata_config = QGroupBox("Metadata Configuration")
        metadata_config_lay = QVBoxLayout()
        metadata_config.setLayout(metadata_config_lay)

        self.pdish_sel = []
        for i in range(6):
            pdish_lay, pdish_sel = generate_pdish_layout(i + 1)
            self.pdish_sel.append(pdish_sel)
            metadata_config_lay.addLayout(pdish_lay)

        layout.addWidget(metadata_config, 0, 1)

        # END METADATA CONFIGURATION LAYOUT

        # BEGIN SAMPLING STATUS LAYOUT

        sampling_status = QGroupBox("Sampling Status")
        sampling_status_lay = QGridLayout()
        sampling_status.setLayout(sampling_status_lay)

        progress_bar = QProgressBar()

        sampling_act_label = QLabel("Current State:")
        self.sampling_act_status_msg = QLabel("N/A")

        self.start_button = QPushButton()
        self.start_button.setText("START")
        self.start_button.clicked.connect(self.start_button_state_transition)
        self.start_button.clicked.connect(self.spawn_process_control)

        self.stop_button = QPushButton()
        self.stop_button.setText("STOP")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_clicked)

        sampling_status_lay.addWidget(progress_bar, 0, 0, 1, 4)
        sampling_status_lay.addWidget(sampling_act_label, 1, 0)
        sampling_status_lay.addWidget(self.sampling_act_status_msg, 1, 1)
        sampling_status_lay.setColumnStretch(1, 1)
        sampling_status_lay.addWidget(self.start_button, 1, 2)
        sampling_status_lay.addWidget(self.stop_button, 1, 3)

        layout.addWidget(sampling_status, 1, 0, 1, 2)

        # END SAMPLING STATUS LAYOUT

        layout.setRowStretch(layout.rowCount(), 1)

        self.setCentralWidget(widget)

    def set_status_pdish_entry_fields(self, pdish_count):
        for i in range(pdish_count):
            self.pdish_sel[i].setEnabled(True)
        for i in range(pdish_count, 6):
            self.pdish_sel[i].setEnabled(False)

    def start_button_state_transition(self):
        match self.state:
            case State.IDLE | State.PAUSED:
                self.state = State.RUNNING
            case State.RUNNING:
                self.state = State.PAUSED
        self.update_ui_state()

    def update_ui_state(self):
        match self.state:
            case State.IDLE:
                self.stop_button.setEnabled(False)
                # TODO Make this iterate
                self.pdish_count.setReadOnly(False)
                self.dwellt_ster.setReadOnly(False)
                self.dwellt_cool.setReadOnly(False)
                for i in self.pdish_sel:
                    i.setReadOnly(False)
                self.start_button.setText("START")
            case State.PAUSED:
                self.stop_button.setEnabled(True)
                # TODO Make this iterate
                self.pdish_count.setReadOnly(True)
                self.dwellt_ster.setReadOnly(True)
                self.dwellt_cool.setReadOnly(True)
                for i in self.pdish_sel:
                    i.setReadOnly(True)
                self.start_button.setText("RESUME")
            case State.RUNNING:
                self.stop_button.setEnabled(True)
                # TODO Make this iterate
                self.pdish_count.setReadOnly(True)
                self.dwellt_ster.setReadOnly(True)
                self.dwellt_cool.setReadOnly(True)
                for i in self.pdish_sel:
                    i.setReadOnly(True)
                self.start_button.setText("PAUSE")

    def spawn_process_control(self):
        self.init_thread = QThread()
        self.proc_ctrl_worker = ProcessControlWorker(self.pdish_count.value())
        self.proc_ctrl_worker.moveToThread(self.init_thread)

        self.init_thread.started.connect(self.proc_ctrl_worker.run_full_proc)

        self.proc_ctrl_worker.finished.connect(self.sample_done_callback)
        self.proc_ctrl_worker.finished.connect(self.init_thread.quit)
        self.proc_ctrl_worker.exception.connect(self.init_thread.quit)
        self.proc_ctrl_worker.finished.connect(self.proc_ctrl_worker.deleteLater)

        self.proc_ctrl_worker.status_msg.connect(self.update_status_msg)
        self.proc_ctrl_worker.exception.connect(self.report_exception)

        self.init_thread.finished.connect(self.init_thread.deleteLater)

        self.init_thread.start()

    def update_status_msg(self, msg):
        self.sampling_act_status_msg.setText(msg)

    def report_exception(self, exception):
        self.state = State.IDLE
        self.update_ui_state()
        self.sampling_act_status_msg.setText(exception)

    def sample_done_callback(self):
        self.state = State.IDLE
        self.update_ui_state()

    def stop_clicked(self):
        self.state = State.IDLE
        self.stop_button.setEnabled(False)
        self.pdish_count.setReadOnly(False)
        self.dwellt_ster.setReadOnly(False)
        self.dwellt_cool.setReadOnly(False)
        self.start_button.setText("START")
        for i in self.pdish_sel:
            i.setReadOnly(False)
        self.update_status_msg("Terminating process control...")
        self.proc_ctrl_worker.terminate(polite=False)
        self.update_status_msg("Terminated by user!")


if __name__ == "__main__":
    app = QApplication(sys.argv)

    window = MainWindow()
    window.show()

    app.exec()
