import re
import json
from collections import defaultdict
import logging
import os

# Konfiguracja logowania
logging.basicConfig(
    filename='data_processing.log',
    filemode='a',
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)

# Ścieżki do plików
WANTS_FILE_PATH = 'C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\data\\data.txt'
OUTPUT_JSON_PATH = 'C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\data\\german_feb_2014_trade.json'

# Słownik mapujący ID przedmiotu na jego nazwę i właściciela
item_id_to_name = {}

# Słownik mapujący użytkowników na oferowane przedmioty i listę życzeń
users = defaultdict(lambda: {'offers': {}, 'wants': {}})

# Flagi do śledzenia, w której sekcji się znajdujemy
current_user = None
in_official_names = False

# Regularne wyrażenia do parsowania
pragma_user_pattern = re.compile(r'^#pragma user\s+"?([\w\-]+)"?$')
offer_pattern = re.compile(r'^\(([\w\-]+)\)\s+(\S+)(?:\s*:\s*(.*))?$')
item_pattern = re.compile(r'^(\d{4}-[A-Z]+(?:-COPY\d+)?)\s+==>\s+"([^"]+)"\s+\(from\s+([\w\-]+)\)$')

# Funkcja do czyszczenia dodatkowych znaków z listy życzeń
def clean_wants(wants_str):
    if not wants_str:
        return []
    wants_str = wants_str.split('%')[0]
    wants_ids = re.split(r'[\s,]+', wants_str.strip())
    return [item for item in wants_ids if item]

# Funkcja do sanityzacji nazw przedmiotów
def sanitize_name(name, line_number):
    if '�' in name:
        logging.warning(f"Nieznane znaki znalezione w nazwie na linii {line_number}: {name}")
        sanitized_name = name.replace('�', '')
        return sanitized_name
    return name

# Funkcja do walidacji i analizy listy życzeń
def validate_wishlist(wishlist, item_id_to_name, user):
    valid_wishlist = []
    for item_id in wishlist:
        if item_id in item_id_to_name:
            valid_wishlist.append(item_id)
        else:
            logging.warning(f"Przedmiot '{item_id}' z listy życzeń użytkownika '{user}' nie istnieje.")
    return valid_wishlist

# Sprawdzenie, czy plik istnieje
if not os.path.exists(WANTS_FILE_PATH):
    logging.error(f"Plik {WANTS_FILE_PATH} nie istnieje.")
    raise FileNotFoundError(f"Plik {WANTS_FILE_PATH} nie został znaleziony.")

# Przetwarzanie pliku WANTS
with open(WANTS_FILE_PATH, 'r', encoding='utf-8', errors='replace') as file:
    for line_number, line in enumerate(file, 1):
        line = line.strip()

        # Sprawdzenie, czy linia zaczyna się od !BEGIN-OFFICIAL-NAMES
        if line.startswith('!BEGIN-OFFICIAL-NAMES'):
            in_official_names = True
            logging.debug(f"Rozpoczęto sekcję '!BEGIN-OFFICIAL-NAMES' na linii {line_number}.")
            continue
        elif line.startswith('!END-OFFICIAL-NAMES'):
            in_official_names = False
            logging.debug(f"Zakończono sekcję '!END-OFFICIAL-NAMES' na linii {line_number}.")
            continue

        if in_official_names:
            item_match = item_pattern.match(line)
            if item_match:
                item_id, item_name, owner = item_match.groups()
                item_name = sanitize_name(item_name, line_number)
                # Dodanie kopii do klucza item_id jeśli istnieje
                if item_id in item_id_to_name:
                    # Generowanie unikalnego identyfikatora dla kopii
                    copy_id = 1
                    new_item_id = f"{item_id}-COPY{copy_id}"
                    while new_item_id in item_id_to_name:
                        copy_id += 1
                        new_item_id = f"{item_id}-COPY{copy_id}"
                    item_id = new_item_id
                    logging.debug(f"Utworzono kopię przedmiotu '{item_id}'.")

                item_id_to_name[item_id] = {'name': item_name, 'owner': owner}
                logging.debug(f"Dodano przedmiot '{item_id}': '{item_name}' od '{owner}' na linii {line_number}.")
            else:
                logging.warning(f"Nieznany format w sekcji oficjalnych nazw na linii {line_number}: {line}")
            continue

        # Sprawdzenie, czy linia zaczyna się od #pragma user
        pragma_match = pragma_user_pattern.match(line)
        if pragma_match:
            current_user = pragma_match.group(1)
            logging.debug(f"Ustawiono aktualnego użytkownika na '{current_user}' na linii {line_number}.")
            continue

        # Pomijanie pustych linii lub linii komentarzy niebędących pragma user
        if not line or (line.startswith('#') and not line.startswith('(przykład)')):
            continue

        # Parsowanie linii z ofertą i życzeniami
        offer_match = offer_pattern.match(line)
        if offer_match and current_user:
            user, item_id, wants = offer_match.groups()
            if user != current_user:
                logging.warning(
                    f"Uwaga: Użytkownik w ofercie ({user}) różni się od aktualnego użytkownika ({current_user}) na linii {line_number}. Pomijanie linii.")
                continue

            # Czyszczenie i przypisanie przedmiotu oraz jego życzeń
            wants_ids = clean_wants(wants)
            # Walidacja i dodanie do listy życzeń
            wants_ids = validate_wishlist(wants_ids, item_id_to_name, current_user)

            # Dodanie przedmiotu do mapowania z właścicielem
            if item_id not in item_id_to_name:
                item_id_to_name[item_id] = {'name': item_id, 'owner': current_user}
                logging.debug(f"Dodano przedmiot '{item_id}' oferowany przez '{current_user}' na linii {line_number}.")
            else:
                existing_owner = item_id_to_name[item_id]['owner']
                if existing_owner != current_user:
                    # Jeśli przedmiot jest już oferowany przez innego użytkownika, generujemy unikalne ID dla kopii
                    copy_id = 1
                    new_item_id = f"{item_id}-COPY{copy_id}"
                    while new_item_id in item_id_to_name:
                        copy_id += 1
                        new_item_id = f"{item_id}-COPY{copy_id}"
                    item_id = new_item_id
                    item_id_to_name[item_id] = {'name': item_id, 'owner': current_user}
                    logging.debug(f"Utworzono kopię przedmiotu '{item_id}' dla użytkownika '{current_user}'.")

            # Dodanie oferty i listy życzeń do słownika użytkowników
            users[current_user]['offers'][item_id] = wants_ids
            logging.debug(
                f"Dodano ofertę dla użytkownika '{current_user}': item_id='{item_id}', wants={wants_ids} na linii {line_number}.")
            continue

        if line:
            logging.warning(f"Nieznana linia na {line_number}: {line}")

# Zapis do pliku JSON
data_to_save = {
    'users': users,
    'items': item_id_to_name
}

try:
    with open(OUTPUT_JSON_PATH, 'w', encoding='utf-8') as json_file:
        json.dump(data_to_save, json_file, ensure_ascii=False, indent=4)
    logging.info(f"Dane zostały zapisane do pliku JSON: {OUTPUT_JSON_PATH}")
except Exception as e:
    logging.error(f"Nie udało się zapisać danych do pliku JSON: {e}")
    raise

print(f"Dane zostały zapisane do pliku JSON: {OUTPUT_JSON_PATH}")
