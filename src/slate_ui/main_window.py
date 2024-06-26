from enum import Enum
from functools import partial
import time

from PyQt6.QtCore import QThread
from PyQt6.QtGui import QValidator
from PyQt6.QtWidgets import (
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
    STARTUP = 1
    RUNNING = 2
    #  PAUSED = 3


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("CPR Slate Interface")
        self.state = State.IDLE
        self.setFixedSize(480, 300)
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
        )  # TODO Raise default
        dwellt_cool_lay, self.dwellt_cool = generate_spinbox_layout(
            "Cooling Time (s):", 0, 1000, 5.0
        )

        self.basic_setup_lay.addLayout(pdish_count_lay)
        self.basic_setup_lay.addLayout(dwellt_ster_lay)
        self.basic_setup_lay.addLayout(dwellt_cool_lay)

        self.basic_setup_lay.addStretch(1)
        layout.addWidget(basic_setup, 0, 0)

        # END BASIC SETUP LAYOUT

        # BEGIN OUTPUT CONFIGURATION LAYOUT

        output_config = QGroupBox("Output Configuration")
        output_config_lay = QVBoxLayout()
        output_config.setLayout(output_config_lay)

        # Petri dish name fields
        self.pdish_sel = []
        self.pdish_layout = []
        for i in range(6):
            pdish_layout, pdish_sel, pdish_valid = generate_pdish_layout(i + 1)
            pdish_valid.validationChanged.connect(
                partial(self.pdish_name_validator_callback, pdish_sel)
            )
            self.pdish_sel.append(pdish_sel)
            self.pdish_layout.append(pdish_layout)
            output_config_lay.addLayout(pdish_layout)

        layout.addWidget(output_config, 0, 1)

        # END OUTPUT CONFIGURATION LAYOUT

        # BEGIN SAMPLING STATUS LAYOUT

        sampling_status = QGroupBox("Sampling Status")
        sampling_status_lay = QGridLayout()
        sampling_status.setLayout(sampling_status_lay)

        self.progress_bar = QProgressBar()

        sampling_act_label = QLabel("Current Task:")
        self.sampling_act_status_msg = QLabel("N/A")

        # Start/pause button
        self.start_button = QPushButton()
        self.start_button.setText("START")
        self.start_button.clicked.connect(self.start_button_callback)

        # Stop button
        self.stop_button = QPushButton()
        self.stop_button.setText("STOP")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_button_callback)

        sampling_status_lay.addWidget(self.progress_bar, 0, 0, 1, 4)
        sampling_status_lay.addWidget(sampling_act_label, 1, 0)
        sampling_status_lay.addWidget(self.sampling_act_status_msg, 1, 1)
        sampling_status_lay.setColumnStretch(1, 1)
        sampling_status_lay.addWidget(self.start_button, 1, 2)
        sampling_status_lay.addWidget(self.stop_button, 1, 3)

        layout.addWidget(sampling_status, 1, 0, 1, 2)

        # END SAMPLING STATUS LAYOUT

        layout.setRowStretch(layout.rowCount(), 1)

        self.setCentralWidget(widget)
        self.update_ui_state()

    def set_status_pdish_entry_fields(self, pdish_count):
        """Enable Petri dish name fields up to `pdish_count` and disable the rest."""
        for i in range(pdish_count):
            self.pdish_sel[i].setEnabled(True)
        for i in range(pdish_count, 6):
            self.pdish_sel[i].setEnabled(False)

    def pdish_name_validator_callback(self, origin_dish, state):
        match state:
            case QValidator.State.Intermediate:
                origin_dish.setStyleSheet(
                    """
                        QLineEdit {
                            background-color: #fff0f0;
                            border: 1.5px solid red;
                        }
                        QLineEdit:disabled {
                            border: 0px;
                        }
                        """
                )
            case QValidator.State.Acceptable:
                origin_dish.setStyleSheet("")

    def set_config_entry(self, entry_enabled):
        self.pdish_count.setReadOnly(not entry_enabled)
        self.dwellt_ster.setReadOnly(not entry_enabled)
        self.dwellt_cool.setReadOnly(not entry_enabled)
        for i in self.pdish_sel:
            i.setReadOnly(not entry_enabled)

    def update_ui_state(self):
        """Update the UI entry elements based on the state."""
        match self.state:
            case State.IDLE:
                self.stop_button.setEnabled(False)
                self.start_button.setEnabled(True)
                self.set_config_entry(True)
                #  self.start_button.setText("START")
            case State.STARTUP:
                self.stop_button.setEnabled(False)
                self.start_button.setEnabled(False)
                self.set_config_entry(False)
                #  self.start_button.setText("RESUME")
            #  case State.PAUSED:
            #  self.stop_button.setEnabled(True)
            #  self.start_button.setEnabled(True)
            #  self.set_config_entry(False)
            #  self.start_button.setText("RESUME")
            case State.RUNNING:
                self.stop_button.setEnabled(True)
                self.start_button.setEnabled(False)
                self.set_config_entry(False)
                #  self.start_button.setText("PAUSE")

    def start_button_callback(self):
        """Start the sampling process via a `ProcessControl` instance."""

        match self.state:
            case State.IDLE:
                # First, check if the Petri names are valid
                pdish_names = []
                pdish_names_valid = True
                for pdish_index in range(self.pdish_count.value()):
                    pdish_names.append(self.pdish_sel[pdish_index].text())
                    if not self.pdish_sel[pdish_index].hasAcceptableInput():
                        pdish_names_valid = False
                        break
                if len(pdish_names) != len(set(pdish_names)):
                    pdish_names_valid = False

                if pdish_names_valid:
                    self.state = State.STARTUP
                    self.init_thread = QThread()
                    self.proc_ctrl_worker = ProcessControlWorker(
                        pdish_names,
                        self.pdish_count.value(),
                        self.dwellt_ster.value(),
                        self.dwellt_cool.value(),
                    )
                    self.proc_ctrl_worker.moveToThread(self.init_thread)

                    self.init_thread.started.connect(
                        self.proc_ctrl_worker.run_full_proc
                    )

                    # Task completed callbacks
                    self.proc_ctrl_worker.finished.connect(self.sample_done_callback)
                    self.proc_ctrl_worker.finished.connect(self.init_thread.quit)
                    self.proc_ctrl_worker.finished.connect(
                        self.proc_ctrl_worker.deleteLater
                    )

                    # Task error callbacks
                    self.proc_ctrl_worker.exception.connect(self.report_exception)
                    self.proc_ctrl_worker.exception.connect(self.init_thread.quit)

                    # Status/state update callbacks
                    self.proc_ctrl_worker.status_msg.connect(self.update_status_msg)
                    self.proc_ctrl_worker.state.connect(
                        self.sample_state_update_callback
                    )
                    self.proc_ctrl_worker.colony_count.connect(self.update_progress_max)
                    self.proc_ctrl_worker.colony_index.connect(self.update_progress)

                    # Thread cleanup
                    self.init_thread.finished.connect(self.init_thread.deleteLater)

                    self.init_thread.start()
            #  case State.RUNNING:
            #  self.state = State.PAUSED
            #  self.proc_ctrl_worker.pause()
            #  case State.PAUSED:
            #  self.state = State.RUNNING
            #  self.proc_ctrl_worker.resume()
        self.update_ui_state()

    def update_progress_max(self, new_max):
        self.progress_bar.setMaximum(new_max)

    def update_progress(self, new_progress):
        self.progress_bar.setValue(new_progress)

    def sample_state_update_callback(self, state_msg):
        """Update state based on on state message from `ProcessControl`."""
        if state_msg == "DRIVE_HOME":
            self.state = State.RUNNING
        self.update_ui_state()

    def update_status_msg(self, msg):
        """Update the displayed task label."""
        self.sampling_act_status_msg.setText(msg)

    def report_exception(self, exception):
        """Handle exception from `ProcessControl`."""
        self.state = State.IDLE
        self.update_ui_state()
        self.sampling_act_status_msg.setText(exception)
        self.progress_bar.reset()
        if self.state is State.RUNNING:
            self.proc_ctrl_worker.terminate(polite=False)

    def sample_done_callback(self):
        """Update state/UI for task completion."""
        self.progress_bar.reset()
        self.state = State.IDLE
        self.update_ui_state()

    def stop_button_callback(self):
        """Handle the stop button being clicked."""
        self.state = State.IDLE
        self.stop_button.setEnabled(False)
        self.pdish_count.setReadOnly(False)
        self.dwellt_ster.setReadOnly(False)
        self.dwellt_cool.setReadOnly(False)
        #  self.start_button.setText("START")
        for i in self.pdish_sel:
            i.setReadOnly(False)
        self.update_status_msg("Terminating process control...")
        self.proc_ctrl_worker.terminate(polite=False)
        self.progress_bar.reset()
        self.update_status_msg("Terminated by user!")
        time.sleep(0.5)  # HACK Race condition with rapid stop/start causing crash
        self.start_button.setEnabled(True)
