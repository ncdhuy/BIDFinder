import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "apps" / "api" / "server.py"

EXPECTED_ROUTES = [
    ("API_ROUTE", "/health"),
    ("GET", "/ready"),
    ("GET", "/config.js"),
    ("GET", "/api/auth/config"),
    ("POST", "/api/auth/register"),
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/google"),
    ("GET", "/api/auth/me"),
    ("POST", "/api/auth/logout"),
    ("PATCH", "/api/auth/profile"),
    ("POST", "/api/auth/forgot-password"),
    ("POST", "/api/auth/reset-password"),
    ("POST", "/api/auth/change-password"),
    ("POST", "/api/feedback"),
    ("GET", "/api/feedback/topics"),
    ("POST", "/api/feedback/topics"),
    ("GET", "/api/feedback/topics/{topic_id}"),
    ("PATCH", "/api/feedback/topics/{topic_id}"),
    ("POST", "/api/feedback/topics/{topic_id}/replies"),
    ("GET", "/api/filter-config"),
    ("GET", "/api/search-contract"),
    ("POST", "/api/ai/search-plan"),
    ("GET", "/api/ai/usage"),
    ("POST", "/api/ai/search-preview"),
    ("POST", "/api/query"),
    ("POST", "/api/bulk-query"),
    ("POST", "/api/query-preview"),
    ("GET", "/api/warmup"),
    ("POST", "/api/autocomplete"),
    ("GET", "/api/metadata"),
]


def app_routes():
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    routes = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            owner = decorator.func.value
            if (
                not isinstance(owner, ast.Name)
                or owner.id != "app"
                or decorator.func.attr not in {"api_route", "get", "post", "patch", "put", "delete"}
            ):
                continue
            routes.append((decorator.func.attr.upper(), ast.literal_eval(decorator.args[0])))
    return routes


class ApiContractTest(unittest.TestCase):
    def test_method_and_path_snapshot(self):
        self.assertEqual(EXPECTED_ROUTES, app_routes())

    def test_compatibility_entrypoint_exists(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        assigned_names = {
            target.id
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
            if isinstance(target, ast.Name)
        }
        self.assertIn("app", assigned_names)

    def test_public_readiness_does_not_expose_internal_typesense_endpoint(self):
        source = SERVER.read_text(encoding="utf-8")
        ready_start = source.index('@app.get("/ready")')
        ready_end = source.index('\n\ndef auth_error_response', ready_start)
        ready_source = source[ready_start:ready_end]
        self.assertIn('typesense_status = status.get("typesense")', ready_source)
        self.assertIn('typesense_status.pop("endpoint", None)', ready_source)

    def test_typesense_primary_enforces_anonymous_query_quota(self):
        source = SERVER.read_text(encoding="utf-8")
        primary_start = source.index("async def query_typesense_primary")
        primary_end = source.index("\n\nasync def autocomplete_typesense_primary", primary_start)
        primary_source = source[primary_start:primary_end]
        self.assertIn("get_anonymous_full_query_usage_snapshot(request)", primary_source)
        self.assertIn("consume_anonymous_full_query_usage(request)", primary_source)
        self.assertIn('get_env_int("ANONYMOUS_FULL_QUERY_DAILY_LIMIT", 3)', source)

    def test_feedback_reads_allow_anonymous_but_writes_still_require_authentication(self):
        source = SERVER.read_text(encoding="utf-8")
        list_start = source.index('@app.get("/api/feedback/topics")')
        list_end = source.index('@app.post("/api/feedback/topics")', list_start)
        detail_start = source.index('@app.get("/api/feedback/topics/{topic_id}")')
        detail_end = source.index('@app.patch("/api/feedback/topics/{topic_id}")', detail_start)
        create_start = source.index('@app.post("/api/feedback/topics")')
        create_end = source.index('@app.get("/api/feedback/topics/{topic_id}")', create_start)
        reply_start = source.index('@app.post("/api/feedback/topics/{topic_id}/replies")')
        reply_end = source.index('@app.get("/api/filter-config")', reply_start)

        self.assertIn("get_optional_authenticated_user(conn, request)", source[list_start:list_end])
        self.assertIn("get_optional_authenticated_user(conn, request)", source[detail_start:detail_end])
        self.assertIn("require_authenticated_user(conn, request)", source[create_start:create_end])
        self.assertIn("require_authenticated_user(conn, request)", source[reply_start:reply_end])


if __name__ == "__main__":
    unittest.main()
