import glob
import json
import networkx as nx
from pyvis.network import Network
import pulp
import time
import tracemalloc
import os

def warn(message, metrics):
    """Funkcja do obsługi ostrzeżeń, zwiększa licznik ostrzeżeń i wypisuje komunikat."""
    metrics["num_warnings"] += 1
    print(f"Ostrzeżenie: {message}")

def load_data(file_path, metrics):
    """Wczytuje dane z pliku JSON."""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        warn(f"Nie można wczytać pliku '{file_path}': {e}", metrics)
        return None

def standardize_usernames(users):
    """Tworzy mapowanie nazw użytkowników w lowercase do oryginalnych nazw."""
    return {user.lower(): user for user in users}

def create_item_mappings(items, user_lower_to_original, metrics):
    """Tworzy mapowania właścicieli przedmiotów i nazw z ujednoliconymi nazwami użytkowników."""
    item_owner = {}
    item_name = {}
    for item_id, item_info in items.items():
        owner_lower = item_info['owner'].lower()
        if owner_lower in user_lower_to_original:
            item_owner[item_id] = owner_lower
            item_name[item_id] = item_info['name']
        else:
            warn(f"Właściciel '{item_info['owner']}' przedmiotu '{item_id}' nie znajduje się w users.", metrics)
            item_owner[item_id] = 'unknown'
            item_name[item_id] = item_info['name']
    return item_owner, item_name

def build_exchange_graph(users_lower, items, item_owner, metrics):
    """Buduje skierowany graf reprezentujący możliwe wymiany."""
    G = nx.DiGraph()

    for item_id in items:
        G.add_node(item_id)

    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_id, wishlist in offers.items():
            for wish_item_id in wishlist:
                if wish_item_id in item_owner:
                    desired_item_owner = item_owner[wish_item_id]
                    if desired_item_owner != user_lower:
                        G.add_edge(offer_id, wish_item_id)
                else:
                    warn(f"Przedmiot '{wish_item_id}' z listy życzeń użytkownika '{user_lower}' nie jest dostępny.", metrics)

    return G

def clean_wishlists(users_lower, item_owner, metrics):
    """Usuwa z list życzeń przedmioty, które nie są dostępne."""
    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_id, wishlist in offers.items():
            original_wishlist = wishlist.copy()
            wishlist[:] = [item_id for item_id in wishlist if item_id in item_owner]
            removed_items = set(original_wishlist) - set(wishlist)
            if removed_items:
                warn(f"Usunięto niedostępne przedmioty z listy życzeń oferty '{offer_id}' użytkownika '{user_lower}': {removed_items}", metrics)

def find_exchange_cycles_ilp(G, item_owner, user_lower_to_original, max_cycle_length, metrics):
    """Znajduje optymalne cykle wymian używając programowania liniowego całkowitoliczbowego (ILP)."""
    cycles = []
    simple_cycles = list(nx.simple_cycles(G))
    for cycle in simple_cycles:
        if 2 <= len(cycle) <= max_cycle_length:
            cycles.append(cycle)

    metrics["num_cycles_found"] = len(cycles)
    print(f"Znaleziono {len(cycles)} cykli o długości do {max_cycle_length}.")

    if not cycles:
        return []

    # Tworzenie modelu ILP
    model = pulp.LpProblem("Exchange_Cycle_Optimization", pulp.LpMaximize)

    # Tworzenie zmiennych decyzyjnych dla każdego cyklu
    cycle_vars = {}
    for i, cycle in enumerate(cycles):
        var = pulp.LpVariable(f"cycle_{i}", cat='Binary')
        cycle_vars[i] = var

    # Funkcja celu
    user_vars = {}
    for i, cycle in enumerate(cycles):
        for item in cycle:
            owner = item_owner[item]
            if owner not in user_vars:
                user_vars[owner] = pulp.LpVariable(f"user_{owner}", cat='Binary')

    model += pulp.lpSum(user_vars.values())

    item_to_cycles = {}
    for i, cycle in enumerate(cycles):
        for item in cycle:
            if item not in item_to_cycles:
                item_to_cycles[item] = []
            item_to_cycles[item].append(cycle_vars[i])

    for item, vars_list in item_to_cycles.items():
        model += pulp.lpSum(vars_list) <= 1

    # Ograniczenia: jeśli cykl jest wybrany, to użytkownicy w nim uczestniczący muszą mieć y_u = 1
    for user in user_vars:
        user_cycles = []
        for i, cycle in enumerate(cycles):
            cycle_users = set(item_owner[item] for item in cycle)
            if user in cycle_users:
                user_cycles.append(cycle_vars[i])
        if user_cycles:
            model += user_vars[user] <= pulp.lpSum(user_cycles)

    for i, cycle in enumerate(cycles):
        cycle_users = set(item_owner[item] for item in cycle)
        for user in cycle_users:
            model += user_vars[user] >= cycle_vars[i]

    user_give_receive = {user: {'give': [], 'receive': []} for user in user_vars}

    for i, cycle in enumerate(cycles):
        n = len(cycle)
        for j in range(n):
            giver_item = cycle[j]
            receiver_item = cycle[(j + 1) % n]
            giver_user = item_owner[giver_item]
            receiver_user = item_owner[receiver_item]

            # Użytkownik oddaje przedmiot
            user_give_receive[giver_user]['give'].append(cycle_vars[i])

            # Użytkownik otrzymuje przedmiot
            user_give_receive[receiver_user]['receive'].append(cycle_vars[i])

    for user in user_vars:
        give_expr = pulp.lpSum(user_give_receive[user]['give'])
        receive_expr = pulp.lpSum(user_give_receive[user]['receive'])
        model += give_expr == receive_expr

    # Rozwiązanie modelu i pomiar czasu
    ilp_start_time = time.time()
    solver = pulp.PULP_CBC_CMD(msg=False)  # Używamy domyślnego solvera CBC
    model.solve(solver)
    ilp_end_time = time.time()
    metrics["ilp_solving_time_seconds"] = ilp_end_time - ilp_start_time

    # Liczba zmiennych i ograniczeń w modelu ILP
    metrics["ilp_num_variables"] = len(model.variables())
    metrics["ilp_num_constraints"] = len(model.constraints)

    # Sprawdzenie statusu rozwiązania
    if model.status != pulp.LpStatusOptimal:
        warn("Nie znaleziono optymalnego rozwiązania.", metrics)
        return []

    # Wybranie cykli, które zostały wybrane w rozwiązaniu
    selected_cycles = [cycles[i] for i in cycle_vars if pulp.value(cycle_vars[i]) == 1]

    metrics["num_cycles_selected"] = len(selected_cycles)
    print(f"Wybrano {len(selected_cycles)} cykli do wymiany.")

    return selected_cycles

