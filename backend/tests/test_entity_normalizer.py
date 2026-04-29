from app.services.entity_normalizer import merge_properties, normalize_graph_data, normalize_node_data


def test_self_aliases_collapse_to_single_person_node():
    graph = normalize_graph_data(
        {
            "nodes": [
                {"name": "User", "type": "person"},
                {"name": "用户", "type": "person"},
                {"name": "我", "type": "person"},
                {"name": "Jira", "type": "tool"},
            ],
            "edges": [
                {"source": "User", "target": "Jira", "relation": "uses"},
                {"source": "用户", "target": "Jira", "relation": "uses"},
                {"source": "我", "target": "Jira", "relation": "uses"},
            ],
        }
    )

    nodes = {node["name"]: node for node in graph["nodes"]}
    assert set(nodes) == {"我", "Jira"}
    assert nodes["我"]["type"] == "person"
    assert graph["edges"] == [{"source": "我", "target": "Jira", "relation": "uses"}]


def test_generic_roles_are_not_treated_as_specific_people():
    node = normalize_node_data({"name": "员工", "type": "person"})

    assert node["name"] == "员工"
    assert node["type"] == "topic"
    assert node["properties"]["original_type"] == "person"
    assert node["properties"]["resolution_method"] == "rule:generic_role"


def test_generic_product_users_stay_as_topic_when_not_person():
    node = normalize_node_data({"name": "users", "type": "concept"})

    assert node["name"] == "用户群体"
    assert node["type"] == "topic"
    assert node["properties"]["normalized_from"] == "users"
    assert node["properties"]["original_type"] == "concept"
    assert node["properties"]["resolution_method"] == "rule:generic_user"


def test_fuzzy_matches_existing_nodes_and_preserves_aliases():
    graph = normalize_graph_data(
        {
            "nodes": [
                {"name": "Google Sheet", "type": "tool"},
                {"name": "用户", "type": "person"},
            ],
            "edges": [{"source": "用户", "target": "Google Sheet", "relation": "uses"}],
        },
        existing_nodes=[
            {
                "name": "Google Sheets",
                "type": "tool",
                "properties": {"aliases": ["Sheets"]},
            }
        ],
    )

    nodes = {node["name"]: node for node in graph["nodes"]}
    assert set(nodes) == {"我", "Google Sheets"}
    assert nodes["Google Sheets"]["properties"]["normalized_from"] == "Google Sheet"
    assert "Google Sheet" in nodes["Google Sheets"]["properties"]["aliases"]
    assert "Sheets" in nodes["Google Sheets"]["properties"]["aliases"]
    assert graph["edges"] == [{"source": "我", "target": "Google Sheets", "relation": "uses"}]


def test_low_confidence_candidate_is_recorded_but_not_merged():
    graph = normalize_graph_data(
        {"nodes": [{"name": "Alpha", "type": "project"}], "edges": []},
        existing_nodes=[{"name": "Alpine", "type": "project", "properties": {}}],
    )

    node = graph["nodes"][0]
    assert node["name"] == "Alpha"
    assert node["properties"]["canonical_name"] == "Alpha"


def test_merge_properties_unions_aliases():
    merged = merge_properties(
        {"aliases": ["Google Sheet"], "resolution_method": "rapidfuzz"},
        {"aliases": ["Sheets"], "canonical_name": "Google Sheets"},
    )

    assert merged["canonical_name"] == "Google Sheets"
    assert merged["aliases"] == ["Google Sheet", "Sheets"]
