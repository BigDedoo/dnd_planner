from fastapi.testclient import TestClient

EXPECTED_GROUPS = [
    {
        "name": "Green flag",
        "players": ["Quentin", "Arnaud", "Ulrich", "Daerrus", "Dembe"],
    },
    {
        "name": "1D6",
        "players": ["Gaelle", "Rico", "Yoann", "Romane", "Victor", "Dembe"],
    },
    {
        "name": "Underdark",
        "players": ["Dembe", "Arnaud", "Quentin", "Martin", "Baptiste"],
    },
]


def test_groups_preserve_current_names_members_and_display_order(
    legacy_client: TestClient,
) -> None:
    response = legacy_client.get("/groups")

    assert response.status_code == 200
    assert response.json() == EXPECTED_GROUPS
    assert all(set(group) == {"name", "players"} for group in response.json())