def reconstruct_exchanges(cycles, item_owner, item_name, user_lower_to_original, metrics):
    """Rekonstruuje wymiany na podstawie wybranych cykli, grupując je per użytkownik."""
    user_transactions = {}

    for cycle in cycles:
        n = len(cycle)
        for i in range(n):
            user_item = cycle[i]
            user_lower = item_owner[user_item]
            user = user_lower_to_original.get(user_lower, 'Unknown')

            previous_item = cycle[i - 1]

            item_given = item_name.get(user_item, 'Unknown')
            item_received = item_name.get(previous_item, 'Unknown')

            if user not in user_transactions:
                user_transactions[user] = {
                    'items_given': [],
                    'items_received': []
                }
            user_transactions[user]['items_given'].append(item_given)
            user_transactions[user]['items_received'].append(item_received)

    # Zliczenie liczby wymian
    metrics["num_exchanges"] = sum(len(v['items_given']) for v in user_transactions.values())

    return user_transactions

def summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics):
    """Tworzy podsumowanie wymian dla każdego użytkownika."""
    user_summary = {
        user_lower_to_original[user]: {
            'items_offered': list(users_lower[user].get('offers', {}).keys()),
            'items_given': [],
            'items_received': []
        }
        for user in users_lower
    }

    for user, transactions in user_transactions.items():
        if user in user_summary:
            user_summary[user]['items_given'].extend(transactions['items_given'])
            user_summary[user]['items_received'].extend(transactions['items_received'])
        else:
            warn(f"Użytkownik '{user}' nie istnieje w podsumowaniu.", metrics)

    # Obliczanie procentowej uczestnictwa
    total_users = len(user_summary)
    participating_users = sum(
        1 for summary in user_summary.values() if summary['items_given'] or summary['items_received'])
    participation_percent = (participating_users / total_users * 100) if total_users else 0.0
    metrics["participation_percent"] = participation_percent

    return user_summary

def calculate_effectiveness(user_summary, metrics):
    """Oblicza procentową skuteczność wymiany dla wszystkich użytkowników."""
    total_offers = 0
    total_exchanged = 0
    for user, summary in user_summary.items():
        total_offers += len(summary['items_offered'])
        items_exchanged = len(summary['items_given'])
        total_exchanged += items_exchanged

    overall_effectiveness = (total_exchanged / total_offers * 100) if total_offers else 0.0
    metrics["overall_effectiveness_percent"] = overall_effectiveness

