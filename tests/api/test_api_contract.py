import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "apps" / "api" / "server.py"

EXPECTED_ROUTES = [
    ("API_ROUTE", "/health"),
    ("GET", "/ready"),
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
            if not isinstance(owner, ast.Name) or owner.id != "app" or decorator.func.attr == "middleware":
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


if __name__ == "__main__":
    unittest.main()
