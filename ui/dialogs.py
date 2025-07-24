from PyQt6 import QtWidgets, QtCore
from ..utils import unmatched_songs, export_all_unmatched_songs, msg
import os

class UnmatchedSongsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, tagger=None):
        super().__init__(parent)
        self.setWindowTitle(msg("Nicht erkannte Songs", "Unmatched Songs"))
        self.resize(700, 400)
        self.tagger = tagger
        layout = QtWidgets.QVBoxLayout(self)

        # Tabelle für Songs
        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([
            msg("Datei", "File"),
            msg("Titel", "Title"),
            msg("Künstler", "Artist")
        ])
        self.table.setRowCount(len(unmatched_songs))
        for i, song in enumerate(unmatched_songs):
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(song.get("file_path", "")))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(song.get("title", "")))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(song.get("artist", "")))
        self.table.resizeColumnsToContents()
        layout.addWidget(self.table)

        # Hinweis
        label = QtWidgets.QLabel(msg(
            "Diese Songs konnten nicht automatisch erkannt werden. Du kannst sie als CSV exportieren und ggf. zu MusicBrainz hinzufügen.",
            "These songs could not be identified automatically. You can export them as CSV and add them to MusicBrainz."
        ))
        label.setWordWrap(True)
        layout.addWidget(label)

        # Button-Leiste
        button_layout = QtWidgets.QHBoxLayout()
        self.export_btn = QtWidgets.QPushButton(msg("Exportieren", "Export"))
        self.export_btn.clicked.connect(self.export_csv)
        self.close_btn = QtWidgets.QPushButton(msg("Schließen", "Close"))
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.export_btn)
        button_layout.addWidget(self.close_btn)
        layout.addLayout(button_layout)

    def export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, msg("Exportiere als CSV", "Export as CSV"), os.path.expanduser("~"), "CSV (*.csv)")
        if path:
            export_all_unmatched_songs(path, tagger=self.tagger)
            # QtWidgets.QMessageBox.information(self, msg("Export erfolgreich", "Export successful"), msg(f"CSV gespeichert: {path}", f"CSV saved: {path}"))
