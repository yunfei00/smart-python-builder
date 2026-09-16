from PySide6.QtWidgets import QApplication, QLabel

from helpers.message import message

app = QApplication([])
label = QLabel(message())
label.resize(320, 120)
label.show()
app.exec()
