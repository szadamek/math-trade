import glob
import json
import os

import networkx as nx
import random
import time
import tracemalloc


def warn(message, metrics):
    metrics["num_warnings"] += 1


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


def build_exchange_graph(users_lower, items, item_owner, metrics):
    """Buduje skierowany graf reprezentujący możliwe wymiany z uwzględnieniem priorytetów"""
    G = nx.DiGraph()

    G.add_nodes_from(items.keys())

    for user_lower, user_data in users_lower.items():
        offers = user_data.get('offers', {})
        for offer_id, wishlist in offers.items():
            for priority, wish_item_id in enumerate(wishlist, start=1):
                if wish_item_id in item_owner:
                    desired_item_owner = item_owner[wish_item_id]
                    if desired_item_owner != user_lower:
                        weight = 1 / priority
                        G.add_edge(offer_id, wish_item_id, weight=weight)
                else:
                    warn(f"Przedmiot '{wish_item_id}' z listy życzeń użytkownika '{user_lower}' nie jest dostępny.",
                         metrics)

    return G


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


def find_all_cycles(G, max_cycle_length):
    """Znajduje wszystkie cykle do długości max_cycle_length"""
    cycles = []
    for cycle in nx.simple_cycles(G):
        if len(cycle) <= max_cycle_length:
            cycles.append(cycle)
    return cycles


def initialize_population(all_cycles, population_size, item_owner):
    """Inicjalizuje populację chromosomów (rozwiązań)"""
    population = []
    for _ in range(population_size):
        random.shuffle(all_cycles)
        chromosome = []
        items_used = set()
        for cycle in all_cycles:
            if not items_used.intersection(cycle):
                chromosome.append(cycle)
                items_used.update(cycle)
        population.append(chromosome)
    return population


def fitness_function(chromosome, item_owner):
    """Oblicza wartość funkcji przystosowania dla danego chromosomu"""
    players_involved = set()
    for cycle in chromosome:
        for item_id in cycle:
            owner = item_owner[item_id]
            players_involved.add(owner)
    num_players = len(players_involved)
    return num_players


def selection(population, fitness_values, num_parents):
    """Selekcja ruletkowa."""
    total_fitness = sum(fitness_values)
    if total_fitness == 0:
        # Wszystkie wartości fitness są zero; wybierz losowo
        return random.sample(population, num_parents)
    selection_probs = [f / total_fitness for f in fitness_values]
    parents = random.choices(population, weights=selection_probs, k=num_parents)
    return parents


def crossover(parent1, parent2):
    """Krzyżowanie, które łączy cykle z obu rodziców unikając konfliktów."""
    child = []
    items_used = set()

    for cycle in parent1:
        if not items_used.intersection(cycle):
            child.append(cycle)
            items_used.update(cycle)

    for cycle in parent2:
        if not items_used.intersection(cycle):
            child.append(cycle)
            items_used.update(cycle)

    return child


def mutation(chromosome, all_cycles, mutation_rate):
    """Mutacja chromosomu przez dodanie lub usunięcie cyklu"""
    if random.uniform(0, 1) < mutation_rate:
        operation = random.choice(['add', 'remove'])
        if operation == 'add':
            items_used = set()
            for cycle in chromosome:
                items_used.update(cycle)
            remaining_cycles = [cycle for cycle in all_cycles if not items_used.intersection(cycle)]
            if remaining_cycles:
                new_cycle = random.choice(remaining_cycles)
                chromosome.append(new_cycle)
        elif operation == 'remove' and chromosome:
            chromosome.pop(random.randint(0, len(chromosome) - 1))
    return chromosome


def calculate_diversity(population):
    """Oblicza różnorodność populacji."""
    unique_individuals = {tuple(sorted([tuple(sorted(cycle)) for cycle in chromosome])) for chromosome in population}
    diversity = len(unique_individuals) / len(population)
    return diversity


def genetic_algorithm(G, item_owner, all_cycles, population_size=100, num_generations=200, crossover_rate=0.8,
                      mutation_rate=0.1, elite_size=2):
    """Algorytm genetyczny do optymalizacji wymian"""

    population = initialize_population(all_cycles, population_size, item_owner)

    best_solution = None
    best_fitness = -float('inf')
    no_improvement_counter = 0
    max_no_improvement = 10  # Liczba pokoleń bez poprawy, po której zwiększymy mutation_rate

    for generation in range(num_generations):
        fitness_values = [fitness_function(chromosome, item_owner) for chromosome in population]

        sorted_population = [x for _, x in
                             sorted(zip(fitness_values, population), key=lambda pair: pair[0], reverse=True)]
        fitness_values.sort(reverse=True)

        if fitness_values[0] > best_fitness:
            best_fitness = fitness_values[0]
            best_solution = sorted_population[0]
            no_improvement_counter = 0
        else:
            no_improvement_counter += 1

        new_population = sorted_population[:elite_size]

        num_parents = int(population_size * crossover_rate)
        parents = selection(population, fitness_values, num_parents)

        while len(new_population) < population_size:
            parent1, parent2 = random.sample(parents, 2)
            child = crossover(parent1, parent2)
            child = mutation(child, all_cycles, mutation_rate)
            new_population.append(child)

        population = new_population

        if no_improvement_counter > max_no_improvement:
            mutation_rate = min(mutation_rate * 1.5, 0.5)
            no_improvement_counter = 0

        diversity = calculate_diversity(population)
        if diversity < 0.1:
            num_new_individuals = int(population_size * 0.2)
            new_individuals = initialize_population(all_cycles, num_new_individuals, item_owner)
            population.extend(new_individuals)
            population = population[:population_size]

    return best_solution


