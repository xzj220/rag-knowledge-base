from app.data import register_user, check_user, load_convs, save_convs, next_id, get_user_collection


class TestUserDB:
    def test_register_and_check(self):
        assert register_user("alice", "pass123")
        assert check_user("alice", "pass123")
        assert not check_user("alice", "wrong")

    def test_register_duplicate(self):
        assert register_user("bob", "pass")
        assert not register_user("bob", "pass2")

    def test_check_nonexistent(self):
        assert not check_user("nobody", "pass")


class TestConversations:
    def test_empty_convs(self):
        assert load_convs("newuser") == []

    def test_save_and_load_convs(self):
        convs = [{"id": "c1", "title": "test", "messages": []}]
        save_convs("convuser", convs)
        loaded = load_convs("convuser")
        assert len(loaded) == 1
        assert loaded[0]["id"] == "c1"


class TestCollections:
    def test_get_or_create(self):
        col = get_user_collection("colluser")
        assert col is not None
        assert col.count() == 0

    def test_add_and_count(self):
        col = get_user_collection("colluser2")
        col.add(documents=["test doc"], embeddings=[[0.1] * 768], ids=["doc_1"])
        assert col.count() == 1

    def test_next_id_sequential(self):
        id1 = next_id("iduser")
        id2 = next_id("iduser")
        assert id1.startswith("doc_")
        assert id2.startswith("doc_")
        assert int(id2.split("_")[1]) == int(id1.split("_")[1]) + 1