def create_trade_graph(users_lower, user_transactions, user_lower_to_original, output_graph_path, metrics):
    """Tworzy wizualizację grafu wymian za pomocą pyvis."""
    try:
        net = Network(height='750px', width='100%', bgcolor='#ffffff', font_color='black', directed=True)

        # Dodajemy węzły dla każdego użytkownika
        for user_lower in users_lower:
            user = user_lower_to_original[user_lower]
            net.add_node(user, label=user, title=user, color='#1f78b4')

        # Tworzymy słownik mapujący przedmioty na właścicieli
        item_to_user = {}
        for user, transactions in user_transactions.items():
            for item in transactions['items_given']:
                item_to_user[item] = user

        # Dodajemy krawędzie reprezentujące wymiany
        for user, transactions in user_transactions.items():
            for item_received in transactions['items_received']:
                giver_user = item_to_user.get(item_received)
                if giver_user:
                    label = f"'{item_received}'"
                    title = f"{giver_user} daje '{item_received}' do {user}"
                    net.add_edge(giver_user, user, title=title, label=label, arrows='to', color='#ff7f0e')

        # Opcje wizualizacji
        net.set_options("""
        var options = {
          "nodes": {
            "font": {
              "size": 16,
              "strokeWidth": 2
            },
            "shape": "dot",
            "size": 16,
            "shadow": {
              "enabled": true,
              "color": "#000000",
              "size": 10,
              "x": 5,
              "y": 5
            }
          },
          "edges": {
            "arrows": {
              "to": {
                "enabled": true,
                "scaleFactor": 1,
                "type": "arrow"
              }
            },
            "color": {
              "color": "#848484",
              "highlight": "#848484",
              "inherit": false,
              "opacity": 1
            },
            "font": {
              "size": 12,
              "align": "middle",
              "color": "#000000",
              "multi": "html"
            },
            "smooth": {
              "enabled": true,
              "type": "continuous"
            }
          },
          "physics": {
            "enabled": true,
            "barnesHut": {
              "gravitationalConstant": -30000,
              "centralGravity": 0.3,
              "springLength": 95,
              "springConstant": 0.04,
              "damping": 0.09,
              "avoidOverlap": 0
            },
            "minVelocity": 0.75
          }
        }
        """)
        net.show(output_graph_path, notebook=False)
        print(f"\nGraf wymian został zapisany jako '{output_graph_path}'. Otwórz ten plik w przeglądarce, aby zobaczyć wizualizację.")
    except Exception as e:
        warn(f"Błąd podczas tworzenia grafu wymian: {e}", metrics)

def process_file(file_path, output_graph_path, metrics):
    """Przetwarza pojedynczy plik JSON i zwraca jego miary oraz informacje o transakcjach."""
    # Inicjalizacja miar
    metrics.update({
        "execution_time_seconds": 0,
        "memory_usage_MB": 0,
        "num_users": 0,
        "num_items": 0,
        "num_cycles_found": 0,
        "num_cycles_selected": 0,
        "num_exchanges": 0,
        "ilp_solving_time_seconds": 0,
        "ilp_num_variables": 0,
        "ilp_num_constraints": 0,
        "num_warnings": 0,
        "overall_effectiveness_percent": 0.0,
        "participation_percent": 0.0
    })

    # Start pomiarów czasu i pamięci
    start_time = time.time()
    tracemalloc.start()

    data = load_data(file_path, metrics)
    if data is None:
        tracemalloc.stop()
        return metrics, {}
    users = data.get('users', {})
    items = data.get('items', {})

    # Aktualizacja miar
    metrics["num_users"] = len(users)
    metrics["num_items"] = len(items)

    # Standaryzacja nazw użytkowników
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}

    # Tworzenie mapowań przedmiotów
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)

    # Oczyszczanie list życzeń
    clean_wishlists(users_lower, item_owner, metrics)

    # Budowanie grafu wymian
    G = build_exchange_graph(users_lower, items, item_owner, metrics)

    # Znajdowanie cykli wymian za pomocą ILP
    selected_cycles = find_exchange_cycles_ilp(G, item_owner, user_lower_to_original, max_cycle_length=10, metrics=metrics)

    # Rekonstrukcja
    user_transactions = reconstruct_exchanges(selected_cycles, item_owner, item_name, user_lower_to_original, metrics)

    # Podsumowanie
    user_summary = summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics)

    # Obliczanie
    calculate_effectiveness(user_summary, metrics)

    # Tworzenie grafu wymian
    create_trade_graph(users_lower, user_transactions, user_lower_to_original, output_graph_path, metrics)

    # Zakończenie pomiarów
    end_time = time.time()
    metrics["execution_time_seconds"] = end_time - start_time
    current, peak = tracemalloc.get_traced_memory()
    metrics["memory_usage_MB"] = peak / (1024 * 1024)
    tracemalloc.stop()

    return metrics, user_transactions



def main():
    """Główna funkcja programu."""
    # Ścieżka do katalogu z plikami JSON
    data_directory = r'C:\Users\szyma\Desktop\System wspomagania i monitorowania procesu wymiany gier\data\for_tests'

    # Znajdź wszystkie pliki JSON w katalogu
    input_files = glob.glob(os.path.join(data_directory, '*.json'))

    if not input_files:
        print("Brak dostępnych plików JSON do przetworzenia.")
        return

    all_metrics = {}

    for file_path in input_files:
        print(f"\nPrzetwarzanie pliku: {file_path}")
        metrics = process_file(file_path)
        all_metrics[file_path] = metrics

    # # Zapisanie wszystkich miar do pliku JSON
    # save_metrics_to_json(all_metrics)
    #
    # # Wyświetlenie wszystkich miar w konsoli
    # display_metrics(all_metrics)


if __name__ == "__main__":
    main()
