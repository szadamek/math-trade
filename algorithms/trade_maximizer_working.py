import json
import networkx as nx
from networkx.algorithms import bipartite
import pulp
from pyvis.network import Network
import time
import tracemalloc
import os
import glob


def warn(message, metrics):
    metrics["num_warnings"] += 1
    print(f"Ostrzeżenie: {message}")


def load_data(file_path, metrics):
    """Wczytuje dane z pliku JSON"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return json.load(file)
    except Exception as e:
        warn(f"Nie można wczytać pliku '{file_path}': {e}", metrics)
        return None


def standardize_usernames(users):
    """Tworzy mapowanie nazw użytkowników w lowercase do oryginalnych nazw"""
    return {user.lower(): user for user in users}


def create_item_mappings(items, user_lower_to_original, metrics):
    """Tworzy mapowania właścicieli przedmiotów i nazw z ujednoliconymi nazwami użytkowników"""
    item_owner = {}
    item_name = {}
    for item_id, item_info in items.items():
        owner_lower = item_info['owner'].lower()
        if owner_lower in user_lower_to_original:
            item_owner[item_id] = owner_lower
            item_name[item_id] = item_info['name']
        else:
            warn(f"Właściciel '{item_info['owner']}' przedmiotu '{item_id}' nie znajduje się w users.", metrics)
            item_owner[item_id] = owner_lower  # Możesz ustawić na 'Unknown' lub inną wartość
            item_name[item_id] = item_info['name']
    return item_owner, item_name


def clean_wishlists(users_lower, item_owner, metrics):
    """Usuwa z list życzeń przedmioty, które nie są dostępne"""
    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_id, wishlist in offers.items():
            original_wishlist = wishlist.copy()
            wishlist[:] = [item_id for item_id in wishlist if item_id in item_owner]
            removed_items = set(original_wishlist) - set(wishlist)
            if removed_items:
                warn(
                    f"Usunięto niedostępne przedmioty z listy życzeń oferty '{offer_id}' użytkownika '{user_lower}': {removed_items}",
                    metrics)


def build_exchange_graph(users_lower, items, item_owner, metrics):
    """Buduje dwudzielny graf reprezentujący możliwe wymiany, dzieląc wierzchołki na Receiver i Sender."""
    G = nx.Graph()

    # Dla każdego przedmiotu tworzymy dwa węzły: Receiver (R) i Sender (S)
    for item_id in items:
        G.add_node(f"{item_id}_R", bipartite=0)  # Grupa 0: Receivery
        G.add_node(f"{item_id}_S", bipartite=1)  # Grupa 1: Sendery

        # Dodajemy self-edge między Receiver i Sender tego samego przedmiotu (self-edge)
        # Reprezentuje to możliwość pozostania z własnym przedmiotem (brak wymiany)
        G.add_edge(f"{item_id}_R", f"{item_id}_S",
                   weight=1000000000)  # Duży koszt, aby zniechęcić do pozostawiania przedmiotów

    # Dodajemy krawędzie na podstawie list życzeń
    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_id, wishlist in offers.items():
            for wish_item_id in wishlist:
                if wish_item_id in item_owner:
                    desired_item_owner = item_owner[wish_item_id]
                    if desired_item_owner != user_lower:
                        # Krawędź od Receiver oferowanego przedmiotu do Sendera życzenia
                        G.add_edge(f"{offer_id}_R", f"{wish_item_id}_S", weight=1)
                else:
                    warn(f"Przedmiot '{wish_item_id}' z listy życzeń użytkownika '{user_lower}' nie jest dostępny.",
                         metrics)

    return G


def find_minimum_cost_perfect_matching(G, metrics):
    """Znajduje minimalny koszt doskonałego skojarzenia w grafie dwudzielnym."""
    # Upewniamy się, że graf jest dwudzielny
    is_bipartite = nx.is_bipartite(G)
    if not is_bipartite:
        warn("Graf nie jest dwudzielny.", metrics)
        return {}

    # Wyodrębniamy węzły z dwóch części
    left_nodes = {n for n, d in G.nodes(data=True) if d.get('bipartite') == 0}
    right_nodes = set(G.nodes()) - left_nodes

    # Znajdujemy minimalny koszt doskonałego skojarzenia
    try:
        matching = bipartite.minimum_weight_full_matching(G, top_nodes=left_nodes, weight='weight')
    except Exception as e:
        warn(f"Nie udało się znaleźć minimalnego kosztu doskonałego skojarzenia: {e}", metrics)
        matching = {}

    return matching


def reconstruct_exchanges_from_matching(matching, item_owner, item_name, user_lower_to_original, metrics):
    """Rekonstruuje wymiany na podstawie znalezionego skojarzenia."""
    user_transactions = {}
    exchanges = []

    for node_u, node_v in matching.items():
        if node_u.endswith('_R'):
            receiver_node = node_u
            sender_node = node_v
        else:
            continue

        receiver_item_id = receiver_node[:-2]
        sender_item_id = sender_node[:-2]

        if receiver_item_id == sender_item_id:
            continue

        receiver_user_lower = item_owner[receiver_item_id]
        sender_user_lower = item_owner[sender_item_id]

        receiver_user = user_lower_to_original.get(receiver_user_lower, 'Unknown')
        sender_user = user_lower_to_original.get(sender_user_lower, 'Unknown')

        item_given = item_name[receiver_item_id]
        item_received = item_name[sender_item_id]

        exchanges.append({
            'from_user': receiver_user,
            'to_user': sender_user,
            'item': item_given,
        })

        if receiver_user not in user_transactions:
            user_transactions[receiver_user] = {'items_given': [], 'items_received': []}
        user_transactions[receiver_user]['items_given'].append(item_given)
        user_transactions[receiver_user]['items_received'].append(item_received)

        if sender_user not in user_transactions:
            user_transactions[sender_user] = {'items_given': [], 'items_received': []}
        user_transactions[sender_user]['items_given'].append(item_received)
        user_transactions[sender_user]['items_received'].append(item_given)

    metrics["num_exchanges"] = len(exchanges)

    return user_transactions, exchanges


def display_transactions(user_transactions):
    """Wyświetla wyniki transakcji oraz łączną liczbę wymian"""
    print("\nWyniki Transakcji:")
    if user_transactions:
        for user, transactions in user_transactions.items():
            for item_given, item_received in zip(transactions['items_given'], transactions['items_received']):
                print(f"{user} oddaje '{item_given}' i otrzymuje '{item_received}'")
        total_exchanges = sum(len(v['items_given']) for v in user_transactions.values())
        print(f"\nŁączna liczba wymian: {total_exchanges}")
    else:
        print("Brak transakcji.")


def summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics):
    """Tworzy podsumowanie wymian dla każdego użytkownika"""
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


def display_user_summary(user_summary):
    """Wyświetla podsumowanie wymian dla każdego użytkownika"""
    print("\nPodsumowanie wymian dla każdego użytkownika:")
    for user, summary in user_summary.items():
        print(f"\nUżytkownik {user}:")
        if summary['items_given'] or summary['items_received']:
            if summary['items_given']:
                print("  Przedmioty oddane:")
                for item in summary['items_given']:
                    print(f"    - {item}")
            else:
                print("  Nie oddał żadnych przedmiotów.")
            if summary['items_received']:
                print("  Przedmioty otrzymane:")
                for item in summary['items_received']:
                    print(f"    - {item}")
            else:
                print("  Nie otrzymał żadnych przedmiotów.")
        else:
            print("  Nie dokonał żadnej wymiany.")


def calculate_effectiveness(user_summary, metrics):
    """Oblicza i wyświetla procentową skuteczność wymiany dla każdego użytkownika."""
    print("\nProcentowa skuteczność wymiany dla każdego użytkownika:")
    total_offers = 0
    total_exchanged = 0
    for user, summary in user_summary.items():
        num_offered = len(summary['items_offered'])
        num_exchanged = len(summary['items_given'])
        total_offers += num_offered
        total_exchanged += num_exchanged
        effectiveness = (num_exchanged / num_offered * 100) if num_offered else 0.0
        print(f"- {user}: {effectiveness:.2f}% ({num_exchanged}/{num_offered} wymienionych przedmiotów)")

    # Obliczanie ogólnej skuteczności
    overall_effectiveness = (total_exchanged / total_offers * 100) if total_offers else 0.0
    metrics["overall_effectiveness_percent"] = overall_effectiveness
    print(
        f"\nOgólna skuteczność wymiany: {overall_effectiveness:.2f}% ({total_exchanged}/{total_offers} wymienionych przedmiotów)")


def calculate_participation_distribution(user_transactions, users, metrics):
    """
    Oblicza, ile wymian przypada na każdego użytkownika.
    """
    # Inicjalizacja słownika z liczbą wymian dla każdego użytkownika
    user_exchange_counts = {user: 0 for user in users}

    for user, transactions in user_transactions.items():
        user_exchange_counts[user] += len(transactions['items_given'])
        user_exchange_counts[user] += len(transactions['items_received'])

    # Tworzymy dystrybucję uczestnictwa
    participation_distribution = {}
    for count in user_exchange_counts.values():
        participation_distribution[count] = participation_distribution.get(count, 0) + 1

    return participation_distribution


def display_participation_distribution(participation_distribution):
    """
    Wyświetla statystyki uczestnictwa w wymianach.
    """
    print("\nStatystyki uczestnictwa w wymianach:")
    for count, num_users in sorted(participation_distribution.items()):
        print(f"{num_users} użytkowników uczestniczyło w {count} wymianach.")


def create_trade_graph(users_lower, user_lower_to_original, exchanges, output_graph_path, metrics):
    """Tworzy wizualizację grafu wymian za pomocą pyvis"""
    try:
        net = Network(height='750px', width='100%', bgcolor='#ffffff', font_color='black', directed=True)

        for user_lower in users_lower:
            user = user_lower_to_original[user_lower]
            net.add_node(user, label=user, title=user, color='#1f78b4')

        for exchange in exchanges:
            from_user = exchange['from_user']
            to_user = exchange['to_user']
            item = exchange['item']

            label = f"'{item}'"
            title = f"{from_user} daje '{item}' do {to_user}"
            net.add_edge(from_user, to_user, title=title, label=label, arrows='to', color='#ff7f0e')

        # Ustawienia wizualizacji
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

        # Zapisanie grafu do pliku HTML z notebook=False
        net.show(output_graph_path, notebook=False)
        print(
            f"\nGraf wymian został zapisany jako '{output_graph_path}'. Otwórz ten plik w przeglądarce, aby zobaczyć wizualizację.")
    except Exception as e:
        warn(f"Error while creating trade graph: {e}", metrics)


def save_metrics_to_json(all_metrics,
                         output_file='C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\benchmark\\benchmark_metrics_trademaximizer.json'):
    """Zapisuje wszystkie miary do pliku JSON"""
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_metrics, f, ensure_ascii=False, indent=4)
        print(f"\nMiary benchmark zostały zapisane do pliku '{output_file}'.")
    except Exception as e:
        print(f"Nie można zapisać miar do pliku '{output_file}': {e}")


def display_metrics(all_metrics):
    """Wyświetla wszystkie miary w konsoli"""
    print("\nBenchmark Metrics:")
    print(json.dumps(all_metrics, ensure_ascii=False, indent=4))


def process_file(file_path, output_graph_path, metrics):
    """Przetwarza pojedynczy plik JSON i zwraca jego miary oraz informacje o transakcjach."""
    # Inicjalizacja miar
    metrics.update({
        "execution_time_seconds": 0,
        "memory_usage_MB": 0,
        "num_users": 0,
        "num_items": 0,
        "num_exchanges": 0,
        "num_warnings": 0
    })

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

    # Znajdowanie minimalnego kosztu doskonałego skojarzenia
    matching = find_minimum_cost_perfect_matching(G, metrics)

    # Rekonstrukcja
    user_transactions, exchanges = reconstruct_exchanges_from_matching(matching, item_owner, item_name,
                                                                       user_lower_to_original,
                                                                       metrics)

    # Wyświetlanie wyników
    display_transactions(user_transactions)

    # Podsumowanie
    user_summary = summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics)
    display_user_summary(user_summary)

    # Obliczanie
    calculate_effectiveness(user_summary, metrics)

    # Obliczanie i wyświetlanie statystyk
    participation_distribution = calculate_participation_distribution(user_transactions, users.keys(), metrics)
    display_participation_distribution(participation_distribution)

    create_trade_graph(users_lower, user_lower_to_original, exchanges, output_graph_path, metrics)

    # Zakończenie pomiarów
    end_time = time.time()
    metrics["execution_time_seconds"] = end_time - start_time
    current, peak = tracemalloc.get_traced_memory()
    metrics["memory_usage_MB"] = peak / (1024 * 1024)
    tracemalloc.stop()

    return metrics, user_transactions


def main():
    """Główna funkcja programu."""
    data_directory = r'C:\Users\szyma\Desktop\System wspomagania i monitorowania procesu wymiany gier\data\for_tests'  # Zmień na odpowiednią ścieżkę

    input_files = glob.glob(os.path.join(data_directory, '*.json'))

    if not input_files:
        print("Brak dostępnych plików JSON do przetworzenia.")
        return

    all_metrics = {}

    for file_path in input_files:
        print(f"\nPrzetwarzanie pliku: {file_path}")
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_graph_path = f"trade_graph_{base_name}.html"
        metrics = {}
        metrics, user_transactions = process_file(file_path, output_graph_path, metrics)
        all_metrics[file_path] = metrics

    save_metrics_to_json(all_metrics)

    display_metrics(all_metrics)


if __name__ == "__main__":
    main()
