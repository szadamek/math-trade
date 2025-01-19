import pytest
import os
import json
from unittest.mock import patch
from algorithms.greedy_algorithm import (
    warn,
    load_data,
    build_ownership_map,
    build_graph,
    find_cycles,
    find_possible_exchanges,
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
                    "item2": ["item1"]
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

def test_build_ownership_map(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    items = data.get('items', {})
    ownership = build_ownership_map(items)
    assert ownership == {"item1": "alice", "item2": "bob"}

def test_build_graph(sample_data):
    metrics = {"num_warnings": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    assigned_items = set()
    G = build_graph(users, items, assigned_items, metrics)
    assert G.number_of_nodes() == 2  # item1, item2
    assert G.number_of_edges() == 2  # item1 -> item2, item2 -> item1
    assert G.has_edge("item1", "item2")
    assert G.has_edge("item2", "item1")

def test_find_cycles(sample_data):
    metrics = {"num_warnings": 0, "num_cycles_found": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    assigned_items = set()
    G = build_graph(users, items, assigned_items, metrics)
    cycles = find_cycles(G, max_cycle_length=6, metrics=metrics)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"item1", "item2"}
    assert metrics["num_cycles_found"] == 1

def test_find_possible_exchanges(sample_data):
    metrics = {"num_warnings": 0, "num_cycles_found": 0}
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    items = data.get('items', {})
    exchanges = find_possible_exchanges(users, items, metrics, max_cycle_length=6)
    assert len(exchanges) == 2  # Alice and Bob both exchange items
    # Sprawdzenie transakcji
    expected_exchanges = [
        {
            'from_user': 'alice',
            'to_user': 'bob',
            'item_given': 'item1',
            'item_received': 'item2'
        },
        {
            'from_user': 'bob',
            'to_user': 'alice',
            'item_given': 'item2',
            'item_received': 'item1'
        }
    ]
    # Sortowanie list przed porównaniem
    exchanges_sorted = sorted(exchanges, key=lambda x: (x['from_user'], x['to_user']))
    expected_exchanges_sorted = sorted(expected_exchanges, key=lambda x: (x['from_user'], x['to_user']))
    assert exchanges_sorted == expected_exchanges_sorted
    assert metrics["num_cycles_found"] == 1
    assert metrics["num_exchanges"] == 2

def test_summarize_exchanges(sample_data):
    metrics = {"num_warnings": 0}
    exchanges = [
        {
            'from_user': 'alice',
            'to_user': 'bob',
            'item_given': 'item1',
            'item_received': 'item2'
        },
        {
            'from_user': 'bob',
            'to_user': 'alice',
            'item_given': 'item2',
            'item_received': 'item1'
        }
    ]
    data = load_data(str(sample_data), metrics)
    users = data.get('users', {})
    # Upewnij się, że funkcja summarize_exchanges jest poprawnie zaimplementowana
    user_summary = summarize_exchanges(users, exchanges, metrics)
    expected_summary = {
        'alice': {
            'items_offered': {'item1'},
            'items_given': {'item1'},
            'items_received': {'item2'}
        },
        'bob': {
            'items_offered': {'item2'},
            'items_given': {'item2'},
            'items_received': {'item1'}
        }
    }
    assert user_summary == expected_summary
    assert metrics["participation_percent"] == 100.0

def test_calculate_effectiveness(sample_data):
    metrics = {"num_warnings": 0}
    user_summary = {
        'alice': {
            'items_offered': {'item1'},
            'items_given': {'item1'},
            'items_received': {'item2'}
        },
        'bob': {
            'items_offered': {'item2'},
            'items_given': {'item2'},
            'items_received': {'item1'}
        }
    }
    calculate_effectiveness(user_summary, metrics)
    assert metrics["overall_effectiveness_percent"] == 100.0

def test_process_file(sample_data, tmp_path):
    metrics = {}
    with patch('builtins.print'):  # Opcjonalnie, aby ukryć wydruki
        metrics = process_file(str(sample_data), max_cycle_length=6)
    # Sprawdzenie miar
    assert metrics["num_users"] == 2
    assert metrics["num_items"] == 2
    assert metrics["num_cycles_found"] == 1
    assert metrics["num_exchanges"] == 2
    assert metrics["overall_effectiveness_percent"] == 100.0
    assert metrics["participation_percent"] == 100.0
    assert metrics["num_warnings"] == 0  # Jeśli po poprawkach liczba ostrzeżeń wynosi 0
