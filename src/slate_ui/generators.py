from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
)

from PyQt6.QtCore import QRegularExpression
from PyQt6.QtGui import QRegularExpressionValidator


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

    re = QRegularExpression("[a-zA-Z0-9]*")
    validator = QRegularExpressionValidator(re)
    selection.setValidator(validator)

    layout.addWidget(label)
    layout.addWidget(selection)
    return layout, selection
