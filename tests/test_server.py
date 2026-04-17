"""
测试 Web Server API
"""
import pytest
from fastapi.testclient import TestClient
from core.server import app

client = TestClient(app)

class TestBooksAPI:
    def test_list_books(self):
        response = client.get("/api/books")
        assert response.status_code == 200
        assert isinstance(response.json(), list)
    def test_get_book_not_found(self):
        response = client.get("/api/books/nonexistent_book")
        assert response.status_code == 404

class TestChaptersAPI:
    def test_list_chapters_not_found(self):
        response = client.get("/api/books/nonexistent/chapters")
        assert response.status_code == 404
    def test_get_chapter_not_found(self):
        response = client.get("/api/books/nonexistent/chapters/1")
        assert response.status_code == 404

class TestCausalChainAPI:
    def test_get_causal_chain_not_found(self):
        response = client.get("/api/books/nonexistent/causal-chain")
        assert response.status_code == 404

class TestEmotionalArcsAPI:
    def test_get_emotional_arcs_not_found(self):
        response = client.get("/api/books/nonexistent/emotional-arcs")
        assert response.status_code == 404

class TestHooksAPI:
    def test_get_hooks_not_found(self):
        response = client.get("/api/books/nonexistent/hooks")
        assert response.status_code == 404

class TestRelationshipsAPI:
    def test_get_relationships_not_found(self):
        response = client.get("/api/books/nonexistent/relationships")
        assert response.status_code == 404

class TestOutlineAPI:
    def test_get_outline_not_found(self):
        response = client.get("/api/books/nonexistent/outline")
        assert response.status_code == 404
    def test_get_chapter_outlines_not_found(self):
        response = client.get("/api/books/nonexistent/chapter-outlines")
        assert response.status_code == 404
