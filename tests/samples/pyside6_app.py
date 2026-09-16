import sys

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


app = QApplication(sys.argv)
window = QMainWindow()
window.setWindowTitle("Smart Python Builder - Case C")
window.resize(480, 220)
window.setCentralWidget(QLabel("Case C PySide6 build succeeded"))
window.show()
sys.exit(app.exec())
