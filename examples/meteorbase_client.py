"""
Minimal MeteorBase client - use this inside any of your client apps
(web frontends, server jobs, scripts) to talk to EVERY service through
the single MeteorBase gateway.

    mb = MeteorBase("https://your-meteorbase.onrender.com", "mb_live_<key>")
    sessions = mb.get("oblivion", "/sessions")
    mb.post("oblivion", "/sessions", json={"title": "Focus block"})
"""
import requests


class MeteorBase:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def request(self, app: str, method: str, path: str, **kwargs):
        url = f"{self.base_url}/api/v1/{app}/{path.lstrip('/')}"
        headers = {"X-API-Key": self.api_key, **kwargs.pop("headers", {})}
        resp = requests.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        if resp.status_code == 204:
            return None
        return resp.json()

    def get(self, app: str, path: str, params=None):
        return self.request(app, "GET", path, params=params)

    def post(self, app: str, path: str, **kwargs):
        return self.request(app, "POST", path, **kwargs)

    def put(self, app: str, path: str, **kwargs):
        return self.request(app, "PUT", path, **kwargs)

    def patch(self, app: str, path: str, **kwargs):
        return self.request(app, "PATCH", path, **kwargs)

    def delete(self, app: str, path: str, **kwargs):
        return self.request(app, "DELETE", path, **kwargs)

    def list_apps(self):
        return requests.get(f"{self.base_url}/api/v1/apps").json()


if __name__ == "__main__":
    mb = MeteorBase("http://localhost:5000", "YOUR_API_KEY")
    print("Registered apps:", mb.list_apps())
    print("Sessions:", mb.get("oblivion", "/sessions"))