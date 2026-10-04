def start(client, **body):
    response = client.post("/api/practice/start", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def send(client, conversation_id, content):
    return client.post(f"/api/conversations/{conversation_id}/messages", json={"content": content})


def test_create_conversation_has_opening_message(client):
    data = start(client)
    assert data["messages"][0]["role"] == "assistant"
    again = client.get(f"/api/conversations/{data['conversation']['id']}")
    assert again.status_code == 200 and len(again.json()["messages"]) == 1


def test_conversations_endpoint_defaults_to_free_conversation(client):
    response = client.post("/api/conversations")
    assert response.status_code == 201
    assert response.json()["conversation"]["mode"] == "free_conversation"


def test_workplace_scenario_uses_its_prompt(client):
    data = start(client, mode="workplace_english", scenario="daily_standup")
    assert "blockers" in data["messages"][0]["content"]


def test_unknown_scenario_is_rejected(client):
    response = client.post("/api/practice/start", json={"mode": "workplace_english", "scenario": "nope"})
    assert response.status_code == 422


def test_empty_and_whitespace_messages_rejected(client):
    cid = start(client)["conversation"]["id"]
    for content in ("", "   \n "):
        assert send(client, cid, content).status_code == 422


def test_overlong_message_rejected_with_friendly_text(client):
    cid = start(client)["conversation"]["id"]
    response = send(client, cid, "a" * 2001)
    assert response.status_code == 422 and "too long" in response.json()["detail"]


def test_message_submission_with_mock_ai(client):
    cid = start(client)["conversation"]["id"]
    body = send(client, cid, "  Yesterday I go to market and buy vegetables.  ").json()
    assert body["reply"]
    feedback = body["feedback"]
    assert feedback["available"] and feedback["mistakes"][0]["category"] == "past_tense"
    assert feedback["patterns"] == []
    history = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in history] == ["assistant", "user", "assistant"]
    assert history[1]["content"] == "Yesterday I go to market and buy vegetables."


def test_second_mistake_triggers_pattern_and_feeds_next_prompt(client, provider):
    cid = start(client)["conversation"]["id"]
    send(client, cid, "Yesterday I go to the office.")
    second = send(client, cid, "Yesterday I buy a coffee.").json()
    assert second["feedback"]["patterns"][0]["type"] == "past_tense"
    send(client, cid, "Hello there")
    assert any("past tense" in item for item in provider.contexts[-1].recurring_mistakes)

    progress = client.get("/api/progress").json()
    assert progress["recurring_mistakes"][0]["frequency"] == 2
    assert client.get("/api/mistakes").json()["mistakes"][0]["category"] == "past_tense"


def test_targeted_recurring_practice_uses_stored_mistakes(client, provider):
    cid = start(client)["conversation"]["id"]
    send(client, cid, "Yesterday I go to the office.")
    send(client, cid, "Yesterday I buy a coffee.")
    data = start(client, mode="targeted_practice", focus="recurring_mistakes")
    assert "past tense" in data["messages"][0]["content"].lower()
    assert data["notice"] is None


def test_targeted_recurring_without_history_falls_back(client):
    data = start(client, mode="targeted_practice", focus="recurring_mistakes")
    assert data["notice"] and data["conversation"]["focus"] == "grammar"


def test_ai_failure_returns_friendly_error_and_stores_nothing(client, provider):
    cid = start(client)["conversation"]["id"]
    provider.fail = True
    response = send(client, cid, "Hello")
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
    provider.fail = False
    assert len(client.get(f"/api/conversations/{cid}").json()["messages"]) == 1


def test_conversations_are_private_to_their_owner(client):
    cid = start(client)["conversation"]["id"]
    client.cookies.clear()
    assert client.get(f"/api/conversations/{cid}").status_code == 404


def test_forged_cookie_gets_a_fresh_identity(client):
    client.cookies.set("epa_uid", "u-" + "0" * 32 + ".forged")
    cid = start(client)["conversation"]["id"]
    assert client.get(f"/api/conversations/{cid}").status_code == 200


def test_progress_structure(client):
    body = client.get("/api/progress").json()
    assert set(body) >= {
        "has_data", "data_quality", "disclaimer", "skills", "recurring_mistakes", "strengths", "recent_sessions"
    }
    assert [s["key"] for s in body["skills"]] == [
        "grammar", "vocabulary", "natural_english", "professional_english"
    ]


def test_progress_without_data_reports_not_enough_data(client):
    body = client.get("/api/progress").json()
    assert body["data_quality"]["level"] == "none" and not body["has_data"]
    assert all(skill["score"] is None for skill in body["skills"])


def test_practice_modes_listing(client):
    body = client.get("/api/practice/modes").json()
    assert len(body["scenarios"]) == 9 and len(body["modes"]) == 3


def test_provider_choice_never_echoes_key(client):
    response = client.put(
        "/api/session/provider", json={"mode": "google", "api_key": "super-secret-key"}
    )
    assert response.status_code == 204
    assert "super-secret-key" not in response.text


def test_google_requires_key_but_lmstudio_does_not(client):
    assert client.put("/api/session/provider", json={"mode": "google"}).status_code == 422
    assert client.put("/api/session/provider", json={"mode": "lmstudio"}).status_code == 204
    assert client.put("/api/session/provider", json={"mode": "bogus"}).status_code == 422


def test_model_dropdown_lists(client):
    google = client.post("/api/session/models", json={"mode": "google"}).json()
    assert google["models"] == [] and "error" in google  # no key: nothing invented, just a hint
    assert client.post("/api/session/models", json={"mode": "x"}).status_code == 422


def test_provider_status_masks_key_and_can_be_deleted(client):
    client.put("/api/session/provider", json={"mode": "google", "api_key": "super-secret-key", "model": "gemma-3-4b-it"})
    status = client.get("/api/session/provider")
    body = status.json()
    assert "super-secret-key" not in status.text
    assert body["key_masked"] == "**********" and body["model"] == "gemma-3-4b-it"
    assert 0 < body["expires_in"] <= 1800
    client.delete("/api/session/provider")
    assert client.get("/api/session/provider").json().get("mode") != "google"
