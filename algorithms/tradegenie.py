import glob
import json
import networkx as nx
from pulp import LpProblem, LpVariable, LpMaximize, lpSum, LpBinary, LpStatusOptimal
from pyvis.network import Network
import time
import tracemalloc
import os

def warn(message, metrics):
    metrics["num_warnings"] += 1
    print(f"Ostrzeżenie: {message}")

def load_data(file_path, metrics):
    """Wczytuje dane z pliku JSON."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
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

def clean_wishlists(users_lower, item_owner, metrics):
    """Usuwa z list życzeń przedmioty, które nie są dostępne."""
    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_item_id, wishlist in offers.items():
            original_wishlist = wishlist.copy()
            wishlist[:] = [item_id for item_id in wishlist if item_id in item_owner]
            removed_items = set(original_wishlist) - set(wishlist)
            if removed_items:
                warn(f"Usunięto niedostępne przedmioty z listy życzeń oferty '{offer_item_id}' użytkownika '{user_lower}': {removed_items}", metrics)

def build_exchange_graph(users_lower, items, item_owner, metrics):
    """Buduje skierowany graf reprezentujący możliwe wymiany."""
    G = nx.DiGraph()

    # Dodajemy węzły dla każdego przedmiotu
    for item_id in items:
        G.add_node(item_id)

    # Dodajemy krawędzie na podstawie list życzeń
    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_item_id, wishlist in offers.items():
            for priority, wanted_item_id in enumerate(wishlist, start=1):
                if wanted_item_id in item_owner:
                    desired_item_owner = item_owner[wanted_item_id]
                    if desired_item_owner != user_lower:
                        # Krawędź od offer_item_id do wanted_item_id z wagą zależną od priorytetu
                        G.add_edge(offer_item_id, wanted_item_id, weight=1 / priority)
                else:
                    warn(f"Przedmiot '{wanted_item_id}' z listy życzeń użytkownika '{user_lower}' nie jest dostępny.", metrics)

    # Logowanie liczby węzłów i krawędzi po zbudowaniu grafu
    print(f"Liczba węzłów w grafie przed odchwaszczaniem: {G.number_of_nodes()}")
    print(f"Liczba krawędzi w grafie przed odchwaszczaniem: {G.number_of_edges()}")

    return G

def weed_out_unwanted_items(G, item_owner, item_name, metrics):
    """
    Usuwa z grafu i mapowań te przedmioty, których nikt nie chce.
    Jeśli dany węzeł (przedmiot) nie ma żadnej krawędzi przychodzącej,
    oznacza to, że nikt go nie chce i nie może uczestniczyć w wymianie.
    """
    items_to_remove = []
    for item in list(G.nodes()):
        # sprawdzamy krawędzie przychodzące
        if G.in_degree(item) == 0:
            # nikt tego nie chce
            items_to_remove.append(item)

    if items_to_remove:
        warn(f"Usuwanie niechcianych przedmiotów: {items_to_remove}", metrics)
        G.remove_nodes_from(items_to_remove)
        for it in items_to_remove:
            if it in item_owner:
                del item_owner[it]
            if it in item_name:
                del item_name[it]

    print(f"Liczba węzłów w grafie po odchwaszczaniu: {G.number_of_nodes()}")
    print(f"Liczba krawędzi w grafie po odchwaszczaniu: {G.number_of_edges()}")

def find_most_popular_item(G):
    """
    Znajduje najpopularniejszy przedmiot jako punkt startowy.
    Za miarę popularności uznajemy liczbę krawędzi przychodzących (ile osób go chce).
    """
    best_item = None
    best_score = -1
    for item in G.nodes():
        score = G.in_degree(item)
        if score > best_score:
            best_score = score
            best_item = item
    return best_item

def find_cycles(G, max_cycle_length=8, metrics=None):
    """Znajduje wszystkie cykle o długości do max_cycle_length."""
    cycles = []
    for cycle in nx.simple_cycles(G):
        if 2 <= len(cycle) <= max_cycle_length:
            cycles.append(cycle)
    if metrics is not None:
        metrics["num_cycles_found"] = len(cycles)
    print(f"Liczba znalezionych cykli: {len(cycles)}")
    return cycles

def optimize_trades(G, cycles, metrics):
    """Optymalizuje wymiany, wybierając rozłączne cykle maksymalizujące liczbę wymian."""
    prob = LpProblem("Trade_Optimization", LpMaximize)

    # Zmienna decyzyjna dla każdego cyklu: 1 jeśli cykl jest wybrany, 0 w przeciwnym razie
    cycle_vars = LpVariable.dicts("Cycle", range(len(cycles)), cat=LpBinary)

    # Funkcja celu: maksymalizacja liczby wymian
    prob += lpSum([len(cycles[i]) * cycle_vars[i] for i in range(len(cycles))])

    # Ograniczenia: każdy przedmiot może uczestniczyć maksymalnie w jednym cyklu
    item_to_cycles = {}
    for i, cycle in enumerate(cycles):
        for item in cycle:
            if item not in item_to_cycles:
                item_to_cycles[item] = []
            item_to_cycles[item].append(cycle_vars[i])

    for item, vars_list in item_to_cycles.items():
        prob += lpSum(vars_list) <= 1

    # Rozwiązanie problemu ILP i pomiar czasu
    ilp_start_time = time.time()
    prob.solve()
    ilp_end_time = time.time()
    metrics["ilp_solving_time_seconds"] = ilp_end_time - ilp_start_time

    # Liczba zmiennych i ograniczeń w modelu ILP
    metrics["ilp_num_variables"] = len(prob.variables())
    metrics["ilp_num_constraints"] = len(prob.constraints)

    # Sprawdzenie statusu rozwiązania
    if prob.status != LpStatusOptimal:
        warn("Nie znaleziono optymalnego rozwiązania.", metrics)
        return []

    # Wybranie cykli, które zostały wybrane w rozwiązaniu
    selected_cycles = [cycles[i] for i in cycle_vars if cycle_vars[i].varValue == 1]

    metrics["num_cycles_selected"] = len(selected_cycles)
    print(f"Wybrano {len(selected_cycles)} cykli do wymiany.")

    # Zapisywanie aktualnego najlepszego wyniku do pliku (jak w opisie TradeGenie)
    # Możesz tu dodać zapis do pliku JSON z aktualnym najlepszym rozwiązaniem
    # np.:
    # with open('partial_result.json', 'w', encoding='utf-8') as f:
    #     json.dump(selected_cycles, f, ensure_ascii=False, indent=4)

    return selected_cycles

def reconstruct_exchanges(selected_cycles, item_owner, item_name, user_lower_to_original, metrics):
    """Rekonstruuje wymiany na podstawie wybranych cykli, grupując je per użytkownik."""
    user_transactions = {}

    for cycle in selected_cycles:
        n = len(cycle)
        for i in range(n):
            giver_item = cycle[i]
            receiver_item = cycle[(i + 1) % n]
            giver_user_lower = item_owner[giver_item]
            receiver_user_lower = item_owner[receiver_item]

            giver_user = user_lower_to_original.get(giver_user_lower, 'Unknown')
            receiver_user = user_lower_to_original.get(receiver_user_lower, 'Unknown')

            # Zapobieganie odbieraniu własnych przedmiotów
            if giver_user == receiver_user:
                warn(f"Użytkownik '{giver_user}' próbuje wymienić przedmiot '{giver_item}' na własny '{receiver_item}'. Pomijanie wymiany.", metrics)
                continue

            item_given = item_name.get(giver_item, 'Unknown')
            item_received = item_name.get(receiver_item, 'Unknown')

            if giver_user not in user_transactions:
                user_transactions[giver_user] = {
                    'items_given': [],
                    'items_received': []
                }
            user_transactions[giver_user]['items_given'].append(item_given)
            user_transactions[giver_user]['items_received'].append(item_received)

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

    total_users = len(user_summary)
    participating_users = sum(
        1 for summary in user_summary.values() if summary['items_given'] or summary['items_received'])
    participation_percent = (participating_users / total_users * 100) if total_users else 0.0
    metrics["participation_percent"] = participation_percent

    return user_summary

def calculate_effectiveness(user_summary, metrics):
    """Oblicza i zapisuje procentową skuteczność wymiany dla wszystkich użytkowników."""
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
        for user_lower in users_lower:
            user = user_lower_to_original[user_lower]
            net.add_node(user, label=user, title=user, color='#1f78b4')

        item_to_user = {}
        for user, transactions in user_transactions.items():
            for item in transactions['items_given']:
                item_to_user[item] = user

        for user, transactions in user_transactions.items():
            for item_received in transactions['items_received']:
                giver_user = item_to_user.get(item_received)
                if giver_user:
                    label = f"'{item_received}'"
                    title = f"{giver_user} daje '{item_received}' do {user}"
                    net.add_edge(giver_user, user, title=title, label=label, arrows='to', color='#ff7f0e')

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

    start_time = time.time()
    tracemalloc.start()

    data = load_data(file_path, metrics)
    if data is None:
        tracemalloc.stop()
        return metrics, {}

    users = data.get('users', {})
    items = data.get('items', {})

    metrics["num_users"] = len(users)
    metrics["num_items"] = len(items)

    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}

    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)

    clean_wishlists(users_lower, item_owner, metrics)

    G = build_exchange_graph(users_lower, items, item_owner, metrics)

    # Odchwaszczanie niechcianych przedmiotów
    weed_out_unwanted_items(G, item_owner, item_name, metrics)

    # Wybór najpopularniejszego przedmiotu startowego (opcjonalne)
    start_item = find_most_popular_item(G)
    print(f"Najpopularniejszy przedmiot startowy to: {start_item}")

    # Znajdowanie cykli
    cycles = find_cycles(G, max_cycle_length=8, metrics=metrics)

    selected_cycles = optimize_trades(G, cycles, metrics)

    user_transactions = reconstruct_exchanges(selected_cycles, item_owner, item_name, user_lower_to_original, metrics)

    user_summary = summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics)

    calculate_effectiveness(user_summary, metrics)

    create_trade_graph(users_lower, user_transactions, user_lower_to_original, output_graph_path, metrics)

    end_time = time.time()
    metrics["execution_time_seconds"] = end_time - start_time
    current, peak = tracemalloc.get_traced_memory()
    metrics["memory_usage_MB"] = peak / (1024 * 1024)
    tracemalloc.stop()

    return metrics, user_transactions

def main():
    data_directory = r'C:\Users\szyma\Desktop\System wspomagania i monitorowania procesu wymiany gier\data'
    input_files = glob.glob(os.path.join(data_directory, '*.json'))

    if not input_files:
        print("Brak dostępnych plików JSON do przetworzenia.")
        return

    all_metrics = {}

    for file_path in input_files:
        print(f"\nPrzetwarzanie pliku: {file_path}")
        metrics, user_transactions = process_file(file_path, f"trade_graph_{os.path.basename(file_path)}.html", {})
        all_metrics[file_path] = metrics

    # Można tu dodać zapisywanie all_metrics do pliku, jeśli to potrzebne.

if __name__ == "__main__":
    main()
