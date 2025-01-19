import sys
import os
import json
import time
import tracemalloc
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QComboBox,
    QFileDialog, QTextEdit, QVBoxLayout, QHBoxLayout, QMessageBox, QGridLayout, QGroupBox
)
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtGui import QFont

# Importujemy istniejące funkcje z plików algorytmów
from algorithms.trade_maximizer_working import process_file as trademaximizer_process_file
from algorithms.trade_maximizer_max_players import process_file as trademaximizer_max_players_process_file
from algorithms.greedy_algorithm import process_file as greedy_algorithm_process_file
from algorithms.genetic_algorithm import process_file as genetic_algorithm_process_file
from algorithms.tradegenie import process_file as tradegenie_process_file


class MathTradeApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Math-Trade Solver')
        self.setGeometry(100, 100, 1000, 700)

        self.initUI()

    def initUI(self):
        # Główny widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)

        # Główny layout
        self.main_layout = QVBoxLayout(self.central_widget)

        # Grupa wyboru pliku i algorytmu
        self.setup_input_group()

        # Przycisk uruchomienia
        self.run_button = QPushButton('Uruchom algorytm')
        self.run_button.setFixedHeight(40)
        self.run_button.clicked.connect(self.run_algorithm)
        self.main_layout.addWidget(self.run_button)

        # Grupa wyników
        self.setup_results_group()

        # Grupa grafu
        self.setup_graph_group()

    def setup_input_group(self):
        input_group = QGroupBox("Dane wejściowe")
        input_layout = QGridLayout()

        # Wybór pliku
        self.file_label = QLabel('Nie wybrano pliku.')
        self.file_label.setStyleSheet("border: 1px solid gray; padding: 5px;")
        self.select_file_button = QPushButton('Wybierz plik')
        self.select_file_button.clicked.connect(self.select_file)

        input_layout.addWidget(QLabel('Plik wejściowy:'), 0, 0)
        input_layout.addWidget(self.file_label, 0, 1)
        input_layout.addWidget(self.select_file_button, 0, 2)

        # Wybór algorytmu
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItems([
            'TradeMaximizer',
            'TradeMaximizer z priorytetami',
            'TradeMaximizer maks. gracze',
            'TradeGenie',
            'Algorytm zachłanny',
            'Algorytm genetyczny'
        ])
        input_layout.addWidget(QLabel('Algorytm:'), 1, 0)
        input_layout.addWidget(self.algorithm_combo, 1, 1, 1, 2)

        input_group.setLayout(input_layout)
        self.main_layout.addWidget(input_group)

    def setup_results_group(self):
        results_group = QGroupBox("Wyniki")
        results_layout = QVBoxLayout()

        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont("Courier", 10))

        results_layout.addWidget(self.results_text)
        results_group.setLayout(results_layout)
        self.main_layout.addWidget(results_group)

    def setup_graph_group(self):
        graph_group = QGroupBox("Graf wymian")
        graph_layout = QVBoxLayout()

        self.graph_view = QWebEngineView()
        graph_layout.addWidget(self.graph_view)
        graph_group.setLayout(graph_layout)
        self.main_layout.addWidget(graph_group)

    def select_file(self):
        options = QFileDialog.Options()
        options |= QFileDialog.ReadOnly
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Wybierz plik wejściowy",
            "",
            "JSON Files (*.json);;All Files (*)",
            options=options
        )
        if file_path:
            self.file_path = file_path
            self.file_label.setText(os.path.basename(file_path))
        else:
            self.file_path = ''
            self.file_label.setText('Nie wybrano pliku.')

    def run_algorithm(self):
        if not hasattr(self, 'file_path') or not self.file_path:
            QMessageBox.warning(self, 'Brak pliku', 'Proszę wybrać plik wejściowy.')
            return

        algorithm = self.algorithm_combo.currentText()
        self.results_text.clear()

        # Ścieżka do pliku grafu
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        # Dodajemy nazwę algorytmu do nazwy pliku grafu, aby uniknąć nadpisywania
        graph_name = f"{algorithm.replace(' ', '_').lower()}_{base_name}"
        self.output_graph_path = f"trade_graph_{graph_name}.html"

        # Wywołanie odpowiedniej funkcji algorytmu
        try:
            metrics = {}
            if algorithm == 'TradeMaximizer':
                metrics, user_transactions = trademaximizer_process_file(
                    self.file_path, self.output_graph_path, metrics
                )
            # elif algorithm == 'TradeMaximizer z priorytetami':
            #     metrics, user_transactions = trademaximizer_priorities_process_file(
            #         self.file_path, self.output_graph_path, metrics
            #     )
            elif algorithm == 'TradeMaximizer maks. gracze':
                metrics, user_transactions = trademaximizer_max_players_process_file(
                    self.file_path, self.output_graph_path, metrics
                )
            elif algorithm == 'TradeGenie':
                metrics, user_transactions = tradegenie_process_file(
                    self.file_path, self.output_graph_path, metrics
                )
            elif algorithm == 'Algorytm zachłanny':
                metrics, user_transactions = greedy_algorithm_process_file(
                    self.file_path, self.output_graph_path, metrics
                )
            elif algorithm == 'Algorytm genetyczny':
                metrics, user_transactions = genetic_algorithm_process_file(
                    self.file_path, self.output_graph_path, metrics
                )
            else:
                QMessageBox.warning(self, 'Nieznany algorytm', f'Algorytm {algorithm} nie jest rozpoznawany.')
                return

            self.display_results(metrics, user_transactions)

        except Exception as e:
            QMessageBox.critical(self, 'Błąd', f'Wystąpił błąd podczas uruchamiania algorytmu:\n{e}')
            return

        # Wyświetlanie grafu
        self.display_graph()

    def display_results(self, metrics, user_transactions):
        # Lista kluczy, które chcemy pominąć
        excluded_metrics = [
            'ilp_solving_time_seconds',
            'ilp_num_variables',
            'ilp_num_constraints',
            'matching_time_seconds',
            'num_users_exchanged',
            'user_transactions'
        ]

        # Słownik tłumaczeń i bardziej czytelnych nazw:
        translations = {
            'execution_time_seconds': 'Czas wykonania (s)',
            'memory_usage_mb': 'Użycie pamięci (MB)',
            'num_users': 'Liczba użytkowników',
            'num_items': 'Liczba przedmiotów',
            'num_exchanges': 'Liczba wymian',
            'num_warnings': 'Liczba ostrzeżeń',
            'participation_percent': 'Udział (%)',
            'overall_effectiveness_percent': 'Całkowita efektywność (%)'
        }

        self.results_text.clear()

        html_content = "<h2>Wyniki</h2><hr>"

        html_content += "<ul>"
        for key, value in metrics.items():
            if key not in excluded_metrics:
                display_name = translations.get(key, key.replace('_', ' ').capitalize())

                if isinstance(value, float):
                    value = round(value, 2)
                elif isinstance(value, int):
                    pass

                html_content += f"<li><b>{display_name}:</b> {value}</li>"
        html_content += "</ul>"

        # Wyświetlanie informacji o wymianach
        if user_transactions:
            html_content += "<h3>Szczegóły wymian</h3><hr>"
            for user, transactions in user_transactions.items():
                html_content += f"<p><b>Użytkownik:</b> {user}</p>"
                if transactions['items_given']:
                    html_content += "<p><b>Przedmioty oddane:</b></p><ul>"
                    for item in transactions['items_given']:
                        html_content += f"<li>{item}</li>"
                    html_content += "</ul>"
                else:
                    html_content += "<p><i>Nie oddał żadnych przedmiotów.</i></p>"

                if transactions['items_received']:
                    html_content += "<p><b>Przedmioty otrzymane:</b></p><ul>"
                    for item in transactions['items_received']:
                        html_content += f"<li>{item}</li>"
                    html_content += "</ul>"
                else:
                    html_content += "<p><i>Nie otrzymał żadnych przedmiotów.</i></p>"

                html_content += "<hr>"
        else:
            html_content += "<p><i>Brak transakcji.</i></p>"

        html_content += "<h3>Koniec wyników</h3>"

        self.results_text.setHtml(html_content)

    def display_graph(self):
        if os.path.exists(self.output_graph_path):
            local_url = QUrl.fromLocalFile(os.path.abspath(self.output_graph_path))
            self.graph_view.load(local_url)
        else:
            self.results_text.append('\nNie znaleziono pliku grafu wymian.')
            self.graph_view.setHtml('<h3>Brak grafu do wyświetlenia.</h3>')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MathTradeApp()
    window.show()
    sys.exit(app.exec_())
