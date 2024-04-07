from PyQt6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
)


def generate_spinbox_layout(label_text, min_bound, max_bound, default_val):
    layout = QHBoxLayout()

    label = QLabel(label_text)

    spinbox = QSpinBox() if isinstance(default_val, int) else QDoubleSpinBox()
    spinbox.setRange(min_bound, max_bound)
    spinbox.setValue(default_val)

    layout.addWidget(label)
    layout.addWidget(spinbox)
    return layout, spinbox


def generate_pdish_layout(name):
    layout = QHBoxLayout()
    label = QLabel(f"Petri Dish {name}: ")

    selection = QLineEdit()
    selection.setMaxLength(16)
    selection.setText(f"P{name}")

    layout.addWidget(label)
    layout.addWidget(selection)
    return layout, selection
