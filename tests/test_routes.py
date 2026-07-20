import json


class TestBasic:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.data.decode() == "ok"

    def test_index_not_logged_in(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "登录" in resp.data.decode()

    def test_reg_page(self, client):
        resp = client.get("/reg")
        assert resp.status_code == 200
        assert "注册" in resp.data.decode()


class TestAuth:
    def test_register_success(self, client):
        resp = client.post("/register", data={"username": "newuser", "password": "pass123"})
        assert resp.status_code == 200
        assert "注册成功" in resp.data.decode()

    def test_register_short_fields(self, client):
        resp = client.post("/register", data={"username": "a", "password": "ab"})
        assert resp.status_code == 200
        assert "至少" in resp.data.decode()

    def test_register_duplicate(self, client):
        client.post("/register", data={"username": "dup", "password": "pass"})
        resp = client.post("/register", data={"username": "dup", "password": "other"})
        assert "已存在" in resp.data.decode()

    def test_login_success(self, client):
        client.post("/register", data={"username": "loginok", "password": "pass"})
        resp = client.post("/login", data={"username": "loginok", "password": "pass"})
        assert resp.status_code == 200

    def test_login_fail(self, client):
        resp = client.post("/login", data={"username": "nope", "password": "x"})
        assert resp.status_code == 200
        assert "用户名或密码错误" in resp.data.decode()

    def test_logout(self, client):
        client.post("/register", data={"username": "logout", "password": "p"})
        client.post("/login", data={"username": "logout", "password": "p"})
        resp = client.get("/logout")
        assert resp.status_code == 200


class TestAsk:
    def test_no_login(self, client):
        resp = client.post("/ask", json={"q": "hello"})
        assert resp.status_code == 200
        assert json.loads(resp.data)["answer"] == ""

    def test_with_login(self, client):
        client.post("/register", data={"username": "asker", "password": "p"})
        with client.session_transaction() as sess:
            sess["user"] = "asker"
        client.post("/add_batch", json={"text": "苹果是水果\n香蕉是热带水果"})
        resp = client.post("/ask", json={"q": "苹果是什么"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["answer"] != ""


class TestKnowledgeBase:
    def test_add_batch(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "batcher"
        resp = client.post("/add_batch", json={"text": "问1是答1\n问2是答2"})
        data = json.loads(resp.data)
        assert "成功" in data["msg"]

    def test_add_batch_no_login(self, client):
        resp = client.post("/add_batch", json={"text": "x是y"})
        assert json.loads(resp.data)["msg"] == "未登录"

    def test_kb_docs(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "kbviewer"
        client.post("/add_batch", json={"text": "Q是A"})
        resp = client.get("/kb_docs")
        data = json.loads(resp.data)
        assert len(data["docs"]) > 0

    def test_count_zero(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "counter"
        resp = client.get("/count")
        assert json.loads(resp.data)["count"] == 0

    def test_delete(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "deleter"
        client.post("/add_batch", json={"text": "X是Y"})
        resp = client.post("/delete", json={"idx": 0})
        assert json.loads(resp.data)["ok"] is True

    def test_clear_all(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "clearer"
        client.post("/add_batch", json={"text": "X是Y"})
        resp = client.post("/clear_all")
        assert json.loads(resp.data)["ok"] is True
        resp = client.get("/count")
        assert json.loads(resp.data)["count"] == 0


class TestConversations:
    def test_crud(self, client):
        with client.session_transaction() as sess:
            sess["user"] = "convuser"
        resp = client.post("/conversations", json={"title": "t1", "messages": []})
        data = json.loads(resp.data)
        assert data["ok"]
        conv_id = data["id"]
        resp = client.get("/conversations")
        list_data = json.loads(resp.data)
        assert len(list_data) >= 1
        resp = client.delete(f"/conversations/{conv_id}")
        assert json.loads(resp.data)["ok"] is True

    def test_no_login(self, client):
        resp = client.get("/conversations")
        assert json.loads(resp.data) == []
        resp = client.post("/conversations", json={})
        assert json.loads(resp.data)["ok"] is False
        resp = client.delete("/conversations/foo")
        assert json.loads(resp.data)["ok"] is False
