import pytest
import os
import json
from unittest.mock import patch
from algorithms.genetic_algorithm_max_players import (
    warn,
    load_data,
    standardize_usernames,
    create_item_mappings,
    clean_wishlists,
    build_exchange_graph,
    find_all_cycles,
    initialize_population,
    fitness_function,
    selection,
    crossover,
    mutation,
    calculate_diversity,
    genetic_algorithm,
    reconstruct_exchanges,
    summarize_exchanges,
    calculate_effectiveness,
    process_file
)

@pytest.fixture
def sample_data(tmp_path):
    data = {
        "users": {
            "Alice": {
                "offers": {
                    "item1": ["item2"]
                }
            },
            "Bob": {
                "offers": {
                    "item2": ["item3"]
                }
            },
            "Charlie": {
                "offers": {
                    "item3": ["item1"]
                }
            }
        },
        "items": {
            "item1": {
                "owner": "Alice",
                "name": "Chess Set"
            },
            "item2": {
                "owner": "Bob",
                "name": "Monopoly Game"
            },
            "item3": {
                "owner": "Charlie",
                "name": "Scrabble"
            }
        }
    }
    file_path = tmp_path / "test_data.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return file_path

def test_load_data(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    assert data is not None
    assert "users" in data
    assert "items" in data
    assert metrics["num_warnings"] == 0

def test_standardize_usernames(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    assert user_lower_to_original == {"alice": "Alice", "bob": "Bob", "charlie": "Charlie"}

def test_create_item_mappings(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    assert item_owner == {"item1": "alice", "item2": "bob", "item3": "charlie"}
    assert item_name == {"item1": "Chess Set", "item2": "Monopoly Game", "item3": "Scrabble"}
    assert metrics["num_warnings"] == 0

def test_clean_wishlists(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, _ = create_item_mappings(data.get('items', {}), user_lower_to_original, metrics)
    # Dodajemy niedostępny przedmiot do wishlisty
    users_lower["alice"]["offers"]["item1"].append("item4")
    clean_wishlists(users_lower, item_owner, metrics)
    assert "item4" not in users_lower["alice"]["offers"]["item1"]
    assert metrics["num_warnings"] == 1

def test_build_exchange_graph(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, _ = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    assert G.number_of_nodes() == 3
    assert G.number_of_edges() == 3
    assert G.has_edge("item1", "item2")
    assert G.has_edge("item2", "item3")
    assert G.has_edge("item3", "item1")

def test_find_all_cycles(sample_data):
    metrics = {}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, _ = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    all_cycles = find_all_cycles(G, max_cycle_length=10)
    assert len(all_cycles) == 1
    assert set(all_cycles[0]) == {"item1", "item2", "item3"}

def test_initialize_population(sample_data):
    metrics = {}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, _ = create_item_mappings(items, user_lower_to_original, metrics)
    G = build_exchange_graph(users, items, item_owner, metrics)
    all_cycles = find_all_cycles(G, max_cycle_length=10)
    population = initialize_population(all_cycles, population_size=10, item_owner=item_owner)
    assert len(population) == 10
    for chromosome in population:
        assert isinstance(chromosome, list)

def test_fitness_function(sample_data):
    metrics = {}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, _ = create_item_mappings(items, user_lower_to_original, metrics)
    chromosome = [['item1', 'item2', 'item3']]
    fitness = fitness_function(chromosome, item_owner)
    assert fitness == 3  # Trzech unikalnych graczy

def test_genetic_algorithm(sample_data):
    metrics = {}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    all_cycles = find_all_cycles(G, max_cycle_length=10)
    best_solution = genetic_algorithm(
        G,
        item_owner,
        all_cycles,
        population_size=10,
        num_generations=5,
        crossover_rate=0.8,
        mutation_rate=0.1,
        elite_size=2
    )
    assert isinstance(best_solution, list)
    assert len(best_solution) >= 1
    # Sprawdź, czy fitness najlepszej solucji to 3 (maksymalna liczba graczy)
    fitness = fitness_function(best_solution, item_owner)
    assert fitness == 3

def test_reconstruct_exchanges(sample_data):
    metrics = {}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    all_cycles = find_all_cycles(G, max_cycle_length=10)
    best_solution = genetic_algorithm(
        G,
        item_owner,
        all_cycles,
        population_size=10,
        num_generations=5,
        crossover_rate=0.8,
        mutation_rate=0.1,
        elite_size=2
    )
    user_transactions = reconstruct_exchanges(best_solution, item_owner, item_name, user_lower_to_original, metrics)
    expected_transactions = {
        "Alice": {
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_given": ["Monopoly Game"],
            "items_received": ["Scrabble"]
        },
        "Charlie": {
            "items_given": ["Scrabble"],
            "items_received": ["Chess Set"]
        }
    }
    assert user_transactions == expected_transactions
    assert metrics["num_exchanges"] == 3

def test_summarize_exchanges(sample_data):
    metrics = {}
    user_transactions = {
        "Alice": {
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_given": ["Monopoly Game"],
            "items_received": ["Scrabble"]
        },
        "Charlie": {
            "items_given": ["Scrabble"],
            "items_received": ["Chess Set"]
        }
    }
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    user_summary = summarize_exchanges(users_lower, user_transactions, user_lower_to_original, metrics)
    expected_summary = {
        "Alice": {
            "items_offered": ["item1"],
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_offered": ["item2"],
            "items_given": ["Monopoly Game"],
            "items_received": ["Scrabble"]
        },
        "Charlie": {
            "items_offered": ["item3"],
            "items_given": ["Scrabble"],
            "items_received": ["Chess Set"]
        }
    }
    assert user_summary == expected_summary
    assert metrics["participation_percent"] == 100.0

def test_calculate_effectiveness(sample_data):
    metrics = {}
    user_summary = {
        "Alice": {
            "items_offered": ["item1"],
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_offered": ["item2"],
            "items_given": ["Monopoly Game"],
            "items_received": ["Scrabble"]
        },
        "Charlie": {
            "items_offered": ["item3"],
            "items_given": ["Scrabble"],
            "items_received": ["Chess Set"]
        }
    }
    calculate_effectiveness(user_summary, metrics)
    assert metrics["overall_effectiveness_percent"] == 100.0

def test_process_file(sample_data):
    metrics = {}
    output_graph_path = "output_graph.html"
    metrics, user_transactions = process_file(
        file_path=str(sample_data),
        output_graph_path=output_graph_path,
        metrics=metrics,
        max_cycle_length=10,
        population_size=10,
        num_generations=5,
        crossover_rate=0.8,
        mutation_rate=0.1,
        elite_size=2
    )
    # Sprawdzenie miar
    assert metrics["num_users"] == 3
    assert metrics["num_items"] == 3
    assert metrics["num_cycles_found"] == 1
    assert metrics["num_cycles_selected"] == 1
    assert metrics["num_exchanges"] == 3
    assert metrics["overall_effectiveness_percent"] == 100.0
    assert metrics["participation_percent"] == 100.0
    assert metrics["num_warnings"] == 0
    # Sprawdzenie transakcji użytkowników
    expected_transactions = {
        "Alice": {
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_given": ["Monopoly Game"],
            "items_received": ["Scrabble"]
        },
        "Charlie": {
            "items_given": ["Scrabble"],
            "items_received": ["Chess Set"]
        }
    }
    assert user_transactions == expected_transactions
