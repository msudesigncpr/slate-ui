from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
)

from PyQt6.QtCore import pyqtSignal, QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator, QValidator


class PetriDishValidator(QRegularExpressionValidator):
    validationChanged = pyqtSignal(QValidator.State)

    def validate(self, input, pos):
        # First, check against the regex
        state, input, pos = super().validate(input, pos)

        # Next, check that we aren't empty
        if not bool(input.strip()):
            state = QValidator.State.Intermediate

        # TODO We don't check for duplicate entry fields
        self.validationChanged.emit(state)
        return state, input, pos


def generate_spinbox_layout(label_text, min_bound, max_bound, default_val):
    layout = QHBoxLayout()

    label = QLabel(label_text)

    spinbox = QSpinBox() if isinstance(default_val, int) else QDoubleSpinBox()
    spinbox.setRange(min_bound, max_bound)
    spinbox.setValue(default_val)

    layout.addWidget(label)
    layout.addWidget(spinbox)
    return layout, spinbox


def generate_pdish_layout(id):
    layout = QHBoxLayout()
    label = QLabel(f"Petri Dish {id}: ")

    selection = QLineEdit()
    selection.setMaxLength(12)
    selection.setText(f"P{id}")

    regex = QRegularExpression("[a-zA-Z0-9]+")
    pname_validator = PetriDishValidator(regex)
    selection.setValidator(pname_validator)

    layout.addWidget(label)
    layout.addWidget(selection)
    return layout, selection, pname_validator
