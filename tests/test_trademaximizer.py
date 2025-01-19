import pytest
import os
import json
from algorithms.trade_maximizer_working import (
    load_data,
    standardize_usernames,
    create_item_mappings,
    clean_wishlists,
    build_exchange_graph,
    find_minimum_cost_perfect_matching,
    reconstruct_exchanges_from_matching
)

@pytest.fixture
def sample_data(tmp_path):
    data = {
        "users": {
            "Alice": {
                "offers": {
                    "item1": ["item2"]  # Zmieniono 'offer1' na 'item1'
                }
            },
            "Bob": {
                "offers": {
                    "item2": ["item1"]  # Zmieniono 'offer2' na 'item2'
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
            }
        }
    }
    file_path = tmp_path / "test_data.json"
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    return file_path

def test_load_data(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    assert data is not None
    assert "users" in data
    assert "items" in data
    assert metrics["num_warnings"] == 0

def test_standardize_usernames(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    assert user_lower_to_original == {"alice": "Alice", "bob": "Bob"}

def test_create_item_mappings(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    assert item_owner == {"item1": "alice", "item2": "bob"}
    assert item_name == {"item1": "Chess Set", "item2": "Monopoly Game"}
    assert metrics["num_warnings"] == 0

def test_clean_wishlists(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    # Dodajemy wishlist zawierający nieistniejący przedmiot
    users_lower["alice"]["offers"]["item1"].append("item3")
    clean_wishlists(users_lower, item_owner, metrics)
    assert "item3" not in users_lower["alice"]["offers"]["item1"]
    assert metrics["num_warnings"] == 1

def test_build_exchange_graph(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    # Sprawdzenie liczby węzłów i krawędzi
    assert G.number_of_nodes() == 4  # item1_R, item1_S, item2_R, item2_S
    assert G.number_of_edges() == 4  # 2 self-edges + 2 exchange edges
    # Dodanie oczekiwanych krawędzi z wishlist
    # Alice offers item1, wants item2
    # Bob offers item2, wants item1
    # Hence, edges:
    # item1_R - item1_S (self-edge)
    # item2_R - item2_S (self-edge)
    # item1_R - item2_S (exchange edge)
    # item2_R - item1_S (exchange edge)
    expected_edges = {
        frozenset(("item1_R", "item1_S")),
        frozenset(("item2_R", "item2_S")),
        frozenset(("item1_R", "item2_S")),
        frozenset(("item2_R", "item1_S"))
    }
    actual_edges = set(frozenset(edge) for edge in G.edges())
    assert actual_edges == expected_edges

def test_find_minimum_cost_perfect_matching(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    matching = find_minimum_cost_perfect_matching(G, metrics)
    # Przetwarzamy dopasowanie, aby uwzględnić tylko pary z 'item_R' jako kluczami
    processed_matching = {k: v for k, v in matching.items() if k.endswith('_R')}
    # Oczekiwane dopasowanie:
    # item1_R -> item2_S (Alice wants item2 from Bob)
    # item2_R -> item1_S (Bob wants item1 from Alice)
    expected_matching = {
        "item1_R": "item2_S",
        "item2_R": "item1_S"
    }
    assert processed_matching == expected_matching

def test_reconstruct_exchanges_from_matching(sample_data):
    metrics = {"num_warnings": 0}  # Inicjalizacja num_warnings
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    matching = find_minimum_cost_perfect_matching(G, metrics)
    user_transactions = reconstruct_exchanges_from_matching(matching, item_owner, item_name, user_lower_to_original, metrics)
    expected_transactions = {
        "Alice": {
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_given": ["Monopoly Game"],
            "items_received": ["Chess Set"]
        }
    }
    assert user_transactions == expected_transactions
    assert metrics["num_exchanges"] == 2