def reconstruct_exchanges(cycles, item_owner, item_name, user_lower_to_original, metrics):
    """Rekonstruuje wymiany na podstawie wybranych cykli, grupując je per użytkownik"""
    user_transactions = {}

    for cycle in cycles:
        n = len(cycle)
        for i in range(n):
            giver_item = cycle[i]
            receiver_item = cycle[(i + 1) % n]

            giver_user_lower = item_owner[giver_item]
            receiver_user_lower = item_owner[receiver_item]

            giver_user = user_lower_to_original.get(giver_user_lower, 'Unknown')
            receiver_user = user_lower_to_original.get(receiver_user_lower, 'Unknown')

            if giver_user == receiver_user:
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


def display_metrics(all_metrics):
    """Wyświetla wszystkie miary w konsoli."""
    print("\nBenchmark Metrics:")
    print(json.dumps(all_metrics, ensure_ascii=False, indent=4))


def save_metrics_to_json(all_metrics,
                         output_file='C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\benchmark\\benchmark_metrics_genetic_algorithm_max_users.json'):
    """Zapisuje wszystkie miary do pliku JSON."""
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_metrics, f, ensure_ascii=False, indent=4)
        print(f"\nMiary benchmark zostały zapisane do pliku '{output_file}'.")
    except Exception as e:
        print(f"Nie można zapisać miar do pliku '{output_file}': {e}")


def process_file(file_path, output_graph_path, metrics, max_cycle_length=6, population_size=100, num_generations=200,
                 crossover_rate=0.8, mutation_rate=0.1, elite_size=2):
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
        "genetic_algorithm_time_seconds": 0,
        "participation_percent": 0.0,
        "overall_effectiveness_percent": 0.0,
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

    metrics["num_users"] = len(users)
    metrics["num_items"] = len(items)

    # Standaryzacja nazw użytkowników
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}

    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)

    clean_wishlists(users_lower, item_owner, metrics)

    G = build_exchange_graph(users_lower, items, item_owner, metrics)

    # Znajdowanie wszystkich cykli do długości max_cycle_length
    all_cycles = find_all_cycles(G, max_cycle_length)
    metrics["num_cycles_found"] = len(all_cycles)

    if not all_cycles:
        print("Nie znaleziono żadnych cykli wymian.")
        metrics["execution_time_seconds"] = time.time() - start_time
        tracemalloc.stop()
        return metrics, {}

    # Uruchomienie algorytmu genetycznego
    ga_start_time = time.time()
    best_solution = genetic_algorithm(G, item_owner, all_cycles, population_size, num_generations, crossover_rate,
                                      mutation_rate, elite_size)
    ga_end_time = time.time()
    metrics["genetic_algorithm_time_seconds"] = ga_end_time - ga_start_time

    metrics["num_cycles_selected"] = len(best_solution)

    # Rekonstrukcja
    user_transactions = reconstruct_exchanges(best_solution, item_owner, item_name, user_lower_to_original, metrics)

    # Podsumowanie
    user_summary = summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics)

    # Obliczanie
    calculate_effectiveness(user_summary, metrics)

    # Zakończenie pomiarów czasu i pamięci
    end_time = time.time()
    metrics["execution_time_seconds"] = end_time - start_time
    current, peak = tracemalloc.get_traced_memory()
    metrics["memory_usage_MB"] = peak / (1024 * 1024)
    tracemalloc.stop()

    return metrics, user_transactions


def main():
    """Główna funkcja programu."""
    data_directory = r'C:\\Users\\szyma\\Desktop\\System wspomagania i monitorowania procesu wymiany gier\\data\\for_tests'

    input_files = glob.glob(os.path.join(data_directory, '*.json'))

    if not input_files:
        print("Brak dostępnych plików JSON do przetworzenia.")
        return

    all_metrics = {}

    # Parametry
    max_cycle_length = 10
    population_size = 100
    num_generations = 200
    crossover_rate = 0.8
    mutation_rate = 0.1
    elite_size = 2

    for file_path in input_files:
        print(f"\nPrzetwarzanie pliku: {file_path}")
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        output_graph_path = f"trade_graph_{base_name}.html"
        metrics = {}
        metrics, user_transactions = process_file(
            file_path,
            output_graph_path,
            metrics,
            max_cycle_length,
            population_size,
            num_generations,
            crossover_rate,
            mutation_rate,
            elite_size
        )
        all_metrics[file_path] = metrics

    save_metrics_to_json(all_metrics)

    display_metrics(all_metrics)


if __name__ == "__main__":
    main()
