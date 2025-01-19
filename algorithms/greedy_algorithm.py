import json
import networkx as nx
import time
import tracemalloc
import os
import glob


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


def build_ownership_map(items):
    """Tworzy mapowanie przedmiotów do właścicieli."""
    ownership = {}
    for item_id, item_info in items.items():
        ownership[item_id] = item_info['owner'].lower()  # Standaryzacja na małe litery
    return ownership


def build_graph(users, items, assigned_items, metrics):
    """Buduje graf wymian jako obiekt NetworkX DiGraph."""
    ownership = build_ownership_map(items)
    G = nx.DiGraph()

    for user, user_info in users.items():
        user_lower = user.lower()
        for item_id, desired_items in user_info.get('offers', {}).items():
            if item_id in assigned_items:
                continue
            for desired_item in desired_items:
                if desired_item in assigned_items:
                    continue
                if desired_item in items and ownership[desired_item] != user_lower:
                    priority = desired_items.index(
                        desired_item) + 1
                    G.add_edge(item_id, desired_item, weight=1 / priority)
                else:
                    warn(
                        f"Przedmiot '{desired_item}' w ofercie '{item_id}' użytkownika '{user}' jest własnością użytkownika '{ownership.get(desired_item, 'Unknown')}'.",
                        metrics)
    return G


def find_cycles(G, max_cycle_length=6, metrics=None):
    """Znajduje wszystkie cykle w grafie do określonej długości."""
    cycles = []
    for cycle in nx.simple_cycles(G):
        if 2 <= len(cycle) <= max_cycle_length:
            cycles.append(cycle)
    if metrics is not None:
        metrics["num_cycles_found"] = len(cycles)
    print(f"Znaleziono {len(cycles)} cykli.")
    return cycles


def find_possible_exchanges(users, items, metrics, max_cycle_length=6):
    """Znajduje możliwe wymiany w sposób zachłanny."""
    ownership = build_ownership_map(items)
    assigned_items = set()
    exchanges = []

    G = build_graph(users, items, assigned_items, metrics)
    cycles = find_cycles(G, max_cycle_length, metrics)

    # Sortowanie cykli według długości - malejąco
    cycles.sort(key=lambda x: -len(x))

    for cycle in cycles:
        if any(item in assigned_items for item in cycle):
            continue
        # Przypisujemy cykl
        n = len(cycle)
        cycle_valid = True
        temp_exchanges = []
        for i in range(n):
            from_item = cycle[i]
            to_item = cycle[(i + 1) % n]
            from_user = ownership.get(from_item, 'unknown')
            to_user = ownership.get(to_item, 'unknown')
            # Zapobieganie wymianie przedmiotów własnych
            if from_user == to_user:
                warn(
                    f"Użytkownik '{from_user}' próbuje wymienić przedmiot '{from_item}' na własny '{to_item}'. Pomijanie wymiany.",
                    metrics)
                cycle_valid = False
                break
            temp_exchanges.append({
                'from_user': from_user,
                'to_user': to_user,
                'item_given': from_item,
                'item_received': to_item
            })
        if cycle_valid:
            exchanges.extend(temp_exchanges)
            assigned_items.update(cycle)
            # Aktualizacja grafu poprzez usunięcie przypisanych przedmiotów
            G.remove_nodes_from(cycle)

    metrics["num_exchanges"] = len(exchanges)
    print(f"Łączna liczba wymian: {len(exchanges)}")
    return exchanges


def summarize_exchanges(users, exchanges, metrics):
    """Tworzy podsumowanie wymian dla każdego użytkownika."""
    user_summary = {
        user.lower(): {  # Standaryzacja na małe litery
            'items_offered': set([item.lower() for item in user_info.get('offers', {}).keys()]),
            'items_given': set(),
            'items_received': set()
        }
        for user, user_info in users.items()
    }

    for exchange in exchanges:
        from_user = exchange['from_user'].lower()
        to_user = exchange['to_user'].lower()
        item_given = exchange['item_given'].lower()
        item_received = exchange['item_received'].lower()

        if from_user in user_summary:
            user_summary[from_user]['items_given'].add(item_given)
            user_summary[from_user]['items_received'].add(item_received)
        else:
            warn(f"Użytkownik '{exchange['from_user']}' nie istnieje w podsumowaniu.", metrics)

        if to_user in user_summary:
            user_summary[to_user]['items_received'].add(item_received)
        else:
            warn(f"Użytkownik '{exchange['to_user']}' nie istnieje w podsumowaniu.", metrics)

    # Obliczanie procentu użytkowników uczestniczących w wymianach
    participating_users = sum(
        1 for summary in user_summary.values() if summary['items_given'] or summary['items_received'])
    total_users = len(user_summary)
    participation_percent = (participating_users / total_users * 100) if total_users else 0.0
    metrics["participation_percent"] = participation_percent

    return user_summary


def display_transactions(exchanges, metrics):
    """Wyświetla wyniki wymian oraz zlicza liczbę wymian."""
    print("\nWyniki Transakcji:")
    if exchanges:
        for exchange in exchanges:
            item_given_name = exchange['item_given']
            item_received_name = exchange['item_received']
            print(f"{exchange['from_user']} oddaje '{item_given_name}' i otrzymuje '{item_received_name}'")
        total_exchanges = len(exchanges)
        print(f"\nŁączna liczba wymian: {total_exchanges}")
        metrics["num_exchanges"] = total_exchanges
    else:
        print("Brak transakcji.")


