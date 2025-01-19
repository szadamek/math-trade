import pytest
import os
import json
from unittest.mock import patch
from algorithms.tradegenie import (
    warn,
    load_data,
    standardize_usernames,
    create_item_mappings,
    clean_wishlists,
    build_exchange_graph,
    find_cycles,
    optimize_trades,
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
                    "item1": ["item2"]  # Alice oferuje item1 i chce item2
                }
            },
            "Bob": {
                "offers": {
                    "item2": ["item1"]  # Bob oferuje item2 i chce item1
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
    assert user_lower_to_original == {"alice": "Alice", "bob": "Bob"}


def test_create_item_mappings(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    assert item_owner == {"item1": "alice", "item2": "bob"}
    assert item_name == {"item1": "Chess Set", "item2": "Monopoly Game"}
    assert metrics["num_warnings"] == 0


def test_clean_wishlists(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(data.get('items', {}), user_lower_to_original, metrics)
    # Dodajemy niedostępny przedmiot do wishlisty
    users_lower["alice"]["offers"]["item1"].append("item3")
    clean_wishlists(users_lower, item_owner, metrics)
    assert "item3" not in users_lower["alice"]["offers"]["item1"]
    assert metrics["num_warnings"] == 1


def test_build_exchange_graph(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    assert G.number_of_nodes() == 2
    assert G.number_of_edges() == 2
    assert G.has_edge("item1", "item2")
    assert G.has_edge("item2", "item1")


def test_find_cycles(sample_data):
    metrics = {"num_warnings": 0, "num_cycles_found": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, _ = create_item_mappings(data.get('items', {}), user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, data.get('items', {}), item_owner, metrics)
    cycles = find_cycles(G, max_cycle_length=8, metrics=metrics)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"item1", "item2"}
    assert metrics["num_cycles_found"] == 1


def test_optimize_trades(sample_data):
    metrics = {"num_warnings": 0, "num_cycles_found": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, _ = create_item_mappings(data.get('items', {}), user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, data.get('items', {}), item_owner, metrics)
    cycles = find_cycles(G, max_cycle_length=8, metrics=metrics)
    selected_cycles = optimize_trades(G, cycles, metrics)
    assert len(selected_cycles) == 1
    assert set(selected_cycles[0]) == {"item1", "item2"}
    assert metrics["num_cycles_selected"] == 1


def test_reconstruct_exchanges(sample_data):
    metrics = {"num_warnings": 0, "num_cycles_found": 0, "num_cycles_selected": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    user_lower_to_original = standardize_usernames(users)
    users_lower = {user.lower(): user_data for user, user_data in users.items()}
    item_owner, item_name = create_item_mappings(items, user_lower_to_original, metrics)
    clean_wishlists(users_lower, item_owner, metrics)
    G = build_exchange_graph(users_lower, items, item_owner, metrics)
    cycles = find_cycles(G, max_cycle_length=8, metrics=metrics)
    selected_cycles = optimize_trades(G, cycles, metrics)
    user_transactions = reconstruct_exchanges(selected_cycles, item_owner, item_name, user_lower_to_original, metrics)
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


def test_summarize_exchanges(sample_data):
    metrics = {"num_warnings": 0}
    user_transactions = {
        "Alice": {
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_given": ["Monopoly Game"],
            "items_received": ["Chess Set"]
        }
    }
    users_lower = {
        "alice": {
            "offers": {
                "item1": ["item2"]
            }
        },
        "bob": {
            "offers": {
                "item2": ["item1"]
            }
        }
    }
    user_lower_to_original = {
        "alice": "Alice",
        "bob": "Bob"
    }
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
            "items_received": ["Chess Set"]
        }
    }
    assert user_summary == expected_summary
    assert metrics["participation_percent"] == 100.0


def test_calculate_effectiveness(sample_data):
    metrics = {"num_warnings": 0}
    user_summary = {
        "Alice": {
            "items_offered": ["item1"],
            "items_given": ["Chess Set"],
            "items_received": ["Monopoly Game"]
        },
        "Bob": {
            "items_offered": ["item2"],
            "items_given": ["Monopoly Game"],
            "items_received": ["Chess Set"]
        }
    }
    calculate_effectiveness(user_summary, metrics)
    assert metrics["overall_effectiveness_percent"] == 100.0


def test_process_file(sample_data, tmp_path):
    metrics = {}
    output_graph_path = tmp_path / "trade_graph.html"
    metrics, user_transactions = process_file(str(sample_data), str(output_graph_path), metrics)
    # Sprawdzenie miar
    assert metrics["num_users"] == 2
    assert metrics["num_items"] == 2
    assert metrics["num_cycles_found"] == 1
    assert metrics["num_cycles_selected"] == 1
    assert metrics["num_exchanges"] == 2
    assert metrics["overall_effectiveness_percent"] == 100.0
    assert metrics["participation_percent"] == 100.0
    assert metrics["num_warnings"] == 0
    # Sprawdzenie transakcji
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
    # Sprawdzenie, czy plik grafu został utworzony
    assert os.path.exists(output_graph_path)
