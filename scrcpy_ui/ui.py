# -*- coding: utf-8 -*-

from PySide6.QtCore import QCoreApplication, QMetaObject, QSize  # pylint: disable=no-name-in-module
from PySide6.QtGui import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QWidget,
    QLabel,
    QLayout,
    QHBoxLayout,
    QVBoxLayout,
    QComboBox,
    QPushButton,
    QSpacerItem,
    QSizePolicy,
    QMainWindow,
)


class UI:
    """ui design"""

    def __init__(self, parent: QMainWindow):
        if not parent.objectName():
            parent.setObjectName("MainWindow")
        parent.resize(523, 566)

        self.central_widget = QWidget(parent)
        self.central_widget.setObjectName("central_widget")

        layout = QVBoxLayout(self.central_widget)
        layout.setObjectName("vertical_layout")
        layout.setSizeConstraint(QLayout.SetFixedSize)

        layout.addLayout(self.header())
        layout.addLayout(self.body())
        layout.addLayout(self.bottom())
        layout.setStretch(1, 100)

        parent.setCentralWidget(self.central_widget)
        self.translate(parent)
        QMetaObject.connectSlotsByName(parent)

    def header(self):
        """header layout"""
        layout = QHBoxLayout()
        layout.setObjectName("layout_header")

        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.label_device = QLabel(self.central_widget)
        self.label_device.setObjectName("label_device")

        layout.addWidget(self.label_device)

        self.combo_device = QComboBox(self.central_widget)
        self.combo_device.setObjectName("combo_device")
        self.combo_device.setMinimumSize(QSize(100, 0))

        layout.addWidget(self.combo_device)

        # self.flip = QCheckBox(self.centralwidget)
        # self.flip.setObjectName("flip")
        # layout.addWidget(self.flip)

        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        return layout

    def body(self):
        """body layout"""
        layout = QHBoxLayout()
        layout.setObjectName("layout_body")
        layout.setSizeConstraint(QLayout.SetFixedSize)
        layout.setContentsMargins(-1, -1, 0, -1)

        self.label = QLabel(self.central_widget)
        self.label.setObjectName("label")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)
        return layout

    def bottom(self):
        """bottom layout"""
        layout = QHBoxLayout()
        layout.setSpacing(6)
        layout.setObjectName("layout_bottom")
        layout.setSizeConstraint(QLayout.SetFixedSize)

        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.button_home = QPushButton(self.central_widget)
        self.button_home.setObjectName("button_home")
        layout.addWidget(self.button_home)

        self.button_back = QPushButton(self.central_widget)
        self.button_back.setObjectName("button_back")
        layout.addWidget(self.button_back)

        self.button_overview = QPushButton(self.central_widget)
        self.button_overview.setObjectName("button_overview")
        layout.addWidget(self.button_overview)

        self.button_screenshot = QPushButton(self.central_widget)
        self.button_screenshot.setObjectName("button_screenshot")
        layout.addWidget(self.button_screenshot)

        layout.addItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        return layout

    def translate(self, parent: QMainWindow):
        """translate text"""
        parent.setWindowTitle(QCoreApplication.translate("MainWindow", "MainWindow", None))
        self.label_device.setText(QCoreApplication.translate("MainWindow", "Device", None))
        # self.flip.setText(QCoreApplication.translate("MainWindow", "Flip", None))
        self.label.setText(
            QCoreApplication.translate(
                "MainWindow",
                '<html><head/><body><p><span style=" font-size:20pt;">Loading</span></p></body></html>',
                None,
            )
        )
        self.button_home.setText(QCoreApplication.translate("MainWindow", "Home", None))
        self.button_back.setText(QCoreApplication.translate("MainWindow", "Back", None))
        self.button_overview.setText(QCoreApplication.translate("MainWindow", "Overview", None))
        self.button_screenshot.setText(QCoreApplication.translate("MainWindow", "ScreenShot", None))