def display_user_summary(user_summary):
    """Wyświetla podsumowanie wymian dla każdego użytkownika."""
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
        total_offers += len(summary['items_offered'])
        items_exchanged = len(summary['items_given'])
        total_exchanged += items_exchanged
        effectiveness = (items_exchanged / len(summary['items_offered']) * 100) if summary['items_offered'] else 0.0
        print(f"- {user}: {effectiveness:.2f}% ({items_exchanged}/{len(summary['items_offered'])} wymienionych gier)")

    overall_effectiveness = (total_exchanged / total_offers * 100) if total_offers else 0.0
    metrics["overall_effectiveness_percent"] = overall_effectiveness
    print(
        f"\nOgólna skuteczność wymiany: {overall_effectiveness:.2f}% ({total_exchanged}/{total_offers} wymienionych gier)")


def create_trade_graph(users, exchanges, output_graph_path, metrics):
    """Tworzy wizualizację grafu wymian za pomocą pyvis."""
    try:
        from pyvis.network import Network
    except ImportError:
        warn("Biblioteka pyvis nie jest zainstalowana. Pomijanie tworzenia grafu wymian.", metrics)
        return

    net = Network(height='750px', width='100%', bgcolor='#ffffff', font_color='black', directed=True)

    # Dodajemy węzły dla każdego użytkownika
    for user in users:
        user_lower = user.lower()
        net.add_node(user_lower, label=user, title=user, color='#1f78b4')

    # Tworzymy słownik mapujący przedmioty na właścicieli
    item_to_user = {}
    for exchange in exchanges:
        item_to_user[exchange['item_given']] = exchange['from_user'].lower()

    # Dodajemy krawędzie reprezentujące wymiany
    for exchange in exchanges:
        giver_user = exchange['from_user'].lower()
        receiver_user = exchange['to_user'].lower()
        item_given = exchange['item_given']
        item_received = exchange['item_received']
        label = f"'{item_given}' → '{item_received}'"
        title = f"{exchange['from_user']} daje '{item_given}' do {exchange['to_user']} i otrzymuje '{item_received}'"

        # Sprawdzenie, czy oba użytkownicy są w grafie
        if giver_user not in net.nodes:
            warn(f"Użytkownik '{exchange['from_user']}' nie istnieje w grafie. Pomijanie krawędzi.", metrics)
            continue
        if receiver_user not in net.nodes:
            warn(f"Użytkownik '{exchange['to_user']}' nie istnieje w grafie. Pomijanie krawędzi.", metrics)
            continue

        net.add_edge(giver_user, receiver_user, title=title, label=label, arrows='to', color='#ff7f0e')

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
    print(
        f"\nGraf wymian został zapisany jako '{output_graph_path}'. Otwórz ten plik w przeglądarce, aby zobaczyć wizualizację.")


def save_metrics_to_json(all_metrics,
                         output_file='C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\benchmark\\benchmark_metrics_greedy_algorithm.json'):
    """Zapisuje wszystkie miary do pliku JSON."""
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_metrics, f, ensure_ascii=False, indent=4)
        print(f"\nMiary benchmark zostały zapisane do pliku '{output_file}'.")
    except Exception as e:
        print(f"Nie można zapisać miar do pliku '{output_file}': {e}")


def display_metrics(all_metrics):
    """Wyświetla wszystkie miary w konsoli."""
    print("\nBenchmark Metrics:")
    print(json.dumps(all_metrics, ensure_ascii=False, indent=4))


def process_file(file_path, max_cycle_length=6):
    """Przetwarza pojedynczy plik JSON i zwraca jego miary."""
    metrics = {
        "execution_time_seconds": 0,
        "memory_usage_MB": 0,
        "num_users": 0,
        "num_items": 0,
        "num_cycles_found": 0,
        "num_exchanges": 0,
        "num_warnings": 0,
        "overall_effectiveness_percent": 0.0,
        "participation_percent": 0.0
    }

    # Start pomiarów czasu i pamięci
    start_time = time.time()
    tracemalloc.start()

    data = load_data(file_path, metrics)
    if data is None:
        tracemalloc.stop()
        return metrics

    users = data.get('users', {})
    items = data.get('items', {})

    # Aktualizacja miar
    metrics["num_users"] = len(users)
    metrics["num_items"] = len(items)

    # Znajdowanie możliwych wymian
    exchanges = find_possible_exchanges(users, items, metrics, max_cycle_length=max_cycle_length)

    # Wyświetlanie wyników
    display_transactions(exchanges, metrics)

    # Podsumowanie wymian
    user_summary = summarize_exchanges(users, exchanges, metrics)
    display_user_summary(user_summary)

    # Obliczanie skuteczności
    calculate_effectiveness(user_summary, metrics)

    # Tworzenie grafu wymian
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    output_graph_path = f"trade_graph_{base_name}.html"
    create_trade_graph(users, exchanges, output_graph_path, metrics)

    # Zakończenie pomiarów czasu i pamięci
    end_time = time.time()
    metrics["execution_time_seconds"] = end_time - start_time
    current, peak = tracemalloc.get_traced_memory()
    metrics["memory_usage_MB"] = peak / (1024 * 1024)  # MB
    tracemalloc.stop()

    return metrics


def main():
    """Główna funkcja programu."""
    data_directory = r'C:\Users\szyma\Desktop\System wspomagania i monitorowania procesu wymiany gier\data\for_tests'

    input_files = glob.glob(os.path.join(data_directory, '*.json'))

    if not input_files:
        print("Brak dostępnych plików JSON do przetworzenia.")
        return

    all_metrics = {}

    for file_path in input_files:
        print(f"\nPrzetwarzanie pliku: {file_path}")
        metrics = process_file(file_path)
        all_metrics[file_path] = metrics

    save_metrics_to_json(all_metrics)

    display_metrics(all_metrics)


if __name__ == "__main__":
    main()
